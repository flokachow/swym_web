"""OpenAI (experimental). No video input, so the clip arrives as still frames."""

from __future__ import annotations

import base64
import json

from .base import Adapter, ProviderError, expand_video

# Not chat models: skipped when listing what a key can use.
NOT_CHAT = ("embedding", "whisper", "tts", "audio", "realtime", "image", "transcribe",
            "moderation", "search", "dall", "davinci", "babbage", "instruct", "codex")


def strictify(schema):
    """OpenAI's strict structured output wants every object closed and every
    property required. Our schemas are written for Gemini, which does not."""
    if isinstance(schema, dict):
        out = {k: strictify(v) for k, v in schema.items()}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(schema, list):
        return [strictify(v) for v in schema]
    return schema


class OpenAI(Adapter):
    id = "openai"
    label = "OpenAI (experimental)"
    env_key = "OPENAI_API_KEY"
    models_setting = "modelsOpenai"
    key_url = "https://platform.openai.com/api-keys"
    base_env = "SWIMFORM_OPENAI_BASE"
    default_base = "https://api.openai.com/v1"

    def endpoint(self, model: str) -> str:
        return f"{self.base()}/chat/completions"

    def models_url(self) -> str:
        return f"{self.base()}/models"

    def headers(self, key: str) -> dict:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}

    def prepare(self, parts):
        return expand_video(parts)

    def build_body(self, model, parts, schema, temperature):
        content = []
        for p in parts:
            if "text" in p:
                content.append({"type": "text", "text": p["text"]})
            elif "image_bytes" in p:
                b64 = base64.b64encode(p["image_bytes"]).decode("ascii")
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}})
        body: dict = {"model": model, "messages": [{"role": "user", "content": content}]}
        if temperature is not None:
            body["temperature"] = temperature
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "swimform_result", "strict": True, "schema": strictify(schema)}}
        return body

    def extract(self, payload, schema):
        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Unexpected response shape:\n{json.dumps(payload)[:800]}")
        if message.get("refusal"):
            raise ProviderError(f"The model declined: {message['refusal'][:300]}")
        text = message.get("content") or ""
        if not text:
            raise ProviderError(f"Model returned no content (finish_reason={choice.get('finish_reason')})")
        if schema is None:
            return text
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Model returned malformed JSON ({e}):\n{text[:500]}")

    def parse_models(self, payload):
        names = sorted(m["id"] for m in payload.get("data", [])
                       if m.get("id", "").startswith(("gpt-", "chatgpt-", "o1", "o3", "o4"))
                       and not any(x in m["id"] for x in NOT_CHAT))
        return names, ""
