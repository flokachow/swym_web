"""AI providers behind one interface.

Gemini is the recommended one: it takes video directly, so it sees the whole
stroke. OpenAI and Anthropic cannot, so swimform sends them still frames cut from
the clip, each labelled with its time — a different method, with coarser timing,
and marked experimental everywhere it is offered.

Parts are provider-neutral:  {"text": str} · {"image": Path} · {"video": bytes, "fps": f, "duration": s}
"""

from __future__ import annotations

from .. import config
from . import base
from .anthropic import Anthropic
from .base import KeyRejected, ProviderError, scrub
from .gemini import Gemini
from .openai import OpenAI

_ADAPTERS = {a.id: a for a in (Gemini(), OpenAI(), Anthropic())}
assert tuple(_ADAPTERS) == config.PROVIDER_IDS

__all__ = ["ProviderError", "KeyRejected", "scrub", "get", "generate", "list_models", "info"]


def get(provider: str | None = None) -> base.Adapter:
    provider = provider or config.load()["provider"]
    try:
        return _ADAPTERS[provider]
    except KeyError:
        raise ProviderError(f"Unknown provider '{provider}'.") from None


def generate(provider, parts, schema, key, model=None, temperature=None, timeout=300):
    return base.generate(get(provider), parts, schema, key, model, temperature, timeout)


def list_models(provider, key, timeout=20):
    return base.list_models(get(provider), key, timeout)


def info() -> list[dict]:
    cfg = config.load()
    return [{**a.info(), "models": cfg[a.models_setting]} for a in _ADAPTERS.values()]
