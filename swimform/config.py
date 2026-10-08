"""Runtime configuration and API-key loading.

Everything the user can reasonably want to change lives in config.json rather
than in code — the model list especially, since which model is best changes
faster than this repository does.

The Gemini key is NOT part of the config. It is held by the browser and sent
per request by the web app, or read from the environment by the command line.
Nothing in this module ever writes a key to disk.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("SWIMFORM_HOME", Path.home() / ".config" / "swimform"))
CONFIG_PATH = CONFIG_DIR / "config.json"
ENV_PATH = CONFIG_DIR / ".env"
UPLOAD_DIR = CONFIG_DIR / "uploads"
OVERLAY_ROOT = CONFIG_DIR / "overlays"

DATA_DIR = Path(__file__).resolve().parent / "data"

# Model names end up in a request path, so they are held to a strict shape.
MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

DEFAULTS = {
    # Tried in order; the first one that answers wins. Free-tier models
    # saturate at peak times, and falling back beats failing.
    "models": [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
    ],
    # A freestyle stroke cycle takes ~1.2s, so sampling at 1fps aliases the
    # stroke phases. 2fps is the floor that actually sees the catch.
    "fps": 2.0,
    "overlays": 3,
    "temperature": 0.2,
    # Below this, a deviation is not worth putting in front of a swimmer.
    "reportThreshold": 0.2,
    # Stills of the moments a fault was seen, per fault.
    "evidencePerFault": 4,
    # Stored stills and overlays are pictures of a person; they are deleted
    # after this long, and can be deleted at any time from Settings.
    "retentionHours": 24,
}

_lock = threading.Lock()


class ConfigError(ValueError):
    """A settings update was rejected."""


def _number(lo: float, hi: float, integer: bool = False):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ConfigError("must be a number")
        if integer and int(v) != v:
            raise ConfigError("must be a whole number")
        if not lo <= v <= hi:
            raise ConfigError(f"must be between {lo:g} and {hi:g}")
        return int(v) if integer else float(v)
    return check


def _models(v):
    if not isinstance(v, list) or not 1 <= len(v) <= 8:
        raise ConfigError("must be a list of 1-8 model names")
    for name in v:
        if not isinstance(name, str) or not MODEL_RE.match(name):
            raise ConfigError(f"bad model name {name!r}")
    return list(dict.fromkeys(v))


VALIDATORS = {
    "models": _models,
    "fps": _number(0.5, 10),
    "overlays": _number(0, 6, integer=True),
    "temperature": _number(0, 2),
    "reportThreshold": _number(0, 1),
    "evidencePerFault": _number(0, 6, integer=True),
    "retentionHours": _number(1, 720, integer=True),
}


def validate_patch(patch: dict) -> dict:
    """Check a settings update; unknown keys are an error, not ignored."""
    if not isinstance(patch, dict):
        raise ConfigError("settings must be an object")
    clean = {}
    for key, value in patch.items():
        check = VALIDATORS.get(key)
        if check is None:
            raise ConfigError(f"unknown setting '{key}'")
        try:
            clean[key] = check(value)
        except ConfigError as e:
            raise ConfigError(f"{key}: {e}") from None
    return clean


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text())
            if isinstance(stored, dict):
                for k, v in stored.items():
                    if k in VALIDATORS:
                        try:
                            cfg[k] = VALIDATORS[k](v)
                        except ConfigError:
                            pass  # a bad stored value falls back to the default
        except json.JSONDecodeError as e:
            print(f"[swimform] {CONFIG_PATH} is not valid JSON ({e}); using defaults",
                  file=sys.stderr)
    return cfg


def save(patch: dict) -> dict:
    """Merge a validated update into the stored settings and write it."""
    clean = validate_patch(patch)
    with _lock:
        merged = load()
        merged.update(clean)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=2) + "\n")
        os.replace(tmp, CONFIG_PATH)
    return merged


class MissingKey(RuntimeError):
    """Raised instead of exiting, so the server can report it over HTTP."""


def api_key() -> str:
    """The key for command-line use: environment first, then the .env file."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if line.startswith("GEMINI_API_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise MissingKey(
        "No API key found.\n"
        "  In the web app: Settings, then paste your key.\n"
        f"  On the command line: put GEMINI_API_KEY=... in {ENV_PATH}\n"
        "  or export it:        export GEMINI_API_KEY=...\n"
        "  Free key: https://aistudio.google.com/apikey"
    )


def has_server_key() -> bool:
    try:
        api_key()
        return True
    except MissingKey:
        return False
