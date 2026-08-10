"""Is this scholarship relevant to *this* student, right now?

Eligibility and relevance are different questions, and answering only the first
one produces results that are technically correct and practically useless. A
B.Tech student is genuinely eligible for a school coaching scheme that names no
upper level — the rules pass — but showing it wastes the one screen of attention
we get.

So after `matching.py` decides who *can* apply, this module decides what is
worth putting in front of them, and sorts the survivors into two labelled
buckets:

    APPLICABLE_NOW   fits what they are studying today
    ASPIRATIONAL     one realistic step ahead on the path they told us about

Anything that is neither is suppressed. Nothing here uses a language model —
relevance is as deterministic as eligibility, for the same reason.

Two halves live here on purpose:

  * `tag()` runs at BUILD time (`src/make_deliverables.py`) and bakes the
    scheme-side facts into the dataset, so they can be inspected and diffed.
  * `bucket()` runs at REQUEST time and needs the student.

They share the stage ladder below, which is the whole reason they are one file.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------- the ladder
#
# Indian education is not a single line, so this is a rank rather than a
# sequence: ITI, diploma, UG and professional courses all follow Class 12 and
# none of them follows the others. Two schemes are "one step apart" when their
# ranks differ by one, whichever branch they sit on.

SCHOOL_PRIMARY = "school_primary"        # Class 1–8
SCHOOL_SECONDARY = "school_secondary"    # Class 9–10
SCHOOL_SENIOR = "school_senior"          # Class 11–12

STAGE_RANK: dict[str, int] = {
    SCHOOL_PRIMARY: 0,
    SCHOOL_SECONDARY: 1,
    SCHOOL_SENIOR: 2,
    "ITI": 3,
    "diploma": 3,
    "UG": 3,
    "professional": 3,
    "PG": 4,
    "PhD": 5,
}

# What a student at each stage would normally do next. Used only to decide
# whether an aspirational suggestion is realistic, never to filter.
NEXT_STAGES: dict[str, tuple[str, ...]] = {
    SCHOOL_PRIMARY: (SCHOOL_SECONDARY,),
    SCHOOL_SECONDARY: (SCHOOL_SENIOR,),
    SCHOOL_SENIOR: ("ITI", "diploma", "UG", "professional"),
    "ITI": ("diploma", "UG"),
    "diploma": ("UG", "professional"),
    "UG": ("PG", "professional"),
    "professional": ("PG",),
    "PG": ("PhD",),
    "PhD": (),
}

NOW = "now"
LATER = "later"
SUPPRESS = "suppress"


# ------------------------------------------------------------ scheme tagging

# A coaching or test-prep scheme pays for classes towards an exam. It is the
# clearest case of "eligible but wrong": the rules rarely name an upper level,
# so it matches everybody.
_COACHING = re.compile(
    r"\bcoach|coaching|test[- ]prep|entrance (?:exam|test) prep|"
    r"pre[- ]?examination training|free coaching\b", re.I)

# Which exam the coaching is for decides who it is actually useful to.
_TARGET_AFTER_SCHOOL = re.compile(
    r"\bneet\b|\bjee\b|\bcet\b|\bnata\b|\bclat\b|medical entrance|"
    r"engineering entrance|professional (?:entrance|course) exam", re.I)
_TARGET_SERVICES = re.compile(
    r"\bupsc\b|\brpsc\b|\bssc\b|\bias\b|\bips\b|\brbi\b|civil service|"
    r"public service commission|competitive exam|banking (?:service|exam)|"
    r"staff selection", re.I)

_RESEARCH = re.compile(r"\bresearch fellow|fellowship for research|\bjrf\b|\bsrf\b|"
                       r"doctoral|post[- ]?doctoral", re.I)

_STREAMS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bengineer|technical|polytechnic|b\.?tech|m\.?tech|iit\b|nit\b|"
                r"technology institute", re.I), "engineering"),
    (re.compile(r"\bmedical|mbbs|nursing|ayush|ayurved|dental|pharmac|"
                r"health science|paramedic", re.I), "medical"),
    (re.compile(r"\blaw\b|\bllb\b|\bllm\b|legal studies|judicial", re.I), "law"),
    (re.compile(r"\bagricultur|veterinary|horticultur|fisheries", re.I), "agriculture"),
    (re.compile(r"\bmanagement\b|\bmba\b|commerce\b|chartered account", re.I), "commerce"),
    (re.compile(r"\bfine arts|performing arts|music|handicraft|artisan", re.I), "arts"),
]


def _school_bands(class_min: int | None, class_max: int | None) -> list[str]:
    """Which school bands a class range touches. No range stated means all of
    school — the source didn't narrow it, so neither do we."""
    lo = class_min if class_min is not None else 1
    hi = class_max if class_max is not None else 12
    bands = []
    if lo <= 8 and hi >= 1:
        bands.append(SCHOOL_PRIMARY)
    if lo <= 10 and hi >= 9:
        bands.append(SCHOOL_SECONDARY)
    if hi >= 11:
        bands.append(SCHOOL_SENIOR)
    return bands or [SCHOOL_SECONDARY]


def tag(rec: dict) -> dict:
    """Scheme-side relevance facts. Pure function of one record.

    Returns only the new keys, so the caller decides how to merge them.
    """
    name = " ".join(((rec.get("name") or "") + " " +
                     (rec.get("description_short") or "")).split())

    stages: list[str] = []
    for lvl in (rec.get("education_levels") or []):
        if lvl == "school":
            stages.extend(_school_bands(rec.get("class_min"), rec.get("class_max")))
        elif lvl in STAGE_RANK:
            stages.append(lvl)
    # Dedupe while keeping the ladder order, so diffs stay readable.
    stages = sorted(set(stages), key=lambda s: (STAGE_RANK[s], s))

    kind = "study"
    target = None
    if _COACHING.search(name):
        kind = "coaching"
        if _TARGET_SERVICES.search(name):
            target = "competitive_services"
        elif _TARGET_AFTER_SCHOOL.search(name):
            target = "entrance_after_school"
        # A generic "free coaching" scheme keeps target=None and is therefore
        # never suppressed on that basis. Guessing which exam it funds would be
        # exactly the kind of invention this project refuses everywhere else.
    elif _RESEARCH.search(name):
        kind = "research"

    streams = sorted({s for rx, s in _STREAMS if rx.search(name)})

    return {
        "applicable_stages": stages,          # [] means the source never said
        "scheme_kind": kind,                  # study | coaching | research
        "coaching_target": target,
        "stream_tags": streams,               # [] means open to any stream
    }


# ----------------------------------------------------------- student staging

def student_stage(education_level: str | None, class_level: int | None) -> str | None:
    """Where the student is on the ladder, or None if they haven't said."""
    if education_level == "school":
        if class_level is None:
            return None          # "school" alone is too broad to place
        if class_level <= 8:
            return SCHOOL_PRIMARY
        if class_level <= 10:
            return SCHOOL_SECONDARY
        return SCHOOL_SENIOR
    if education_level in STAGE_RANK:
        return education_level
    if class_level is not None:
        return student_stage("school", class_level)
    return None


# ------------------------------------------------------------ the decision

def bucket(rec: dict, stage: str | None, *,
           field_of_interest: str | None = None,
           wants_higher_studies: str | None = None,
           intended_next_level: str | None = None) -> tuple[str, str]:
    """(NOW | LATER | SUPPRESS, human-readable reason).

    Every branch that suppresses something has to be sure. When the source
    didn't state a level, or the student hasn't told us theirs, the answer is
    NOW — showing a possibly-irrelevant scholarship costs a line of screen;
    hiding a relevant one costs the student the scholarship.
    """
    stages = rec.get("applicable_stages") or []
    kind = rec.get("scheme_kind") or "study"

    # --- coaching, judged before anything else -----------------------------
    # A coaching scheme's own level list is usually junk (it inherits whatever
    # the guideline PDF mentioned in passing), so the exam it funds decides.
    if kind == "coaching":
        target = rec.get("coaching_target")
        if stage is None or target is None:
            return NOW, "coaching support"
        rank = STAGE_RANK[stage]
        if target == "entrance_after_school":
            if rank >= 3:
                return SUPPRESS, "coaching for an entrance exam you have passed"
            return (NOW, "coaching for the entrance exam ahead of you") if rank == 2 \
                else (LATER, "coaching for the entrance exam after Class 12")
        if target == "competitive_services":
            if rank <= 1:
                return SUPPRESS, "civil-services coaching, years away yet"
            if rank == 2:
                return LATER, "civil-services coaching, after your degree"
            return NOW, "civil-services coaching"

    if not stages:
        return NOW, "the source did not state a study level"
    if stage is None:
        return NOW, "your study level is not confirmed yet"

    if stage in stages:
        # Right stage — but a stream-specific scheme still has to match the
        # stream, once the student is old enough to have one.
        if (field_of_interest and rec.get("stream_tags")
                and STAGE_RANK[stage] >= 2
                and field_of_interest not in rec["stream_tags"]):
            return SUPPRESS, f"for {', '.join(rec['stream_tags'])} students"
        return NOW, "matches what you are studying now"

    rank = STAGE_RANK[stage]
    scheme_min = min(STAGE_RANK[s] for s in stages)

    if scheme_min <= rank:
        # Entirely behind them: a Class 9–10 scheme shown to a B.Sc. student.
        return SUPPRESS, "for an earlier stage of study"

    if scheme_min > rank + 1:
        return SUPPRESS, "more than one step ahead of where you are"

    # Exactly one step ahead — aspirational, if they're heading that way.
    if wants_higher_studies == "no":
        return SUPPRESS, "you said you are not planning further study"
    if wants_higher_studies == "unsure":
        # They told us they don't know yet. Guessing a path on their behalf is
        # exactly what "not sure" asked us not to do, so today's options only.
        return SUPPRESS, "you are still deciding what comes next"
    if intended_next_level and intended_next_level in STAGE_RANK:
        if not any(s == intended_next_level for s in stages) and \
                STAGE_RANK[intended_next_level] != scheme_min:
            return SUPPRESS, "not on the path you described"
    if not any(s in NEXT_STAGES.get(stage, ()) for s in stages):
        return SUPPRESS, "not a usual next step from where you are"

    return LATER, _later_reason(rec, stages)


# Anchored to where the SCHEME starts, not to where the student is. "Apply
# after Class 10" is ambiguous; "apply once you reach Class 11" tells them the
# exact moment this becomes theirs.
_ENTRY_PHRASE = {
    SCHOOL_SECONDARY: "once you reach Class 9",
    SCHOOL_SENIOR: "once you reach Class 11",
    "ITI": "if you join an ITI",
    "diploma": "if you join a diploma course",
    "UG": "once you start your degree",
    "professional": "if you join a professional course",
    "PG": "after your degree, for a master's",
    "PhD": "after your master's, for research",
}


def _later_reason(rec: dict, stages: list[str]) -> str:
    entry = min(stages, key=lambda s: STAGE_RANK[s])
    # A scheme that names its own starting class beats the band it falls in:
    # "once you reach Class 12" is exact, "once you reach Class 11" is the band.
    lo = rec.get("class_min")
    if entry in (SCHOOL_SECONDARY, SCHOOL_SENIOR) and lo:
        return f"for later — apply once you reach Class {lo}"
    return ("for later — apply "
            + _ENTRY_PHRASE.get(entry, "once you move up a level"))


def split(results, profile) -> tuple[list, list, list]:
    """Sort matches into (applicable now, aspirational, suppressed).

    `results` are MatchResult objects that already passed eligibility; this only
    ever reorders and hides. Each surviving result gets `.relevance` and
    `.relevance_reason` attached so the message layer can label it without
    recomputing anything.
    """
    stage = student_stage(getattr(profile, "education_level", None),
                          getattr(profile, "class_level", None))
    now, later, hidden = [], [], []
    for r in results:
        b, why = bucket(
            r.scholarship, stage,
            field_of_interest=getattr(profile, "field_of_interest", None),
            wants_higher_studies=getattr(profile, "wants_higher_studies", None),
            intended_next_level=getattr(profile, "intended_next_level", None),
        )
        r.relevance, r.relevance_reason = b, why
        (now if b == NOW else later if b == LATER else hidden).append(r)
    return now, later, hidden
