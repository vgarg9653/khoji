"""WhatsApp reply buttons, and the round trip back.

Typing is the barrier this product exists to remove, so the payload has to be
right on a channel we cannot iterate against — the number is a Meta test number
capped at five recipients, so a bad payload is not something a demo would catch.

The one that would bite silently: the id and the title are deliberately
different ("School" is shown, "1" is what the engine parses), so reading the
wrong one back turns every tap into an unparseable answer.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import app                                          # noqa: E402
import suggestions                                  # noqa: E402
from conversation import Step                       # noqa: E402
from engine import Bot                              # noqa: E402
from matching import Matcher                        # noqa: E402

DATA = HERE.parent / "deliverables" / "dataset" / "bot_matching.json"


@pytest.fixture(scope="module")
def matcher():
    if not DATA.exists():
        pytest.skip(f"catalogue not built at {DATA}")
    return Matcher.from_file(DATA)


# ------------------------------------------------------------- payload shape

def test_three_or_fewer_options_render_as_buttons():
    chips = [{"label": "more", "send": "more"},
             {"label": "documents", "send": "documents"},
             {"label": "restart", "send": "restart"}]
    body = app._meta_interactive("911", "Pick one", chips)
    assert body["interactive"]["type"] == "button"
    assert len(body["interactive"]["action"]["buttons"]) == 3


def test_more_than_three_options_render_as_a_list():
    chips = [{"label": f"opt {i}", "send": str(i)} for i in range(1, 6)]
    body = app._meta_interactive("911", "Pick one", chips)
    assert body["interactive"]["type"] == "list"
    assert len(body["interactive"]["action"]["sections"][0]["rows"]) == 5


def test_id_carries_what_the_engine_parses_not_the_label():
    """The bug this is here to prevent: sending "School" instead of "1"."""
    chips = [{"label": "School", "send": "1"},
             {"label": "ITI", "send": "2"}]
    body = app._meta_interactive("911", "What are you studying?", chips)
    buttons = body["interactive"]["action"]["buttons"]
    assert [b["reply"]["id"] for b in buttons] == ["1", "2"]
    assert [b["reply"]["title"] for b in buttons] == ["School", "ITI"]


def test_inbound_tap_reads_the_id():
    payload = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "919999999999", "type": "interactive",
        "interactive": {"type": "button_reply",
                        "button_reply": {"id": "1", "title": "School"}},
    }]}}]}]}
    got = app._meta_extract(payload)
    assert got[0]["text"] == "1"          # not "School"
    assert got[0]["kind"] == "text"


def test_inbound_tap_falls_back_to_title_when_id_is_missing():
    payload = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "919999999999", "type": "interactive",
        "interactive": {"list_reply": {"title": "documents"}},
    }]}}]}]}
    assert app._meta_extract(payload)[0]["text"] == "documents"


# ------------------------------------------------------------- the fallbacks

def test_no_options_means_plain_text():
    assert app._meta_interactive("911", "hello", None) is None
    assert app._meta_interactive("911", "hello", []) is None


def test_a_body_over_the_limit_falls_back_to_text():
    """Results screens are long. Long beats buttonless; buttonless beats
    rejected."""
    chips = [{"label": "1", "send": "1"}]
    assert app._meta_interactive("911", "x" * 1100, chips) is None


def test_an_overlong_label_falls_back_rather_than_truncating():
    """"Job or skill trainin" is not what the option means."""
    chips = [{"label": "x" * 25, "send": "1"}, {"label": "ok", "send": "2"}]
    assert app._meta_interactive("911", "pick", chips) is None


def test_never_offers_more_rows_than_whatsapp_accepts():
    chips = [{"label": f"o{i}", "send": str(i)} for i in range(1, 15)]
    body = app._meta_interactive("911", "pick", chips)
    assert len(body["interactive"]["action"]["sections"][0]["rows"]) == 10


# ------------------------------------- the real chips, against the real limits

@pytest.mark.parametrize("step", [Step.NAME, Step.STATE, Step.LEVEL,
                                  Step.CLASS_LEVEL, Step.CATEGORY,
                                  Step.INCOME, Step.ASPIRATION, Step.RESULTS])
@pytest.mark.parametrize("lang", ["en", "hi", "hinglish"])
def test_every_real_step_produces_a_sendable_payload(matcher, step, lang):
    """Chips are written for the web demo, where labels can be any length.
    Anything that cannot become a WhatsApp payload silently loses its buttons on
    the channel that matters most, so every step is checked against the limits."""
    routes = {
        Step.NAME: ("hi",),
        Step.STATE: ("hi", "Farheen"),
        Step.LEVEL: ("hi", "Farheen", "Rajasthan"),
        Step.CLASS_LEVEL: ("hi", "Farheen", "Rajasthan", "1"),
        Step.CATEGORY: ("hi", "Farheen", "Rajasthan", "1", "12"),
        Step.INCOME: ("hi", "Farheen", "Rajasthan", "1", "12", "3"),
        Step.ASPIRATION: ("hi", "Farheen", "Rajasthan", "1", "12", "3", "2 lakh"),
        Step.RESULTS: ("hi", "Farheen", "Rajasthan", "1", "12", "3", "2 lakh", "4"),
    }
    bot = Bot(matcher, llm=None)
    phone = f"wa-{step}-{lang}"
    for m in routes[step]:
        bot.handle(phone, m)
    session = bot.store.get(phone)
    session.language = lang
    bot.store.save(session)

    chips = suggestions.for_session(session)
    body = app._meta_interactive(phone, "a short question", chips)
    assert body is not None, (
        f"{step}/{lang}: chips do not fit WhatsApp's limits -> "
        f"{[c['label'] for c in chips]}")

    kind = body["interactive"]["type"]
    if kind == "button":
        for b in body["interactive"]["action"]["buttons"]:
            assert len(b["reply"]["title"]) <= 20
            assert b["reply"]["id"]
    else:
        for r in body["interactive"]["action"]["sections"][0]["rows"]:
            assert len(r["title"]) <= 24
            assert r["id"]
