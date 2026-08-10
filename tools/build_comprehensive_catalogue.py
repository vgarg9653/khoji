#!/usr/bin/env python3
"""Merge pipeline catalogue + Buddy4Study pilot into one date-aware database.

Strategy (per product ask):
  1. Start from existing official-pipeline records (data/all_scholarships.json).
  2. Add Buddy4Study pilot rows that are not already present.
  3. Where a record has an external official_url and is missing a deadline (or
     has thin prose), fetch that official page first and enrich. Buddy4Study
     text remains the fallback.
  4. Recompute status from application_deadline vs today.
  5. Write:
       data/comprehensive_scholarships.json          full archive (incl. expired)
       data/comprehensive_scholarships_servable.json active + unknown only
       data/all_scholarships.json                    servable (pipeline handoff)
     then rebuild deliverables/dataset/bot_matching.json so the bot can use it.

    ./.venv/bin/python tools/build_comprehensive_catalogue.py
    ./.venv/bin/python tools/build_comprehensive_catalogue.py --skip-official
    ./.venv/bin/python tools/build_comprehensive_catalogue.py --official-limit 80
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fetcher import Fetcher  # noqa: E402
import normalize as N  # noqa: E402
import quality  # noqa: E402
import sources.generic as generic  # noqa: E402
import sources.buddy4study as b4s  # noqa: E402

DATA = ROOT / "data"
B4S_PATH = DATA / "buddy4study_scholarships.json"
OLD_PATH = DATA / "all_scholarships.json"
OUT_FULL = DATA / "comprehensive_scholarships.json"
OUT_SERVABLE = DATA / "comprehensive_scholarships_servable.json"

# Extra fields kept in the comprehensive archive for later intent matching.
ARCHIVE_EXTRA = (
    "eligibility_text", "benefits_text", "documents_text", "how_to_apply_text",
    "important_dates_text", "selection_criteria_text", "more_details_text",
    "applicable_for", "purpose_award", "intent_blob", "page_format",
    "pilot_tags", "bsid", "scholarship_id", "rules", "enrichment_notes",
    "source_primary", "source_urls",
)


def _norm_name(name: str | None) -> str:
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(
        r"\b(20\d{2}|20\d{2}\s*27|scholarship|scholarships|scheme|program|"
        r"programme|for|the|and|of|nsp|india)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def _deadline_status(deadline: str | None, today: str | None = None) -> str:
    today = today or date.today().isoformat()
    if not deadline:
        return "unknown"
    try:
        datetime.strptime(deadline[:10], "%Y-%m-%d")
    except ValueError:
        return "unknown"
    return "active" if deadline[:10] >= today else "expired"


def _is_external(url: str | None) -> bool:
    if not url:
        return False
    host = (urlparse(url).netloc or "").lower()
    return bool(host) and "buddy4study.com" not in host


def _short(text: str | None, n: int = 280) -> str | None:
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rsplit(" ", 1)[0] + "…"


def _completeness(rec: dict) -> float:
    """Mirror schema.COMPLETENESS_FIELDS without requiring a Scholarship object."""
    from schema import COMPLETENESS_FIELDS
    filled = 0
    for f in COMPLETENESS_FIELDS:
        v = rec.get(f)
        if isinstance(v, (list, tuple, set)):
            if len(v) > 0:
                filled += 1
        elif v is not None and v != "":
            filled += 1
    return round(100.0 * filled / len(COMPLETENESS_FIELDS), 1)


def b4s_to_catalogue(row: dict) -> dict:
    """Map a Buddy4Study pilot row onto the shared catalogue shape."""
    desc = row.get("description_short") or _short(
        row.get("description_long")
        or row.get("eligibility_text")
        or row.get("applicable_for")
    )
    rec = {
        "id": row.get("id"),
        "name": row.get("name"),
        "provider_name": row.get("provider_name"),
        "provider_type": row.get("provider_type"),
        "administering_body": row.get("administering_body") or row.get("provider_name"),
        "states": list(row.get("states") or []),
        "education_levels": list(row.get("education_levels") or []),
        "course_types": list(row.get("course_types") or []),
        "class_min": row.get("class_min"),
        "class_max": row.get("class_max"),
        "categories": list(row.get("categories") or []),
        "gender": row.get("gender"),
        "income_ceiling_inr": row.get("income_ceiling_inr"),
        "income_evidence": row.get("income_evidence"),
        "min_marks_percent": row.get("min_marks_percent"),
        "benefit_amount_min_inr": row.get("benefit_amount_min_inr"),
        "benefit_amount_max_inr": row.get("benefit_amount_max_inr"),
        "benefit_amount_text": row.get("benefit_amount_text") or row.get("purpose_award"),
        "documents_required": list(row.get("documents_required") or []),
        "application_mode": row.get("application_mode") or "provider_website",
        "application_url": row.get("application_url") or row.get("source_url"),
        "application_deadline": row.get("application_deadline"),
        "application_start_date": row.get("application_start_date"),
        "deadline_is_tentative": False,
        "official_url": row.get("official_url") or (
            row.get("application_url") if _is_external(row.get("application_url")) else None
        ),
        "description_short": desc,
        "source_name": "Buddy4Study",
        "source_url": row.get("source_url"),
        "source_urls": list(row.get("source_urls") or ([row.get("source_url")] if row.get("source_url") else [])),
        "source_primary": "buddy4study",
        "confidence": row.get("confidence") or "medium",
        "needs_review": True,  # B4S-sourced until a human verifies
        "needs_review_reason": "imported from Buddy4Study pilot; verify against official page",
        "last_verified_date": None,
        "extraction_date": row.get("extraction_date") or date.today().isoformat(),
        "reach_score": None,
        "tier": "backlog",
        "rank": None,
        "status": _deadline_status(row.get("application_deadline")),
        # archive extras for intent matching
        "eligibility_text": row.get("eligibility_text"),
        "benefits_text": row.get("benefits_text"),
        "documents_text": row.get("documents_text"),
        "how_to_apply_text": row.get("how_to_apply_text"),
        "important_dates_text": row.get("important_dates_text"),
        "selection_criteria_text": row.get("selection_criteria_text"),
        "more_details_text": row.get("more_details_text"),
        "applicable_for": row.get("applicable_for"),
        "purpose_award": row.get("purpose_award"),
        "intent_blob": row.get("intent_blob"),
        "page_format": row.get("page_format"),
        "pilot_tags": list(row.get("pilot_tags") or []),
        "bsid": row.get("bsid"),
        "scholarship_id": row.get("scholarship_id"),
        "rules": list(row.get("rules") or []),
        "enrichment_notes": [],
    }
    rec["field_completeness_percent"] = _completeness(rec)
    return rec


def _prefer_fill(dst: dict, src: dict, fields: list[str]) -> list[str]:
    """Copy non-empty src fields into empty dst fields. Returns filled names."""
    filled = []
    for f in fields:
        cur = dst.get(f)
        empty = cur in (None, "", [], {})
        val = src.get(f)
        if empty and val not in (None, "", [], {}):
            dst[f] = val
            filled.append(f)
    return filled


def enrich_from_official(fetcher: Fetcher, rec: dict) -> bool:
    """Fetch official_url and overlay deadline / structured fields when found.

    Returns True if the official page contributed anything useful.
    """
    url = rec.get("official_url")
    if not _is_external(url):
        return False
    # Skip government mega-portals that are listings, not scheme pages.
    host = urlparse(url).netloc.lower()
    if host in {"scholarships.gov.in", "www.scholarships.gov.in"}:
        return False

    r = fetcher.get(url)
    if not r.ok:
        (rec.setdefault("enrichment_notes", [])
         .append(f"official_fetch_failed:{r.status or r.skipped_reason}"))
        return False

    parsed = generic.parse_page(
        r.final_url or url,
        r.text,
        provider_hint=rec.get("provider_name"),
        source_name="official_enrichment",
    )
    if not parsed:
        # Still try a deadline regex pass on raw text for date gating.
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        m = generic._DEADLINE_CTX.search(text)
        if m and not rec.get("application_deadline"):
            iso = N.parse_date(m.group(0))
            if iso:
                rec["application_deadline"] = iso
                rec["deadline_is_tentative"] = N.is_tentative(m.group(0))
                rec.setdefault("enrichment_notes", []).append("deadline_from_official_text")
                rec["status"] = _deadline_status(iso)
                return True
        rec.setdefault("enrichment_notes", []).append("official_page_unparsed")
        return False

    d = parsed.__dict__ if hasattr(parsed, "__dict__") else dict(parsed)
    before_dl = rec.get("application_deadline")
    # Official deadline wins when present (fresher / authoritative).
    if d.get("application_deadline"):
        rec["application_deadline"] = d["application_deadline"]
        rec["deadline_is_tentative"] = bool(d.get("deadline_is_tentative"))
        if before_dl and before_dl != d["application_deadline"]:
            rec.setdefault("enrichment_notes", []).append(
                f"deadline_overridden_by_official:{before_dl}->{d['application_deadline']}"
            )
        else:
            rec.setdefault("enrichment_notes", []).append("deadline_from_official")

    filled = _prefer_fill(rec, d, [
        "application_start_date", "income_ceiling_inr", "income_evidence",
        "min_marks_percent", "class_min", "class_max", "benefit_amount_min_inr",
        "benefit_amount_max_inr", "benefit_amount_text", "gender",
        "description_short", "provider_name", "administering_body",
    ])
    for list_f in ("states", "categories", "education_levels", "documents_required",
                   "course_types"):
        if not rec.get(list_f) and d.get(list_f):
            rec[list_f] = list(d[list_f])
            filled.append(list_f)

    # Prefer a longer official description when ours is thin.
    off_desc = d.get("description_short")
    if off_desc and len(off_desc) > len(rec.get("description_short") or ""):
        rec["description_short"] = off_desc
        filled.append("description_short")

    if filled:
        rec.setdefault("enrichment_notes", []).append(
            "official_fields:" + ",".join(filled)
        )
    rec["source_primary"] = "official+buddy4study" if rec.get("source_name") == "Buddy4Study" else "official"
    if url not in (rec.get("source_urls") or []):
        rec.setdefault("source_urls", []).append(url)
    rec["status"] = _deadline_status(rec.get("application_deadline"))
    rec["field_completeness_percent"] = _completeness(rec)
    return True


def needs_official_enrichment(rec: dict) -> bool:
    if not _is_external(rec.get("official_url")):
        return False
    name = (rec.get("name") or "").strip()
    # Skip page furniture the quality gate will withhold anyway.
    if not name or len(name) < 8:
        return False
    if re.match(
        r"^(?:overview|navigation|schemes|home/|general instructions|"
        r"our scholars|batch\s+\d|regulation|student services|"
        r"\d{4}\s+highlights)",
        name,
        re.I,
    ):
        return False
    # Prefer confirming deadlines on provider sites for B4S / private rows.
    if rec.get("source_name") == "Buddy4Study" or rec.get("provider_type") == "private":
        return True
    if not rec.get("application_deadline"):
        return True
    desc = rec.get("description_short") or ""
    elig = rec.get("eligibility_text") or ""
    if len(desc) < 120 and len(elig) < 200:
        return True
    return False


def merge_catalogues(
    old_rows: list[dict],
    b4s_rows: list[dict],
    *,
    include_expired_b4s: bool = True,
) -> list[dict]:
    by_key: dict[str, dict] = {}
    order: list[str] = []

    for row in old_rows:
        rec = dict(row)
        rec["status"] = _deadline_status(rec.get("application_deadline"))
        rec.setdefault("source_primary", rec.get("source_name") or "pipeline")
        rec.setdefault("enrichment_notes", [])
        rec.setdefault("source_urls", list(rec.get("source_urls") or (
            [rec["source_url"]] if rec.get("source_url") else []
        )))
        key = _norm_name(rec.get("name"))
        if not key:
            continue
        if key not in by_key:
            order.append(key)
        by_key[key] = rec

    added = 0
    merged_into = 0
    for raw in b4s_rows:
        if not include_expired_b4s and raw.get("status") == "expired":
            continue
        rec = b4s_to_catalogue(raw)
        key = _norm_name(rec.get("name"))
        if not key:
            continue
        if key in by_key:
            # Overlay richer B4S text onto an existing pipeline record without
            # clobbering verified structured fields.
            existing = by_key[key]
            filled = _prefer_fill(existing, rec, [
                "description_short", "application_deadline", "application_start_date",
                "income_ceiling_inr", "income_evidence", "min_marks_percent",
                "benefit_amount_text", "benefit_amount_min_inr", "benefit_amount_max_inr",
                "gender", "class_min", "class_max", "official_url", "application_url",
            ])
            for list_f in ("states", "categories", "education_levels",
                           "documents_required", "course_types"):
                if not existing.get(list_f) and rec.get(list_f):
                    existing[list_f] = rec[list_f]
                    filled.append(list_f)
            for extra in ARCHIVE_EXTRA:
                if not existing.get(extra) and rec.get(extra):
                    existing[extra] = rec[extra]
            if filled:
                existing.setdefault("enrichment_notes", []).append(
                    "merged_b4s_fields:" + ",".join(filled)
                )
                merged_into += 1
            existing["status"] = _deadline_status(existing.get("application_deadline"))
            existing["field_completeness_percent"] = _completeness(existing)
        else:
            by_key[key] = rec
            order.append(key)
            added += 1

    print(f"  merge: kept {len(old_rows)} pipeline, added {added} B4S, "
          f"enriched {merged_into} overlaps → {len(order)} total")
    return [by_key[k] for k in order]


def rebuild_bot_matching(servable: list[dict]) -> None:
    """Re-run the deliverables builder against the updated all_scholarships.json."""
    # Import here so the script still works if content deps shift.
    sys.path.insert(0, str(ROOT / "src"))
    import make_deliverables as md
    md.main()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-official", action="store_true",
                    help="Skip fetching official provider pages")
    ap.add_argument("--official-limit", type=int, default=100,
                    help="Max official pages to fetch for enrichment")
    ap.add_argument("--drop-expired-b4s", action="store_true",
                    help="Do not import expired Buddy4Study cycles into the archive")
    ap.add_argument("--skip-bot-rebuild", action="store_true",
                    help="Write data files only; do not regenerate bot_matching.json")
    args = ap.parse_args()

    if not OLD_PATH.exists():
        print(f"missing {OLD_PATH}", file=sys.stderr)
        return 1
    if not B4S_PATH.exists():
        print(f"missing {B4S_PATH} — run tools/crawl_b4s_pilot.py first", file=sys.stderr)
        return 1

    old = json.loads(OLD_PATH.read_text(encoding="utf-8"))
    b4s_payload = json.loads(B4S_PATH.read_text(encoding="utf-8"))
    b4s_rows = b4s_payload.get("scholarships") or b4s_payload

    print("[1/4] Merging pipeline catalogue + Buddy4Study pilot…")
    merged = merge_catalogues(
        old, b4s_rows, include_expired_b4s=not args.drop_expired_b4s
    )

    print("[2/4] Official-site enrichment (deadline + thin prose)…")
    enriched = 0
    attempted = 0
    if not args.skip_official:
        fetcher = Fetcher()
        candidates = [r for r in merged if needs_official_enrichment(r)]
        # Prefer active / private first.
        candidates.sort(key=lambda r: (
            0 if r.get("status") == "active" else 1,
            0 if r.get("provider_type") == "private" else 1,
            r.get("name") or "",
        ))
        for rec in candidates[: args.official_limit]:
            attempted += 1
            print(f"  official [{attempted}/{min(len(candidates), args.official_limit)}] "
                  f"{(rec.get('name') or '')[:60]}")
            if enrich_from_official(fetcher, rec):
                enriched += 1
        print(f"  official enrichment: attempted={attempted} improved={enriched}")
    else:
        print("  skipped")

    print("[3/4] Quality gate + date status…")
    for rec in merged:
        rec["status"] = _deadline_status(rec.get("application_deadline"))
        rec["open_for_applications"] = rec["status"] == "active" or (
            rec["status"] == "unknown"  # unknown deadline: still show, labelled
        )
        rec["field_completeness_percent"] = _completeness(rec)
    q = quality.apply(merged)
    print(f"  quality: servable={q['servable']} withheld={q['withheld']}")

    servable = [
        r for r in merged
        if r.get("servable") is not False
        and r.get("status") in ("active", "unknown")
    ]
    # Expired records stay in the full archive for intent / history, but are
    # excluded from what the bot can show (Matcher also double-checks dates).

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_records": len(old),
        "b4s_records_in": len(b4s_rows),
        "merged_total": len(merged),
        "servable_active_or_unknown": len(servable),
        "status_counts": dict(Counter(r.get("status") for r in merged)),
        "official_enrichment_attempted": attempted,
        "official_enrichment_improved": enriched,
        "note": (
            "Full archive keeps expired cycles. Servable set is active+unknown "
            "only; bot Matcher also excludes past application_deadline."
        ),
    }

    OUT_FULL.write_text(
        json.dumps({"meta": meta, "scholarships": merged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUT_SERVABLE.write_text(
        json.dumps({"meta": meta, "scholarships": servable}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Pipeline handoff: make_deliverables reads all_scholarships.json
    OLD_PATH.write_text(json.dumps(servable, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {OUT_FULL}")
    print(f"  wrote {OUT_SERVABLE} ({len(servable)} servable)")
    print(f"  updated {OLD_PATH} ({len(servable)} servable)")

    print("[4/4] Rebuilding bot_matching.json…")
    if args.skip_bot_rebuild:
        print("  skipped")
    else:
        rebuild_bot_matching(servable)

    # Snapshot for the terminal.
    active = sum(1 for r in servable if r.get("status") == "active")
    unknown = sum(1 for r in servable if r.get("status") == "unknown")
    priv = sum(1 for r in servable if r.get("provider_type") == "private")
    with_dl = sum(1 for r in servable if r.get("application_deadline"))
    print(
        f"\nDone. Servable for students: {len(servable)} "
        f"(active={active}, unknown_deadline={unknown}, private={priv}, "
        f"with_deadline={with_dl})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
