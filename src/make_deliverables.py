"""Assemble deliverables/ — the handoff folder for building the WhatsApp bot.

Copies the pipeline outputs into one place and generates two derived artifacts
that are useful when wiring up matching:

  filters_index.json  — the distinct values actually present in the dataset, so
                        the bot's matcher and NLU are built against real data
                        rather than an assumed vocabulary.
  bot_matching.json   — the subset of fields a matcher needs, nulls kept
                        explicit so "unknown" is never mistaken for "no".

Nothing here invents data. Re-run any time after `pipeline.py export`.
"""

from __future__ import annotations

import collections
import json
import pathlib
import shutil
import sys

import content

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "deliverables"
# The handoff docs live here, not in deliverables/. This function rebuilds the
# output directory from scratch, so anything authored directly inside it would
# be destroyed on the next run.
DOCS = ROOT / "docs" / "dataset"

MATCH_FIELDS = [
    "id", "rank", "name", "provider_name", "provider_type", "administering_body",
    "states", "education_levels", "class_min", "class_max", "categories",
    "gender", "income_ceiling_inr", "income_evidence", "min_marks_percent",
    "age_min", "age_max",
    "orphan_or_single_parent", "parent_occupation_specific",
    "benefit_amount_min_inr", "benefit_amount_max_inr", "benefit_amount_text",
    "benefit_type", "renewable", "number_of_awards",
    "application_mode", "application_url", "application_deadline",
    "deadline_is_tentative", "documents_required", "official_url",
    "status", "confidence", "needs_review", "last_verified_date",
    "reach_score", "tier", "servable", "field_completeness_percent",
    "description_short",
]

LIST_FIELDS = ["states", "education_levels", "categories", "documents_required",
               "course_types", "field_of_study"]
SCALAR_FIELDS = ["provider_type", "gender", "benefit_type", "application_mode",
                 "selection_process", "status", "confidence"]


def copy(src: pathlib.Path, dst: pathlib.Path) -> None:
    if not src.exists():
        print(f"  ! missing, skipped: {src.name}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    print(f"  + {dst.relative_to(OUT)}")


def build_filters_index(records: list[dict]) -> dict:
    """Distinct values actually present, with counts. Build the matcher against
    this, not against an assumed vocabulary."""
    idx: dict = {}
    for f in LIST_FIELDS:
        c = collections.Counter(v for r in records for v in (r.get(f) or []))
        if c:
            idx[f] = {"distinct": len(c), "values": dict(c.most_common())}
    for f in SCALAR_FIELDS:
        c = collections.Counter(r.get(f) for r in records if r.get(f))
        if c:
            idx[f] = {"distinct": len(c), "values": dict(c.most_common())}
    idx["_coverage"] = {
        f: sum(1 for r in records if r.get(f) not in (None, [], "", False))
        for f in MATCH_FIELDS
    }
    idx["_total_records"] = len(records)
    return idx


def main() -> None:
    if not (DATA / "top100.json").exists():
        sys.exit("No data/top100.json — run `python pipeline.py all` first.")

    required_docs = ["README.md", "ACTION_ITEMS.md", "DATA_DICTIONARY.md"]
    missing = [d for d in required_docs if not (DOCS / d).exists()]
    if missing:
        sys.exit(f"Missing handoff docs in {DOCS}: {', '.join(missing)}\n"
                 f"They are the entry point to the folder; refusing to publish "
                 f"a dataset nobody can interpret.")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    print(f"Building {OUT}/\n")

    print("docs/")
    for doc in required_docs:
        copy(DOCS / doc, OUT / doc)

    print("\ndataset/")
    for name in ("top100.csv", "top100.json", "all_scholarships.csv",
                 "scholarships.db"):
        copy(DATA / name, OUT / "dataset" / name)

    print("\nreview/")
    copy(DATA / "review_queue.csv", OUT / "review" / "review_queue.csv")
    copy(DATA / "needs_review", OUT / "review" / "raw_pages")

    print("\ndiscovery/")
    copy(DATA / "interim" / "b4s_names.json",
         OUT / "discovery" / "discovered_names_backlog.json")

    print("\ncompliance/")
    copy(DATA / "raw" / "robots" / "robots_policy.json",
         OUT / "compliance" / "robots_policy.json")
    copy(DATA / "raw" / "robots" / "robots_report.csv",
         OUT / "compliance" / "robots_report.csv")
    copy(DATA / "logs" / "robots_skips.jsonl",
         OUT / "compliance" / "skipped_urls.jsonl")

    print("\nreports/")
    copy(DATA / "report.txt", OUT / "reports" / "coverage_report.txt")

    # --- derived artifacts ---
    print("\nderived/")
    # The bot serves the whole catalogue. Top-tier records are verified and rank
    # first; the rest are still useful and are labelled, not hidden. A quality
    # filter can be applied later without another crawl.
    full = DATA / "all_scholarships.json"
    source = full if full.exists() else (DATA / "top100.json")
    records = json.loads(source.read_text(encoding="utf-8"))
    records = [r for r in records if r.get("status") in ("active", "unknown")]
    before = len(records)
    # servable is None for records exported before the gate existed; treat only
    # an explicit False as withheld so an older export still works.
    records = [r for r in records if r.get("servable") is not False]
    if before != len(records):
        print(f"  (quality gate withheld {before - len(records)} non-scheme records)")
    print(f"  (serving {len(records)} records from {source.name})")

    idx = build_filters_index(records)
    p = OUT / "dataset" / "filters_index.json"
    p.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  + {p.relative_to(OUT)}  ({idx['_total_records']} records indexed)")

    bot = [{k: r.get(k) for k in MATCH_FIELDS} for r in records]
    # Relevance tags and plain-language content. Both are deterministic
    # functions of the fields above plus human-written phrasing — no model runs
    # here — so they are baked in at build time where they can be diffed and
    # audited, rather than generated per request where they could not.
    content.augment_all(bot)
    approved = sum(1 for r in bot if r.get("content_status") == "human_approved")
    p = OUT / "dataset" / "bot_matching.json"
    p.write_text(json.dumps(bot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  + {p.relative_to(OUT)}  ({len(bot)} records, "
          f"{len(MATCH_FIELDS) + len(content.CONTENT_FIELDS) + 5} fields)")
    print(f"    content: {len(bot) - approved} composed, {approved} human-approved")

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    n = sum(1 for f in OUT.rglob("*") if f.is_file())
    print(f"\nDone: {n} files, {total/1024/1024:.1f} MB in {OUT}")


if __name__ == "__main__":
    main()
