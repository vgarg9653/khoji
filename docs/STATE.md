# Current state — Khoji.AI

*Written 9 Aug 2026, as a handoff so work can resume without the full history.*

Formerly EduDisha / ScholarSaathi. The Cloud Run service and GCP project still
carry the old name — see "Open items".

## Live right now

| | |
|---|---|
| Web demo (no limits) | `https://edudisha-e5crtuobjq-el.a.run.app/demo` |
| Health | `https://edudisha-e5crtuobjq-el.a.run.app/health` |
| WhatsApp | `+1 555-202-9853` — **Meta test number, 5 recipients max** |
| GCP project | `edudisha-bot` (823683909408), region `asia-south1` |
| Cloud Run service | `edudisha` |
| Meta app | **still named `EduDisha`** (id `1017501961097775`) · WABA `3918211888485437` · phone id `1346817201841648` |
| WhatsApp profile | renamed to Khoji.AI (about/description/site/category) — display name stuck at *Test Number*, see below |
| Models | router/generation/audio `gemini-3.5-flash-lite`, fallback `gemini-3.1-flash-lite` — see `bot/models.py`. `/health` prints the live chains. |
| Tests | 138 (`pytest tests/ bot/tests/ -q`) + `deploy/smoke_test.sh` (21 live checks) |

Live and current as of 10 Aug 2026: revision `edudisha-00013-qxw`, all 21
`smoke_test.sh` checks passing against the deployed service.

**Deadline: submission 10 Aug.** See `submission/README.md` for the checklist.

## Data

219 served (251 crawled, 32 withheld by the quality gate) · 22 Rajasthan-specific ·
30 states · 75 with income ceiling · 139 with deadline · 68 re-verified.

## What the catalogue actually covers (measured 10 Aug 2026)

**NSP is complete.** All three public filter views were rendered and parsed with
no pagination: central sector 31, centrally sponsored 105, state schemes 32 →
165 unique. That is everything `scholarships.gov.in/All-Scholarships` lists.

**Everything else is thin, and two gaps are structural:**

1. **The biggest states are missing.** Bihar, Madhya Pradesh, Tamil Nadu, Andhra
   Pradesh, Odisha and Jharkhand have **zero** state-specific schemes; UP, West
   Bengal and Karnataka have one each. The over-represented states (Himachal 20,
   Puducherry 11, Uttarakhand 11) are the small ones — precisely because small
   states publish *through* NSP while large states run their own portals. We
   crawled exactly one of those portals (Rajasthan → 22 schemes).
2. **Private is effectively zero.** 5 "private" + 4 "ngo" records, and most are
   page artifacts scraped off provider websites — "Our Scholars 2025-26",
   "The Scholarship". Perhaps two are real. `data/interim/b4s_names.json` holds
   **1,205 discovered names we have never crawled**, ~63 clearly corporate/CSR.

Field completeness on the 219 served: income ceiling 34%, deadline 63%,
documents 63%, amount 22%, marks cutoff 2%, re-verified 31%.

## Architecture in one paragraph

An offline pipeline (`src/`, `pipeline.py`) crawls official sources under a
robots policy, extracts eligibility from guideline PDFs, ranks by reach, verifies
against the source, and exports `deliverables/dataset/bot_matching.json`. The bot
(`bot/`) serves that file: `intent.py` classifies each message, `matching.py`
decides eligibility with **rules only**, `relevance.py` then decides what is worth
showing, `llm.py` handles language/voice/questions, `app.py` exposes Twilio + Meta
webhooks and the `/demo` page. Cloud Run + Firestore.

## Two filters, both rules-only

`matching.py` answers *can they apply* — three-valued, never guessing.
`relevance.py` answers *is it worth their screen* and sorts the survivors:

- **applicable now** — fits what they are studying today
- **plan ahead** (🔭) — exactly one step up the ladder, and on the path they
  described. These fail eligibility on level alone, so `match()` deliberately
  keeps records whose *only* failing criterion is how far along the student is.
- **suppressed** — an earlier stage, more than one step ahead, the wrong stream,
  or coaching for an exam they have passed. Shown only if nothing else survives,
  and labelled when it is.

Missing data never suppresses: a scheme that states no level, or a student who
has not said theirs, always lands in "applicable now".

## Models

One model doing every job meant one `429` took Hindi, voice notes and free-form
answers down together, silently, for a day — the bot was found live in exactly
that state, with `gemini-3.6-flash` exhausted and three other models on the same
key answering instantly.

`bot/models.py` routes by **role** (router / generation / audio) and falls back
to a **different family** on 429/404, because a free-tier quota is per model:
falling back is capacity already paid for, not a downgrade. All four are env
vars, so a price change or a deprecation is a redeploy, not an edit.

Measured on this key, 10 Aug 2026 (`scratchpad/bench.py`):

| model | extraction | latency | verdict |
|---|---|---|---|
| `gemini-3.5-flash-lite` | 5/5 | ~1.0s | primary for every role |
| `gemini-3.1-flash-lite` | 5/5 | ~1.1s | fallback — separate bucket |
| `gemini-3.6-flash` | — | — | quota exhausted |
| `gemini-2.5-flash-lite` | — | — | 404, not available to this key |
| `gemma-4-31b-it` | 5/5 | ~13.6s | correct, far too slow for WhatsApp |

Embeddings (`gemini-embedding-2`) exist on this key and are deliberately unused:
219 records matched by deterministic rules do not need semantic search, and it
would add a way to be confidently wrong.

## Understanding an answer

Three layers per slot, cheapest first (`Bot._understand`):

1. the option list — a number, the exact value, a label
2. `extract_rules` — synonyms, Hindi, Hinglish, abbreviation expansions
3. the model — genuinely unusual phrasing and typos

Layer 2 exists because "Scheduled Caste" is what SC *abbreviates*; being told
that was not understood is indefensible, and it should not cost a network call.
Layer 3 is a fallback, not a rationing decision — when a model is available it
gets used.

## Conversation

`welcome` (bilingual, never translated) → name → state → level → class → category
→ income → aspiration (optional) → results → detail → `more` / `documents`.

- **Language is re-decided on every message** from script and wording — Devanagari
  → `hi`, Roman-script Hindi markers → `hinglish`, else `en`. **Never from the
  name.** Copy for all three ships pre-translated (`copy_hi.py`,
  `copy_hinglish.py`), so a full conversation still costs zero model calls.
- **Inferred profiles are read back before matching.** Anything from a voice note
  or a one-sentence profile gets one confirmation line; answers typed one at a
  time do not.
- `bas dikhao` / "just show me" skips the rest and shows what we have.

## The rule everything follows

**A field we could not read is `null`, and the student is told so.** Eligibility
is three-valued — `ELIGIBLE` / `NOT_ELIGIBLE` / `UNKNOWN` — and `UNKNOWN` never
silently passes or fails. The model handles language; it is never allowed near a
fact.

## Deploy loop

```bash
./deploy/setup_secrets.sh --check     # what's configured
./deploy/push_secrets.sh              # .env -> Secret Manager
./deploy/deploy.sh                    # verifies live config matches intent
./deploy/smoke_test.sh                # 14 checks against the deployed service
```

Data rebuild: `pipeline.py crawl parse rank verify export` then
`src/make_deliverables.py`. **NSP state scoping is assigned during `crawl`, not
`parse`** — changing `sources/nsp.py` or state logic needs a re-crawl (~20s, cached).

## Open items, in priority order

1. **Rotate the Gemini key** — the current one appeared in a chat transcript.
   `./deploy/set_key.sh GEMINI_API_KEY` → `push_secrets` → `deploy`.
2. **Rename the Cloud Run service** — `SERVICE=khoji ./deploy/deploy.sh` creates a
   *second* service on a *new* URL; the Meta webhook and every shared link must be
   re-pointed the same day. The GCP project id `edudisha-bot` cannot be renamed
   at all. Left as-is deliberately.
3. **Webhook signature validation** (`X-Hub-Signature-256`) — not implemented.
   Fine behind a 5-number allowlist; required before real students.
4. **Register own WhatsApp number** — removes the 5-recipient cap. Registering a
   real number does NOT require Business Verification; the 250/day cap applies
   only to business-*initiated* messages, and this bot only ever replies.
   Blocked on deleting WhatsApp Business from that SIM (irreversible).
5. **Voice notes need the model** — capped at 20/day on the free tier.
6. **144 records without income ceiling** — not legibly in the sources.
7. **Content is composed, not yet human-approved.** `src/content.py` builds the
   plain-language fields from verified data + fixed human-written phrasing, and
   marks them `content_status: "composed"`. `data/content_approvals.json` lets a
   human edit or approve any record; approved ones flip to `"human_approved"`.
8. **"Not sure yet" hides plan-ahead results** by design (the brief's rule). Worth
   revisiting — it is the most common answer, so it may be quietly switching off
   the exposure half of the product.
9. **Part B — the bebarfi.com rebuild** — not started.

## Gotchas already paid for

- `requests` defaults to ISO-8859-1 without a `charset` header → mangles Devanagari.
- PDFs wrap mid-sentence, splitting `Rs. 8.00` from `lakh`.
- An object defining `__len__` is falsy when empty — `store or Default()` discards it.
- Firestore doesn't persist `last_results`; only ids are stored and rehydrated.
- Meta: ticking `messages` is not enough — the **app must be subscribed to the
  WABA** (`POST /{waba-id}/subscribed_apps`).
- **Meta returns `success: true` for a display-name change on a test number and
  does nothing.** `POST /{phone-id}` with `new_display_name` is accepted and
  `verified_name` stays `Test Number`. Always re-read the field; do not trust
  the write.
- The WhatsApp *business profile* (about, description, website, category) IS
  writable on a test number — that is the part a student sees when they tap the
  contact, so the brand can land there before the display name can.
- Renaming the WABA needs a capability the System User token lacks; renaming the
  Meta app needs an **app access token** (`{app-id}|{app-secret}`), not a user or
  system-user token.
- Model ids go stale; `bot/llm.py` run directly lists what the key can actually use.
- Eligibility already filters by level, so a relevance layer bolted on after it
  is a no-op — the aspirational bucket was empty for every student until `match()`
  stopped discarding level-only failures.
- The catalogue is written in English and translated at delivery. Multi-paragraph
  screens translate in ONE call and fall back to English if the paragraph count
  comes back different.
- **The intent classifier will hijack literal commands.** With a model attached,
  "documents" was classified as a QUESTION and answered in invented prose — a
  quota call spent to produce something worse than the list we already had.
  Commands are matched by rule and answered before anything interprets them.
- **A hand-written list of persisted fields always drifts.** `store_firestore`
  now derives its field set from the `Session` dataclass, and a test asserts the
  two agree. Adding a Session field without deciding about persistence used to
  pass every test and fail only in production, because the in-memory store keeps
  the whole object.
