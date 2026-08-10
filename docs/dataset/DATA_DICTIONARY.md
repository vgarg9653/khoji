# Data dictionary — `top100.json` / `top100.csv` / `bot_matching.json`

100 records. Coverage counts below are **out of 100** and were measured on the
shipped file, not estimated.

## The one rule that governs everything here

**`null` means the source did not say. It never means "no" or "zero".**

This matters most for eligibility. `income_ceiling_inr: null` does **not** mean
the scheme has no income cap — it means we could not read one. If your matcher
treats null as "no limit", it will tell a student they qualify when they may not.
Treat null as *unknown* and show it as "not stated — check the official page".

## Trust fields — read these before using a record

| Field | Coverage | Meaning |
|---|---:|---|
| `confidence` | 100 | `high` (75) = re-fetched and confirmed against the official source on `last_verified_date`. `medium` (25) = something needs a human; see `needs_review_reason`. |
| `needs_review` | 44 | True = a human should look before this record is trusted for that scheme's specifics. **A record can be `confidence:high` AND `needs_review:true`** — the deadline was verified, but e.g. its class range came from a PDF shared with other schemes. |
| `needs_review_reason` | 44 | Plain-language reason. Matches a row in `review/review_queue.csv`. |
| `last_verified_date` | 75 | Date the official source was re-read. Absent = not verified. |
| `status` | 100 | `active` (84) = deadline still ahead. `unknown` (16) = no deadline published. No `expired` records are exported. |
| `official_url` | 92 | The provider's own page or guideline PDF. Never an aggregator. |
| `source_url` | 100 | Where we actually read it. |
| `field_completeness_percent` | 100 | Share of the 30 substantive fields that are non-null. |

## Matching fields — what the bot filters on

| Field | Coverage | Notes for matching |
|---|---:|---|
| `states` | 100 | `["all"]` = national (30 records). Otherwise named states. 25 distinct values. **Always populated** — safe to filter on. |
| `education_levels` | 91 | `school` 74, `professional` 18, `PG` 15, `UG` 13, `diploma` 9, `PhD` 8. A record may hold several. |
| `categories` | 74 | `OBC` 28, `ST` 26, `DNT` 18, `SC` 16, `PwD` 5. **26 records state no category** — usually open to all, but do not assume; show as unstated. |
| `class_min` / `class_max` | 35 | Integers 1–12. Only for school-level schemes. |
| `income_ceiling_inr` | **15** | ⚠️ **The weakest field, and the most important one for your users.** Only 15 records carry a readable cap. See ACTION_ITEMS #1. |
| `gender` | 6 | Only `female` appears (6 records). Null = no gender restriction stated. |
| `parent_occupation_specific` | 17 | e.g. armed forces, beedi workers, farmers, police personnel. |
| `orphan_or_single_parent` | 10 | True where the scheme names it. |
| `min_marks_percent` | 4 | Rarely published on the listing. |
| `age_min` / `age_max` | 1 | Almost never stated. Do not build a flow that depends on it. |

**70 of 100 records** have state + level + category together — the realistic
core for a first matcher. Only **10** additionally have an income ceiling.

### A note on "national"

`["all"]` means the scheme is open across India. It is **not** simply a synonym
for "centrally funded": a central-government scheme restricted to one region
(e.g. *PM USP Special Scholarship for Jammu Kashmir and Ladakh*) carries
`["Jammu and Kashmir", "Ladakh"]`, not `["all"]`. Filter on `states` and trust it.

## Application fields — what you tell the student to do

| Field | Coverage | Notes |
|---|---:|---|
| `application_mode` | 100 | `NSP` 94, `provider_website` 6. |
| `application_url` | 100 | Where to apply. For NSP schemes this is the NSP listing. |
| `application_deadline` | 84 | ISO `YYYY-MM-DD`. **Re-verify before every send** — see ACTION_ITEMS #2. |
| `deadline_is_tentative` | 10 | True = the source itself hedged. Never present this as firm. |
| `documents_required` | 87 | Controlled vocabulary. Most common: aadhaar 78, bank_passbook 52, domicile_certificate 52, income_certificate 45, marksheet 38, self_declaration 33. |
| `benefit_amount_min_inr` / `_max_inr` | 37 | Integers. When equal, the scheme states a single figure. |
| `benefit_amount_text` | 45 | Verbatim source text. **Prefer showing this** over the parsed integers when both exist — it carries conditions the integers drop. |
| `benefit_type` | 48 | `maintenance` 24, `mixed` 21, `tuition` 3. |
| `renewable` | 55 | True = continues across years subject to `renewal_criteria` (69). |
| `duration_years` | 2 | Almost never stated separately. |
| `number_of_awards` | 3 | Deliberately sparse — see ACTION_ITEMS #3. |

## Identity fields

| Field | Coverage | Notes |
|---|---:|---|
| `id` | 100 | Stable hash of normalized name + provider. Use as primary key. |
| `name` | 100 | Cleaned title, selection-basis suffix stripped. |
| `provider_type` | 100 | `central_govt` 92, `private` 4, `state_govt` 4. |
| `administering_body` | 94 | The ministry/department or state that runs it. |
| `provider_name` | 41 | Often duplicates `administering_body`; prefer that field. |
| `scheme_year` | 94 | e.g. `2026-27`. |
| `selection_process` | 94 | `merit`, `means`, `merit_cum_means`, `interview`, `test`. |

## Fields that are structurally empty

`aliases`, `course_types`, `field_of_study`, `districts`, `religion_specific`,
`disability_type`, `grade_criteria`, `entrance_exam_required`,
`entrance_exam_name`, `other_criteria`, `typical_announcement_month`,
`documents_other` are **0/100**.

They exist in the schema and the extractors are written, but no source in this
crawl published them in a form we could read without guessing. They are kept in
the schema so later sources can fill them. Do not build UI that assumes them.

## Ranking

`reach_score` (0–100) estimates how many students a scheme can serve — geography
34, category 18, level 18, awards 18, recurrence 12, then ×1.08 if active. It is
a **reach** measure, not a quality or generosity measure. `rank` is the position
after sorting. Ties break on completeness.

A component the source did not state scores 0. So a genuinely broad scheme that
published little will rank below an equally broad one that published fully. That
is intended — it rewards sources students can actually act on.

## Files

| File | Use |
|---|---|
| `dataset/bot_matching.json` | **Start here.** 37 matching-relevant fields, nulls explicit. |
| `dataset/top100.json` | Full records, all fields. |
| `dataset/top100.csv` | Same, spreadsheet-friendly. Lists are `; `-joined. |
| `dataset/filters_index.json` | Every distinct value actually present, with counts. Build dropdowns and NLU vocab from this. |
| `dataset/all_scholarships.csv` | All 229 incl. 129 backlog records (unverified). |
| `dataset/scholarships.db` | SQLite: `scholarships`, `review_queue`, `crawl_log`, `run_meta`. |
