"""Exports and the summary report."""

from __future__ import annotations

import csv
import json
import pathlib
from collections import Counter
from dataclasses import asdict

from schema import Scholarship, FIELD_NAMES, row_to_scholarship

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"

# Exported column order: identity first, then what a student needs to decide.
EXPORT_ORDER = [
    "rank", "id", "name", "aliases", "provider_name", "provider_type",
    "administering_body", "scheme_year",
    "education_levels", "class_min", "class_max", "course_types", "field_of_study",
    "states", "districts", "categories", "religion_specific", "gender",
    "income_ceiling_inr", "income_evidence", "disability", "disability_type",
    "min_marks_percent",
    "grade_criteria", "entrance_exam_required", "entrance_exam_name",
    "age_min", "age_max", "orphan_or_single_parent", "parent_occupation_specific",
    "other_criteria",
    "benefit_amount_min_inr", "benefit_amount_max_inr", "benefit_amount_text",
    "benefit_type", "duration_years", "renewable", "renewal_criteria",
    "number_of_awards",
    "application_mode", "application_url", "application_start_date",
    "application_deadline", "deadline_is_tentative", "selection_process",
    "typical_announcement_month",
    "documents_required", "documents_other",
    "tier", "official_url", "source_url", "source_name", "extraction_date",
    "last_verified_date", "status", "confidence", "needs_review",
    "needs_review_reason", "reach_score", "servable", "not_servable_reason", "field_completeness_percent",
    "description_short", "languages_of_official_page",
]


def load_records(conn, tier: str | None = None,
                 statuses: tuple[str, ...] | None = None) -> list[Scholarship]:
    q = "SELECT * FROM scholarships"
    where, args = [], []
    if tier:
        where.append("tier = ?")
        args.append(tier)
    if statuses:
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        args.extend(statuses)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY CASE WHEN rank IS NULL THEN 1 ELSE 0 END, rank"
    return [row_to_scholarship(r) for r in conn.execute(q, args)]


def _flat(v):
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else v


def export_csv(records: list[Scholarship], path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_ORDER, extrasaction="ignore")
        w.writeheader()
        for s in records:
            d = asdict(s)
            w.writerow({k: _flat(d.get(k)) for k in EXPORT_ORDER})


def export_json(records: list[Scholarship], path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for s in records:
        d = asdict(s)
        out.append({k: d.get(k) for k in EXPORT_ORDER})
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def export_review_queue(rows: list[dict], path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["scholarship_id", "name", "rank", "reason", "field", "stored_value",
            "found_value", "snippet", "official_url"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _flat(r.get(k)) for k in cols})


# ------------------------------------------------------------------- report

def _bar(n: int, total: int, width: int = 28) -> str:
    if not total:
        return ""
    filled = int(round(width * n / total))
    return "█" * filled + "·" * (width - filled)


def build_report(all_records: list[Scholarship], top: list[Scholarship],
                 crawl_stats: dict | None = None) -> str:
    L: list[str] = []
    A = L.append
    A("=" * 78)
    A("Khoji.AI — scholarship dataset summary")
    A("=" * 78)

    A(f"\nTotal records in db : {len(all_records)}")
    A(f"Top-100 tier        : {len(top)}")
    A(f"Backlog tier        : {len(all_records) - len(top)}")

    if crawl_stats:
        A(f"\nCrawl: {crawl_stats}")

    # --- provider type ---
    A("\n" + "-" * 78)
    A("TOP 100 — counts by provider_type")
    A("-" * 78)
    c = Counter(s.provider_type or "(unknown)" for s in top)
    for k, v in c.most_common():
        A(f"  {k:<16} {v:>4}  {_bar(v, len(top))}")

    # --- state coverage ---
    A("\n" + "-" * 78)
    A("TOP 100 — state / geography coverage")
    A("-" * 78)
    national = sum(1 for s in top if any(x.lower() == "all" for x in (s.states or [])))
    unstated = sum(1 for s in top if not s.states)
    A(f"  national (all states)  {national:>4}  {_bar(national, len(top))}")
    A(f"  scope not stated       {unstated:>4}  {_bar(unstated, len(top))}")
    st = Counter(x for s in top for x in (s.states or []) if x.lower() != "all")
    if st:
        A("  named states:")
        for k, v in st.most_common(15):
            A(f"    {k:<34} {v:>3}")
        A(f"  distinct states represented: {len(st)}")

    # --- level coverage ---
    A("\n" + "-" * 78)
    A("TOP 100 — education level coverage")
    A("-" * 78)
    lv = Counter(x for s in top for x in (s.education_levels or []))
    if lv:
        for k, v in lv.most_common():
            A(f"  {k:<16} {v:>4}  {_bar(v, len(top))}")
    A(f"  level not stated  {sum(1 for s in top if not s.education_levels):>4}")

    # --- category coverage ---
    A("\n" + "-" * 78)
    A("TOP 100 — category coverage")
    A("-" * 78)
    ct = Counter(x for s in top for x in (s.categories or []))
    for k, v in ct.most_common():
        A(f"  {k:<16} {v:>4}  {_bar(v, len(top))}")
    A(f"  category not stated {sum(1 for s in top if not s.categories):>4}")

    # --- completeness & trust ---
    A("\n" + "-" * 78)
    A("TOP 100 — completeness and trust")
    A("-" * 78)
    comp = [s.field_completeness_percent or 0 for s in top]
    if comp:
        avg = sum(comp) / len(comp)
        A(f"  average field completeness : {avg:.1f}%")
        A(f"  best / worst               : {max(comp):.1f}% / {min(comp):.1f}%")
    A(f"  with a deadline stored     : {sum(1 for s in top if s.application_deadline)}")
    A(f"  deadline VERIFIED on source: {sum(1 for s in top if s.last_verified_date and s.application_deadline)}")
    A(f"  confidence=high            : {sum(1 for s in top if s.confidence == 'high')}")
    A(f"  confidence=medium          : {sum(1 for s in top if s.confidence == 'medium')}")
    A(f"  with official_url          : {sum(1 for s in top if s.official_url)}")
    A(f"  status active              : {sum(1 for s in top if s.status == 'active')}")
    A(f"  status unknown             : {sum(1 for s in top if s.status == 'unknown')}")
    A(f"  status expired             : {sum(1 for s in top if s.status == 'expired')}")

    # --- needs review ---
    flagged = [s for s in top if s.needs_review]
    A("\n" + "-" * 78)
    A(f"TOP 100 — needs_review ({len(flagged)} records)")
    A("-" * 78)
    if not flagged:
        A("  none")
    for s in flagged:
        A(f"  #{s.rank:<4} {(s.name or '')[:52]:<52}")
        A(f"        reason: {(s.needs_review_reason or '')[:150]}")

    A("\n" + "=" * 78)
    return "\n".join(L)
