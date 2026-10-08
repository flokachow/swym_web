"""What every AI provider shares: errors, the fallback chain and frame sampling.

An adapter (one file per provider) only knows how to speak that provider's API:
where to send, how to authenticate, how to lay out the request, how to read the
answer. Everything about *behaviour* — which failures retry, which fall through
to the next model, which stop the run, how the key is kept out of errors — lives
here once, so it is identical for all of them.

Fallback rules (what moves on to the next model, and what stops the run):

    timeout                      next model at once (a retry costs another full wait)
    network error                3 tries, then the next model
    429 / 5xx / overloaded       backoff and retry, then the next model
    404 / 400                    next model (retired name, or a limit of that one model)
    401 / 403 / invalid key      stop: the key is wrong on every model
    TLS certificate failure      stop: the machine's trust store, not the model
"""

from __future__ import annotations

import json
import random
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import config

# Transient. Anything else is a real error and retrying just wastes the user's
# quota on the same failure. 529 is Anthropic's "overloaded".
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}
MAX_ATTEMPTS_PER_MODEL = 3

# Providers that cannot take video get still frames instead.
MAX_FRAMES = 24
FRAME_WIDTH = 768

_sleep = time.sleep  # a seam, so tests do not wait out real backoff

KEY_REJECTED_PHRASES = (
    "api key not valid", "api_key_invalid", "incorrect api key", "invalid x-api-key",
    "invalid api key", "invalid_api_key", "authentication_error",
)

CERT_HELP = (
    "Your computer could not verify the service's certificate (TLS). On macOS with a "
    "python.org install, run the \"Install Certificates.command\" that ships with "
    "Python, or use the system Python."
)


class ProviderError(RuntimeError):
    pass


class KeyRejected(ProviderError):
    """The key was rejected. Retrying or falling back cannot help."""


def scrub(text: str, key: str | None) -> str:
    return text.replace(key, "[key]") if key and text else text


def is_key_rejection(code: int, detail: str) -> bool:
    d = detail.lower()
    return code in (401, 403) or any(p in d for p in KEY_REJECTED_PHRASES)


def is_cert_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ssl.SSLCertVerificationError)


def request(url: str, headers: dict, body: dict | None, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Adapter:
    """One provider's way of speaking. Subclasses fill in the blanks."""

    id = ""
    label = ""
    env_key = ""               # environment variable the command line reads
    models_setting = "models"  # which config key holds this provider's model order
    key_url = ""
    recommended = False
    native_video = False
    base_env = ""              # environment override of the API root, for tests only
    default_base = ""

    def __init__(self) -> None:
        # Models that rejected a temperature setting; remembered so the next call
        # does not spend a request finding out again.
        self.no_temperature: set[str] = set()

    # -- to implement -----------------------------------------------------

    def endpoint(self, model: str) -> str: raise NotImplementedError
    def models_url(self) -> str: raise NotImplementedError
    def headers(self, key: str) -> dict: raise NotImplementedError
    def build_body(self, model: str, parts: list[dict], schema: dict | None,
                   temperature: float | None) -> dict: raise NotImplementedError
    def extract(self, payload: dict, schema: dict | None): raise NotImplementedError
    def parse_models(self, payload: dict) -> tuple[list[str], str]: raise NotImplementedError

    # -- shared -----------------------------------------------------------

    def base(self) -> str:
        import os
        return os.environ.get(self.base_env, self.default_base).rstrip("/")

    def prepare(self, parts: list[dict]) -> list[dict]:
        """Turn the abstract parts into what this provider can accept, once."""
        return parts

    def info(self) -> dict:
        return {"id": self.id, "label": self.label, "recommended": self.recommended,
                "nativeVideo": self.native_video, "keyUrl": self.key_url,
                "modelsSetting": self.models_setting}


# --------------------------------------------------------------------------
# frames, for providers that cannot take video
# --------------------------------------------------------------------------

def sample_frames(video: bytes, fps: float | None, duration: float | None,
                  max_frames: int = MAX_FRAMES, width: int = FRAME_WIDTH
                  ) -> tuple[list[tuple[float, bytes]], float]:
    """Evenly spaced JPEG frames from a clip, each with its time in seconds.

    The rate is capped so a long clip does not become hundreds of images. The
    times are what let the model say "at 4.5 s" about a picture it cannot play.
    """
    rate = fps if fps and fps > 0 else 2.0
    if duration and duration > 0:
        rate = min(rate, max_frames / duration)
    rate = max(rate, 0.2)
    with tempfile.TemporaryDirectory(prefix="swimform-frames-") as tmp:
        src = Path(tmp) / "clip.mp4"
        src.write_bytes(video)
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(src),
                 "-vf", f"fps={rate:.4f},scale='min({width},iw)':-2", "-q:v", "3",
                 str(Path(tmp) / "f_%04d.jpg")],
                check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as e:
            raise ProviderError(f"Could not cut frames from the clip: {getattr(e, 'stderr', e)}"[:300]) from None
        files = sorted(Path(tmp).glob("f_*.jpg"))[:max_frames]
        frames = [(round(i / rate, 2), f.read_bytes()) for i, f in enumerate(files)]
    if not frames:
        raise ProviderError("The clip produced no frames to send.")
    return frames, rate


def expand_video(parts: list[dict]) -> list[dict]:
    """Replace a video part by its frames, each introduced by its timestamp.

    Parts afterwards are only {"text"}, {"image_bytes"}.
    """
    out: list[dict] = []
    for p in parts:
        if "video" in p:
            frames, rate = sample_frames(p["video"], p.get("fps"), p.get("duration"))
            out.append({"text":
                f"The clip is given as {len(frames)} still frames, sampled every {1 / rate:.2f} seconds, "
                "in time order. Each frame is introduced by its time in seconds from the start of the clip. "
                "Judge the stroke across these frames and quote those times for timestamps."})
            for t, data in frames:
                out.append({"text": f"Frame at t = {t:.1f} s:"})
                out.append({"image_bytes": data})
        elif "image" in p:
            out.append({"image_bytes": Path(p["image"]).read_bytes()})
        else:
            out.append(p)
    return out


# --------------------------------------------------------------------------
# the fallback chain
# --------------------------------------------------------------------------

def generate(adapter: Adapter, parts: list[dict], schema: dict | None, key: str,
             model: str | None = None, temperature: float | None = None,
             timeout: int = 300):
    """Run one generation across the provider's model fallback chain.

    Returns parsed JSON when `schema` is given, otherwise the raw text.
    """
    cfg = config.load()
    chain = [model] if model else cfg[adapter.models_setting]
    for name in chain:
        if not config.MODEL_RE.match(name or ""):
            raise ProviderError(f"'{name}' is not a valid model name.")
    temp = cfg["temperature"] if temperature is None else temperature
    prepared = adapter.prepare(parts)

    last_error = ""
    payload = None

    for candidate in chain:
        url = adapter.endpoint(candidate)
        use_temp = candidate not in adapter.no_temperature
        attempt = 0
        while attempt < MAX_ATTEMPTS_PER_MODEL:
            attempt += 1
            body = adapter.build_body(candidate, prepared, schema, temp if use_temp else None)
            try:
                payload = request(url, adapter.headers(key), body, timeout)
                if candidate != chain[0]:
                    print(f"[swimform] served by fallback model {candidate}", file=sys.stderr)
                break
            except urllib.error.HTTPError as e:
                detail = scrub(e.read().decode("utf-8", errors="replace")[:400], key)
                last_error = f"{candidate}: {e.code}: {detail}"
                if is_key_rejection(e.code, detail):
                    raise KeyRejected(
                        "The AI service rejected the API key. Check it was pasted whole and that "
                        "the key is allowed to use this service.") from None
                if use_temp and e.code == 400 and "temperature" in detail.lower():
                    # Some models only accept their default temperature.
                    adapter.no_temperature.add(candidate)
                    use_temp = False
                    attempt -= 1
                    continue
                if e.code in RETRY_STATUSES:
                    if attempt < MAX_ATTEMPTS_PER_MODEL:
                        # Exponential backoff with jitter. A saturated model clears
                        # in seconds; hammering it makes the queue worse.
                        delay = (2 ** attempt) + random.uniform(0, 1)
                        print(f"[swimform] {candidate} busy ({e.code}), retrying in "
                              f"{delay:.1f}s ({attempt}/{MAX_ATTEMPTS_PER_MODEL})", file=sys.stderr)
                        _sleep(delay)
                        continue
                    break  # out of attempts: next model
                break  # 404 / 400 and friends: next model, no retry
            except (TimeoutError, socket.timeout):
                last_error = f"{candidate} did not answer within {timeout}s"
                break  # accepted, then silence: straight to the next model
            except (urllib.error.URLError, OSError) as e:
                if is_cert_error(e):
                    raise ProviderError(CERT_HELP) from None
                reason = getattr(e, "reason", e)
                if isinstance(reason, (TimeoutError, socket.timeout)):
                    last_error = f"{candidate} did not answer within {timeout}s"
                    break
                last_error = f"{candidate}: network: {scrub(str(reason), key)}"
                if attempt < MAX_ATTEMPTS_PER_MODEL:
                    print(f"[swimform] {candidate} {reason}, retrying "
                          f"({attempt}/{MAX_ATTEMPTS_PER_MODEL})", file=sys.stderr)
                    _sleep(2 ** attempt)
                    continue
                break
        if payload is not None:
            break
        print(f"[swimform] {candidate} unavailable, trying next model", file=sys.stderr)

    if payload is None:
        raise ProviderError(
            f"No model in the fallback chain could answer. Last error — {last_error}\n"
            "Free tiers saturate at peak times; waiting a few minutes usually clears it. "
            "If a model name is retired, change the model in Settings."
        )
    return adapter.extract(payload, schema)


def list_models(adapter: Adapter, key: str, timeout: float = 20) -> list[str]:
    """Names of the models this key can use — a call that costs no quota.

    Doubles as the key check: a wrong key is rejected here, before a user has
    uploaded anything.
    """
    names: list[str] = []
    token = ""
    for _ in range(3):  # a few pages is plenty; the list is short
        url = adapter.models_url() + (f"&pageToken={token}" if token and "?" in adapter.models_url()
                                      else f"?pageToken={token}" if token else "")
        try:
            page = request(url, adapter.headers(key), None, timeout)
        except urllib.error.HTTPError as e:
            detail = scrub(e.read().decode("utf-8", errors="replace")[:300], key)
            if is_key_rejection(e.code, detail) or e.code == 400:
                raise KeyRejected("The AI service rejected the API key. Check it was pasted whole.") from None
            raise ProviderError(f"API error {e.code}: {detail}") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("The AI service did not answer in time.") from None
        except (urllib.error.URLError, OSError) as e:
            if is_cert_error(e):
                raise ProviderError(CERT_HELP) from None
            raise ProviderError(f"Could not reach the AI service: {scrub(str(getattr(e, 'reason', e)), key)}") from None
        found, token = adapter.parse_models(page)
        names.extend(found)
        if not token:
            break
    return names
