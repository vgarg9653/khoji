# Action items

Ordered by what actually blocks a trustworthy bot. Counts are from the shipped
dataset.

---

## Before the bot talks to a real student

### 1. Fill the income ceiling gap — 85 of 100 records lack it
**Why it blocks you:** your users are underprivileged students, and family
income is the single most common gate on Indian scholarships. With
`income_ceiling_inr` on only **15/100**, the bot cannot answer "am I eligible?"
for most schemes. The number is usually stated in the guideline PDF but in prose
we would have had to guess at, so it was left null rather than fabricated.

**Do this:** work the 100 records by hand against `official_url`. Most ceilings
are one of a few standard values (₹1L, ₹2L, ₹2.5L, ₹4.5L, ₹8L). Budget roughly
2–3 hours for all 100. This is the highest-value hour you will spend.

**Until then:** never state eligibility as a conclusion. Say "income limit not
confirmed — check the official page", and link `official_url`.

### 2. Re-verify every deadline at send time — do not trust the stored date
**Why it blocks you:** `application_deadline` is populated on 84/100 and was
correct when read (`last_verified_date`), but Indian scholarship deadlines get
extended and revised constantly. A bot that tells a student the wrong last date
does real harm.

**Do this:** run `python pipeline.py verify` on a schedule (daily during the
Aug–Nov application season, weekly otherwise) and never send a deadline whose
`last_verified_date` is more than a few days old. **10 records already carry
`deadline_is_tentative: true`** — present those as provisional, always.

### 3. Work the review queue — 44 rows, ~2 hours total
`review/review_queue.csv` has one row per flag, each with the reason and the
exact snippet that triggered it, so most resolve in under a minute.

| Rows | Task | Effort |
|---:|---|---|
| 20 | Re-check a date once NSP confirms it (currently tentative/unannounced) | recurring, quick |
| 14 | Attribute shared-PDF values to the right scheme (see below) | ~30 min |
| 5 | Read a raw page dump in `review/raw_pages/` by hand | ~20 min |
| 4 | Read a scanned PDF by hand (no text layer) | ~20 min |
| 1 | One-off: category eligibility not corroborated | 2 min |

**The 14 shared-PDF rows matter most.** NSP publishes one guidelines document
covering several schemes — `DEPDGuidelines_1.pdf` covers three. Rather than copy
one scheme's class range and amounts onto all of them, those fields were left
null and flagged. Open the PDF, find the section for each scheme, and fill in
`class_min`, `class_max`, `benefit_amount_*`, `number_of_awards`.

### 4. Decide your null-handling policy and enforce it in one place
Write a single helper the bot calls for every eligibility check, returning
`ELIGIBLE / NOT_ELIGIBLE / UNKNOWN` — never a bare boolean. `UNKNOWN` must
render as "not stated, check the official page", not as a silent pass or fail.
Given the coverage above, `UNKNOWN` will be common and that is fine, provided
the student is told.

---

## To make the dataset genuinely national

### 5. Add the big-state portals — the current mix is 92% central government
Named-state coverage skews to NE states and UTs because those flow through NSP.
The states with the most students run their own portals and are **not** in this
dataset.

- **MahaDBT (Maharashtra) is already vetted and reachable** — `mahadbt2.maharashtra.gov.in`
  came back `ALLOW_FULL` with a sitemap. This is the cheapest big win available.
- Karnataka SSP, Telangana ePASS, Kerala e-Grantz were crawled but yielded
  little; they need per-source parsers like `src/sources/nsp.py`.
- **Five states are unreachable from the build machine** — West Bengal, Bihar,
  Andhra Pradesh, Jharkhand, Madhya Pradesh. TCP 80 and 443 are filtered, which
  is a network/geo block, not a bot block, so no crawler change fixes it. **Run
  the pipeline from an India-hosted machine** and these should come in.

### 6. Mine the 1,212-name discovery backlog
`discovery/discovered_names_backlog.json` holds scholarship names harvested from
Buddy4Study's sitemap (names only — none of their content). Many are private and
NGO schemes absent from NSP, which is exactly where the current dataset is thin
(only 4/100 private, 4/100 state).

**Do this:** diff those names against `dataset/all_scholarships.csv`, pick the
ones aimed at underprivileged students, find each provider's official domain,
add it to `data/raw/robots/domains.txt`, re-run `src/fetch_robots.py` to vet it,
then add a seed in `src/seeds.py`. The vetting step is not optional — the
fetcher refuses any domain absent from the policy.

### 7. Promote from the 129-record backlog
`dataset/all_scholarships.csv` holds 129 records ranked 101+, crawled but never
verified. As you fix completeness on those, some will out-rank current top-100
entries. Re-run `rank` → `verify` → `export` and the tiers re-sort themselves.

---

## Operational

### 8. Keep the compliance trail
`compliance/` holds the robots policy, the per-domain report, and
`skipped_urls.jsonl` — 25 URLs the crawler refused, including 5 cross-domain
redirects blocked because the destination was not vetted. If anyone asks how the
data was gathered, this is the answer. Keep it with the dataset.

Note that `wcd.gov.in` (blanket `Disallow: /`) and three WAF-refusing domains
were excluded entirely and deliberately. Don't "fix" that by spoofing a browser
user-agent.

### 9. Re-run cadence
```bash
python pipeline.py crawl      # cached; only fetches what changed
python pipeline.py parse
python pipeline.py rank
python pipeline.py verify     # the important one — dates go stale
python pipeline.py export
python pipeline.py report
python src/make_deliverables.py
```
Everything is cached under `data/raw/`, so a re-run costs few requests. Run the
whole chain weekly, and `verify` daily in season.

**Gotcha worth knowing:** NSP records get their state scoping assigned during
`crawl`, not `parse`. If you change `src/sources/nsp.py` or the state logic in
`src/normalize.py`, you must re-run `crawl` (cached, ~20s) or the change will
silently not appear. This caught us once.

### 10. Two things to carry into the bot's copy
- Show `benefit_amount_text` rather than the parsed integers when both exist —
  the verbatim text carries conditions ("per annum for 4 years", "as per actuals")
  that a single number drops.
- Always surface `official_url`. The bot's value is helping a student *find* the
  scheme; the provider's page is the authority on whether they qualify.

---

## Regression tests worth keeping

`tests/test_extractors.py` (24 tests) encodes real bugs found during the build.
Each asserts the conservative behaviour: when text is unclear, return `None`.
Four are worth knowing about because they were producing wrong data a student
would have acted on:

- "maximum **4 years** duration" was read as `age_max = 4`
- an award *amount* was read as an award *count*
- a table row label "Sl. No. **2**" became `benefit_amount_min = ₹2`
- a central scheme restricted to J&K/Ladakh was tagged national, so it matched
  students in every other state — while *"Central Armed Police Forces and **Assam
  Rifles**"* (a regiment, not the state) had to stay national. Opposite fixes,
  both tested.

Run them before shipping any parser change: `python -m pytest tests/ -q`.
