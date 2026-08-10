# Submission — Khoji.AI

**Deadline: 10 August.** Form: <https://airtable.com/app1aMCFN8uXV3xmR/pagVsH6fhygczzUfL/form>

The brief asks for three things. Each has a file here, written to be pasted or
linked directly.

| Brief asks for | File | Status |
|---|---|---|
| 1. An AI workflow you can show | **`AI_WORKFLOW.md`** | ✅ ready |
| 2. A project someone can use | **`PROJECT.md`** | ⬜ needs public repo |
| 3. A real impact angle | **`IMPACT.md`** | ✅ ready |
| — Demo video | **`DEMO_SCRIPT.md`** | ⬜ needs recording |

---

# What you need to do

Roughly **2 hours**, in this order. Steps 1–3 are the blockers.

---

## ☐ 1. Make the repo public (~20 min)

The brief requires a public repo. **Safety first — this has been checked:**

- ✅ `.env` is git-ignored, verified
- ✅ No live API key appears in any file git would track
- ✅ `data/raw`, `data/logs`, `data/interim` excluded

```bash
cd "/Users/voyager/Desktop/AI Hackathons/ScholarSaathi AI"

# Confirm for yourself that no secret is about to be committed:
git status --short
git check-ignore -v .env          # must print a .gitignore line

git add -A
git commit -m "Khoji.AI: WhatsApp scholarship bot for Indian students"

gh repo create khoji-ai --public --source=. --push
```

⚠️ **Before pushing, open `.env.example` and confirm every value is blank.**
It is a template; it must never carry a real key.

Then paste the repo URL into `PROJECT.md` where it says `<repo-url>`.

---

## ☐ 2. Copy the README to the repo root (~2 min)

The brief says *"a README that gets someone running in 5 minutes."*
`PROJECT.md` is exactly that.

```bash
cp submission/PROJECT.md README.md
```

*(This overwrites the current pipeline-focused README — which is fine; the old
content lives on in `docs/`.)*

---

## ☐ 3. Record the demo video (~40 min)

Follow **`DEMO_SCRIPT.md`** — 3 minutes, exact lines and inputs.

```bash
# Kill the cold start first:
gcloud run services update edudisha --region asia-south1 --min-instances 1
```

Record the **web demo**, not WhatsApp — no allowlist, and you can retake instantly.

Upload unlisted to YouTube, put the link in the form.

```bash
# Afterwards, back to free:
gcloud run services update edudisha --region asia-south1 --min-instances 0
```

---

## ☐ 4. Fill the form (~20 min)

I couldn't read the Airtable form (it needs a real browser), so map by hand:

| Likely field | Use |
|---|---|
| Project name | **Khoji.AI** |
| One-line description | *A WhatsApp bot that helps underprivileged Indian students find scholarships they actually qualify for — in Hindi, on a shared family phone.* |
| Live URL | `https://edudisha-e5crtuobjq-el.a.run.app/demo` |
| Repo | your GitHub URL |
| Demo video | your YouTube link |
| AI workflow | paste from `AI_WORKFLOW.md` — lead with the twelve failures |
| Impact | paste from `IMPACT.md` — lead with Farheen |

**If a field has a tight character limit,** use these:

*AI workflow, short version:*
> Claude Code wrote the pipeline and bot; Gemini reads Hindi at runtime. The
> rule I enforced: **AI handles language, never facts.** Eligibility is
> deterministic rules over government PDFs. Twelve real extraction failures
> shaped that — "maximum 4 years duration" became an age limit of 4, a table row
> label became a ₹2 benefit, one PDF covering three schemes labelled a
> university scholarship "class 9–10". Each is now a regression test; 138 tests
> plus a 21-check live smoke test, because four of the bugs passed every unit
> test and only showed up end-to-end.

*Impact, short version:*
> Farheen, Class 10, Tonk, Rajasthan. 88%. Her family can't pay next year's
> fees, and a scholarship she qualifies for sits unclaimed. ₹3,400 crore of
> minority scholarship budget went unspent 2023–26 while students drop out for
> want of it. The money exists; discovery doesn't. She sends one Hindi message
> and gets five verified matches with deadlines, documents and official links.

---

## ☐ 5. Optional if time allows

- **Update the pitch deck.** Slide 15 shows an illustrative conversation — you
  can now screenshot the real one. Slide 13's "15–20 hand-verified schemes"
  understates it: 219 served, 22 Rajasthan-specific.
- **Register your own WhatsApp number** so evaluators can message it directly
  (~30 min, irreversible for that SIM). Not required — the web demo has no limit.

---

# Say this plainly if asked

**"Can evaluators message the WhatsApp bot?"**
Not from any number yet — it's on Meta's test number, capped at 5 pre-registered
recipients. That's a Meta account tier, not a product limit. **The web demo has
no such limit and is the same bot.**

**"How much of this is real?"**
219 scholarships crawled from government sources, 68 re-verified against their
official pages, 22 specific to Rajasthan with Hindi names. Live on Cloud Run and
WhatsApp Cloud API. 138 tests.

**"What doesn't work yet?"**
144 of 219 records have no income ceiling — the government PDFs don't legibly
publish one, and the bot says so rather than guessing. Voice notes need the
model, which is on a free tier capped at 20 calls/day. Mentor matching is V3 and
deliberately not built, because it involves minors and the safety infrastructure
comes first.

Being straight about these is a feature. The whole product is built on refusing
to state things the source didn't.
