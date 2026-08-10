# EduDisha — dataset handoff

Everything needed to build the WhatsApp scholarship bot on top of this data.

**Read in this order:** this file → `ACTION_ITEMS.md` → `DATA_DICTIONARY.md`.

## What this is

**229 scholarships** for Indian students, crawled from the National Scholarship
Portal, central ministry and state government sites, and foundation/PSU pages.
The **top 100 by reach** were re-checked against their official sources; the
remaining 129 are kept as an unverified backlog.

| | |
|---|---|
| Records in the primary dataset | **100** |
| Verified against the official source (`confidence: high`) | **75** |
| Currently active (deadline still ahead) | **84** — 0 expired |
| Carry an official, non-aggregator URL | **92** |
| Average field completeness | **51.4%** |
| Flagged for human review | **44 rows** in `review/review_queue.csv` |
| Backlog (crawled, unverified) | 129 |
| Names discovered for future crawling | 1,212 |

## The one rule to carry into the bot

**`null` means the source did not say it. It never means "no" or "zero".**

`income_ceiling_inr: null` does not mean the scheme has no income cap — it means
we could not read one without guessing. If the matcher treats null as "no
limit", it will tell students they qualify when they may not. Treat null as
*unknown* and say so.

This is why average completeness is 51% rather than 90%: unreadable fields were
left empty instead of filled with plausible values. The gaps are the honest
part, and `ACTION_ITEMS.md` tells you which ones to close first.

## Folder map

```
deliverables/
├── README.md                        you are here
├── ACTION_ITEMS.md                  what to do next, in priority order
├── DATA_DICTIONARY.md               every field, its real coverage, how to use it
│
├── dataset/
│   ├── bot_matching.json            ← START HERE. 100 records, 37 matching fields
│   ├── top100.json                  full records, every field
│   ├── top100.csv                   same, spreadsheet-friendly
│   ├── filters_index.json           every distinct value present, with counts
│   ├── all_scholarships.csv         all 229 incl. the 129-record backlog
│   └── scholarships.db              SQLite (scholarships, review_queue, crawl_log)
│
├── review/
│   ├── review_queue.csv             44 human tasks, each with the triggering snippet
│   └── raw_pages/                   60 pages too unstructured to parse safely
│
├── discovery/
│   └── discovered_names_backlog.json  1,212 scholarship names to crawl next
│
├── compliance/
│   ├── robots_policy.json           per-domain crawl decision + reason
│   ├── robots_report.csv            the same, readable
│   └── skipped_urls.jsonl           25 URLs the crawler refused, with reasons
│
└── reports/
    └── coverage_report.txt          provider / state / level / category breakdown
```

## Quick start

```python
import json
records = json.load(open("dataset/bot_matching.json"))

def matches(r, state, level, category):
    # "all" means national. An empty list means the source didn't say —
    # that is NOT the same as "excluded", so don't filter it out silently.
    if r["states"] and "all" not in r["states"] and state not in r["states"]:
        return False
    if r["education_levels"] and level not in r["education_levels"]:
        return False
    if r["categories"] and category not in r["categories"]:
        return False
    return True

hits = [r for r in records
        if matches(r, "Assam", "school", "ST") and r["status"] == "active"]
hits.sort(key=lambda r: -r["reach_score"])
```

Note what that function does *not* do: it never rejects a record because a field
is empty. Unknown is surfaced to the student, not silently filtered.

Build dropdowns and NLU vocabulary from `dataset/filters_index.json` so the bot
only offers values that actually exist in the data.

## Known limits — state these plainly if asked

1. **Income ceiling is on only 15/100 records.** The most important eligibility
   filter is the thinnest field. `ACTION_ITEMS.md` #1.
2. **92% central government.** Foundation and PSU pages are marketing-shaped and
   extract poorly; 60 such pages sit in `review/raw_pages/` rather than being
   guessed at.
3. **Named-state coverage skews to NE states and UTs.** Maharashtra, Karnataka,
   Tamil Nadu and UP run their own portals. Five states (WB, Bihar, AP,
   Jharkhand, MP) are network-filtered from the build machine — running the
   pipeline from an India-hosted machine should bring them in.
4. **Deadlines go stale fast.** Re-run `verify` on a schedule; 10 records are
   already flagged `deadline_is_tentative`.

## How the data was gathered

robots.txt was checked on all 64 domains before any crawling, and the resulting
policy gates every request in code. Rate limit 1 request / 3 seconds per domain
with jitter, descriptive user-agent with a contact address, no logins, nothing
behind auth. `wcd.gov.in` (blanket `Disallow: /`) and three domains that refuse
our user-agent were excluded entirely.

**Buddy4Study was used as a discovery index only** — 12 requests total, reading
their public sitemap for scholarship *names*. None of their content was copied;
every scheme detail comes from the provider's own page.

`compliance/skipped_urls.jsonl` is the receipt: 25 refusals, including 5
cross-domain redirects blocked because the destination host had not been vetted.

## Regenerating

From the project root (one level up):

```bash
python pipeline.py crawl      # cached — only fetches what changed
python pipeline.py parse
python pipeline.py rank
python pipeline.py verify     # run this most often; dates go stale
python pipeline.py export
python pipeline.py report
python src/make_deliverables.py   # rebuilds this folder
```

Note: NSP records get their state scoping assigned during **crawl**, not parse.
If you change `src/sources/nsp.py` or the state logic in `src/normalize.py`,
re-run `crawl` (it is cached and takes ~20s) or the change will not appear.

Adding a new source domain requires vetting it first — add it to
`data/raw/robots/domains.txt`, run `python src/fetch_robots.py`, then add a seed
in `src/seeds.py`. The fetcher refuses any domain absent from the policy.

The markdown docs in this folder are generated from `docs/deliverables/`. Edit
them there, not here — `make_deliverables.py` rebuilds this directory from
scratch each run.
