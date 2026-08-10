# The project

*Criterion 2: live URL, public repo, a README that gets someone running in 5 minutes.*

---

## Try it right now — nothing to install

**Web demo (open to anyone, any device):**

```
https://khoji-e5crtuobjq-el.a.run.app/demo
```

WhatsApp-styled chat, same engine and same data as the real bot.

**Three things to try:**

| Type this | What it shows |
|---|---|
| `hi` then `Rajasthan` → `1` → `12` → `3` → `2.5 lakh` | The guided flow, 5 real matches |
| `I'm an OBC girl in class 12 in Rajasthan, income 2 lakh` | One sentence → straight to results |
| `मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख` | Full Hindi in, full Hindi out |

Then reply with a result number for the deadline, documents and official link.

**Health/status:** `https://khoji-e5crtuobjq-el.a.run.app/health`

---

## WhatsApp — live, with one honest caveat

The bot is fully working on **WhatsApp Cloud API**: `+1 555-202-9853`

⚠️ It currently runs on Meta's **test number**, which is limited to **5
pre-registered recipients**. If you message from an unlisted number you will get
silence, because Meta blocks the outbound reply.

**This is a Meta account-tier limit, not a limitation of the product.** Removing
it means registering a dedicated number (irreversible for that SIM) and is a
30-minute change: one environment variable and a redeploy.

**Please evaluate using the web demo** — it has no allowlist and is the same bot.
Happy to add a specific number to the WhatsApp allowlist on request.

---

## What's actually built

| | |
|---|---|
| Scholarships served | **219** (251 crawled, 32 withheld by a quality gate) |
| Rajasthan-specific | **22**, with Hindi names |
| States represented | **30** |
| With a verified income ceiling | 75 |
| With a deadline | 139 |
| Re-checked against the official source | 68 |
| Domains robots-checked before crawling | **70** |
| Automated tests | **138** + a 21-check live smoke test |

---

## Architecture

```
WhatsApp / Web
      │
      ▼
Cloud Run (FastAPI)  ── Firestore (sessions, hashed phone, 48h TTL)
      │                └ Secret Manager (keys)
      ├── intent.py     what is the student doing?      (rules first)
      ├── matching.py   eligibility                     (rules ONLY — no model)
      ├── llm.py        language, voice, questions      (Gemini / OpenRouter)
      └── bot_matching.json   the verified catalogue
                    ▲
                    │  built offline, never at request time
      crawl → parse → rank → verify → export
      (Playwright, pypdf, tesseract OCR)
```

**Eligibility never touches the model.** It is deterministic rules over a
verified catalogue; the model only turns a result into language the student
reads. A wrong "yes" costs a student an application cycle.

---

## Run it yourself in 5 minutes

```bash
git clone https://github.com/vgarg9653/khoji && cd khoji-ai
python3 -m venv .venv
./.venv/bin/pip install -r requirements-bot.txt
./.venv/bin/python bot/simulate.py
```

That's it — a working bot in your terminal, using the committed dataset.
**No API key needed**: without one it runs rule-based in English, which covers
the whole guided flow.

**Optional, for Hindi/voice:**
```bash
cp .env.example .env
./deploy/set_key.sh GEMINI_API_KEY      # hidden input, never echoed
```

**Run the tests:**
```bash
./.venv/bin/python -m pytest tests/ bot/tests/ -q      # 102 tests
```

**Rebuild the data from scratch** (needs Playwright, ~20 min, polite crawler):
```bash
./.venv/bin/pip install -r requirements.txt
./.venv/bin/playwright install chromium
./.venv/bin/python src/fetch_robots.py     # robots policy FIRST
./.venv/bin/python pipeline.py crawl parse rank verify export
```

**Deploy your own:**
```bash
./deploy/setup_secrets.sh     # guided, generates the random secrets for you
./deploy/push_secrets.sh      # into Google Secret Manager
./deploy/deploy.sh            # Cloud Run
./deploy/smoke_test.sh        # 14 checks against the live service
```

---

## Repo layout

```
bot/          the WhatsApp bot — matching, intent, language, webhooks
src/          the data pipeline — crawler, parsers, ranking, verification
deploy/       guided secret setup, deploy, smoke test, progress checker
tests/        102 regression tests, each from a real observed failure
deliverables/ the dataset + data dictionary + compliance trail
docs/         handoff documentation
submission/   this folder
```

---

## Cost

**₹0 to run.** Cloud Run scales to zero, Firestore's free tier covers the
volume, and WhatsApp service conversations — replies to a student who messaged
first — are free. The bot never initiates a conversation, so it never enters
paid territory.

The main path uses **zero model calls**: English *and* Hindi conversations run
entirely on rules. The model is only needed for voice notes and unusual phrasing.

---

## Privacy

- Phone numbers stored as a **salted SHA-256 hash** — the database never holds a
  readable number, and they are redacted from logs too
- Sessions **auto-delete after 48 hours** (enforced by a Firestore TTL policy)
- **No documents, no Aadhaar, no bank details** are collected — V1 is guidance only
- Secrets live in Secret Manager; `.env` is git-ignored and never shipped
