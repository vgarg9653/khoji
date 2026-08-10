# Working principles

The three standing directives for this and every future digital product, with
what each one actually changed here. They are also saved to project memory, so
they carry into new work without being restated.

---

## 1. Work as a startup team, not a lone coder

Four lenses, each with a veto:

| Lens | Asks |
|---|---|
| **Product manager** | Who is the user? What is the one metric? What ships in v1 and what is deliberately cut? |
| **UI/UX designer** | What are the actual words on screen? How many steps? What does a confused, low-literacy user on a 4-inch screen see? |
| **Full-stack engineer** | Architecture, data model, cost, what breaks at scale, what stays maintainable. |
| **GenAI engineer** | Where does a model genuinely help vs. where is deterministic code safer? Grounding, guardrails, graceful degradation. |

When lenses conflict, **name the trade-off** rather than silently picking.

### What this caught here

- **PM lens:** results were ranked by `reach_score` — how many students a scheme
  serves *nationally*. Right for choosing what to crawl, wrong for ranking for
  *one* student. 22 Rajasthan schemes sat in the catalogue and never once
  appeared to a Rajasthan student. Fixed with a relevance bonus and a reserved
  slot for home-state schemes.
- **Designer lens:** every PhD scheme carried a "⚠️ check: class" warning,
  because the source stated no class range. A warning on everything teaches
  users to ignore warnings. Criteria that don't apply are now skipped.
- **Designer lens:** the Rajasthan portal shouts in caps. "Economic HELP TO
  Tribal Girls" reads as a bug to anyone watching a demo.
- **GenAI lens:** the model handles language; the catalogue handles facts. Every
  value the model returns is validated against a controlled vocabulary, so a
  hallucinated state is dropped rather than trusted.

---

## 2. Teach while building

The goal is a working product **and** a more capable builder. So: name the tool,
say why it beat the alternative, and explain the concept behind a bug rather
than just patching it.

### Concepts worth keeping from this build

**Why Hindi arrived corrupted.** `requests` falls back to ISO-8859-1 when a
server omits `charset` — an HTTP default from the Latin-1 era. Indian government
portals routinely omit it, so `विभाग` became `à¤µà¤¿à¤­à¤¾à¤`. Every Hindi scheme
name in the crawl was mangled and only a Hindi-language source exposed it.
*Lesson: encoding bugs are invisible until you handle non-ASCII data.*

**Why "who runs it" ≠ "who may use it".** Rajasthan lists Anuprati under the
Minority department, so I tagged it minority-only. Anuprati is open to
SC/ST/OBC/EBC *and* minority — the inference excluded OBC students from a scheme
they qualify for. *Lesson: administrative structure is not eligibility.*

**Why provenance beats content heuristics.** Filtering junk records by "does the
name contain 'scholarship'" would have dropped the real scheme *"Opportunity
Cost To Parents Of SC Girl Students"*. What actually separates a scheme from
page furniture is **where it came from**: every row on NSP's scheme list is a
scheme by construction. *Lesson: trust the source's structure before you trust
the text.*

**Why a missing value is not a negative value.** `income_ceiling: null` means we
could not read one, not that no limit exists. Collapsing those is how a bot
tells a student they qualify when they don't.

---

## 3. Privacy and safety, designed in

### Secrets
- Every key lives in a git-ignored `.env`. **`.gitignore` is created before the
  first key exists** — here there was none, so a `.env` would have been
  committed the moment the repo was initialised.
- `.env.example` is committed and documents every variable: what it does, where
  to generate it, whether it is skippable.
- `./deploy/setup_secrets.sh` walks through each key, opens the right URL, and
  **generates the random ones** (`openssl rand -hex 32`). `.env` is `chmod 600`.
- Values are **never echoed back in full** — masked as `AIza…7f2c`. Never
  hardcoded, never logged.
- Production uses a managed secret store (GCP Secret Manager); `.env` is local.

### Personal data
- Collect the minimum; prefer bands over exact values.
- **Pseudonymise identifiers at rest** — phone numbers are stored as a salted
  SHA-256. An unsalted hash of an Indian mobile is brute-forceable in seconds,
  so a missing salt warns loudly rather than degrading silently.
- **Logs are a disclosure surface too.** A phone number in Cloud Logging is a
  phone number stored, whatever the database holds. All of them are redacted.
- Set retention (sessions expire in 48h) and say so.
- Assume minors are users. That raises the bar for consent and handling under
  India's DPDP Act.

### Choosing tools, models and techniques
Judged on three axes **together** — effectiveness, cost, and openness:

| Choice | Why |
|---|---|
| **OpenRouter** as default LLM provider | One OpenAI-compatible endpoint, any model, swap via `LLM_MODEL`. No lock-in. Gemini-direct stays available for Google credits. |
| **Cloud Run** | Scales to zero — a pilot costs nothing idle. |
| **Firestore** | No server to run; free at this volume. |
| **Deterministic matcher, not an LLM** | Eligibility is a rules problem. A model would be less accurate, more expensive, and unauditable. |
| **tesseract + poppler** for OCR | Open, already installed, no per-page API cost. |
| **SQLite** for the catalogue | One file, no server, trivially inspectable. |

---

## The gate before shipping anything

1. Would a PM cut this? Would a designer read it aloud?
2. Does the user understand *why*, not just *what*?
3. Is any secret outside `.env`? Any personal data unhashed, unbounded, or in a log?
4. Was the tool chosen on effectiveness **and** cost **and** openness?
5. Does the code guess anywhere it should say "not stated"?
