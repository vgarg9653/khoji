# Who this is for

*Criterion 3: a specific person with a specific problem.*

---

## Farheen, Class 10, Tonk district, Rajasthan

She scored 88%. Her family cannot pay next year's fees.

**A scholarship she qualifies for exists right now, unclaimed.** She has no way
to find it and no one to ask.

Her school has no counsellor. The National Scholarship Portal is a web form in
English, gated behind Aadhaar seeding, that assumes you already know the name of
the scheme you are looking for. The family has one phone, and WhatsApp is the
only app anyone in the house uses confidently.

She is not short of ability. She is short of **information she cannot reach in a
language she reads on a device she shares.**

---

## The gap is measurable, and it is money already allocated

| | |
|---|---|
| Minority scholarship budget unspent, 2023–26 | **₹3,400 crore** |
| Telangana minority tuition-fee funds unspent in one cycle | **₹227 cr of ₹300 cr** |
| Secondary-level dropout rate (UDISE+ 2021–22) | **12.6%**, financial constraint the leading cause |
| Certified career counsellors per school-leaver | roughly **1 : 3,000** |

*Sources: Parliamentary Standing Committee (Mar 2026); RTI reply (Mar 2025);
UDISE+ 2021–22.*

This is not a funding problem. **The money is appropriated and returned
unspent** while students like Farheen drop out for want of it. The failure is
discovery and distribution.

---

## Why the existing options don't reach her

| | What exists | Why it misses Farheen |
|---|---|---|
| **Scholarship portals** | NSP (140+ schemes), Buddy4Study | Web-first, English-heavy, Aadhaar-gated — built for someone who already knows what to search for |
| **Career guidance** | iDreamCareer, Mindler | ₹1,000–5,000 a session. Her family cannot pay next year's fees. |
| **Mentor programmes** | Desh Ke Mentor | App-based — needs a download and a device that is hers |

All three assume **the student arrives.** Khoji.AI goes to where she already is:
WhatsApp, in Hindi, on a shared phone, with no download.

---

## What she actually does

She sends one message:

> `मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख`

and gets back, in Hindi, within seconds:

```
✅ *5* मिलीं — *2* के लिए आप पूरी तरह योग्य हैं
_सबसे उपयुक्त पहले — ✅ का मतलब आप हर बताई गई शर्त पूरी करते हैं।_

*1.* ✅ PM-USP – Central Sector Scheme of Scholarship for College Students
    🗓 30 Sep 2026
```

Then the deadline, the exact documents to collect, and the official government
link to apply on.

No form. No app. No English. **One message.**

---

## The thing we refuse to do

Farheen's real risk is not missing a scholarship. It is **being told she
qualifies for one she doesn't** — collecting documents, spending money on
photocopies and a trip to a cyber café, and being rejected.

So the bot never guesses. 152 of 298 records have no readable income ceiling
because the government PDFs don't legibly state one. For those it says
**"income limit not stated by the source — check the official page"** rather than
assuming.

That is why eligibility is three-valued in the code:

| Verdict | Meaning |
|---|---|
| `ELIGIBLE` | she meets a criterion the source stated |
| `NOT_ELIGIBLE` | she fails a stated criterion — the scheme is hidden |
| `UNKNOWN` | **the source never said** — shown, and flagged to check |

`UNKNOWN` never silently passes and never silently fails. For a student who
bears the cost of a wrong answer, that distinction is the product.

---

## Where it starts

**Rajasthan. Class 10, 12 and undergraduate. Hindi and English.**

One state, because a scholarship bot that is shallow everywhere helps no one.
22 Rajasthan-specific schemes are in the catalogue with their Hindi names —
including *मुख्यमंत्री उच्च शिक्षा छात्रवृत्ति योजना* — alongside 197 national
schemes she can also apply for.

## What success looks like

Not downloads, not conversations, not "users engaged".

**The percentage of eligible-but-not-applying students who reach a submitted
application** — measured separately for bot-only and mentor-assisted, at a known
cost per application.

Farheen filing one form she would otherwise never have known existed.
