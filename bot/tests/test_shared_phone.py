"""One phone is one session, and these households share phones.

"hi" was a silent reset. A sibling or a parent picking up the family phone and
opening the chat the way anyone opens a chat wiped a profile that had just cost
six questions to build — and the student had no idea it had happened, because
the reply looked like a normal welcome.

The rule these tests pin down: an explicit "restart" still resets immediately,
but a *greeting* on top of real answers asks first, and anything short of a
clear "start fresh" keeps the data.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

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


def _partway(matcher, phone="shared"):
    """A student who has answered their way to the income question."""
    bot = Bot(matcher, llm=None)
    for msg in ("hi", "Farheen", "Rajasthan", "1", "12", "3"):
        bot.handle(phone, msg)
    s = bot.store.get(phone)
    assert s.step is Step.INCOME and s.profile.state == "Rajasthan"
    return bot


def test_greeting_midway_asks_before_wiping(matcher):
    bot = _partway(matcher)
    replies = bot.handle("shared", "hi")

    s = bot.store.get("shared")
    assert s.pending_restart is True
    # Nothing has been thrown away yet.
    assert s.profile.state == "Rajasthan"
    assert s.profile.name == "Farheen"
    assert s.step is Step.INCOME
    # And it names who it thinks is asking, which is the whole point on a
    # shared phone.
    assert "Farheen" in " ".join(replies)


def test_carrying_on_keeps_every_answer(matcher):
    bot = _partway(matcher)
    bot.handle("shared", "hi")
    bot.handle("shared", "1")            # "yes, carry on"

    s = bot.store.get("shared")
    assert s.pending_restart is False
    assert s.profile.state == "Rajasthan"
    assert s.profile.category == "OBC"
    assert s.step is Step.INCOME         # back on the question they were on


def test_start_fresh_actually_clears(matcher):
    bot = _partway(matcher)
    bot.handle("shared", "hi")
    bot.handle("shared", "2")            # "start a new search"

    s = bot.store.get("shared")
    assert s.profile.state is None
    assert s.profile.name is None
    assert s.step is Step.NAME


def test_explicit_restart_still_resets_immediately(matcher):
    """"restart" is unambiguous — asking about it would be friction, not care."""
    bot = _partway(matcher)
    bot.handle("shared", "restart")

    s = bot.store.get("shared")
    assert s.pending_restart is False
    assert s.profile.state is None
    assert s.step is Step.NAME


@pytest.mark.parametrize("word", ["restart", "फिर से", "phir se", "dobara"])
def test_explicit_restart_in_every_language(matcher, word):
    bot = _partway(matcher)
    bot.handle("shared", word)
    assert bot.store.get("shared").profile.state is None


@pytest.mark.parametrize("greeting", ["hi", "hello", "namaste", "नमस्ते"])
def test_every_greeting_asks_rather_than_wipes(matcher, greeting):
    bot = _partway(matcher, phone=f"g-{greeting}")
    bot.handle(f"g-{greeting}", greeting)
    s = bot.store.get(f"g-{greeting}")
    assert s.pending_restart is True
    assert s.profile.state == "Rajasthan"


def test_greeting_from_a_fresh_sender_still_just_starts(matcher):
    """The guard must not put a confirmation in front of a first-time user."""
    bot = Bot(matcher, llm=None)
    replies = bot.handle("new", "hi")
    s = bot.store.get("new")
    assert s.pending_restart is False
    assert s.step is Step.NAME
    assert replies


def test_greeting_before_any_answers_does_not_ask(matcher):
    """Named but nothing matchable yet — there is nothing worth protecting."""
    bot = Bot(matcher, llm=None)
    bot.handle("early", "hi")
    bot.handle("early", "Farheen")       # now at STATE, profile still empty
    bot.handle("early", "hi")
    s = bot.store.get("early")
    assert s.pending_restart is False
    assert s.step is Step.NAME


def test_unrecognised_answer_defaults_to_keeping_the_data(matcher):
    """Losing six answers is the expensive mistake; re-asking one is cheap."""
    bot = _partway(matcher)
    bot.handle("shared", "hi")
    bot.handle("shared", "kya?")         # neither option

    s = bot.store.get("shared")
    assert s.profile.state == "Rajasthan"
    assert s.pending_restart is False


def test_chips_offer_the_two_choices(matcher):
    bot = _partway(matcher)
    bot.handle("shared", "hi")
    sends = {c["send"] for c in suggestions.for_session(bot.store.get("shared"))}
    assert sends == {"1", "2"}


def test_language_survives_a_fresh_start(matcher):
    bot = Bot(matcher, llm=None)
    for msg in ("hi", "नमस्ते", "राजस्थान", "1", "12", "3"):
        bot.handle("hindi", msg)
    assert bot.store.get("hindi").language == "hi"
    bot.handle("hindi", "restart")
    assert bot.store.get("hindi").language == "hi"
