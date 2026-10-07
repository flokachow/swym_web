"""A stand-in for the Gemini REST API, for TESTS ONLY.

It is a test double, not a product mode: swimform has no demo or mock engine and
this file is not part of the package. It lets the suite (and a manual
walkthrough) exercise the real code paths — header handling, fallback, ffmpeg,
Pillow, merging — without a key or the network.

    fake = FakeGemini(); base = fake.start()
    os.environ["SWIMFORM_GEMINI_BASE"] = base

The assessment it returns depends on the length of the clip, which the real
prompt states ("runs from 0.0 to N seconds"): a short clip reads as a side-on
view, a longer one as a front-on view, so a test can film two "angles" by
making two clips of different lengths.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD_KEY = "test-key-0123456789abcdefghij"

POINTS = [
    ("head_top", 300, 480), ("ear", 330, 500), ("shoulder_near", 400, 520),
    ("elbow_near", 470, 560), ("wrist_near", 540, 520), ("hip_top", 600, 560),
    ("hip_rear", 640, 570), ("knee_near", 700, 600), ("ankle_near", 800, 620),
]


def scenario(kind: str, duration: float) -> dict:
    """A canned assessment, with timestamps spread across the clip."""
    top = max(1.0, duration - 0.6)
    ts = lambda *fr: [round(min(top, f * duration), 1) for f in fr]  # noqa: E731
    if kind == "front":
        return {
            "viewpoint": "front", "swimmerVisible": True, "strokeCount": 7,
            "summary": "From the front your right hand crosses the centre line on entry.",
            "assessments": [
                {"faultId": "crossover_entry", "deviation": 0.62, "confidence": 0.85,
                 "timestamps": ts(.15, .45, .75), "evidence": "Right hand lands left of the nose."},
                {"faultId": "scissor_kick", "deviation": 0.35, "confidence": 0.7,
                 "timestamps": ts(.3, .6), "evidence": "Feet split wider than the hips on the breath."},
                {"faultId": "insufficient_rotation", "deviation": 0.12, "confidence": 0.8,
                 "timestamps": [], "evidence": "Shoulders roll about 45 degrees."},
                {"faultId": "low_body_position", "deviation": 0.5, "confidence": 0.3,
                 "timestamps": ts(.5), "evidence": "Cannot see hips well from the front."},
            ],
            "notAssessable": [
                {"faultId": "short_stroke_finish", "reason": "The exit is behind the swimmer."},
            ],
        }
    return {
        "viewpoint": "side", "swimmerVisible": True, "strokeCount": 9,
        "summary": "Your hips sink as you breathe; lifting the head is the likely cause.",
        "assessments": [
            {"faultId": "low_body_position", "deviation": 0.7, "confidence": 0.9,
             "timestamps": ts(.2, .5, .8), "evidence": "Hips well below the shoulders."},
            {"faultId": "breathing_head_lift", "deviation": 0.45, "confidence": 0.8,
             "timestamps": ts(.35, .65), "evidence": "Head rises to breathe."},
            {"faultId": "short_stroke_finish", "deviation": 0.15, "confidence": 0.7,
             "timestamps": [], "evidence": "Hand clears the hip."},
            {"faultId": "crossover_entry", "deviation": 0.2, "confidence": 0.4,
             "timestamps": ts(.4), "evidence": "Hard to judge from the side."},
        ],
        "notAssessable": [
            {"faultId": "scissor_kick", "reason": "Legs overlap from this angle."},
            {"faultId": "insufficient_rotation", "reason": "Rotation cannot be judged side-on."},
        ],
    }


class FakeGemini:
    def __init__(self, good_key: str = GOOD_KEY):
        self.good_key = good_key
        self.calls: list[dict] = []
        # model -> list of behaviours consumed in order, then "ok" forever.
        # Behaviours: "ok", "404", "400", "429", "503", "401", "timeout", "drop", "echo503"
        self.behaviours: dict[str, list[str]] = {}
        self.delay = 0.0           # seconds to sleep before answering any call
        self.side_max_seconds = 7.0  # clips up to this long read as "side"
        self.models = ["gemini-3.8-flash", "gemini-3.7-flash"]
        self.pages = 1
        self._server: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> str:
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _reply(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self) -> bool:
                key = self.headers.get("x-goog-api-key", "")
                if "key=" in self.path:
                    self._reply(400, {"error": {"message": "key must be in the header"}})
                    return False
                if key != fake.good_key:
                    self._reply(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                                "message": "API key not valid. Please pass a valid API key."}})
                    return False
                return True

            def do_GET(self):  # noqa: N802
                fake.calls.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
                if fake.delay:
                    time.sleep(fake.delay)
                if not self._auth():
                    return
                if self.path.startswith("/v1beta/models"):
                    token = "next" if "pageToken" not in self.path and fake.pages > 1 else ""
                    names = fake.models if not token else fake.models[:1]
                    body = {"models": [{"name": f"models/{n}",
                                        "supportedGenerationMethods": ["generateContent"]}
                                       for n in names]
                            + [{"name": "models/embed-x", "supportedGenerationMethods": ["embedContent"]}]}
                    if token:
                        body["nextPageToken"] = token
                    return self._reply(200, body)
                self._reply(404, {"error": {"message": "nope"}})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                m = re.match(r"^/v1beta/models/([^:]+):generateContent", self.path)
                model = m.group(1) if m else ""
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = {}
                with fake._lock:
                    fake.calls.append({"method": "POST", "path": self.path, "model": model,
                                       "headers": dict(self.headers), "body": body})
                    queue = fake.behaviours.get(model, [])
                    behaviour = queue.pop(0) if queue else "ok"
                if fake.delay:
                    time.sleep(fake.delay)
                if not self._auth():
                    return
                if behaviour == "timeout":
                    time.sleep(3)
                    return
                if behaviour == "drop":
                    self.connection.close()
                    return
                if behaviour == "echo503":
                    leaked = self.headers.get("x-goog-api-key", "")
                    return self._reply(503, {"error": {"message": f"upstream saw {leaked}"}})
                if behaviour in ("404", "400", "429", "503", "401"):
                    return self._reply(int(behaviour), {"error": {"message": f"scripted {behaviour}"}})
                self._reply(200, fake._answer(body))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1beta"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    # -- answers ----------------------------------------------------------

    def _answer(self, body: dict) -> dict:
        schema = body.get("generationConfig", {}).get("response_schema") or {}
        props = schema.get("properties", {})
        parts = body["contents"][0]["parts"]
        prompt = " ".join(p.get("text", "") for p in parts)

        if "assessments" in props:
            m = re.search(r"from 0\.0 to ([0-9.]+) seconds", prompt)
            duration = float(m.group(1)) if m else 6.0
            kind = "side" if duration <= self.side_max_seconds else "front"
            payload = scenario(kind, duration)
        elif "waterline_y" in props:
            payload = {"waterline_y": 495, "points": [
                {"name": n, "x": x, "y": y, "visible": True} for n, x, y in POINTS]}
        elif "onTopic" in props:
            payload = {"onTopic": True, "faults": [
                {"faultId": "low_body_position", "likelihood": 0.8, "why": "Sinking legs."}]}
        else:
            payload = None

        text = json.dumps(payload) if payload is not None else \
            "Your legs sink because your head is high. Try **Kick sets** this week."
        return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
