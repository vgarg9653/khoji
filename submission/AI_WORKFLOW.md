# How this was built with AI

*Criterion 1: which tools, in what order, actual prompts, where it went wrong, what was verified.*

The short version: **AI wrote most of the code and reads the language. It was not
allowed anywhere near the facts.** Every scholarship figure a student sees comes
from a deterministic parser reading an official government PDF, and the twelve
bugs below are the reason that rule exists.

---

## The tools, in the order they were used

| # | Stage | Tool | What it did |
|---|---|---|---|
| 1 | Build | **Claude Code (Opus)** | Wrote the crawler, parsers, matcher, bot, deploy scripts, 224 tests |
| 2 | Crawl | **Playwright (headless Chromium)** | NSP renders its scheme list client-side; static HTML returns an empty table |
| 3 | Extract | **pypdf → pdfminer.six** | Read 130 official guideline PDFs |
| 4 | Extract (fallback) | **tesseract + poppler** | OCR for 35 scanned PDFs with no text layer |
| 5 | Runtime | **Gemini 3.5 Flash Lite** | Reads Hindi/Hinglish, transcribes voice notes, answers questions |
| 6 | Host | **Cloud Run + Firestore + Secret Manager** | Scales to zero; sessions expire in 48h |

**Model choice is one environment variable.** `LLM_PROVIDER=gemini|openrouter`,
`LLM_MODEL=<anything>`. Built that way deliberately — see failure #11.

---

## The rule that shaped the architecture

> **The model handles LANGUAGE. The catalogue handles FACTS.**

A wrong "yes" costs a student an application cycle. So eligibility is decided by
`bot/matching.py` — pure rules, no model — and every value the model returns is
validated against a controlled vocabulary before it is trusted.

```python
# bot/llm.py — every model output passes through this
def validate_extraction(data: dict) -> ExtractedProfile:
    state = (data.get("state") or "").strip()
    for s in STATES:                      # 36 real states/UTs
        if s.lower() == state.lower():
            out.state = s                 # accepted only if it exists
            break
```

Feed it `{"state": "Wakanda", "category": "VIP"}` and both are dropped. There is
a test asserting exactly that.

---

## Actual prompts in production

**Extraction** (`bot/llm.py`), with the anti-guessing instruction that matters:

```
You extract structured facts from an Indian student's message.

Return ONLY fields the student actually stated or clearly implied. If something
is not stated, return null for it. Never guess. Guessing causes a student to be
shown scholarships they cannot apply for.

- state: one Indian state or union territory, spelled in full English. Map
  cities to their state (Jaipur -> Rajasthan).
- family_income_inr: yearly family income as a plain integer in rupees.
  "2 lakh" is 200000. "ढाई लाख" is 250000. If monthly, multiply by 12.

The student may write in any Indian language, in that language's script or in
Latin transliteration (Hinglish). Understand both.
```

**Grounded answering** — the model may only use the record it is given:

```
You will be given that scholarship's record as JSON. Answer ONLY from that
record. This is the entire basis for your answer.

- If the record does not contain the answer, say plainly that the source does
  not state it and tell the student to check the official page. Do NOT use
  general knowledge about Indian scholarships to fill the gap, even if you are
  confident.
- A field that is null means the source did not publish it. Say so.
```

**Voice transcription** — instructed to admit uncertainty:

```
Set confident to false if the audio is noisy, clipped, or you had to guess at
numbers, names or amounts. A wrong number here sends a student to the wrong
scholarship, so say when you are unsure.
```

When `confident` is false the bot repeats what it heard and asks before acting.

---

## Where it went wrong — twelve real failures

Every one was caught in this build. Each now has a regression test.

### Extraction inventing plausible numbers

| # | What happened | Why it mattered | Fix |
|---|---|---|---|
| 1 | `"maximum 4 years duration"` → **age limit 4** | Would exclude every applicant | Age must appear in the same sentence as the number |
| 2 | An award **amount** read as an award **count** | Fabricated slot numbers | Count and noun must be adjacent; sentences about money rejected |
| 3 | A table row label `"Sl. No. 2"` → **benefit of ₹2** | Absurd figure shown as fact | Floor of ₹100 on any rupee value |
| 4 | OCR read a ceiling of **₹24,000** | Would wrongly exclude nearly everyone | Figures from OCR must match a standard ceiling (₹1L, ₹2.5L, ₹8L…) or be dropped |

### Attributing one scheme's facts to another

**5. One PDF, three schemes.** `DEPDGuidelines_1.pdf` covers pre-matric,
post-matric and top-class scholarships. The parser applied its class range to
all three, labelling a **university** scholarship "classes 9–10". Now
scheme-specific fields are left null unless the document can be split by scheme.

**6. Department ≠ eligibility.** Rajasthan lists *Anuprati* under its Minority
department, so I tagged it minority-only. Anuprati is open to SC/ST/OBC/EBC
**and** minority — the inference **excluded OBC students from a scheme they
qualify for.** Categories now come only from what a scheme's own name states.

**7. Central ≠ national.** *PM USP Special Scholarship for Jammu Kashmir and
Ladakh* was tagged as open India-wide, so it surfaced for a student in Assam.
The mirror case sat beside it: *"Central Armed Police Forces and **Assam
Rifles**"* is a regiment, not the state, and genuinely *is* national. Opposite
fixes, both tested.

### Silent data loss between layers

**8. Devanagari destroyed by an HTTP default.** `requests` falls back to
ISO-8859-1 when a server omits `charset`. Indian government portals routinely
omit it, so `विभाग` arrived as `à¤µà¤¿à¤­à¤¾à¤`. Every Hindi scheme name in the
crawl was corrupted — invisible until a Hindi-language source was added.

**9. A line break ate the money.** PDFs wrap mid-sentence:

```
"...family income from all sources up to Rs. 8.00
 lakh per annum..."
```

Treating the newline as a sentence end left `Rs. 8.00` without its unit, and a
bare `8.00` is not a plausible amount. **Systematic across every PDF.** I had
already concluded "the sources don't publish it" from a bucketed diagnostic —
reading the raw text proved that wrong.

**10. An empty database made itself disappear.** `self.store = store or
InMemorySessionStore()`. `FirestoreSessionStore` defines `__len__`, and an object
whose `__len__` returns 0 is **falsy** in Python — so an empty session collection
caused a working Firestore store to be silently replaced by an in-memory one.
It would have "fixed itself" after the first conversation.

**11. Hindi understood, answered in English.** The bot parsed
`मैं राजस्थान से हूँ, कक्षा 12, ओबीसी, आय ढाई लाख` perfectly — then replied in
English, because language was only ever detected by the model and the model was
out of quota. For a vernacular-first product that is worse than not understanding.

### Infrastructure that looked fine

**12. A green deploy running the wrong model.** `deploy.sh` defaulted
`LLM_PROVIDER` to `openrouter` instead of reading `.env`, so a Gemini key shipped
as an OpenRouter key against a model that returns 404. Exit code 0, healthy
banner, would have failed on the first student message. The deploy script now
**compares what you asked for against what is actually live** and says so if they
differ.

Related: the hardcoded default model `gemini-2.5-flash` had been retired —
*"no longer available to new users"*. Model ids go stale faster than docs.

---

## What was verified, and how

**224 automated tests.** Not coverage theatre — every case is a real failure
from the list above:

```python
def test_age_ignores_course_duration():
    # Seen in AICTE Swanath: "maximum 4 years duration" was read as age <= 4.
    assert E.parse_age("Rs. 50,000 per annum for maximum 4 years duration.") == (None, None)
```

**A live smoke test** (`deploy/smoke_test.sh`, 21 checks) that talks to the
deployed service over HTTP. This matters because **four of the twelve bugs passed
every unit test** — they lived in the seams between layers, where only an
end-to-end check can see them.

**Verification against the source.** `pipeline.py verify` re-fetches each
scholarship's official URL, re-reads the deadline and eligibility, and flags any
mismatch with the exact snippet that triggered it. 68 records currently carry a
verification date.

**Provenance over content.** Filtering junk records by "does the name say
scholarship" would have dropped the real scheme *"Opportunity Cost To Parents Of
SC Girl Students"*. What separates a scheme from page furniture is **where it came
from** — every row on NSP's list is a scheme by construction. That rescued
`PM-USPY (SSSJKL)` while still withholding `Overview` and `अल्पसंख्यक कार्य मंत्रालय`.

**Nothing is deleted.** The quality gate withheld 32 records — each keeps a
`not_servable_reason`, so a rule can be reviewed or relaxed without re-crawling.

---

## Crawling ethics, enforced in code

robots.txt was checked on **70 domains before any crawling**, and the resulting
policy gates every request:

- **1 request / 3 seconds per domain** with jitter
- **Fails closed** — an unreadable robots.txt is not permission
- `wcd.gov.in` sends `Disallow: /` → **excluded entirely**
- Three domains 403 our user-agent → **excluded**; reaching them would need
  UA spoofing, which was ruled out
- **33 URLs refused and logged**, including 5 cross-domain redirects blocked
  because the destination host had not been vetted

Buddy4Study's public index is one of the sources, crawled under the same policy
as the rest. Records built from it carry `needs_review: true` until they have
been checked against the provider's own page, and the matcher ranks unreviewed
records below verified ones.

---

## The one lesson worth taking away

The most dangerous AI failures here were not hallucinations that looked wrong.
They were **plausible values in the right format**: an age limit of 4, a benefit
of ₹2, a university scholarship labelled "class 9–10".

Both diagnostics I trusted were wrong in the same direction — they summarised my
own extractor's opinion and reported it as fact about the data. Reading the raw
bytes is what found the truth, twice.

Which is why the guarantee this product ships with is not "the AI is accurate".
It is: **a field we could not read is `null`, and the student is told so.**
