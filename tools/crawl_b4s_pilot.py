#!/usr/bin/env python3
"""Crawl a Buddy4Study pilot subset into data/buddy4study_scholarships.json.

Does NOT merge into the live bot catalogue. Review the output first.

    ./.venv/bin/python tools/crawl_b4s_pilot.py
    ./.venv/bin/python tools/crawl_b4s_pilot.py --limit 200
    ./.venv/bin/python tools/crawl_b4s_pilot.py --refresh-names
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fetcher import Fetcher  # noqa: E402
import sources.buddy4study as b4s  # noqa: E402

DATA = ROOT / "data"
INTERIM = DATA / "interim"
OUT = DATA / "buddy4study_scholarships.json"
NAMES = INTERIM / "b4s_names.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=280, help="Max discovery URLs to fetch")
    ap.add_argument("--refresh-names", action="store_true",
                    help="Re-read Buddy4Study sitemaps before crawling")
    ap.add_argument("--drop-expired", action="store_true",
                    help="Omit schemes whose deadline has already passed")
    ap.add_argument("--force-refresh", action="store_true",
                    help="Bypass HTML cache for scholarship pages")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)

    fetcher = Fetcher(force_refresh=args.force_refresh)

    if args.refresh_names or not NAMES.exists():
        print("[1/2] Refreshing Buddy4Study name index from sitemaps…")
        names = b4s.discover_names(fetcher)
        NAMES.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  wrote {NAMES} ({len(names)} names)")
    else:
        names = json.loads(NAMES.read_text(encoding="utf-8"))
        print(f"[1/2] Using cached name index: {NAMES} ({len(names)} names)")

    print(f"[2/2] Crawling pilot subset (limit={args.limit})…")
    payload = b4s.crawl_pilot(
        fetcher,
        names,
        limit=args.limit,
        keep_expired=not args.drop_expired,
    )
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = payload["meta"]
    print(f"\nWrote {OUT}")
    print(
        f"  records={meta['records']}  targets={meta['targets_fetched']}  "
        f"errors={meta['errors']}"
    )

    # Quick quality snapshot for the terminal.
    rows = payload["scholarships"]
    if rows:
        active = sum(1 for r in rows if r.get("status") == "active")
        priv = sum(1 for r in rows if r.get("provider_type") == "private")
        with_elig = sum(1 for r in rows if (r.get("eligibility_text") or "").strip())
        with_income = sum(1 for r in rows if r.get("income_ceiling_inr") is not None)
        avg_blob = round(sum(len(r.get("intent_blob") or "") for r in rows) / len(rows))
        print(
            f"  active={active}  private={priv}  with_eligibility={with_elig}  "
            f"with_income={with_income}  avg_intent_blob_chars={avg_blob}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
