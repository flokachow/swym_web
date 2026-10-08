"""Anthropic Claude (experimental). No video input, so the clip arrives as still frames."""

from __future__ import annotations

import base64
import json

from .base import Adapter, ProviderError, expand_video

TOOL = "report"
MAX_TOKENS = 4096


class Anthropic(Adapter):
    id = "anthropic"
    label = "Anthropic Claude (experimental)"
    env_key = "ANTHROPIC_API_KEY"
    models_setting = "modelsAnthropic"
    key_url = "https://console.anthropic.com/settings/keys"
    base_env = "SWIMFORM_ANTHROPIC_BASE"
    default_base = "https://api.anthropic.com/v1"

    def endpoint(self, model: str) -> str:
        return f"{self.base()}/messages"

    def models_url(self) -> str:
        return f"{self.base()}/models?limit=100"

    def headers(self, key: str) -> dict:
        return {"Content-Type": "application/json", "x-api-key": key,
                "anthropic-version": "2023-06-01"}

    def prepare(self, parts):
        return expand_video(parts)

    def build_body(self, model, parts, schema, temperature):
        content = []
        for p in parts:
            if "text" in p:
                content.append({"type": "text", "text": p["text"]})
            elif "image_bytes" in p:
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": base64.b64encode(p["image_bytes"]).decode("ascii")}})
        body: dict = {"model": model, "max_tokens": MAX_TOKENS,
                      "messages": [{"role": "user", "content": content}]}
        if temperature is not None:
            body["temperature"] = temperature
        if schema is not None:
            # A forced tool call is the reliable way to get structured JSON out.
            body["tools"] = [{"name": TOOL, "description": "Report the result.", "input_schema": schema}]
            body["tool_choice"] = {"type": "tool", "name": TOOL}
        return body

    def extract(self, payload, schema):
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ProviderError(f"Unexpected response shape:\n{json.dumps(payload)[:800]}")
        if schema is not None:
            for b in blocks:
                if b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                    return b["input"]
            raise ProviderError(f"Model returned no structured result (stop_reason={payload.get('stop_reason')})")
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise ProviderError(f"Model returned no content (stop_reason={payload.get('stop_reason')})")
        return text

    def parse_models(self, payload):
        return [m["id"] for m in payload.get("data", []) if m.get("id")], ""
