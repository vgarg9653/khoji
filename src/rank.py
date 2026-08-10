"""reach_score — how many students a scheme can plausibly serve.

This is a reach measure, not a quality measure. A national scheme open to every
category outranks an excellent but district-limited one, because the WhatsApp
bot's job is to surface what the most students can actually use.

Scoring is additive and bounded per component, so no single dimension can
dominate. Components where the source said nothing score 0 rather than a
midpoint guess — a scheme that hid its details does not get credit for them.
"""

from __future__ import annotations

from schema import Scholarship

# Component ceilings. They sum to 100.
W_GEOGRAPHY = 34
W_CATEGORY = 18
W_LEVEL = 18
W_AWARDS = 18
W_RECURRENCE = 12

_ALL_LEVELS = ["school", "ITI", "diploma", "UG", "PG", "PhD", "professional"]


def _geography_score(s: Scholarship) -> float:
    states = s.states or []
    if any(x.lower() == "all" for x in states):
        return W_GEOGRAPHY
    n = len({x for x in states if x.lower() != "all"})
    if s.districts:
        return 4.0                       # district-limited: narrowest real reach
    if n == 0:
        return 0.0                       # scope not stated
    if n == 1:
        return 14.0
    if n <= 3:
        return 20.0
    if n <= 8:
        return 26.0
    return 30.0                          # multi-state but not declared national


def _category_score(s: Scholarship) -> float:
    cats = {c.lower() for c in (s.categories or [])}
    if not cats:
        return 0.0
    if "all" in cats or "general" in cats:
        base = W_CATEGORY
    else:
        # Each additional eligible category widens the pool, with diminishing returns.
        base = min(W_CATEGORY, 6.0 + 3.5 * len(cats))
    # A scheme restricted to one gender reaches roughly half the pool.
    if s.gender in ("female", "male"):
        base *= 0.75
    if s.religion_specific:
        base *= 0.8
    return round(base, 2)


def _level_score(s: Scholarship) -> float:
    levels = {l for l in (s.education_levels or [])}
    courses = {c for c in (s.course_types or [])}
    span = levels | courses
    if not span:
        # Fall back to an explicit class range if levels were not tagged.
        if s.class_min is not None and s.class_max is not None:
            width = s.class_max - s.class_min + 1
            return min(W_LEVEL, 3.0 + 1.2 * width)
        return 0.0
    return min(W_LEVEL, 4.0 + 2.6 * len(span))


def _awards_score(s: Scholarship) -> float:
    n = s.number_of_awards
    if not n or n <= 0:
        return 0.0
    # Log-ish banding: 100k slots is not 1000x more valuable than 100.
    for threshold, pts in ((100_000, W_AWARDS), (20_000, 15.0), (5_000, 12.0),
                           (1_000, 9.0), (200, 6.0), (50, 3.5)):
        if n >= threshold:
            return pts
    return 2.0


def _recurrence_score(s: Scholarship) -> float:
    pts = 0.0
    if s.renewable is True:
        pts += 7.0
    elif s.renewable is False:
        pts += 2.0
    if s.duration_years and s.duration_years >= 2:
        pts += 3.0
    if s.scheme_year or s.typical_announcement_month:
        pts += 2.0
    return min(W_RECURRENCE, pts)


def compute_reach_score(s: Scholarship) -> float:
    total = (_geography_score(s) + _category_score(s) + _level_score(s)
             + _awards_score(s) + _recurrence_score(s))
    # Verified, currently-open schemes are what the bot should surface first.
    if s.status == "active":
        total *= 1.08
    elif s.status == "expired":
        total *= 0.55
    return round(min(total, 100.0), 2)


def score_breakdown(s: Scholarship) -> dict[str, float]:
    return {
        "geography": round(_geography_score(s), 2),
        "category": round(_category_score(s), 2),
        "level": round(_level_score(s), 2),
        "awards": round(_awards_score(s), 2),
        "recurrence": round(_recurrence_score(s), 2),
        "total": compute_reach_score(s),
    }


def rank_all(records: list[Scholarship], top_n: int = 100) -> list[Scholarship]:
    """Score, sort, and tag the top N. Expired records are ranked but never
    promoted into the top tier ahead of an active one, because the score already
    penalises them."""
    for s in records:
        s.reach_score = compute_reach_score(s)

    ordered = sorted(
        records,
        key=lambda r: (-(r.reach_score or 0), -(r.field_completeness_percent or 0),
                       r.name or ""),
    )
    for i, s in enumerate(ordered, start=1):
        s.rank = i
        s.tier = "top100" if i <= top_n else "backlog"
    return ordered
