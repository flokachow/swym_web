"""A stand-in for the Gemini, OpenAI and Anthropic REST APIs, for TESTS ONLY.

It is a test double, not a product mode: swimform has no demo or mock engine and
this file is not part of the package. It lets the suite (and a manual
walkthrough) exercise the real code paths — header handling, fallback, ffmpeg,
Pillow, merging — without a key or the network.

    fake = FakeProviders(); fake.start()      # also points the three SWIMFORM_*_BASE variables at itself

The assessment it returns depends on the length of the clip, which the real
prompt states ("runs from 0.0 to N seconds"): a short clip reads as a side-on
view, a longer one as a front-on view, so a test can film two "angles" by
making two clips of different lengths.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD_KEY = "test-key-0123456789abcdefghij"            # the Gemini key
OPENAI_KEY = "sk-test-openai-0123456789abcdefgh"
ANTHROPIC_KEY = "sk-ant-test-0123456789abcdefghij"
KEYS = {"gemini": GOOD_KEY, "openai": OPENAI_KEY, "anthropic": ANTHROPIC_KEY}
BASE_ENV = {"gemini": "SWIMFORM_GEMINI_BASE", "openai": "SWIMFORM_OPENAI_BASE",
            "anthropic": "SWIMFORM_ANTHROPIC_BASE"}

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


class FakeProviders:
    def __init__(self):
        self.calls: list[dict] = []
        # model -> list of behaviours consumed in order, then "ok" forever.
        # Behaviours: "ok", "404", "400", "429", "503", "529", "401", "timeout", "drop",
        #             "echo503", "reject_temp"
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

            def _provider(self) -> str:
                return self.path.lstrip("/").split("/", 1)[0]

            def _auth(self, provider: str) -> bool:
                h = {k.lower(): v for k, v in self.headers.items()}
                if "key=" in self.path:
                    self._reply(400, {"error": {"message": "key must be in the header"}})
                    return False
                if provider == "gemini":
                    ok = h.get("x-goog-api-key", "") == KEYS["gemini"]
                    err = (400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                           "message": "API key not valid. Please pass a valid API key."}})
                elif provider == "openai":
                    ok = h.get("authorization", "") == f"Bearer {KEYS['openai']}"
                    err = (401, {"error": {"message": "Incorrect API key provided: sk-***.",
                                           "code": "invalid_api_key"}})
                else:
                    ok = h.get("x-api-key", "") == KEYS["anthropic"] and bool(h.get("anthropic-version"))
                    err = (401, {"type": "error", "error": {"type": "authentication_error",
                                                            "message": "invalid x-api-key"}})
                if not ok:
                    self._reply(*err)
                return ok

            def do_GET(self):  # noqa: N802
                provider = self._provider()
                fake.calls.append({"method": "GET", "provider": provider, "path": self.path,
                                   "headers": dict(self.headers)})
                if fake.delay:
                    time.sleep(fake.delay)
                if not self._auth(provider):
                    return
                if provider == "gemini" and "/models" in self.path:
                    token = "next" if "pageToken" not in self.path and fake.pages > 1 else ""
                    names = fake.models if not token else fake.models[:1]
                    body = {"models": [{"name": f"models/{n}",
                                        "supportedGenerationMethods": ["generateContent"]}
                                       for n in names]
                            + [{"name": "models/embed-x", "supportedGenerationMethods": ["embedContent"]}]}
                    if token:
                        body["nextPageToken"] = token
                    return self._reply(200, body)
                if provider == "openai" and "/models" in self.path:
                    ids = ["gpt-5", "gpt-4.1", "text-embedding-3-small", "whisper-1", "gpt-image-1"]
                    return self._reply(200, {"data": [{"id": i} for i in ids]})
                if provider == "anthropic" and "/models" in self.path:
                    return self._reply(200, {"data": [{"id": "claude-sonnet-5-5"}, {"id": "claude-haiku-4-5-20251001"}],
                                             "has_more": False})
                self._reply(404, {"error": {"message": "nope"}})

            def do_POST(self):  # noqa: N802
                provider = self._provider()
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = {}
                if provider == "gemini":
                    m = re.search(r"/models/([^:]+):generateContent", self.path)
                    model = m.group(1) if m else ""
                else:
                    model = body.get("model", "")
                with fake._lock:
                    fake.calls.append({"method": "POST", "provider": provider, "path": self.path,
                                       "model": model, "headers": dict(self.headers), "body": body})
                    queue = fake.behaviours.get(model, [])
                    behaviour = queue.pop(0) if queue else "ok"
                if fake.delay:
                    time.sleep(fake.delay)
                if not self._auth(provider):
                    return
                if behaviour == "timeout":
                    time.sleep(3)
                    return
                if behaviour == "drop":
                    self.connection.close()
                    return
                if behaviour == "echo503":
                    leaked = (self.headers.get("x-goog-api-key") or self.headers.get("x-api-key")
                              or self.headers.get("authorization", ""))
                    return self._reply(503, {"error": {"message": f"upstream saw {leaked}"}})
                if behaviour == "reject_temp" and fake.has_temperature(provider, body):
                    return self._reply(400, {"error": {"message":
                        "Unsupported value: 'temperature' does not support 0.2 with this model."}})
                if behaviour in ("404", "400", "429", "503", "529", "401"):
                    return self._reply(int(behaviour), {"error": {"message": f"scripted {behaviour}"}})
                self._reply(200, fake._answer(provider, body))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        root = f"http://127.0.0.1:{self._server.server_address[1]}"
        os.environ[BASE_ENV["gemini"]] = f"{root}/gemini/v1beta"
        os.environ[BASE_ENV["openai"]] = f"{root}/openai/v1"
        os.environ[BASE_ENV["anthropic"]] = f"{root}/anthropic/v1"
        return f"{root}/gemini/v1beta"

    def kill(self) -> None:
        """Stop answering but leave the base URLs pointing here, so calls fail to connect
        (rather than falling through to the real services)."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def stop(self) -> None:
        self.kill()
        for name in BASE_ENV.values():
            os.environ.pop(name, None)

    # -- answers ----------------------------------------------------------

    @staticmethod
    def has_temperature(provider: str, body: dict) -> bool:
        if provider == "gemini":
            return "temperature" in body.get("generationConfig", {})
        return "temperature" in body

    @staticmethod
    def _texts_and_images(provider: str, body: dict) -> tuple[str, int, dict]:
        """(all the prompt text, how many images/videos were sent, the response schema's properties)"""
        if provider == "gemini":
            parts = body["contents"][0]["parts"]
            text = " ".join(p.get("text", "") for p in parts)
            media = sum(1 for p in parts if "inline_data" in p)
            props = (body.get("generationConfig", {}).get("response_schema") or {}).get("properties", {})
        elif provider == "openai":
            parts = body["messages"][0]["content"]
            text = " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
            media = sum(1 for p in parts if p.get("type") == "image_url")
            props = (((body.get("response_format") or {}).get("json_schema") or {}).get("schema") or {}).get("properties", {})
        else:
            parts = body["messages"][0]["content"]
            text = " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
            media = sum(1 for p in parts if p.get("type") == "image")
            tools = body.get("tools") or [{}]
            props = (tools[0].get("input_schema") or {}).get("properties", {})
        return text, media, props

    def _answer(self, provider: str, body: dict) -> dict:
        prompt, _, props = self._texts_and_images(provider, body)

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

        if provider == "gemini":
            return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
        if provider == "openai":
            return {"choices": [{"message": {"role": "assistant", "content": text},
                                 "finish_reason": "stop"}]}
        if payload is not None:
            return {"content": [{"type": "tool_use", "name": "report", "input": payload}],
                    "stop_reason": "tool_use"}
        return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}


FakeGemini = FakeProviders  # the name older tests use
