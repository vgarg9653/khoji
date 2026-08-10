"""Which model does which job, and what happens when one runs out.

The bot had a single model doing everything, and the failure mode was ugly: one
`429 RESOURCE_EXHAUSTED` and it lost Hindi, voice notes and free-form questions
all at once, silently, for the rest of the day. It was found in exactly that
state — `gemini-3.6-flash` exhausted while three other models on the same key
answered instantly.

Two ideas fix that.

**Different jobs deserve different models.** Deciding whether a message is a
question or an answer is not the same work as writing a paragraph of Hindi.
Routing and extraction are structured, short, and want to be fast and cheap;
generation wants to be good.

**Different models are different quota buckets.** A free-tier limit is per
model, not per key, so falling back from an exhausted model to another one is
not a downgrade — it is capacity that was already paid for. This is the whole
reason `MODEL_FALLBACK` exists, and it is why the fallback is a *different
family* rather than a smaller version of the same one.

Everything is overridable by environment variable, so a model can be swapped
after a price change or a deprecation without touching code — which has already
happened twice on this project.

Measured on this key, 10 Aug 2026 (`scratchpad/bench.py`):

    gemini-3.5-flash-lite   5/5 extraction · ~1.0s · clean Hindi · audio ok
    gemini-3.1-flash-lite   5/5 extraction · ~1.1s · clean Hindi · audio ok, faster
    gemini-3.6-flash        quota exhausted
    gemini-2.5-flash-lite   404 — not available to this key
    gemma-4-31b-it          correct but ~13.6s, far too slow for WhatsApp
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("bot.models")

# Roles, not model names, are what the rest of the code asks for.
ROUTER = "router"           # intent classification, profile extraction
GENERATION = "generation"   # translation, answering from a record
AUDIO = "audio"             # voice notes

_DEFAULTS = {
    ROUTER: "gemini-3.5-flash-lite",
    GENERATION: "gemini-3.5-flash-lite",
    AUDIO: "gemini-3.5-flash-lite",
}
_ENV = {
    ROUTER: "MODEL_ROUTER",
    GENERATION: "MODEL_GENERATION",
    AUDIO: "MODEL_AUDIO",
}

# A *different family*, so its quota is a different bucket. A second-choice
# model that shares a bucket with the first is not a fallback, it is a retry.
DEFAULT_FALLBACK = "gemini-3.1-flash-lite"

# Errors worth trying another model for. A 429 means this bucket is empty; a
# 404 means the id went stale, which Google has done twice here. Anything else
# (a bad request, a safety block) will fail the same way on every model, so
# retrying just spends time the student is waiting through.
_TRY_NEXT = ("429", "resource_exhausted", "quota",
             "404", "not_found", "503", "unavailable", "500", "internal")


def for_role(role: str) -> str:
    """The preferred model for a job."""
    # LLM_MODEL is the old single-model setting. Honouring it keeps an existing
    # deployment behaving exactly as before until it is removed.
    override = os.environ.get("LLM_MODEL", "").strip()
    if override:
        return override
    return os.environ.get(_ENV.get(role, ""), "").strip() or _DEFAULTS[role]


def chain(role: str) -> list[str]:
    """Models to try in order: the one for the job, then the fallback bucket."""
    out = [for_role(role)]
    fb = os.environ.get("MODEL_FALLBACK", "").strip() or DEFAULT_FALLBACK
    if fb and fb not in out:
        out.append(fb)
    return out


def should_try_next(err: BaseException) -> bool:
    text = f"{type(err).__name__} {err}".lower()
    return any(t in text for t in _TRY_NEXT)


def describe() -> dict:
    """What /health reports, so the deployed configuration is never a guess."""
    return {r: chain(r) for r in (ROUTER, GENERATION, AUDIO)}
