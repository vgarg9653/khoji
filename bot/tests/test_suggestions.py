"""Every chip we offer must be an answer the engine actually accepts.

This is the whole point of the module. A chip that produces "I couldn't read
that" is worse than no chip at all: the student is told they got it wrong while
tapping a button we put in front of them.

So these tests don't check the chip *text*. They walk the real conversation to
each step, tap each chip through the real `Bot.handle`, and assert the bot moved
on rather than re-asking.
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

LANGS = ("en", "hi", "hinglish")

# Getting to each step, as (message, ...) from a fresh session. Deliberately the
# real path rather than a hand-built Session, so a change to the flow breaks
# these tests instead of silently making the chips wrong again.
ROUTES = {
    Step.NAME: ("hi",),
    Step.STATE: ("hi", "Farheen"),
    Step.LEVEL: ("hi", "Farheen", "Rajasthan"),
    Step.CLASS_LEVEL: ("hi", "Farheen", "Rajasthan", "1"),
    Step.CATEGORY: ("hi", "Farheen", "Rajasthan", "1", "12"),
    Step.INCOME: ("hi", "Farheen", "Rajasthan", "1", "12", "3"),
    Step.ASPIRATION: ("hi", "Farheen", "Rajasthan", "1", "12", "3", "2 lakh"),
    Step.RESULTS: ("hi", "Farheen", "Rajasthan", "1", "12", "3", "2 lakh", "4"),
}


@pytest.fixture(scope="module")
def matcher():
    if not DATA.exists():
        pytest.skip(f"catalogue not built at {DATA}")
    return Matcher.from_file(DATA)


def _bot(matcher):
    # No llm: the rule layers must carry every chip on their own. If a chip only
    # works when Gemini is reachable, it does not work on a rate-limited key.
    return Bot(matcher, llm=None)


def _walk_to(bot, phone, step):
    for msg in ROUTES[step]:
        bot.handle(phone, msg)
    session = bot.store.get(phone)
    assert session.step is step, f"route to {step} landed on {session.step}"
    return session


# Phrases the bot uses only when it could not read an answer. Kept narrow on
# purpose: "reply with a number from 1 to 12" is the *class* question, not a
# rejection, and matching on it failed a chip that was working perfectly. The
# reliable signal is whether the step advanced — this is a second opinion.
_REJECTIONS = ("couldn't", "could not", "sorry —", "समझ नहीं")


def _looks_rejected(replies: list[str]) -> bool:
    joined = " ".join(replies).lower()
    return any(r in joined for r in _REJECTIONS)


@pytest.mark.parametrize("step", list(ROUTES))
@pytest.mark.parametrize("lang", LANGS)
def test_every_chip_is_accepted(matcher, step, lang):
    """Tap each chip from a fresh session and assert the bot moves forward."""
    probe = _bot(matcher)
    probe_session = _walk_to(probe, f"probe-{step}-{lang}", step)
    probe_session.language = lang
    probe.store.save(probe_session)

    chips = suggestions.for_session(probe_session)
    assert chips, f"no chips offered at {step}"

    for i, chip in enumerate(chips):
        bot = _bot(matcher)
        phone = f"chip-{step}-{lang}-{i}"
        session = _walk_to(bot, phone, step)
        session.language = lang
        bot.store.save(session)

        replies = bot.handle(phone, chip["send"])
        assert replies, f"{step}/{lang}: chip {chip!r} produced no reply"
        assert not _looks_rejected(replies), (
            f"{step}/{lang}: chip {chip!r} was rejected -> {replies}")

        after = bot.store.get(phone)
        # "restart" is the one chip that deliberately goes backwards.
        if chip["send"] in ("restart", "फिर से", "phir se"):
            assert after.step is Step.NAME
        else:
            assert after.step is not step or step is Step.RESULTS, (
                f"{step}/{lang}: chip {chip!r} left the bot on the same "
                f"question -> {replies}")


@pytest.mark.parametrize("step", list(ROUTES))
def test_chips_are_wellformed(matcher, step):
    for lang in LANGS:
        bot = _bot(matcher)
        session = _walk_to(bot, f"form-{step}-{lang}", step)
        session.language = lang
        for chip in suggestions.for_session(session):
            assert chip["label"] and chip["send"], f"empty chip at {step}"
            assert len(chip["label"]) <= 30, f"chip label too long: {chip}"


def test_results_chips_never_exceed_what_is_on_screen(matcher):
    """Offering "3" against a two-result list earns the student a telling-off
    for following instructions."""
    bot = _bot(matcher)
    session = _walk_to(bot, "results-count", Step.RESULTS)
    n = len(session.last_results)
    numeric = [c["send"] for c in suggestions.for_session(session)
               if c["send"].isdigit()]
    assert numeric, "results screen offered no result numbers"
    assert all(int(s) <= n for s in numeric), (
        f"offered {numeric} against {n} results")


def test_detail_step_offers_more_and_documents(matcher):
    bot = _bot(matcher)
    _walk_to(bot, "detail", Step.RESULTS)
    bot.handle("detail", "1")
    session = bot.store.get("detail")
    assert session.step is Step.DETAIL
    sends = {c["send"] for c in suggestions.for_session(session)}
    assert "more" in sends and "documents" in sends


def test_pending_confirm_offers_yes_no_not_step_answers(matcher):
    """A read-back question pre-empts the step machine in `Bot._handle`, so it
    has to pre-empt the chips too."""
    bot = _bot(matcher)
    session = _walk_to(bot, "confirm", Step.STATE)
    session.pending_confirm = True
    sends = {c["send"] for c in suggestions.for_session(session)}
    assert "yes" in sends
    assert "Rajasthan" not in sends


def test_degrades_rather_than_raising(matcher):
    """A demo that 500s over a chip is a worse failure than a demo with none."""
    class Junk:
        step = "not-a-step"
        language = "kl"          # not a language we have copy for

    # An unknown step still leaves a way forward, and an unknown language falls
    # back to English rather than producing a blank label.
    out = suggestions.for_session(Junk())
    assert out == [{"label": "restart", "send": "restart"}]

    class Nothing:
        pass

    # A session with no attributes at all, and no session at all, both land on
    # the same safe row rather than raising into the endpoint.
    assert suggestions.for_session(Nothing()) == [
        {"label": "restart", "send": "restart"}]
    assert suggestions.for_session(None) == [
        {"label": "restart", "send": "restart"}]
