"""Minimal Gemini client: JSON-schema-constrained calls with model fallback.

Stdlib only, on purpose. The whole dependency footprint of this project is
ffmpeg and Pillow; adding an SDK to make a handful of HTTP calls is not a trade
worth making, and it keeps `pip install` from being a prerequisite for reading
the code.

The caller's key travels in the `x-goog-api-key` request header, never in the
URL, so it cannot end up in an access log or a traceback. Error text is scrubbed
of the key before it leaves this module.

Fallback rules (what moves on to the next model, and what stops the run):

    timeout                      next model at once (a retry costs another full wait)
    network error                3 tries, then the next model
    429 / 5xx                    backoff and retry, then the next model
    404 / 400                    next model (retired name, or a limit of that one model)
    401 / 403 / invalid key      stop: the key is wrong on every model
    TLS certificate failure      stop: the machine's trust store, not the model
"""

from __future__ import annotations

import base64
import json
import os
import random
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Transient. Anything else is a real error and retrying just wastes the user's
# quota on the same failure.
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS_PER_MODEL = 3

_sleep = time.sleep  # a seam, so tests do not wait out real backoff


class GeminiError(RuntimeError):
    pass


class GeminiKeyError(GeminiError):
    """The key was rejected. Retrying or falling back cannot help."""


def base_url() -> str:
    """The API root. Overridable by environment for local testing only; it is
    deliberately not a setting, so a web page cannot redirect your key."""
    return os.environ.get("SWIMFORM_GEMINI_BASE", DEFAULT_BASE).rstrip("/")


def scrub(text: str, key: str | None) -> str:
    return text.replace(key, "[key]") if key and text else text


def _headers(key: str) -> dict:
    return {"Content-Type": "application/json", "x-goog-api-key": key}


def _request(url: str, key: str, body: dict | None, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers=_headers(key), method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _is_key_rejection(code: int, detail: str) -> bool:
    d = detail.lower()
    return code in (401, 403) or "api key not valid" in d or "api_key_invalid" in d


def _is_cert_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ssl.SSLCertVerificationError)


CERT_HELP = (
    "Your computer could not verify the service's certificate (TLS). On macOS with a "
    "python.org install, run the \"Install Certificates.command\" that ships with "
    "Python, or use the system Python."
)


def generate(parts: list[dict], schema: dict | None, key: str,
             model: str | None = None, temperature: float | None = None,
             timeout: int = 300) -> dict | str:
    """Run one generation across the model fallback chain.

    Returns parsed JSON when `schema` is given, otherwise the raw text.
    """
    cfg = config.load()
    gen: dict = {"temperature": cfg["temperature"] if temperature is None else temperature}
    if schema is not None:
        gen["response_mime_type"] = "application/json"
        gen["response_schema"] = schema

    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
    chain = [model] if model else cfg["models"]
    for name in chain:
        if not config.MODEL_RE.match(name or ""):
            raise GeminiError(f"'{name}' is not a valid model name.")

    last_error = ""
    payload = None

    for candidate in chain:
        url = f"{base_url()}/models/{candidate}:generateContent"
        for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
            try:
                payload = _request(url, key, body, timeout)
                if candidate != chain[0]:
                    print(f"[swimform] served by fallback model {candidate}", file=sys.stderr)
                break
            except urllib.error.HTTPError as e:
                detail = scrub(e.read().decode("utf-8", errors="replace")[:400], key)
                last_error = f"{candidate}: {e.code}: {detail}"
                if _is_key_rejection(e.code, detail):
                    raise GeminiKeyError(
                        "The AI service rejected the API key. Check it was pasted whole and that "
                        "the API is enabled for it.") from None
                if e.code in RETRY_STATUSES:
                    if attempt < MAX_ATTEMPTS_PER_MODEL:
                        # Exponential backoff with jitter. A saturated model clears
                        # in seconds; hammering it makes the queue worse.
                        delay = (2 ** attempt) + random.uniform(0, 1)
                        print(f"[swimform] {candidate} busy ({e.code}), retrying in "
                              f"{delay:.1f}s ({attempt}/{MAX_ATTEMPTS_PER_MODEL})",
                              file=sys.stderr)
                        _sleep(delay)
                        continue
                    break  # out of attempts: next model
                break  # 404 / 400 and friends: next model, no retry
            except (TimeoutError, socket.timeout):
                last_error = f"{candidate} did not answer within {timeout}s"
                break  # accepted, then silence: straight to the next model
            except (urllib.error.URLError, OSError) as e:
                if _is_cert_error(e):
                    raise GeminiError(CERT_HELP) from None
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
        raise GeminiError(
            f"No model in the fallback chain could answer. Last error — {last_error}\n"
            "Free tiers saturate at peak times; waiting a few minutes usually "
            "clears it. If a model name is retired, change the list in Settings."
        )

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        finish = (payload.get("candidates") or [{}])[0].get("finishReason")
        if finish:
            raise GeminiError(f"Model returned no content (finishReason={finish})")
        raise GeminiError(f"Unexpected response shape:\n{json.dumps(payload)[:800]}")

    if schema is None:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise GeminiError(f"Model returned malformed JSON ({e}):\n{text[:500]}")


def list_models(key: str, timeout: float = 20) -> list[str]:
    """Names of the models this key can generate with — a call that costs no quota.

    Doubles as the key check: a wrong key is rejected here, before a user has
    uploaded anything.
    """
    names: list[str] = []
    token = ""
    for _ in range(3):  # a few pages is plenty; the list is short
        url = f"{base_url()}/models?pageSize=100" + (f"&pageToken={token}" if token else "")
        try:
            page = _request(url, key, None, timeout)
        except urllib.error.HTTPError as e:
            detail = scrub(e.read().decode("utf-8", errors="replace")[:300], key)
            if _is_key_rejection(e.code, detail) or e.code == 400:
                raise GeminiKeyError(
                    "The AI service rejected the API key. Check it was pasted whole.") from None
            raise GeminiError(f"API error {e.code}: {detail}") from None
        except (TimeoutError, socket.timeout):
            raise GeminiError("The AI service did not answer in time.") from None
        except (urllib.error.URLError, OSError) as e:
            if _is_cert_error(e):
                raise GeminiError(CERT_HELP) from None
            raise GeminiError(f"Could not reach the AI service: {scrub(str(getattr(e, 'reason', e)), key)}") from None
        for m in page.get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(m["name"].split("/", 1)[-1])
        token = page.get("nextPageToken", "")
        if not token:
            break
    return names


def video_part(data: bytes, fps: float | None) -> dict:
    part: dict = {
        "inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(data).decode("ascii")}
    }
    if fps:
        part["video_metadata"] = {"fps": fps}
    return part


def image_part(path: Path) -> dict:
    return {
        "inline_data": {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
    }
