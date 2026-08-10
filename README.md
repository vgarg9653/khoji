# Khoji.AI

**Khoji.AI (previously EduDisha / ScholarSaathi) is a free, multilingual
WhatsApp assistant bringing financing and exposure to underserved
students in India. Built by Barfi Institute.

The two barriers it addresses:
- FINANCING — students who qualify for scholarships never find them,
  don't understand eligibility, or stall before applying.
- EXPOSURE — students can't aim at paths they've never seen, and have
  no one to ask about what comes next.

V1 addresses financing: verified scholarship discovery, eligibility
explanation, and guidance to official applications, with a three-mentor
relay for stuck cases. V2 (course-fit guidance) and V3 (mentor matching)
address exposure.**

Built by [Barfi Institute](https://www.bebarfi.com). Always free for students.


---

## Try it right now

**No install, no login, works on any device:**

### → https://khoji-e5crtuobjq-el.a.run.app/demo

Three things worth typing:

| Type this | What it shows |
|---|---|
| `hi` | The guided flow — name, state, class, category, income |
| `I'm an OBC girl in class 12 in Rajasthan, income 2 lakh` | One sentence, straight to results |
| `मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख` | Full Hindi in, full Hindi out |

Then reply with a result number, and try `more` or `documents`.

**On WhatsApp:** `+1 555-202-9853` — but this is Meta's *test* number, capped at
5 pre-registered recipients. Message it from an unlisted number and you get
silence, because Meta blocks the reply. That is an account tier, not a product
limit. **The web demo is the same bot with no cap.**

---

## What is actually in this repository

Two programs that share one file. That is the whole shape of it.

```
src/         The data pipeline.   Runs on your laptop, occasionally.
bot/         The WhatsApp bot.    Runs in the cloud, on every message.
             ↑ they share deliverables/dataset/bot_matching.json
```

The pipeline crawls government scholarship portals, reads their PDF guidelines,
extracts who is eligible, checks it against the source, and writes one JSON
file. The bot serves that file. The bot never crawls anything.

| Folder | What it is |
|---|---|
| **`bot/`** | The conversation. Reads a message, decides what it means, matches it against the catalogue, writes a reply. Runs on Google Cloud Run. |
| **`src/`** | The pipeline that builds the catalogue. Crawlers, PDF readers, the eligibility extractor, the quality gate. Never deployed. |
| **`deliverables/dataset/`** | **`bot_matching.json`** — the 298 scholarships the bot serves. Open it; it is readable. |
| **`deliverables/compliance/`** | Proof of how we crawled: every domain's robots.txt policy, and every URL we refused to fetch. |
| **`deploy/`** | Shell scripts that put it live and check it stayed live. Start with `deploy/check.sh`. |
| **`docs/`** | [Setup](docs/SETUP.md) · [Deploying](docs/DEPLOY.md) · [Current state](docs/STATE.md) · [Principles](docs/PRINCIPLES.md) · [Data dictionary](docs/dataset/DATA_DICTIONARY.md) |
| **`tests/`, `bot/tests/`** | 224 tests. Nearly every one exists because something specific broke once. |
| **`tools/`** | Two dev tools: benchmark language models, and check whether a new source needs a browser. |
| **`data/`** | Pipeline working files. Not in the repo — ~400 MB, and fully reproducible. |

---

## Run it on your machine in 5 minutes

You need **Python 3.11+** and nothing else. No API key, no cloud account, no
database. The catalogue is committed, so there is nothing to crawl.

```bash
git clone <this-repo> && cd khoji-ai

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-bot.txt
```

**Talk to it in your terminal:**

```bash
python bot/simulate.py
```

That is the whole bot — same code that answers on WhatsApp, minus the webhook.
Type `hi` and follow it.

**Or run the web version:**

```bash
uvicorn bot.app:app --reload --port 8000
# then open http://localhost:8000/demo
```

**Run the tests:**

```bash
pip install pytest
python -m pytest tests/ bot/tests/ -q
```

Everything above works with **no API key**. Add a Gemini key to `.env` (copy
`.env.example`) and it additionally handles unusual phrasing, voice notes, and
languages beyond the three that ship pre-translated. Without one it still runs —
the model adds reach, it is not load-bearing.

---

## How it works

**There are two clocks, and almost every confusion comes from merging them.**

**Build time** runs on your laptop when you choose. It crawls, reads PDFs,
extracts eligibility, verifies against the source, and writes one 1.3 MB file.
Takes about three minutes. Needs a browser and OCR. Costs nothing.

```bash
python pipeline.py crawl parse rank verify export
python src/make_deliverables.py
```

**Run time** runs on Cloud Run, once per message, in about a second. It loads
that file into memory at startup and never touches a database for scholarships —
298 records fit comfortably in RAM, and a loop over a list beats a query.

Firestore stores one thing: conversations in progress, keyed by a salted hash of
the phone number, deleted after 48 hours. The database never holds a number
anyone could dial.

### The rule everything follows

> **The model handles language. The catalogue handles facts.**

A language model may read a student's Hindi, transcribe a voice note, or rephrase
an answer. It is **never** asked whether someone is eligible, what a scholarship
pays, or when it closes. Those come from the file, or the student is told the
source did not say.

Eligibility is three-valued — `ELIGIBLE` / `NOT_ELIGIBLE` / `UNKNOWN` — and
`UNKNOWN` never quietly becomes a yes.

This is not caution for its own sake. Twelve real extraction failures shaped it:
`"maximum 4 years duration"` became an age limit of 4; a table row label
`"Sl. No. 2"` became a ₹2 benefit. None of those look wrong in a database. They
are plausible, correctly formatted, and completely false.

---

## How it was built, honestly

Crawling followed rules set before any code was written: check `robots.txt` on
every domain, one request per three seconds, a user agent that says who we are,
never log in, never bypass a paywall, cache everything so we never re-fetch.

**70 domains checked. 33 URLs refused and logged** — including five cross-domain
redirects to hosts we had not vetted. The evidence is in
[`deliverables/compliance/`](deliverables/compliance/), not just this paragraph.

Sources are the government portals plus Buddy4Study's public index, all crawled
under the same robots policy. Each record carries the date it was last checked
against its official page, and a `needs_review` flag where that check is still
outstanding — the bot ranks unreviewed records below verified ones.

---

## What does not work yet

Stated plainly, because the whole product is built on refusing to claim things
the source did not say.

- **152 of 298 records have no income ceiling.** The sources do not legibly
  publish one. The bot says so rather than guessing.
- **209 of 298 records are not yet verified against their official page.** They
  came from the August discovery pass and are flagged `needs_review` in the
  data. The matcher ranks them below verified records; that is a mitigation,
  not a fix.
- **Private scholarships used to be absent and no longer are** — 9 records
  became 50. That is the newest part of the catalogue and the least checked.
- **The largest states are missing.** Bihar, Madhya Pradesh, Tamil Nadu, Andhra
  Pradesh, Odisha and Jharkhand have zero state-specific schemes, because large
  states run their own portals and we have crawled exactly one (Rajasthan → 22).
- **Voice notes need a model**, so they depend on an API quota.
- **Mentor matching is not built.** It involves minors; the safety
  infrastructure has to come first.

[`docs/STATE.md`](docs/STATE.md) tracks all of this, with the next steps ranked
by how many students each would reach.

---

## Licence

The code is **MIT licensed** — read it, check it, reuse it. See [LICENSE](LICENSE).

**The scholarship data is not code and the licence does not cover it.** It is
compiled from public Indian government sources and carries no warranty of
accuracy or currency — deadlines and eligibility rules change without notice.
Always confirm details on a scheme's official page before applying. The bot says
this on every result, and so do we.
