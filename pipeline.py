#!/usr/bin/env python3
"""Khoji.AI scholarship data pipeline.

    python pipeline.py crawl    # fetch sources into data/raw (cached, polite)
    python pipeline.py parse    # parse + enrich + dedupe -> data/scholarships.db
    python pipeline.py rank     # compute reach_score, tag the top 100
    python pipeline.py verify   # re-check the top 100 against official sources
    python pipeline.py export   # write top100.csv / top100.json
    python pipeline.py report   # print the summary report
    python pipeline.py all      # crawl -> parse -> rank -> verify -> export -> report

Every network request in every stage passes through the robots policy in
data/raw/robots/robots_policy.json, is rate limited to one request per three
seconds per domain with jitter, and is cached so re-runs cost nothing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

SRC = pathlib.Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

DATA = pathlib.Path(__file__).resolve().parent / "data"
DB_PATH = DATA / "scholarships.db"
INTERIM = DATA / "interim"

import export as X                       # noqa: E402
import normalize as N                    # noqa: E402
import rank as R                         # noqa: E402
import schema as S                       # noqa: E402
from dedupe import deduplicate           # noqa: E402
from fetcher import Fetcher              # noqa: E402


def _seeds():
    from seeds import SEEDS
    return SEEDS


def _banner(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _save_interim(name: str, records) -> None:
    from dataclasses import asdict
    INTERIM.mkdir(parents=True, exist_ok=True)
    (INTERIM / f"{name}.json").write_text(
        json.dumps([asdict(r) for r in records], indent=2, ensure_ascii=False),
        encoding="utf-8")


def _load_interim(name: str):
    p = INTERIM / f"{name}.json"
    if not p.exists():
        return []
    return [S.Scholarship(**{k: v for k, v in d.items() if k in S.FIELD_NAMES})
            for d in json.loads(p.read_text(encoding="utf-8"))]


# ---------------------------------------------------------------- crawl

def cmd_crawl(args) -> None:
    _banner("PHASE 1 — CRAWL")
    t0 = time.time()
    fetcher = Fetcher(force_refresh=args.refresh)
    records = []

    # --- NSP (needs a browser) ---
    if not args.skip_nsp:
        print("\n[1/3] National Scholarship Portal")
        from render import Renderer
        import sources.nsp as nsp
        try:
            with Renderer(fetcher=fetcher, force_refresh=args.refresh) as rend:
                records.extend(nsp.crawl(rend))
        except Exception as e:
            print(f"  [NSP] failed: {type(e).__name__}: {e}")

    # --- official provider sites ---
    # Seeds are crawled concurrently, one worker per site. Politeness is not
    # weakened by this: the 1-request-per-3-seconds limit is enforced per domain
    # inside Fetcher, and each seed is a different domain.
    print(f"\n[2/3] Official provider sites ({len(SEEDS := _seeds())} seeds, "
          f"{args.workers} concurrent domains)")
    import concurrent.futures as cf
    import sources.generic as generic

    def _one(seed):
        tag, url, provider, ptype = seed
        try:
            got = generic.crawl_site(fetcher, url, provider_hint=provider,
                                     max_pages=args.max_pages)
        except Exception as e:
            return tag, [], f"{type(e).__name__}: {e}"
        for g in got:
            g.provider_type = g.provider_type or ptype
            g.source_name = "official"
        return tag, got, None

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for tag, got, err in ex.map(_one, SEEDS):
            if err:
                print(f"  [{tag}] error {err}")
            elif got:
                print(f"  [{tag}] {len(got)} page(s) parsed")
            records.extend(got)

    # --- Rajasthan: the V1 beachhead (PRD 7.3) ---
    # Given its own module because the state publishes a real scheme table that
    # the generic crawler cannot read, and V1 lives or dies on this state.
    print("\n[3/4] Rajasthan beachhead")
    import sources.rajasthan as rajasthan
    try:
        raj = rajasthan.crawl(fetcher)
        records.extend(raj)
    except Exception as e:
        print(f"  [Rajasthan] failed: {type(e).__name__}: {e}")

    # --- Buddy4Study: names only ---
    print("\n[4/4] Buddy4Study discovery index (names only)")
    import sources.buddy4study as b4s
    try:
        names = b4s.discover_names(fetcher)
        (DATA / "interim").mkdir(parents=True, exist_ok=True)
        (DATA / "interim" / "b4s_names.json").write_text(
            json.dumps(names, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"  [B4S] failed: {type(e).__name__}: {e}")

    _save_interim("crawled", records)
    fetcher.close()
    print(f"\nCrawled {len(records)} raw records in {time.time()-t0:.0f}s")
    print(f"fetcher stats: {fetcher.stats}")
    print(f"raw HTML cached under {DATA/'raw'}")


# ---------------------------------------------------------------- parse

def cmd_parse(args) -> None:
    _banner("PHASE 2 — PARSE, ENRICH, DEDUPE")
    records = _load_interim("crawled")
    if not records:
        print("No crawled records. Run `python pipeline.py crawl` first.")
        return
    print(f"Loaded {len(records)} raw records")

    # Enrich NSP records from their official guideline PDFs.
    if not args.skip_pdf:
        import enrich as E
        import pdf_extract as P
        fetcher = Fetcher()
        targets = [r for r in records
                   if r.official_url and r.official_url.lower().endswith(".pdf")]
        # Many schemes share one guidelines PDF; fetch each document once.
        by_url: dict[str, list] = {}
        for r in targets:
            by_url.setdefault(r.official_url, []).append(r)
        print(f"Enriching from {len(by_url)} distinct guideline PDFs "
              f"({len(targets)} records)...")
        ok = unreadable = sliced = ocr_recovered = 0
        for i, (url, group) in enumerate(by_url.items(), 1):
            text, note = P.get_text(fetcher, url)
            ocr_used = bool(note and note.startswith("text recovered by OCR"))
            if (note and not ocr_used) or not text:
                unreadable += 1
                for r in group:
                    r.needs_review = True
                    r.needs_review_reason = (r.needs_review_reason or "") + \
                        f"; guideline PDF unreadable ({note})"
                continue
            ok += 1
            if ocr_used:
                # Usable text, but OCR misreads digits often enough that any
                # amount taken from it should be treated as provisional.
                ocr_recovered += 1
                for r in group:
                    r.confidence = "medium"
                    r.needs_review_reason = "; ".join(filter(None, [
                        r.needs_review_reason,
                        "eligibility read via OCR from a scanned PDF; "
                        "figures should be spot-checked"]))
                    r.needs_review = True
            names = list({r.name for r in group if r.name})
            distinct = len({r.name_normalized for r in group})

            # A PDF cited by several schemes cannot attribute its scheme-specific
            # numbers to any one of them — unless we can isolate each scheme's
            # own section, which we try first.
            spans = E.slice_by_scheme(text, names) if distinct > 1 else {}
            for r in group:
                span = spans.get(r.name)
                if span:
                    # Isolated: this text really is about this scheme.
                    E.enrich_from_text(r, span, source_url=url, shared_with=1,
                                       low_confidence_text=ocr_used)
                    sliced += 1
                else:
                    E.enrich_from_text(r, text, source_url=url,
                                       shared_with=distinct,
                                       low_confidence_text=ocr_used)
            if i % 20 == 0:
                print(f"  ...{i}/{len(by_url)} PDFs")
        print(f"  PDFs readable: {ok} | unreadable: {unreadable} | "
              f"records resolved by scheme-level slicing: {sliced}")
        if ocr_recovered:
            print(f"  PDFs recovered by OCR: {ocr_recovered}")
        fetcher.close()

    merged, stats = deduplicate(records)
    print(f"\nDedupe: {stats['input']} -> {stats['output']} "
          f"({stats['merged']} merged away)")

    for r in merged:
        r.field_completeness_percent = r.completeness()
        if r.status == "unknown" and r.application_deadline:
            r.status = N.infer_status(r.application_deadline)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = S.connect(DB_PATH)
    conn.execute("DELETE FROM scholarships")
    for r in merged:
        S.upsert(conn, r)
    conn.commit()
    conn.close()
    _save_interim("parsed", merged)

    avg = sum(r.field_completeness_percent or 0 for r in merged) / max(1, len(merged))
    print(f"Wrote {len(merged)} records to {DB_PATH}")
    print(f"Average field completeness: {avg:.1f}%")
    nr = sum(1 for r in merged if r.needs_review)
    print(f"Flagged needs_review: {nr}")
    print(f"Unstructured pages dumped: "
          f"{len(list((DATA/'needs_review').glob('*.txt')))} in data/needs_review/")


# ---------------------------------------------------------------- rank

def cmd_rank(args) -> None:
    _banner("PHASE 3 — RANK BY REACH")
    conn = S.connect(DB_PATH)
    records = X.load_records(conn)
    if not records:
        print("Database empty. Run `python pipeline.py parse` first.")
        return
    ordered = R.rank_all(records, top_n=args.top)
    conn.execute("DELETE FROM scholarships")
    for r in ordered:
        S.upsert(conn, r)
    conn.commit()

    top = [r for r in ordered if r.tier == "top100"]
    print(f"Scored {len(ordered)} records; top {len(top)} tagged 'top100', "
          f"{len(ordered)-len(top)} tagged 'backlog'")
    print(f"\n{'RANK':<6}{'SCORE':>7}{'CMPL':>7}  {'STATUS':<9}NAME")
    print("-" * 78)
    for r in top[:20]:
        print(f"{r.rank:<6}{r.reach_score:>7.1f}{r.field_completeness_percent or 0:>6.0f}%"
              f"  {r.status:<9}{(r.name or '')[:44]}")
    print("\nScore breakdown of #1:")
    for k, v in R.score_breakdown(top[0]).items():
        print(f"   {k:<12} {v}")
    conn.close()


# ---------------------------------------------------------------- verify

def cmd_verify(args) -> None:
    _banner("PHASE 4 — VERIFY TOP 100 AGAINST OFFICIAL SOURCES")
    conn = S.connect(DB_PATH)
    top = X.load_records(conn, tier="top100")
    if not top:
        print("No top100 tier. Run `python pipeline.py rank` first.")
        return
    if args.limit:
        top = top[:args.limit]

    import verify as V
    fetcher = Fetcher(force_refresh=True)   # verification must not read the cache
    queue_rows: list[dict] = []
    passed = 0
    t0 = time.time()

    # NSP schemes get their dates re-read from the NSP listing, which is what
    # published them. Rendered once, then shared across all NSP records.
    nsp_index = None
    if any(s.application_mode == "NSP" for s in top):
        print("  re-reading the NSP listing for current deadlines...")
        try:
            from render import Renderer
            with Renderer(fetcher=fetcher, force_refresh=True) as rend:
                nsp_index = V.build_nsp_deadline_index(rend)
            print(f"  NSP listing indexed: {len(nsp_index)} live schemes")
        except Exception as e:
            print(f"  NSP re-read failed ({type(e).__name__}: {e}); "
                  f"NSP deadlines will be reported as unverified")

    for i, s in enumerate(top, 1):
        s, flags = V.verify_record(fetcher, s, nsp_index=nsp_index)
        if not flags:
            passed += 1
            # Verified against the source, but a parse-stage concern survived;
            # it still needs a human, so it still belongs in the queue.
            if s.needs_review and s.needs_review_reason:
                queue_rows.append({
                    "scholarship_id": s.id, "name": s.name, "rank": s.rank,
                    "reason": s.needs_review_reason, "field": "", "stored_value": "",
                    "found_value": "", "snippet": "(raised during parsing, not verification)",
                    "official_url": s.official_url,
                })
        for f in flags:
            queue_rows.append({
                "scholarship_id": s.id, "name": s.name, "rank": s.rank,
                "reason": f.reason, "field": f.field, "stored_value": f.stored,
                "found_value": f.found, "snippet": f.snippet,
                "official_url": s.official_url,
            })
        S.upsert(conn, s)
        if i % 10 == 0:
            print(f"  verified {i}/{len(top)}  (passed so far: {passed})")
    conn.commit()

    conn.execute("DELETE FROM review_queue")
    for r in queue_rows:
        conn.execute(
            "INSERT INTO review_queue (scholarship_id,name,reason,snippet,field,"
            "stored_value,found_value,official_url,flagged_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (r["scholarship_id"], r["name"], r["reason"], r["snippet"], r["field"],
             r["stored_value"], r["found_value"], r["official_url"], N.today_iso()))
    conn.commit()

    X.export_review_queue(queue_rows, DATA / "review_queue.csv")
    conn.close()
    fetcher.close()

    print(f"\nVerified {len(top)} records in {time.time()-t0:.0f}s")
    print(f"  passed all checks (confidence=high): {passed}")
    print(f"  flagged for review                 : {len(top)-passed}")
    print(f"  review queue rows                  : {len(queue_rows)}")
    print(f"  -> {DATA/'review_queue.csv'}")

    from collections import Counter
    if queue_rows:
        print("\n  Top flag reasons:")
        for reason, n in Counter(r["reason"] for r in queue_rows).most_common(10):
            print(f"    {n:>4}  {reason}")


# ---------------------------------------------------------------- export

def cmd_export(args) -> None:
    _banner("PHASE 5 — EXPORT")
    conn = S.connect(DB_PATH)
    top = [r for r in X.load_records(conn, tier="top100")
           if r.status in ("active", "unknown")]
    X.export_csv(top, DATA / "top100.csv")
    X.export_json(top, DATA / "top100.json")
    allr = X.load_records(conn)

    # Decide what the bot may serve. Nothing is deleted — withheld records keep
    # a reason so the rule can be reviewed or relaxed without re-crawling.
    import quality
    summary = quality.apply(allr)
    for r in allr:
        S.upsert(conn, r)
    conn.commit()
    print(f"  quality gate: {summary['servable']} servable, "
          f"{summary['withheld']} withheld")
    for reason, n in sorted(summary["reasons"].items(), key=lambda kv: -kv[1]):
        print(f"      {n:>3}  {reason}")

    X.export_csv(allr, DATA / "all_scholarships.csv")
    # The bot serves everything, not just the top tier, so the full set needs a
    # JSON export too. `tier` and `confidence` travel with each record so the
    # matcher can rank, and so a quality filter can be applied later without
    # re-crawling.
    X.export_json(allr, DATA / "all_scholarships.json")
    conn.close()
    print(f"  {DATA/'top100.csv'}   ({len(top)} rows, active+unknown only)")
    print(f"  {DATA/'top100.json'}  ({len(top)} records)")
    print(f"  {DATA/'all_scholarships.csv'} ({len(allr)} rows)")
    print(f"  {DB_PATH}")


# ---------------------------------------------------------------- report

def cmd_report(args) -> None:
    conn = S.connect(DB_PATH)
    allr = X.load_records(conn)
    top = X.load_records(conn, tier="top100")
    conn.close()
    text = X.build_report(allr, top)
    print(text)
    (DATA / "report.txt").write_text(text, encoding="utf-8")
    print(f"\nSaved to {DATA/'report.txt'}")


def cmd_all(args) -> None:
    cmd_crawl(args)
    cmd_parse(args)
    cmd_rank(args)
    cmd_verify(args)
    cmd_export(args)
    cmd_report(args)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, fn in (("crawl", cmd_crawl), ("parse", cmd_parse), ("rank", cmd_rank),
                     ("verify", cmd_verify), ("export", cmd_export),
                     ("report", cmd_report), ("all", cmd_all)):
        sp = sub.add_parser(name, help=fn.__doc__)
        sp.set_defaults(func=fn)
        sp.add_argument("--refresh", action="store_true",
                        help="ignore the cache and re-fetch")
        sp.add_argument("--top", type=int, default=100, help="size of the top tier")
        sp.add_argument("--limit", type=int, default=0,
                        help="verify: only the first N records")
        sp.add_argument("--max-pages", type=int, default=20,
                        help="crawl: max pages per provider site")
        sp.add_argument("--workers", type=int, default=8,
                        help="crawl: concurrent domains (per-domain rate limit unchanged)")
        sp.add_argument("--skip-nsp", action="store_true")
        sp.add_argument("--skip-pdf", action="store_true")

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
