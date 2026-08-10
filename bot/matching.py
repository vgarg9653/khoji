"""Eligibility matching for the Khoji.AI bot.

The whole module exists to enforce one distinction the dataset insists on:

    a criterion the student fails          -> NOT_ELIGIBLE
    a criterion the source never stated    -> UNKNOWN

These are not the same, and collapsing them is how a bot ends up telling a
student they qualify for something they don't. Nothing here returns a bare
boolean; callers must decide how to present UNKNOWN, and the message layer
shows it as "not stated - check the official page".
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

import relevance


class Verdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class StudentProfile:
    """What we know about the student. Every field is optional — the bot asks
    for what it can and matches on the rest."""
    state: str | None = None
    education_level: str | None = None     # school | ITI | diploma | UG | PG | PhD | professional
    category: str | None = None            # SC | ST | OBC | EWS | minority | PwD | DNT | general
    family_income_inr: int | None = None
    gender: str | None = None              # female | male | transgender
    class_level: int | None = None         # 1-12, for school students
    is_orphan_or_single_parent: bool | None = None

    # --- where they want to go, not where they are ------------------------
    # These never remove anything the student qualifies for today. They decide
    # which *aspirational* suggestions are worth making, and nothing else — see
    # relevance.bucket(). "unsure" is a normal answer and is stored as such.
    name: str | None = None
    intended_next_level: str | None = None   # a stage on relevance.STAGE_RANK
    field_of_interest: str | None = None     # engineering | medical | law | …
    wants_higher_studies: str | None = None  # yes | no | unsure
    open_to_relocate: bool | None = None

    # Fields that describe the student rather than what they are eligible for.
    # known_fields() feeds the "matched on" line, so these stay out of it.
    _NON_MATCHING = ("name", "intended_next_level", "field_of_interest",
                     "wants_higher_studies", "open_to_relocate")

    def known_fields(self) -> list[str]:
        return [k for k, v in self.__dict__.items()
                if v is not None and k not in self._NON_MATCHING]


@dataclass
class CriterionResult:
    name: str
    verdict: Verdict
    detail: str = ""


@dataclass
class MatchResult:
    scholarship: dict
    verdict: Verdict
    criteria: list[CriterionResult] = field(default_factory=list)
    score: float = 0.0
    # Set by relevance.split(). "now" | "later" | "suppress" — eligibility says
    # the student *can* apply, this says whether it is worth their attention.
    relevance: str = "now"
    relevance_reason: str = ""

    @property
    def unknowns(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.verdict is Verdict.UNKNOWN]

    @property
    def failures(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.verdict is Verdict.NOT_ELIGIBLE]


# --------------------------------------------------------------- criteria

def _check_state(s: dict, p: StudentProfile) -> CriterionResult:
    states = s.get("states") or []
    if not states:
        return CriterionResult("state", Verdict.UNKNOWN, "scheme did not state its scope")
    if any(x.lower() == "all" for x in states):
        return CriterionResult("state", Verdict.ELIGIBLE, "open across India")
    if p.state is None:
        return CriterionResult("state", Verdict.UNKNOWN, "student state not provided")
    if p.state in states:
        return CriterionResult("state", Verdict.ELIGIBLE, f"open in {p.state}")
    return CriterionResult("state", Verdict.NOT_ELIGIBLE,
                           f"only for {', '.join(states[:3])}")


def _check_level(s: dict, p: StudentProfile) -> CriterionResult:
    levels = s.get("education_levels") or []
    if not levels:
        return CriterionResult("education_level", Verdict.UNKNOWN,
                               "scheme did not state a level")
    if p.education_level is None:
        return CriterionResult("education_level", Verdict.UNKNOWN,
                               "student level not provided")
    if p.education_level in levels:
        return CriterionResult("education_level", Verdict.ELIGIBLE,
                               f"covers {p.education_level}")
    return CriterionResult("education_level", Verdict.NOT_ELIGIBLE,
                           f"for {', '.join(levels[:3])}")


def _check_category(s: dict, p: StudentProfile) -> CriterionResult:
    """Category eligibility.

    A scheme that lists no category is treated as not restricting by category —
    the same way a scheme that names no gender is treated as open to all
    genders. Schemes that DO restrict say so in their own title ("for SC
    students", "for Minority students"), so an empty list is a statement about
    the source rather than a hole in it.

    Income is deliberately NOT treated this way. Income ceilings are near
    universal in Indian scholarships, so a missing one is far more likely to be
    a failure to extract than an absence of any limit, and guessing there would
    tell a student they qualify when they may not.
    """
    cats = s.get("categories") or []
    if not cats:
        return CriterionResult("category", Verdict.ELIGIBLE,
                               "no category restriction stated")
    if any(c.lower() in ("all", "general") for c in cats):
        return CriterionResult("category", Verdict.ELIGIBLE, "open to all categories")
    if p.category is None:
        return CriterionResult("category", Verdict.UNKNOWN,
                               "student category not provided")
    if p.category in cats:
        return CriterionResult("category", Verdict.ELIGIBLE, f"for {p.category} students")
    return CriterionResult("category", Verdict.NOT_ELIGIBLE,
                           f"only for {', '.join(cats)}")


def _check_income(s: dict, p: StudentProfile) -> CriterionResult:
    ceiling = s.get("income_ceiling_inr")
    if ceiling is None:
        # The most common gap in the dataset, and the one most likely to mislead.
        return CriterionResult("income", Verdict.UNKNOWN,
                               "income limit not stated by the source")
    if p.family_income_inr is None:
        return CriterionResult("income", Verdict.UNKNOWN,
                               f"limit is Rs {ceiling:,} - student income not provided")
    if p.family_income_inr <= ceiling:
        return CriterionResult("income", Verdict.ELIGIBLE,
                               f"under the Rs {ceiling:,} limit")
    return CriterionResult("income", Verdict.NOT_ELIGIBLE,
                           f"family income above the Rs {ceiling:,} limit")


def _check_gender(s: dict, p: StudentProfile) -> CriterionResult:
    g = s.get("gender")
    if not g or g == "any":
        return CriterionResult("gender", Verdict.ELIGIBLE, "no gender restriction")
    if p.gender is None:
        return CriterionResult("gender", Verdict.UNKNOWN,
                               f"scheme is for {g} students - not provided")
    if p.gender == g:
        return CriterionResult("gender", Verdict.ELIGIBLE, f"for {g} students")
    return CriterionResult("gender", Verdict.NOT_ELIGIBLE, f"only for {g} students")


def _check_class(s: dict, p: StudentProfile) -> CriterionResult | None:
    """Class only means anything for school-level schemes.

    Returning UNKNOWN for a PhD scholarship because it states no class range
    would attach a "⚠️ check: class" warning to almost every record. Students
    who see a warning on everything stop reading warnings, so a criterion that
    does not apply is skipped rather than flagged.
    """
    lo, hi = s.get("class_min"), s.get("class_max")
    scheme_is_school = "school" in (s.get("education_levels") or [])
    student_is_school = p.education_level == "school"

    if lo is None and hi is None:
        if not scheme_is_school or not student_is_school:
            return None                      # not applicable
        return CriterionResult("class", Verdict.UNKNOWN, "class range not stated")
    if p.class_level is None:
        rng = f"class {lo}-{hi}" if lo and hi else f"class {lo or hi}"
        return CriterionResult("class", Verdict.UNKNOWN,
                               f"scheme covers {rng} - student class not provided")
    if lo is not None and p.class_level < lo:
        return CriterionResult("class", Verdict.NOT_ELIGIBLE, f"starts at class {lo}")
    if hi is not None and p.class_level > hi:
        return CriterionResult("class", Verdict.NOT_ELIGIBLE, f"ends at class {hi}")
    return CriterionResult("class", Verdict.ELIGIBLE, f"covers class {p.class_level}")


CRITERIA = [_check_state, _check_level, _check_category, _check_income,
            _check_gender, _check_class]


# ----------------------------------------------------------------- engine

def evaluate(s: dict, p: StudentProfile) -> MatchResult:
    """Score one scholarship against one student.

    A single NOT_ELIGIBLE sinks the whole match — the student genuinely cannot
    apply. UNKNOWNs never disqualify; they are carried through so the bot can
    say what still needs checking.
    """
    # A check returning None means the criterion does not apply to this pairing.
    results = [r for r in (check(s, p) for check in CRITERIA) if r is not None]

    if any(c.verdict is Verdict.NOT_ELIGIBLE for c in results):
        verdict = Verdict.NOT_ELIGIBLE
    elif any(c.verdict is Verdict.UNKNOWN for c in results):
        verdict = Verdict.UNKNOWN
    else:
        verdict = Verdict.ELIGIBLE

    n_known = sum(1 for c in results if c.verdict is Verdict.ELIGIBLE)
    reach = float(s.get("reach_score") or 0)

    # Relevance beats reach when ranking for ONE student.
    #
    # reach_score answers "how many students nationally can use this?", which is
    # the right question when choosing what to crawl and verify. It is the wrong
    # question here: a Rajasthan-only scheme scores low on reach yet is exactly
    # what a Rajasthan student should see first. Without this, 26 Rajasthan
    # schemes sat in the catalogue and never once appeared in a Rajasthan
    # student's results, buried under national schemes with broader reach.
    scheme_states = {x for x in (s.get("states") or []) if x.lower() != "all"}
    if p.state and p.state in scheme_states:
        specificity = 120 - 8 * min(len(scheme_states), 10)   # narrower = better
    else:
        specificity = 0
    # Rank by how confidently the student matches, then by how many students the
    # scheme can serve. The whole catalogue is served, but records that were
    # re-checked against their official source surface first — an unverified
    # record is useful, not equally trustworthy.
    score = n_known * 100 + reach + specificity
    if s.get("tier") == "top100":
        score += 60
    if s.get("confidence") == "high":
        score += 40
    if s.get("needs_review"):
        score -= 15
    if verdict is Verdict.ELIGIBLE:
        score += 1000

    return MatchResult(scholarship=s, verdict=verdict, criteria=results, score=score)


# The criteria that describe *how far along* a student is rather than who they
# are. Failing only these means "not yet", which is a different answer from "not
# you" — and the only one worth keeping as a plan-ahead suggestion.
_STAGE_CRITERIA = {"education_level", "class"}

_FAR_FUTURE = "9999-12-31"


def _rank_key(r: "MatchResult"):
    """Ordering a student can make sense of, and that never shuffles.

    Score first. Then, among equally good matches, the one closing soonest —
    because a deadline is the only thing here the student can miss. Schemes with
    no published deadline sort last rather than first, since "unknown" is not
    urgent. Completeness and id break any remaining tie so the list is stable
    between messages; an order that changes under the reader looks broken.
    """
    s = r.scholarship
    deadline = s.get("application_deadline") or _FAR_FUTURE
    return (-r.score, deadline,
            -(s.get("field_completeness_percent") or 0),
            str(s.get("id") or ""))


class Matcher:
    def __init__(self, records: list[dict]):
        self.records = records

    @classmethod
    def from_file(cls, path: str | pathlib.Path) -> "Matcher":
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return cls(data)

    def match(self, p: StudentProfile, *, limit: int = 5,
              include_unknown: bool = True,
              exclude_expired: bool = True) -> list[MatchResult]:
        """Best matches for a student: what they can use now, then what's next.

        Two filters in sequence, both rules-only. Eligibility decides who *can*
        apply. Relevance decides what is worth showing — a B.Tech student is
        eligible for plenty of school schemes, and every one of them shown is a
        line that pushed something usable off the screen.
        """
        today = date.today().isoformat()
        out: list[MatchResult] = []
        ahead: list[MatchResult] = []
        for s in self.records:
            if exclude_expired:
                dl = s.get("application_deadline")
                if dl and dl < today:
                    continue
                if s.get("status") == "expired":
                    continue
            r = evaluate(s, p)
            if r.verdict is Verdict.NOT_ELIGIBLE:
                # A student in Class 12 fails a UG scholarship on exactly one
                # criterion — the level they have not reached yet. Dropping it
                # here is why "plan ahead" used to be empty for everyone: the
                # eligibility filter had already eaten every candidate for it.
                # So a record that fails ONLY on how far along the student is
                # survives, and relevance decides whether it is a realistic
                # next step or simply out of reach.
                if {c.name for c in r.failures} <= _STAGE_CRITERIA:
                    ahead.append(r)
                continue
            if r.verdict is Verdict.UNKNOWN and not include_unknown:
                continue
            out.append(r)
        out.sort(key=_rank_key)
        ahead.sort(key=_rank_key)

        now, later, hidden = relevance.split(out, p)
        # Anything from `ahead` that relevance does not call LATER is genuinely
        # not for this student — it only reappears in the last-resort fallback
        # below, and only when nothing else survived at all.
        _, ahead_later, ahead_hidden = relevance.split(ahead, p)
        later += ahead_later
        hidden += ahead_hidden
        hidden.sort(key=_rank_key)

        # One slot goes to "plan ahead" when the list would otherwise be full of
        # today's options — a Class 10 student who never sees what exists after
        # Class 12 learns nothing about where they could go.
        reserve_later = 1 if (later and len(now) >= limit) else 0
        chosen = self._with_home_state(now, p, max(limit - reserve_later, 0))
        chosen += later[:limit - len(chosen)]

        if chosen:
            return chosen
        # Relevance suppressed everything the student was eligible for. Showing
        # nothing would be worse than showing these with an honest label, so
        # they go out still marked "suppress" and the message layer says why.
        return hidden[:limit]

    @staticmethod
    def _rank_key_public(r):        # exposed for tests
        return _rank_key(r)

    @staticmethod
    def _with_home_state(ranked: list[MatchResult], p: StudentProfile,
                         limit: int, reserve: int = 2) -> list[MatchResult]:
        """Guarantee the student sees schemes from their own state.

        Pure score ordering buries them: a national scheme with every criterion
        confirmed will always outscore a state scheme whose education level the
        source never stated. In testing this meant a Rajasthan student saw five
        national schemes and none of the 22 from Rajasthan — which is the wrong
        product outcome even though the ranking was arithmetically right.

        So up to `reserve` of the slots go to home-state schemes when any exist.
        They are still ranked among themselves, and nothing unqualified is
        introduced: these results already passed eligibility.
        """
        if not p.state or limit <= 0:
            return ranked[:limit]

        def is_home(r: MatchResult) -> bool:
            states = r.scholarship.get("states") or []
            return p.state in states and not any(s.lower() == "all" for s in states)

        top = ranked[:limit]
        if sum(1 for r in top if is_home(r)) >= min(reserve, limit):
            return top

        home = [r for r in ranked if is_home(r)]
        if not home:
            return top

        keep_home = home[:min(reserve, limit)]
        others = [r for r in ranked if r not in keep_home]
        merged = (keep_home + others)[:limit]
        merged.sort(key=_rank_key)
        return merged

    def by_id(self, scholarship_id: str) -> dict | None:
        """Look up one record, so a shortlist can be rebuilt from stored ids."""
        if not hasattr(self, "_index"):
            self._index = {r.get("id"): r for r in self.records if r.get("id")}
        return self._index.get(scholarship_id)

    def rehydrate(self, ids: list[str], p: StudentProfile) -> list[MatchResult]:
        """Rebuild the previously-shown shortlist, in the same order."""
        out = []
        for sid in ids or []:
            rec = self.by_id(sid)
            if rec is not None:
                out.append(evaluate(rec, p))
        return out

    def stats(self) -> dict:
        return {
            "records": len(self.records),
            "with_income_ceiling": sum(1 for r in self.records
                                       if r.get("income_ceiling_inr")),
            "with_deadline": sum(1 for r in self.records
                                 if r.get("application_deadline")),
            "verified": sum(1 for r in self.records if r.get("confidence") == "high"),
        }
