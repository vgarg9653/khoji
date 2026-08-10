"""Conversation state machine for the Khoji.AI WhatsApp bot.

Deliberately a slot-filling flow rather than free-form chat: the students this
serves are often on slow connections and low-end phones, and numbered replies
("1", "2") are cheaper and more reliable than natural language. Every question
also accepts typed text, so either works.

The flow asks for the fields that actually narrow the search — state, level,
category, income — and stops. Fields the dataset almost never carries (age,
marks) are not asked about, because asking for information we cannot match on
wastes the student's time and data.

State is a plain dict per phone number so it can be moved to Redis or a DB
without touching this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum

from matching import StudentProfile

# Indian states and UTs the dataset can match on.
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
]

LEVELS = [
    ("school", "School (Class 1-12)"),
    ("ITI", "ITI"),
    ("diploma", "Diploma / Polytechnic"),
    ("UG", "Graduation (BA, BSc, BCom, BTech)"),
    ("PG", "Post-graduation (MA, MSc, MTech)"),
    ("PhD", "PhD / Research"),
    ("professional", "Professional (Medical, Engineering, Law)"),
]

CATEGORIES = [
    ("SC", "SC"), ("ST", "ST"), ("OBC", "OBC"), ("EWS", "EWS"),
    ("minority", "Minority"), ("PwD", "Disability (PwD)"),
    ("DNT", "DNT / Nomadic"), ("general", "General / None of these"),
]

# Where the student wants to go next. Asked once, optional, and never used to
# take away something they qualify for today — only to decide which "plan
# ahead" suggestions are worth making.
ASPIRATIONS = [
    ("study_more", "Keep studying — college or higher"),
    ("professional", "A professional course (engineering, medical, law)"),
    ("vocational", "A job or skill training (ITI, diploma)"),
    ("unsure", "Not sure yet"),
]

# What each answer means for matching. "unsure" is a real answer, not a
# non-answer: it says do not speculate about my path, so plan-ahead results are
# held back rather than guessed at.
ASPIRATION_EFFECT = {
    "study_more": {"wants_higher_studies": "yes"},
    "professional": {"wants_higher_studies": "yes",
                     "intended_next_level": "professional"},
    "vocational": {"wants_higher_studies": "yes",
                   "intended_next_level": "ITI"},
    "unsure": {"wants_higher_studies": "unsure"},
}


class Step(str, Enum):
    WELCOME = "welcome"
    NAME = "name"
    STATE = "state"
    LEVEL = "level"
    CLASS_LEVEL = "class_level"
    CATEGORY = "category"
    INCOME = "income"
    ASPIRATION = "aspiration"
    RESULTS = "results"
    DETAIL = "detail"
    DONE = "done"


@dataclass
class Session:
    phone: str
    step: Step = Step.WELCOME
    profile: StudentProfile = field(default_factory=StudentProfile)
    last_results: list = field(default_factory=list)
    # The ids of what we last showed. `last_results` holds full MatchResult
    # objects and is far too heavy to persist; the ids are a few hundred bytes
    # and let the results be rebuilt exactly on the next message.
    last_result_ids: list[str] = field(default_factory=list)
    language: str = "en"
    household_role: str | None = None      # student | parent | guardian
    # Set when a voice note transcribed with low confidence; the next message
    # either confirms it or replaces it.
    pending_transcript: str | None = None
    # Which result the student is currently reading, so "more" and "documents"
    # know what they refer to without being told again.
    last_detail_index: int | None = None
    # How many clarifying questions we have asked in a row. Two is the cap —
    # past that the bot states its assumption and moves on rather than turning
    # into an interrogation.
    clarify_streak: int = 0
    # A one-line profile summary awaiting a yes/no before we run matching.
    pending_confirm: bool = False
    # True once any field was filled by inference — a voice note, or a whole
    # sentence read in one go — rather than by answering the question we asked.
    # Inferred profiles get read back before anything is matched on them.
    profile_inferred: bool = False
    profile_confirmed: bool = False

    def to_dict(self) -> dict:
        return {"phone": self.phone, "step": self.step.value,
                "profile": asdict(self.profile), "language": self.language}


# ------------------------------------------------------------- parsing

def _pick(text: str, options: list) -> str | None:
    """Resolve a reply against a numbered option list.

    Accepts the number ("3"), the exact value, or a distinctive substring, so a
    student can reply however is easiest on their keyboard.
    """
    t = (text or "").strip()
    if not t:
        return None
    values = [o[0] if isinstance(o, tuple) else o for o in options]
    labels = [o[1] if isinstance(o, tuple) else o for o in options]

    if t.isdigit():
        i = int(t) - 1
        return values[i] if 0 <= i < len(values) else None

    low = t.lower()
    for val, lab in zip(values, labels):
        if low == val.lower() or low == lab.lower():
            return val
    # Substring match, but only when exactly one option matches — an ambiguous
    # reply should re-prompt rather than silently pick the first hit.
    hits = [v for v, lab in zip(values, labels)
            if low in lab.lower() or low in v.lower()]
    return hits[0] if len(hits) == 1 else None


_INCOME_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(lakh|lakhs|lac|l|k|thousand|crore)?",
                        re.I)


def parse_income(text: str) -> int | None:
    """Read '2 lakh', '250000', '2.5L', '50k', and their Hindi equivalents."""
    import copy_hi
    t = (text or "").translate(copy_hi.DEVANAGARI_DIGITS)
    # Hindi unit words map onto the English ones the parser already knows.
    for hi, en in (("लाख", "lakh"), ("हज़ार", "thousand"), ("हजार", "thousand"),
                   ("करोड़", "crore"), ("रुपये", ""), ("रुपए", ""), ("रु", "")):
        t = t.replace(hi, f" {en} ")
    # "ढाई"/"डेढ़" are common spoken quantities with no digit form.
    t = t.replace("ढाई", "2.5").replace("डेढ़", "1.5").replace("सवा", "1.25")
    t = t.strip().lower().replace("rs", "").replace("₹", "").strip()
    if not t:
        return None
    if any(w in t for w in ("skip", "don't know", "dont know", "not sure", "no idea")):
        return None
    m = _INCOME_RE.search(t)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit in ("lakh", "lakhs", "lac", "l"):
        val *= 100_000
    elif unit in ("k", "thousand"):
        val *= 1_000
    elif unit == "crore":
        val *= 10_000_000
    val = int(round(val))
    # A bare small number almost certainly means lakhs ("my income is 2").
    if val < 100 and val > 0:
        val *= 100_000
    return val if 0 < val <= 100_000_000 else None


_NAME_PREFIX = re.compile(
    r"^\s*(?:my name is|i am|i'?m|this is|name\s*[:\-]?|call me|"
    r"mera naam|mera nam|main|mai|naam|"
    r"मेरा नाम|मैं|नाम)\s+", re.I)
_NAME_SUFFIX = re.compile(r"\s+(?:hai|hoon|hun|है|हूँ|हूं)\s*[.!]?\s*$", re.I)
# Anything with a digit, an @, or more than three words is not a name being
# offered — it is an answer to some other question that arrived early.
_NOT_A_NAME = re.compile(r"[\d@/]|https?:")


def parse_name(text: str) -> str | None:
    """Pull a name out of "mera naam Farheen hai" or just "Farheen".

    Returns None rather than guessing. A wrong name is used in every subsequent
    message, so the cost of a bad guess compounds in a way no other field's
    does.
    """
    t = (text or "").strip()
    if not t or _NOT_A_NAME.search(t):
        return None
    t = _NAME_SUFFIX.sub("", _NAME_PREFIX.sub("", t)).strip(" ,.!\"'")
    if not t or len(t) > 40:
        return None
    words = t.split()
    if len(words) > 3:
        return None
    # Title-case only ASCII; Devanagari has no case and .title() mangles some
    # conjuncts.
    return " ".join(w if not w.isascii() else w.capitalize() for w in words)


def wants_restart(text: str) -> bool:
    return (text or "").strip().lower() in {
        "restart", "start", "hi", "hello", "menu", "start over", "reset", "namaste"}


def wants_help(text: str) -> bool:
    return (text or "").strip().lower() in {"help", "?", "info", "about"}
