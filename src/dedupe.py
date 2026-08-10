"""Deduplication and merge.

Two records are the same scheme when their normalized names match and their
providers are compatible. Merging keeps the more complete value per field and
records the loser's name as an alias, so nothing is lost silently.

Where two sources disagree on a *factual* value — a deadline, an income ceiling
— we keep the one from the more authoritative source and flag the record for
review rather than quietly picking one. A conflict is information.
"""

from __future__ import annotations

from collections import defaultdict

import normalize as N
from schema import Scholarship, LIST_FIELDS, COMPLETENESS_FIELDS

# Higher wins when two sources disagree on a fact.
SOURCE_AUTHORITY = {
    "NSP": 3,
    "official": 2,
    "Buddy4Study(discovery)": 0,
}

CONFLICT_FIELDS = ["application_deadline", "income_ceiling_inr",
                   "benefit_amount_max_inr", "number_of_awards"]


def _authority(s: Scholarship) -> int:
    return SOURCE_AUTHORITY.get(s.source_name or "", 1)


def _provider_key(s: Scholarship) -> str:
    p = (s.provider_name or s.administering_body or "").lower()
    return N.normalize_name(p) or ""


def _compatible(a: Scholarship, b: Scholarship) -> bool:
    """Same name; providers must not actively contradict each other."""
    pa, pb = _provider_key(a), _provider_key(b)
    if pa and pb and pa != pb:
        # Same scheme name under genuinely different providers = different schemes,
        # unless one is a substring of the other (abbreviation vs full name).
        if pa not in pb and pb not in pa:
            return False
    # A state-specific variant is distinct from another state's variant.
    sa = {x for x in (a.states or []) if x.lower() != "all"}
    sb = {x for x in (b.states or []) if x.lower() != "all"}
    if sa and sb and not (sa & sb):
        return False
    return True


def _merge_pair(base: Scholarship, other: Scholarship) -> Scholarship:
    conflicts: list[str] = []
    base_auth, other_auth = _authority(base), _authority(other)

    for f in COMPLETENESS_FIELDS + ["class_min", "class_max", "age_min", "age_max",
                                    "min_marks_percent", "duration_years",
                                    "renewable", "orphan_or_single_parent",
                                    "entrance_exam_required", "religion_specific",
                                    "disability", "other_criteria",
                                    "renewal_criteria", "application_start_date",
                                    "deadline_is_tentative", "scheme_year",
                                    "typical_announcement_month"]:
        bv, ov = getattr(base, f, None), getattr(other, f, None)
        if f in LIST_FIELDS:
            merged = list(dict.fromkeys((bv or []) + (ov or [])))
            setattr(base, f, merged)
            continue
        if bv in (None, "", []):
            if ov not in (None, "", []):
                setattr(base, f, ov)
        elif ov not in (None, "", []) and bv != ov and f in CONFLICT_FIELDS:
            conflicts.append(f"{f}: {bv!r} vs {ov!r}")
            if other_auth > base_auth:
                setattr(base, f, ov)

    for f in LIST_FIELDS:
        bv, ov = getattr(base, f, None) or [], getattr(other, f, None) or []
        setattr(base, f, list(dict.fromkeys(list(bv) + list(ov))))

    if other.name and other.name != base.name and other.name not in base.aliases:
        base.aliases.append(other.name)

    if other_auth > base_auth and other.source_name:
        base.source_name = other.source_name
    if not base.official_url and other.official_url:
        base.official_url = other.official_url

    if conflicts:
        base.needs_review = True
        prior = base.needs_review_reason
        reason = "source conflict -> " + "; ".join(conflicts[:3])
        base.needs_review_reason = f"{prior}; {reason}" if prior else reason
        base.confidence = "medium"

    base.field_completeness_percent = base.completeness()
    return base


def deduplicate(records: list[Scholarship]) -> tuple[list[Scholarship], dict]:
    """Collapse duplicates. Returns (merged_records, stats)."""
    buckets: dict[str, list[Scholarship]] = defaultdict(list)
    for s in records:
        key = s.name_normalized or N.normalize_name(s.name) or (s.name or "")
        buckets[key].append(s)

    merged: list[Scholarship] = []
    n_merged = 0
    for key, group in buckets.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        # Most authoritative, then most complete, becomes the base.
        group.sort(key=lambda r: (-_authority(r), -(r.field_completeness_percent or 0)))
        kept: list[Scholarship] = []
        for cand in group:
            target = next((k for k in kept if _compatible(k, cand)), None)
            if target is None:
                kept.append(cand)
            else:
                _merge_pair(target, cand)
                n_merged += 1
        merged.extend(kept)

    for s in merged:
        s.id = N.make_id(s.name_normalized,
                         s.provider_name or s.administering_body)
        s.field_completeness_percent = s.completeness()

    # An id collision after merging means two genuinely distinct schemes hashed
    # alike; disambiguate rather than dropping one.
    seen_ids: dict[str, int] = {}
    for s in merged:
        if s.id in seen_ids:
            seen_ids[s.id] += 1
            s.id = f"{s.id}-{seen_ids[s.id]}"
        else:
            seen_ids[s.id] = 0

    return merged, {"input": len(records), "output": len(merged), "merged": n_merged}
