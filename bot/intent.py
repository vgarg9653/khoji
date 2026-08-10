"""What is the student actually doing with this message?

Before this existed, the bot only accepted an answer to the question it had just
asked. A student who typed "what documents do I need?" during the state question
was told "I couldn't find that state" — the message was parsed as a failed
answer rather than recognised as a question. That is what made the bot feel like
a form rather than a conversation, and it is what PRD §8 rules out: "Free-form
questions work at any moment; the menu is never a requirement."

So every inbound message is classified first. Rules handle the cases that are
unambiguous in any language — they are free, instant, and work with no model.
The model is consulted only for the genuinely ambiguous remainder.

Nothing here decides eligibility or invents facts; it only decides which part of
the bot should handle the message.
"""

from __future__ import annotations

import re
from enum import Enum


class Intent(str, Enum):
    ANSWER = "answer"            # answering the question we asked
    QUESTION = "question"        # asking us something
    DEEPER = "deeper"            # "more" / "documents" about a chosen result
    SKIP = "skip"                # declines to answer this one
    CORRECTION = "correction"    # changing something already given
    RESTART = "restart"
    HELP = "help"
    GREETING = "greeting"
    RESULTS = "results"          # "show me", "what did you find"


# ---------------------------------------------------------------- rules
# Deliberately multilingual and literal. These fire before any model call, so
# the common paths cost nothing and work even when the model is unavailable.

_SKIP = re.compile(
    r"^\s*(?:skip|pass|next|later|dunno|don'?t know|do not know|not sure|no idea|"
    r"i don'?t want to (?:say|tell|share)|don'?t want to (?:say|tell|share)|"
    r"prefer not|rather not|can'?t say|cannot say|no comment|"
    r"नहीं पता|पता नहीं|नहीं बताना|छोड़ो|छोड़ दो|आगे बढ़ो|"
    r"nahi pata|pata nahi|nahi bataunga|chodo|aage badho)\s*[.!]?\s*$", re.I)

_HELP = re.compile(
    r"^\s*(?:help|\?+|info|about|what can you do|how does this work|"
    r"मदद|सहायता|madad|kaise)\s*[.!?]?\s*$", re.I)

_RESTART = re.compile(
    r"^\s*(?:restart|start over|reset|start again|begin again|from start|"
    r"फिर से|दोबारा|शुरू|phir se|dobara|shuru)\s*[.!]?\s*$", re.I)

_GREETING = re.compile(
    r"^\s*(?:hi+|hey+|hello+|hola|start|menu|namaste|namaskar|"
    r"नमस्ते|नमस्कार|हाय|salaam|assalam[ou]? ?alaikum)\s*[.!]?\s*$", re.I)

_RESULTS = re.compile(
    r"^\s*(?:show(?: me)?(?: the)?(?: results| scholarships| list)?|"
    r"results?|list|what did you find|show all|see (?:all|list)|"
    r"दिखाओ|दिखाइए|दिखाईये|list dikhao)\s*[.!?]?\s*$", re.I)

# A question is the case that used to break the flow, so detection is generous:
# a leading question word, or a trailing question mark, in English or Hindi.
_QUESTION_WORD = re.compile(
    r"^\s*(?:what|which|who|whom|whose|when|where|why|how|can i|could i|am i|"
    r"is there|are there|do i|does it|will i|should i|kya|kaun|kab|kahan|kaise|"
    r"kitna|kitni|क्या|कौन|कब|कहाँ|कहां|कैसे|कितना|कितनी|क्यों)\b", re.I)

_CORRECTION = re.compile(
    r"\b(?:actually|sorry|i meant|change (?:my|the)|wrong|mistake|not that|"
    r"instead|correction|no i am|no i'?m|galat|maine galat|बदलो|गलत|असल में)\b", re.I)

# Words that make a question-looking message actually an answer. "What is my
# income? 2 lakh" is rare; "2 lakh" is the norm — but "how much is the amount?"
# is a real question. Numbers alone are never questions.
_LOOKS_LIKE_DATA = re.compile(r"^[\s\d,./-]+$")


# The two words the results screen offers by name. They are matched here so the
# model is never consulted about them: it read "documents" as a question and
# answered it in prose, which cost a quota call to produce something worse than
# the list we already had.
_DEEPER = re.compile(
    r"^\s*(?:more|details?|documents?|docs|papers?|"
    r"और|कागज़|दस्तावेज़)\s*[?.!]?\s*$", re.I)


def classify_rule_based(text: str) -> Intent | None:
    """Return an Intent when the rules are certain, else None."""
    t = (text or "").strip()
    if not t:
        return None
    if _LOOKS_LIKE_DATA.match(t):
        return Intent.ANSWER          # "3", "12", "250000"
    if _DEEPER.match(t):
        return Intent.DEEPER
    if _RESTART.match(t):
        return Intent.RESTART
    if _HELP.match(t):
        return Intent.HELP
    if _GREETING.match(t):
        return Intent.GREETING
    if _SKIP.match(t):
        return Intent.SKIP
    if _RESULTS.match(t):
        return Intent.RESULTS
    if _CORRECTION.search(t):
        return Intent.CORRECTION
    # A question mark, or an opening question word with a few words after it.
    if t.endswith("?") or (_QUESTION_WORD.match(t) and len(t.split()) >= 3):
        return Intent.QUESTION
    return None


CLASSIFY_SYSTEM = """Classify what an Indian student is doing with this WhatsApp \
message to a scholarship bot. The bot has just asked them a question.

Reply with ONE word from this list and nothing else:

answer      - they are answering the bot's question (a state, class, category, income)
question    - they are asking the bot something
skip        - they are declining to answer this question
correction  - they are changing something they said earlier
restart     - they want to start over
help        - they want to know what the bot does
greeting    - just a greeting
results     - they want to see the scholarship list

The message may be in any Indian language or in Latin transliteration."""


def classify(text: str, llm=None, current_question: str = "") -> Intent:
    """Rules first, model only for the ambiguous remainder.

    Defaults to ANSWER when nothing is certain: mistaking an answer for a
    question merely produces a slightly odd reply, while mistaking an answer for
    something else loses the student's data and makes them repeat themselves.
    """
    rule = classify_rule_based(text)
    if rule is not None:
        return rule

    if llm is not None and getattr(llm, "available", False):
        prompt = text if not current_question else \
            f"The bot asked: {current_question}\nThe student replied: {text}"
        try:
            out = (llm._chat(CLASSIFY_SYSTEM, prompt) or "").strip().lower()
            word = re.sub(r"[^a-z]", "", out.split()[0]) if out.split() else ""
            for i in Intent:
                if i.value == word:
                    return i
        except Exception:
            pass

    return Intent.ANSWER
