# Khoji.AI WhatsApp bot

Reads the verified dataset and helps a student find scholarships they can
actually apply for.

## Try it right now — no WhatsApp account needed

```bash
python bot/simulate.py                 # interactive, in your terminal
python bot/simulate.py --script demo   # scripted run
```

The simulator drives the *same* engine the webhook calls, so what you see is
what a student sees.

## Run the webhook

```bash
pip install -r requirements.txt
uvicorn bot.app:app --reload --port 8000
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | dataset stats + session count; use as your liveness probe |
| `POST /webhook/twilio` | Twilio WhatsApp (form-encoded in, TwiML out) |
| `GET,POST /webhook/meta` | Meta Cloud API (verify handshake + JSON messages) |
| `POST /webhook/test` | provider-free, for curl and integration tests |

```bash
curl -X POST localhost:8000/webhook/test \
  -H 'Content-Type: application/json' \
  -d '{"phone":"+919812345678","text":"hi"}'
```

### Environment

| Variable | Needed for |
|---|---|
| `EDUDISHA_DATA` | path to `bot_matching.json` (defaults to `deliverables/dataset/`) |
| `TWILIO_AUTH_TOKEN` | validating Twilio's signature — **set this in production** |
| `META_VERIFY_TOKEN` | Meta's subscription handshake |
| `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID` | sending replies via Meta |

Without `TWILIO_AUTH_TOKEN` the server accepts unsigned requests and logs a
warning. That is fine locally and wrong in production — anyone who finds your
URL could drive the bot.

## Design

```
app.py           webhook adapters (Twilio / Meta / test) — protocol only
engine.py        message in -> replies out; owns session state
conversation.py  the slot-filling flow, option lists, input parsing
matching.py      eligibility engine — the important file
messages.py      WhatsApp text rendering
simulate.py      local CLI simulator
```

`engine.py` knows nothing about WhatsApp, which is why the whole flow is
testable without a network.

## The rule the matcher enforces

Eligibility is three-valued, never boolean:

| Verdict | Meaning | What the bot does |
|---|---|---|
| `ELIGIBLE` | student meets a criterion the source stated | ✅ shown as met |
| `NOT_ELIGIBLE` | student fails a stated criterion | scholarship hidden entirely |
| `UNKNOWN` | **the source never stated it** | ❓ shown, and flagged to check |

`UNKNOWN` never disqualifies and never silently passes. A scheme whose income
ceiling we could not read is still offered, with "income limit not stated by the
source" printed against it — because 48 of 100 records have no readable ceiling,
and pretending otherwise would tell students they qualify when they may not.

A criterion that does not apply — class range on a PhD scheme — is skipped
rather than flagged. Warning on everything teaches students to ignore warnings.

## Conversation flow

```
hi ─▸ state ─▸ level ─┬─▸ class (school only) ─┬─▸ category ─▸ income ─▸ results ─▸ detail
                      └────────────────────────┘
```

Four questions, numbered replies. `restart` and `help` work at any point, and
`skip` is accepted for income. Only school students are asked their class —
asking a PhD student wastes a turn.

Free text also works: "up", "TN", "mumbai" all resolve to states; income accepts
"2 lakh", "2,50,000", "50k".

## Tests

```bash
python -m pytest bot/tests/ -q     # 22 tests
```

The ones worth reading assert the safety properties: unstated income stays
`UNKNOWN` even for a student earning ₹50 lakh, expired scholarships are never
offered, wrong-state schemes are excluded outright, and `handle()` never raises
— a crash mid-flow would strand a student with no way forward.

## Before going live

1. **Swap the session store.** `InMemorySessionStore` loses every conversation
   on restart and breaks with more than one worker. Put Redis behind the same
   `get/save/reset` interface.
2. **Set `TWILIO_AUTH_TOKEN`** (or Meta's equivalent signature check).
3. **Re-run `pipeline.py verify` on a schedule** and redeploy the dataset.
   Deadlines are the thing most likely to be wrong, and a stale deadline is the
   error most likely to hurt someone.
4. **Add Hindi and regional languages.** All copy lives in `messages.py`;
   `Session.language` is already threaded through but unused.
5. **Log what students search for.** The gaps in the dataset (private schemes,
   big-state portals) are best prioritised by what people actually ask for.
