"""Quick-reply chips for the web demo.

The demo used to show four fixed chips — `hi`, `Rajasthan`, `Hindi`, `restart` —
on every screen. So the bot asked "which class are you in?" and offered
"Rajasthan", and asked for a category while offering "hi", which restarts the
conversation. Roughly three of the four were wrong at any given moment.

Two rules follow from that, and they are the whole design of this module:

1. **Chips are computed from the session, on the server.** The demo page cannot
   know which question was just asked without duplicating the state machine,
   and a second copy of the state machine drifts from the first. Same reasoning
   as `demo.html` opening with the real welcome message instead of a hardcoded
   greeting.

2. **Every `send` value must be something the engine already accepts at that
   step.** A chip that produces "I couldn't read that" is worse than no chip:
   the student is told they got it wrong while tapping a button we offered
   them. `tests/test_suggestions.py` drives every chip of every step through
   the real engine and asserts the conversation moves forward.

`label` is what the student reads; `send` is what gets typed on their behalf.
They are usually the same string. Where they differ it is because the engine
matches a number more reliably than a word — "Graduation" is a substring of
"Post-graduation", so the option list resolves it ambiguously and rejects it,
while "4" is exact.

The Hindi and Hinglish sends are native, not English: `intent.py` and
`extract_rules.py` already match `छोड़ो`, `पता नहीं`, `दस्तावेज़`, `राजस्थान`
and the rest, so a Hindi conversation stays Hindi in the student's own bubble.
Where a language has no natural equivalent the English falls through.
"""

from __future__ import annotations

from conversation import Step

# A chip is (label, send) per language. `_L` picks the right pair and falls back
# to English, so a half-translated entry degrades to something that still works
# rather than to a missing button.
_LANGS = ("en", "hi", "hinglish")


def _chip(lang: str, en, hi=None, hinglish=None) -> dict:
    """Each argument is either "text" (label and send are the same) or a
    (label, send) pair."""
    chosen = {"en": en, "hi": hi, "hinglish": hinglish}.get(lang) or en
    if isinstance(chosen, str):
        return {"label": chosen, "send": chosen}
    return {"label": chosen[0], "send": chosen[1]}


# ---------------------------------------------------------------- per step

def _name(lang):
    return [
        _chip(lang, "skip", "छोड़ो", "skip"),
    ]


def _state(lang):
    # Rajasthan first: it is the only state portal crawled so far, so it is the
    # one that shows state-specific results rather than central schemes alone.
    return [
        _chip(lang, "Rajasthan", "राजस्थान", "Rajasthan"),
        _chip(lang, "Uttar Pradesh", "उत्तर प्रदेश", "Uttar Pradesh"),
        _chip(lang, "Bihar", "बिहार", "Bihar"),
        _chip(lang, "Delhi", "दिल्ली", "Delhi"),
    ]


def _level(lang):
    # Sends are the option numbers. "Graduation" as text is a substring of
    # "Post-graduation (MA, MSc, MTech)" too, and `_pick` deliberately refuses
    # an ambiguous match rather than guessing the first hit.
    return [
        _chip(lang, ("School", "1"), ("स्कूल", "1"), ("School", "1")),
        _chip(lang, ("ITI", "2"), ("आईटीआई", "2"), ("ITI", "2")),
        _chip(lang, ("Graduation", "4"), ("ग्रेजुएशन", "4"), ("Graduation", "4")),
        _chip(lang, ("Post-graduation", "5"), ("पोस्ट ग्रेजुएशन", "5"),
              ("Post-graduation", "5")),
    ]


def _class_level(lang):
    return [
        _chip(lang, "10"),
        _chip(lang, "12"),
        _chip(lang, "9"),
        _chip(lang, "skip", "छोड़ो", "skip"),
    ]


def _category(lang):
    return [
        _chip(lang, ("SC", "1"), ("अनुसूचित जाति", "1"), ("SC", "1")),
        _chip(lang, ("ST", "2"), ("अनुसूचित जनजाति", "2"), ("ST", "2")),
        _chip(lang, ("OBC", "3"), ("ओबीसी", "3"), ("OBC", "3")),
        _chip(lang, ("General", "8"), ("सामान्य", "8"), ("General", "8")),
    ]


def _income(lang):
    return [
        _chip(lang, "1 lakh", "1 लाख", "1 lakh"),
        _chip(lang, "2.5 lakh", "2.5 लाख", "2.5 lakh"),
        _chip(lang, "8 lakh", "8 लाख", "8 lakh"),
        _chip(lang, ("don't know", "skip"), ("पता नहीं", "पता नहीं"),
              ("pata nahi", "pata nahi")),
    ]


def _aspiration(lang):
    return [
        _chip(lang, ("Keep studying", "1"), ("आगे पढ़ना है", "1"),
              ("Aage padhna hai", "1")),
        _chip(lang, ("Professional course", "2"), ("प्रोफेशनल कोर्स", "2"),
              ("Professional course", "2")),
        _chip(lang, ("Job or skill training", "3"), ("नौकरी या स्किल ट्रेनिंग", "3"),
              ("Job ya skill training", "3")),
        _chip(lang, ("Not sure yet", "4"), ("अभी तय नहीं", "4"),
              ("Abhi tay nahi", "4")),
    ]


def _confirm(lang):
    return [
        _chip(lang, "yes", "हाँ", "haan"),
        _chip(lang, ("no, change something", "no"), ("नहीं, बदलना है", "नहीं"),
              ("nahi, badalna hai", "nahi")),
    ]


def _continue_or_fresh(lang):
    # "1"/"2" rather than words: `_WANTS_FRESH` treats anything unrecognised as
    # "carry on", so the fresh-start chip has to hit exactly.
    return [
        _chip(lang, ("Yes, carry on", "1"), ("हाँ, आगे बढ़ें", "1"),
              ("Haan, aage badhein", "1")),
        _chip(lang, ("Start a new search", "2"), ("नई खोज", "2"),
              ("Nayi search", "2")),
    ]


def _restart(lang):
    return _chip(lang, "restart", "फिर से", "phir se")


def _results(lang, n: int):
    """Numbers for what is actually on screen, never more.

    The old chip row offered a fixed set regardless of how many results came
    back; offering "3" against a two-result list earns "reply with a number
    from 1 to 2" for following instructions.
    """
    chips = [_chip(lang, str(i)) for i in range(1, min(n, 3) + 1)]
    if n == 1:
        # `_detail_screen` only resolves "documents" without a chosen result
        # when there is exactly one — otherwise it has to ask which, so the
        # chip would cost the student a round trip.
        chips.append(_chip(lang, "documents", "दस्तावेज़", "documents"))
    chips.append(_restart(lang))
    return chips


def _detail(lang):
    return [
        _chip(lang, "more", "और", "more"),
        _chip(lang, "documents", "दस्तावेज़", "documents"),
        _restart(lang),
    ]


_BY_STEP = {
    Step.NAME: _name,
    Step.STATE: _state,
    Step.LEVEL: _level,
    Step.CLASS_LEVEL: _class_level,
    Step.CATEGORY: _category,
    Step.INCOME: _income,
    Step.ASPIRATION: _aspiration,
    Step.DETAIL: _detail,
}


def for_session(session) -> list[dict]:
    """The chips to show after this turn. Pure, no I/O, never raises.

    A demo that 500s because a chip could not be computed is a worse failure
    than a demo with no chips, so anything unexpected returns an empty row and
    leaves the text box — which always works — as the way forward.
    """
    try:
        lang = getattr(session, "language", "en")
        if lang not in _LANGS:
            lang = "en"

        # Both of these pre-empt the step machine in `Bot._handle`, so they have
        # to pre-empt the chips too or we would offer answers to a question the
        # bot is not currently asking.
        if getattr(session, "pending_transcript", None):
            return _confirm(lang)
        if getattr(session, "pending_confirm", False):
            return _confirm(lang)
        if getattr(session, "pending_restart", False):
            return _continue_or_fresh(lang)

        step = getattr(session, "step", None)

        if step is Step.RESULTS:
            n = len(getattr(session, "last_results", None)
                    or getattr(session, "last_result_ids", None) or [])
            return _results(lang, n)

        if step is Step.NAME and lang == "en":
            # The one demo affordance kept: a visitor has no way to guess that a
            # whole profile in one Hindi sentence works. Valid here because
            # anything that reads as an answer at NAME is re-handled as one, and
            # offered only in English because a Hindi speaker is already doing it.
            return _name(lang) + [{
                "label": "…or try Hindi",
                "send": "मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख",
            }]

        builder = _BY_STEP.get(step)
        if builder is None:
            return [_restart(lang)]          # WELCOME, DONE, anything new
        return builder(lang)
    except Exception:
        return []
