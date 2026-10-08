"""Google Gemini: the recommended provider, and the only one that takes video natively."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from .base import Adapter, ProviderError


class Gemini(Adapter):
    id = "gemini"
    label = "Google Gemini"
    env_key = "GEMINI_API_KEY"
    models_setting = "models"
    key_url = "https://aistudio.google.com/apikey"
    recommended = True
    native_video = True
    base_env = "SWIMFORM_GEMINI_BASE"
    default_base = "https://generativelanguage.googleapis.com/v1beta"

    def endpoint(self, model: str) -> str:
        return f"{self.base()}/models/{model}:generateContent"

    def models_url(self) -> str:
        return f"{self.base()}/models?pageSize=100"

    def headers(self, key: str) -> dict:
        # In a header, never the URL, so it cannot end up in an access log.
        return {"Content-Type": "application/json", "x-goog-api-key": key}

    def build_body(self, model, parts, schema, temperature):
        out = []
        for p in parts:
            if "text" in p:
                out.append({"text": p["text"]})
            elif "video" in p:
                part = {"inline_data": {"mime_type": "video/mp4",
                                        "data": base64.b64encode(p["video"]).decode("ascii")}}
                if p.get("fps"):
                    # A freestyle stroke is ~1.2 s, so 1 fps aliases it.
                    part["video_metadata"] = {"fps": p["fps"]}
                out.append(part)
            elif "image" in p:
                out.append({"inline_data": {"mime_type": "image/jpeg",
                                            "data": base64.b64encode(Path(p["image"]).read_bytes()).decode("ascii")}})
        gen: dict = {}
        if temperature is not None:
            gen["temperature"] = temperature
        if schema is not None:
            gen["response_mime_type"] = "application/json"
            gen["response_schema"] = schema
        return {"contents": [{"role": "user", "parts": out}], "generationConfig": gen}

    def extract(self, payload, schema):
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            finish = (payload.get("candidates") or [{}])[0].get("finishReason")
            if finish:
                raise ProviderError(f"Model returned no content (finishReason={finish})")
            raise ProviderError(f"Unexpected response shape:\n{json.dumps(payload)[:800]}")
        if schema is None:
            return text
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Model returned malformed JSON ({e}):\n{text[:500]}")

    def parse_models(self, payload):
        names = [m["name"].split("/", 1)[-1] for m in payload.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        return names, payload.get("nextPageToken", "")
