# Demo video script

**Target: 3 minutes.** Strongest material first — most judges stop watching
after 90 seconds, so the product must work on screen before any explanation.

Record the **web demo** (`/demo`), not WhatsApp — no allowlist, no waiting for
messages to arrive, and you can re-record instantly.

**Before recording:**
```bash
gcloud run services update khoji --region asia-south1 --min-instances 1
```
Removes the ~10s cold start. Set back to `0` afterwards.

---

## 0:00–0:20 · The person, not the product

> "Farheen is in Class 10 in Tonk, Rajasthan. She scored 88%. Her family can't
> pay next year's fees — and a scholarship she qualifies for is sitting
> unclaimed right now.
>
> ₹3,400 crore of minority scholarship budget went unspent between 2023 and 2026.
> The money exists. She just can't find it."

*On screen: the phone-sized chat window, empty.*

---

## 0:20–1:00 · It works — one message, in Hindi

Type:
```
मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख
```

> "One message. Hindi. It reads her state, class, category — and 'ढाई लाख',
> two-and-a-half lakh, written in words."

*Let the Hindi reply render fully. Don't talk over it.*

> "Five scholarships, two she fully qualifies for, ranked, in Hindi — and this
> costs zero AI calls. It's all rules."

---

## 1:00–1:30 · The detail — what she actually does next

Type `1`.

> "The deadline. The exact documents to collect. The official government link.
>
> And notice this line —" *(point to a ❓ or the income line)* — "the source
> never published an income limit for this scheme, so it says so. It does not
> guess."

---

## 1:30–2:15 · The part judges should remember

> "The hardest problem wasn't building the bot. It was that AI kept inventing
> numbers that looked completely reasonable."

*Show these three, on screen as text:*

```
"maximum 4 years duration"   →  age limit: 4 years
"Sl. No. 2"                  →  benefit: ₹2
one PDF covering 3 schemes   →  a university scholarship labelled "class 9–10"
```

> "None of those look wrong in a database. They're all plausible, correctly
> formatted, and completely false.
>
> So eligibility never touches the AI. It's deterministic rules over government
> PDFs. The AI reads Hindi and explains results — it is not allowed near a fact.
>
> Twelve failures like this, each one now a regression test. 138 tests."

---

## 2:15–2:45 · Built honestly

> "70 domains robots-checked before a single page was crawled. One said
> Disallow — we skipped it entirely. 33 URLs refused and logged.
>
> Buddy4Study has the best catalogue in India. We took twelve requests from
> their sitemap — names only — and got every detail from the government's own
> page instead."

*Show `deliverables/compliance/skipped_urls.jsonl` briefly.*

---

## 2:45–3:00 · Where it goes

> "Live on WhatsApp Cloud API and on the web. 219 verified scholarships, 22
> specific to Rajasthan. Runs at zero rupees.
>
> Next: Farheen's own district, more states, and the mentor relay for the cases
> a bot shouldn't answer alone."

---

# Cheat sheet — exact inputs

| # | Type | Shows |
|---|---|---|
| 1 | `मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख` | Hindi, one-shot |
| 2 | `1` | Deadline, documents, official link |
| 3 | `restart` | Reset |
| 4 | `I'm an OBC girl in class 12 in Rajasthan, income 2 lakh` | English one-shot |
| 5 | `what documents do I need?` | Question mid-flow (needs the model) |

**If short on time, cut section 2:15–2:45 (ethics).** Keep the failures section
— it is the most differentiated 45 seconds you have.

---

## Recording notes

- **Portrait / phone-shaped window.** It's a WhatsApp product; make it look like one.
- **Don't narrate typing.** Type, pause, let the reply land, then speak.
- **The Hindi reply is your best 10 seconds** — hold on it.
- **Say one number, not five.** "₹3,400 crore unspent" lands; a table doesn't.
- **Never say "we used AI to build it."** Everyone did. Say what it got wrong
  and how you caught it — that is what the brief actually asks for.
