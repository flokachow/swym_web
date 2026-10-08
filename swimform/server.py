"""Local web app: film from two angles, read the analysis, ask follow-up questions.

Binds to 127.0.0.1 by default. This is deliberate — the server receives video of
you and holds, for the length of a request, your Gemini key, and neither belongs
on an open port. `--host 0.0.0.0` exists for phone-on-the-same-wifi use and
warns loudly.

Threaded, so the page stays responsive during a minutes-long analysis and the
two clips of a dual-angle run can be analysed side by side. At most two
analyses run at once; a third is refused rather than queued, because every one
of them spends the user's own quota.

The API key is never stored here. The browser sends it in `X-Api-Key` on
each request; the command line falls back to the environment.
"""

from __future__ import annotations

import json
import mimetypes
import shutil
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, analyze as analyze_mod, coach, config, merge, providers, report
from . import security, storage, taxonomy

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_UPLOAD = 512 * 1024 * 1024  # a 4K phone clip is big before we re-encode it
MAX_JSON = 2 * 1024 * 1024
MAX_CONCURRENT_ANALYSES = 2

STATIC_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

PAGE_CSP = (
    "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
    "frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
    "object-src 'none'"
)
# The 3D viewer is our own bundle, shown in a sandboxed frame. It does nothing but
# draw, so it gets no network and no inline code. No frame-ancestors: a sandboxed
# frame has an opaque origin, and Chromium then refuses 'self' there.
VIEWER_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; base-uri 'none'"
)


class RequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    """
      GET  /                     the web app
      GET  /static/<file>        its scripts, styles and the 3D viewer
      GET  /health               liveness, setup status (never the key)
      GET  /providers            the AI providers on offer, and each one's model order
      GET  /faults               the taxonomy
      GET  /drills[?fault=id]    the drill library
      GET  /config               runtime settings
      POST /config               update them (validated, merged)
      POST /key/check            is this key valid? lists the models it can use
      POST /analyze              raw video bytes for ONE clip; window and angle in headers
      POST /combine              merge one or two analysed clips into a verdict
      POST /ask                  {question, analysis?, history?}
      POST /purge                delete every stored image
      GET  /overlay/<run>/<f>    annotated frames and evidence stills
    """

    server_version = "swimform"
    timeout = 300  # a stalled client must not hold a thread forever

    # -- plumbing ---------------------------------------------------------

    def _send(self, code: int, ctype: str, body: bytes, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser navigated away mid-response; not our problem

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, "application/json", json.dumps(obj).encode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        # The request line only. Headers — where the key travels — are never logged.
        sys.stderr.write(f"[swimform] {fmt % args}\n")

    def _content_length(self, limit: int) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise RequestError(411, "Content-Length is required.")
        try:
            length = int(raw)
        except ValueError:
            raise RequestError(400, "Bad Content-Length.") from None
        if length < 0:
            raise RequestError(400, "Bad Content-Length.")
        if length > limit:
            raise RequestError(413, f"That is {length // (1024 * 1024)}MB; the limit is "
                                    f"{limit // (1024 * 1024)}MB. Trim it to the length you "
                                    "actually want analysed — 10-20 seconds is plenty.")
        return length

    def _body(self) -> dict:
        length = self._content_length(MAX_JSON)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RequestError(400, "The request body is not valid JSON.") from None
        if not isinstance(data, dict):
            raise RequestError(400, "The request body must be a JSON object.")
        return data

    def _provider(self) -> str:
        """Which AI service this request is for: the X-Provider header, else the default."""
        name = (self.headers.get("X-Provider") or "").strip().lower() or config.load()["provider"]
        if name not in config.PROVIDER_IDS:
            raise RequestError(400, "Unknown provider.")
        return name

    def _key(self) -> str | None:
        """The caller's API key from the request header, shape-checked."""
        key = (self.headers.get("X-Api-Key") or "").strip()
        if not key:
            return None
        problem = security.key_problem(key)
        if problem:
            raise RequestError(400, f"That does not look like an API key: it {problem}.")
        return key

    def _guard(self, method: str) -> bool:
        problem = security.check_request(method, self.headers, self.server.hosts)
        if problem:
            self._json(403, {"error": problem})
            return False
        return True

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard("GET"):
            return
        path = self.path.split("?")[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""

        try:
            if path == "/":
                self._send(200, "text/html; charset=utf-8", (WEB_DIR / "index.html").read_bytes(),
                           {"Content-Security-Policy": PAGE_CSP})

            elif path.startswith("/static/"):
                self._static(path[len("/static/"):])

            elif path == "/favicon.ico":
                self._send(204, "image/x-icon", b"")

            elif path == "/health":
                self._json(200, {
                    "ok": True,
                    "version": __version__,
                    "models": config.load()["models"],
                    "serverKeys": {p: config.has_server_key(p) for p in config.PROVIDER_IDS},
                    "ffmpeg": bool(shutil.which("ffmpeg")),
                    "ffprobe": bool(shutil.which("ffprobe")),
                })

            elif path == "/providers":
                self._json(200, {"providers": providers.info(), "default": config.load()["provider"]})

            elif path == "/faults":
                self._json(200, {"faults": taxonomy.faults()})

            elif path == "/drills":
                fault = None
                for part in query.split("&"):
                    if part.startswith("fault="):
                        fault = part[len("fault="):]
                records = taxonomy.drills_for_fault(fault) if fault in taxonomy.fault_ids() \
                    else taxonomy.drills()
                self._json(200, {"drills": [taxonomy.drill_public(d) for d in records]})

            elif path == "/config":
                self._json(200, config.load())

            elif path.startswith("/overlay/"):
                self._overlay(path[len("/overlay/"):])

            else:
                self._json(404, {"error": "not found"})
        except RequestError as e:
            self._json(e.status, {"error": str(e)})

    def _static(self, rel: str) -> None:
        target = (WEB_DIR / rel).resolve()
        ctype = STATIC_TYPES.get(target.suffix.lower())
        if ctype is None or not target.is_relative_to(WEB_DIR.resolve()) or not target.is_file():
            self._json(404, {"error": "not found"})
            return
        extra = {}
        if target.suffix.lower() == ".html":
            in_viewer = target.parent.name == "viewer"
            extra["Content-Security-Policy"] = VIEWER_CSP if in_viewer else PAGE_CSP
        self._send(200, ctype, target.read_bytes(), extra)

    def _overlay(self, rel: str) -> None:
        parts = rel.split("/")
        if len(parts) != 2 or not security.RUN_RE.match(parts[0]) \
                or not security.FILE_RE.match(parts[1]):
            self._json(404, {"error": "not found"})
            return
        target = (config.OVERLAY_ROOT / parts[0] / parts[1]).resolve()
        if not target.is_relative_to(config.OVERLAY_ROOT.resolve()) or not target.is_file():
            self._json(404, {"error": "not found"})
            return
        ctype = mimetypes.types_map.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, ctype, target.read_bytes())

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard("POST"):
            return
        path = self.path.split("?")[0]
        key = None
        try:
            key = self._key()

            if path == "/config":
                self._json(200, config.save(self._body()))

            elif path == "/key/check":
                self._json(200, self._key_check(key, self._provider()))

            elif path == "/analyze":
                self._json(200, self._analyze(key))

            elif path == "/combine":
                body = self._body()
                result = merge.combine(body.get("angles"), limit=6)
                result["markdown"] = report.markdown(result)
                self._json(200, result)

            elif path == "/ask":
                body = self._body()
                question = body.get("question", "")
                if not isinstance(question, str) or len(question) > 2000:
                    raise RequestError(400, "Keep the question under 2000 characters.")
                history = body.get("history") if isinstance(body.get("history"), list) else []
                history = [h for h in history[-6:] if isinstance(h, dict)
                           and isinstance(h.get("text"), str) and h.get("role") in ("swimmer", "coach")]
                analysis = body.get("analysis") if isinstance(body.get("analysis"), dict) else None
                self._json(200, coach.ask(question, analysis, history, key=key,
                                          provider=self._provider()))

            elif path == "/purge":
                self._json(200, {"removed": storage.purge()})

            else:
                self._json(404, {"error": "not found"})

        except RequestError as e:
            self._json(e.status, {"error": str(e)})
        except config.MissingKey as e:
            self._json(503, {"error": str(e), "needsKey": True})
        except providers.KeyRejected as e:
            self._json(401, {"error": str(e), "needsKey": True})
        except (analyze_mod.AnalysisError, coach.CoachError, config.ConfigError,
                merge.CombineError) as e:
            self._json(400, {"error": str(e)})
        except providers.ProviderError as e:
            self._json(502, {"error": providers.scrub(str(e), key)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": providers.scrub(f"{type(e).__name__}: {e}", key)})

    # -- key check --------------------------------------------------------

    def _key_check(self, key: str | None, provider: str) -> dict:
        if not key:
            return {"valid": False, "error": "Paste a key first."}
        try:
            models = providers.list_models(provider, key)
        except providers.KeyRejected as e:
            return {"valid": False, "error": str(e)}
        except providers.ProviderError as e:
            return {"valid": None, "error": providers.scrub(str(e), key)}
        return {"valid": True, "models": models, "provider": provider}

    # -- analysis ---------------------------------------------------------

    def _analyze(self, key: str | None) -> dict:
        length = self._content_length(MAX_UPLOAD)
        if length <= 0:
            raise analyze_mod.AnalysisError("No video in the request.")

        provider = self._provider()
        viewpoint = self.headers.get("X-Viewpoint") or None
        if viewpoint not in (None, "side", "front"):
            raise RequestError(400, "X-Viewpoint must be 'side' or 'front'.")
        model = self.headers.get("X-Model") or None
        if model and not config.MODEL_RE.match(model):
            raise RequestError(400, "Bad model name.")
        start, end = _num(self.headers.get("X-Start-Sec")), _num(self.headers.get("X-End-Sec"))

        storage.prune()
        run_id = storage.new_run_id()
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.UPLOAD_DIR / f"{run_id}.mp4"
        try:
            remaining = length
            with dest.open("wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                raise RequestError(400, "The upload ended early.")

            slots = self.server.slots
            if not slots.acquire(blocking=False):
                raise RequestError(429, "Two analyses are already running. Wait for one to "
                                        "finish — each one spends your API quota.")
            try:
                out_dir = config.OVERLAY_ROOT / run_id
                result = analyze_mod.analyze(
                    dest, start, end, model=model, out_dir=out_dir, key=key, viewpoint=viewpoint,
                    provider=provider)
            finally:
                slots.release()
        finally:
            # The upload has been re-encoded and sent; keeping a copy of someone's
            # swim video on disk is not our call to make.
            dest.unlink(missing_ok=True)

        # Hand the browser URLs, not filesystem paths — and no paths at all.
        def url(p: str) -> str:
            return f"/overlay/{run_id}/{Path(p).name}"

        for a in result.get("assessments", []):
            frame = a.get("frame")
            if frame:
                frame["image"] = url(frame["image"])
                frame.pop("keypoints", None)
                frame.pop("waterlineY", None)
            for ev in a.get("evidenceFrames", []):
                ev["image"] = url(ev["image"])
        result.pop("overlayDir", None)
        result["runId"] = run_id
        return result


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


class _Server(ThreadingHTTPServer):
    # Without this a restart hits TIME_WAIT on the listening socket and fails
    # for a minute or so, which reads as a bug rather than a wait.
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, handler, extra_hosts: tuple[str, ...] = ()):
        super().__init__(addr, handler)
        self.hosts = security.allowed_hosts(self.server_address[1], extra_hosts)
        if addr[0] not in ("127.0.0.1", "localhost", "::1"):
            self.hosts.add(f"{addr[0]}:{self.server_address[1]}".lower())
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT_ANALYSES)


def create_server(host: str = "127.0.0.1", port: int = 8787,
                  extra_hosts: tuple[str, ...] = ()) -> _Server:
    """Bind a server without starting it (port 0 picks a free one — handy for tests)."""
    return _Server((host, port), Handler, extra_hosts)


def serve(port: int = 8787, host: str = "127.0.0.1", open_browser: bool = False,
          extra_hosts: tuple[str, ...] = ()) -> int:
    cfg = config.load()

    if not any(config.has_server_key(p) for p in config.PROVIDER_IDS):
        print("[swimform] no key in the environment — paste yours in the app's Settings.\n",
              file=sys.stderr)

    if not shutil.which("ffmpeg"):
        print("[swimform] warning — ffmpeg not found on PATH; analysis will fail.\n",
              file=sys.stderr)

    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[swimform] WARNING: binding to {host} exposes this service to your "
              "network.\n            It accepts video uploads and handles your API key "
              "with no\n            authentication. Do not do this on a network you do "
              "not trust.\n", file=sys.stderr)

    try:
        server = create_server(host, port, extra_hosts)
    except OSError as e:
        if e.errno in (48, 98):  # EADDRINUSE, macOS and Linux
            print(f"\nerror: port {port} is already in use — most likely a swimform "
                  f"you started earlier.\n"
                  f"  See what holds it:  lsof -nP -iTCP:{port} -sTCP:LISTEN\n"
                  f"  Or use another:     python3 -m swimform serve --port {port + 1}\n",
                  file=sys.stderr)
            return 1
        raise

    removed = storage.prune()
    url = f"http://{host}:{port}"
    print(f"[swimform] {url}")
    print(f"[swimform] models: {', '.join(cfg['models'])}")
    print(f"[swimform] stored images expire after {cfg['retentionHours']}h"
          + (f" ({removed} old runs removed)" if removed else ""))
    print("[swimform] Read docs/RESPONSIBLE_USE.md before filming anyone.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[swimform] stopped")
    return 0
