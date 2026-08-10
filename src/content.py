"""Plain-language content for every scholarship.

A name, an amount and a deadline do not tell a first-generation learner what a
scholarship *is*, or whether it is meant for someone like them. This module adds
the prose that answers those questions.

How it is written, and why it is safe
-------------------------------------
Every sentence here is composed from two things and nothing else:

  1. **Structured fields that were already extracted and verified** by the
     pipeline — states, categories, income ceiling, documents, deadline.
  2. **Human-written phrasing** — the glossaries and templates in this file,
     which I wrote once and which are reused across all records.

No language model runs here, at build time or at request time. That is a
deliberate choice rather than a limitation: a hallucinated description of who a
scholarship is for does exactly the same damage as a hallucinated deadline, and
it is far harder to spot because it reads fluently. A composed sentence can be
wrong only if the underlying field was wrong, which is a failure mode the
pipeline's verification stage already covers.

Where a field is missing, the prose says so out loud. It never fills the gap.

Human approval
--------------
`data/content_approvals.json` lets a human override any composed field for any
record, and records that they did:

    {"<scholarship id>": {"status": "approved",
                          "by": "…", "at": "2026-08-09",
                          "fields": {"what_it_is": "…"}}}

Composed text carries `content_status: "composed"`. Once a human has read and
kept or edited it, the entry above flips it to `"human_approved"`. The bot shows
both; the distinction is recorded so it can be audited, not hidden.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPROVALS = ROOT / "data" / "content_approvals.json"

CONTENT_FIELDS = [
    "what_it_is", "who_its_for", "eligibility_explained", "how_it_helps",
    "documents_explained", "common_reasons_applications_fail", "renewal_note",
]


# ------------------------------------------------------- human-written words

LEVEL_PHRASE = {
    "school": "in school",
    "ITI": "training at an ITI",
    "diploma": "doing a diploma or polytechnic course",
    "UG": "doing a bachelor's degree",
    "PG": "doing a master's degree",
    "PhD": "doing a PhD or research degree",
    "professional": "in a professional course such as medicine, engineering or law",
}

# Used where the category is the subject of its own sentence.
CATEGORY_PHRASE = {
    "SC": "Scheduled Caste (SC)",
    "ST": "Scheduled Tribe (ST)",
    "OBC": "Other Backward Class (OBC)",
    "EWS": "Economically Weaker Section (EWS)",
    "minority": "a minority community — Muslim, Christian, Sikh, Buddhist, Jain or Parsi",
    "PwD": "students with a disability",
    "DNT": "denotified, nomadic or semi-nomadic communities",
    "general": "students of any category",
}

# Used where the category modifies "students" / "girls". Kept separate because
# the two grammars do not mix: "students with a disability students" is what you
# get when one list has to do both jobs.
CATEGORY_ADJ = {
    # Short forms, because they are what students and forms both use. The full
    # expansion appears in eligibility_explained, where there is room for it.
    "SC": "SC",
    "ST": "ST",
    "OBC": "OBC",
    "EWS": "EWS",
    "minority": "minority-community",
    "DNT": "denotified or nomadic community",
    "general": "",
    # PwD deliberately absent — see _subject_phrase(), which puts disability
    # after the noun ("students with a disability") rather than in front of it.
}

PROVIDER_PHRASE = {
    "central_govt": "run by the central government",
    "state_govt": "run by a state government",
    "private": "run by a private trust or company",
    "psu": "run by a public sector company",
    "university": "run by a university",
    "ngo": "run by a non-profit organisation",
}

BENEFIT_PHRASE = {
    "tuition": "It pays towards your course fees.",
    "maintenance": "It pays a maintenance allowance — money towards day-to-day "
                   "study costs such as food, hostel, travel and books.",
    "mixed": "It covers both course fees and a maintenance allowance for living "
             "costs.",
    "mentorship": "It provides coaching and guidance rather than a cash payment.",
    "one_time": "It is paid once, not every year.",
}

# One entry per document type that appears in the dataset. Written for a parent
# who has never applied for anything online.
DOCUMENTS: dict[str, dict[str, str]] = {
    "aadhaar": {
        "label": "Aadhaar card",
        "what": "Your own Aadhaar card, and usually a parent's.",
        "where": "You already have it. It must be linked to your bank account, "
                 "or the money cannot reach you.",
    },
    "income_certificate": {
        "label": "Income certificate",
        "what": "A government paper stating your family's total yearly income.",
        "where": "Tehsildar or SDM office, or online through e-Mitra, a CSC "
                 "centre, or your state's e-district portal.",
    },
    "caste_certificate": {
        "label": "Caste certificate",
        "what": "Proof that you belong to the SC, ST, OBC or DNT category.",
        "where": "Tehsildar or SDM office, or your state's e-district portal. "
                 "Must be issued by a competent authority in your own state.",
    },
    "domicile_certificate": {
        "label": "Domicile / residence certificate",
        "what": "Proof that your family lives in the state.",
        "where": "Tehsildar or SDM office, or e-Mitra / e-district portal.",
    },
    "bank_passbook": {
        "label": "Bank passbook",
        "what": "The first page of your own bank passbook, showing your name, "
                "account number and IFSC code.",
        "where": "Your bank. The account must be in the student's name and "
                 "linked to Aadhaar.",
    },
    "marksheet": {
        "label": "Last marksheet",
        "what": "The marksheet of the exam you passed most recently.",
        "where": "Your school or college office, or your board's website.",
    },
    "bonafide": {
        "label": "Bonafide certificate",
        "what": "A letter from your school or college confirming you study there.",
        "where": "Your institution's office. Ask early — it often takes a few days.",
    },
    "admission_proof": {
        "label": "Proof of admission",
        "what": "The admission letter or fee receipt from your institution.",
        "where": "Your institution's office.",
    },
    "transfer_certificate": {
        "label": "Transfer certificate (TC)",
        "what": "The leaving certificate from the school or college you were in "
                "before this one.",
        "where": "Your previous institution.",
    },
    "photo": {
        "label": "Passport photo",
        "what": "A recent passport-size photograph, scanned or photographed clearly.",
        "where": "Any photo studio, or a plain photo against a light wall.",
    },
    "signature": {
        "label": "Your signature",
        "what": "Your signature on white paper, scanned or photographed.",
        "where": "Sign on plain paper and take a clear picture in good light.",
    },
    "self_declaration": {
        "label": "Self-declaration",
        "what": "A short statement, in a format the scheme gives, confirming the "
                "details you have entered are true.",
        "where": "Download the format from the application portal and sign it.",
    },
    "disability_certificate": {
        "label": "Disability certificate",
        "what": "A certificate stating the type and percentage of disability.",
        "where": "A government hospital's medical board, or the UDID portal "
                 "(swavlambancard.gov.in).",
    },
    "medical_certificate": {
        "label": "Medical certificate",
        "what": "A doctor's certificate, where the scheme requires one.",
        "where": "A government hospital or an authorised medical officer.",
    },
    "parent_death_certificate": {
        "label": "Death certificate",
        "what": "The death certificate of a parent, where the scheme is for "
                "orphans or single-parent families.",
        "where": "Your municipal corporation or gram panchayat.",
    },
    "id_proof": {
        "label": "Photo ID",
        "what": "Any government photo identity document.",
        "where": "Aadhaar, voter ID, or your school or college ID card.",
    },
}

# Operational, not scheme-specific — these are the reasons applications get
# rejected on the portals themselves, and they are the same for every scheme on
# a given portal. Kept general and labelled as such.
FAIL_REASONS = {
    "NSP": [
        "Aadhaar is not linked to the student's bank account, so the payment "
        "fails even after approval.",
        "The institution does not verify the application before the portal's "
        "own (earlier) deadline.",
        "One Time Registration (OTR) was never completed, so the form cannot "
        "be submitted at all.",
        "The income certificate has expired, or was issued in a different state.",
    ],
    "state_portal": [
        "The domicile or caste certificate was issued by another state and is "
        "not accepted.",
        "The school or college does not forward the application in time.",
        "Bank details are entered wrongly — one digit in the account number "
        "sends the money nowhere.",
    ],
    "provider_website": [
        "Applying after the deadline — private schemes rarely reopen.",
        "Documents uploaded in the wrong format or over the size limit.",
        "The income proof does not match the income entered on the form.",
    ],
}

APPLY_PHRASE = {
    "NSP": "Applications are made on the National Scholarship Portal "
           "(scholarships.gov.in).",
    "state_portal": "Applications are made on the state government's own "
                    "scholarship portal.",
    "provider_website": "Applications are made on the provider's own website.",
}


# ----------------------------------------------------------------- helpers

def rupees(n: int | None) -> str | None:
    """Money the way it is spoken in India: '₹2.5 lakh', not '₹250,000'."""
    if n is None:
        return None
    if n >= 10_000_000:
        v = n / 10_000_000
        return f"₹{v:g} crore"
    if n >= 100_000:
        v = n / 100_000
        return f"₹{v:g} lakh"
    return f"₹{n:,}"


# A figure of money, written any of the ways these PDFs write it.
_MONEY = re.compile(
    r"(?:rs\.?|₹|inr)\s*[\d,]+|[\d,]{3,}\s*(?:/-|per\s+(?:month|annum|year)|p\.a\.)"
    r"|\b\d[\d,.]*\s*(?:lakh|lakhs|crore)\b", re.I)
# Lines that are plainly a fragment of the surrounding document rather than a
# statement about money: a numbered clause heading, or a sentence we joined
# mid-way because the extractor started reading from the middle of a paragraph.
_FRAGMENT = re.compile(r"^\s*(?:\d+\.\s*[A-Z]{4,}|[a-z])")


def usable_amount_text(text: str | None) -> bool:
    """Is this safe to show a student on a line that says "Amount"?

    Found in the live demo: a record whose amount read
    "6. INSTITUITIONS ELIGIBLE AND QUANTUM OF ASSISTANCE '\\.) Q The designated
    portal shall allow updating of the i…" — a heading and a clause fragment,
    rendered under a ₹ sign as though it were a figure.

    29 of 219 records were doing some version of this. A student cannot tell
    extraction noise from a real condition, so anything without an actual figure
    of money in it is not shown as an amount at all.
    """
    if not text:
        return False
    t = " ".join(str(text).split())
    if len(t) < 8 or _FRAGMENT.match(t):
        return False
    return bool(_MONEY.search(t))


# "4.0 AMOUNT OF SCHOLARSHIP: Rs. 50,000/- per annum" — the clause number and
# shouting heading are how the PDF is laid out, not something a student needs.
_HEADING_PREFIX = re.compile(
    r"^\s*\d+(?:\.\d+)*\s*[A-Z][A-Z\s/&-]{4,}?\s*[:.\-]\s*")


def clean_amount_text(text: str | None) -> str | None:
    """The amount as a student should read it, or None if it isn't one."""
    if not usable_amount_text(text):
        return None
    t = " ".join(str(text).split())
    t = _HEADING_PREFIX.sub("", t)
    t = re.sub(r"^\d+\)\s*", "", t)          # a leftover "1)" list marker
    return t or None


def _join(items: list[str], conj: str = "and") -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


# The ladder, for ordering and for describing a span compactly.
_LEVEL_ORDER = ["school", "ITI", "diploma", "UG", "professional", "PG", "PhD"]
_LEVEL_SHORT = {
    "school": "school", "ITI": "ITI", "diploma": "diploma",
    "UG": "a bachelor's degree", "professional": "a professional course",
    "PG": "a master's degree", "PhD": "a PhD",
}


def _levels_phrase(rec: dict) -> str:
    """Where the scheme sits in a student's education.

    Schemes that name four or more levels get a span rather than a list. Reading
    "in school, doing a master's degree, doing a PhD or research degree, doing a
    bachelor's degree, doing a diploma or polytechnic course or in a
    professional course" tells a student less than "from school up to PhD
    level", not more.
    """
    levels = [l for l in _LEVEL_ORDER if l in (rec.get("education_levels") or [])]
    if not levels:
        return ""

    lo, hi = rec.get("class_min"), rec.get("class_max")
    if levels == ["school"]:
        if lo and hi:
            return f"in Class {lo} to {hi}"
        if lo:
            return f"in Class {lo} and above"
        if hi:
            return f"up to Class {hi}"
        return "in school"

    if len(levels) >= 4:
        return (f"at almost any level, from {_LEVEL_SHORT[levels[0]]} "
                f"up to {_LEVEL_SHORT[levels[-1]]}")

    parts = []
    for lvl in levels:
        if lvl == "school":
            parts.append(f"in Class {lo} to {hi}" if lo and hi else "in school")
        else:
            parts.append(LEVEL_PHRASE[lvl])
    return _join(parts, "or")


def _subject_phrase(rec: dict) -> str:
    """"OBC girls", "students with a disability" — the people, in one noun phrase."""
    cats = rec.get("categories") or []
    g = rec.get("gender")
    noun = "girls" if g == "female" else "boys" if g == "male" else "students"

    adjectives = [CATEGORY_ADJ[c] for c in cats
                  if c in CATEGORY_ADJ and CATEGORY_ADJ[c]]
    phrase = (_join(adjectives, "and") + " " + noun) if adjectives else noun
    if "PwD" in cats:
        phrase += " with a disability"
    return phrase


def _states_phrase(rec: dict) -> str:
    states = rec.get("states") or []
    if not states:
        return ""
    if any(s.lower() == "all" for s in states):
        return "anywhere in India"
    if len(states) <= 3:
        return "in " + _join(list(states), "or")
    return f"in {len(states)} states including {_join(list(states)[:2], 'and')}"


def _categories_phrase(rec: dict) -> str:
    cats = rec.get("categories") or []
    if not cats:
        return ""
    return _join([CATEGORY_PHRASE.get(c, c) for c in cats], "or")


# --------------------------------------------------------------- composition

# A body already named "Ministry of…" or "…Department" states its own level of
# government; adding "run by the central government" only lengthens the sentence.
_SELF_EVIDENT_BODY = ("ministry", "department", "government", "govt",
                      "commission", "directorate")


def what_it_is(rec: dict) -> str:
    name = " ".join((rec.get("name") or "").split())
    body = rec.get("administering_body") or rec.get("provider_name")
    who = PROVIDER_PHRASE.get(rec.get("provider_type") or "", "")
    if body and any(w in body.lower() for w in _SELF_EVIDENT_BODY):
        who = ""

    first = f"*{name}* is a scholarship"
    if body:
        first += f" from the {body}"
    if who:
        first += f", {who}"
    first += "."

    second = ""
    lv = _levels_phrase(rec)
    st = _states_phrase(rec)
    if lv and st:
        second = f"It supports students {lv}, {st}."
    elif lv:
        second = f"It supports students {lv}."
    elif st:
        second = f"It supports students {st}."

    third = APPLY_PHRASE.get(rec.get("application_mode") or "", "")
    return " ".join(p for p in (first, second, third) if p)


def who_its_for(rec: dict) -> str:
    """The target group in human terms — the sentence a student reads to decide
    "is this meant for someone like me?" before reading anything else."""
    bits = [_subject_phrase(rec)]
    lv = _levels_phrase(rec)
    if lv:
        bits.append(lv)
    st = _states_phrase(rec)
    if st:
        bits.append(st)
    sentence = "For " + ", ".join(bits) + "."

    ceiling = rec.get("income_ceiling_inr")
    if ceiling:
        sentence += (f" Your family's total yearly income must be "
                     f"{rupees(ceiling)} or less.")
    else:
        sentence += (" The source does not publish an income limit for this "
                     "scheme — check the official page before you apply.")

    marks = rec.get("min_marks_percent")
    if marks:
        sentence += f" You need at least {marks:g}% in your last exam."
    return sentence


def eligibility_explained(rec: dict) -> list[str]:
    """One plain sentence per condition, in the order the bot checks them, so a
    parent can walk down the list against their own situation."""
    out = []

    st = rec.get("states") or []
    if not st:
        out.append("Where you live: the source does not say which states this "
                   "covers — check the official page.")
    elif any(s.lower() == "all" for s in st):
        out.append("Where you live: open to students anywhere in India.")
    else:
        out.append("Where you live: you must live in " + _join(list(st), "or") + ".")

    lv = _levels_phrase(rec)
    out.append(f"What you are studying: you must be {lv}." if lv else
               "What you are studying: the source does not state a study level.")

    cats = _categories_phrase(rec)
    out.append(f"Category: this scheme is for {cats}." if cats else
               "Category: no category restriction is stated.")

    ceiling = rec.get("income_ceiling_inr")
    out.append(f"Family income: {rupees(ceiling)} a year or less." if ceiling else
               "Family income: no limit is published for this scheme — confirm "
               "on the official page.")

    g = rec.get("gender")
    if g in ("female", "male"):
        out.append(f"Gender: only {'girls' if g == 'female' else 'boys'} can apply.")

    marks = rec.get("min_marks_percent")
    if marks:
        out.append(f"Marks: at least {marks:g}% in your last qualifying exam.")

    lo, hi = rec.get("age_min"), rec.get("age_max")
    if lo or hi:
        if lo and hi:
            out.append(f"Age: between {lo} and {hi} years.")
        elif hi:
            out.append(f"Age: {hi} years or under.")
        else:
            out.append(f"Age: {lo} years or over.")

    if rec.get("orphan_or_single_parent"):
        out.append("Family: this scheme is meant for orphans or children of a "
                   "single parent.")
    return out


def how_it_helps(rec: dict) -> str:
    lo = rec.get("benefit_amount_min_inr")
    hi = rec.get("benefit_amount_max_inr")
    text = rec.get("benefit_amount_text")
    btype = rec.get("benefit_type")

    # What it pays for comes before how much. A student who cannot tell whether
    # a scheme touches their fees is not helped by a number.
    parts = []
    if btype and btype in BENEFIT_PHRASE:
        parts.append(BENEFIT_PHRASE[btype])
    else:
        parts.append("The source does not spell out exactly which costs this "
                     "covers, so check that on the official page.")

    if lo and hi and lo != hi:
        parts.append(f"You could receive between {rupees(lo)} and {rupees(hi)}.")
    elif lo or hi:
        parts.append(f"You could receive {rupees(hi or lo)}.")
    elif clean_amount_text(text):
        parts.append("The amount depends on your course: "
                     + clean_amount_text(text)[:150] + ".")
    else:
        parts.append("The amount is not published by the source.")

    if btype == "maintenance":
        parts.append("It does not usually pay your college fees directly.")
    elif btype == "tuition":
        parts.append("It does not usually cover hostel or living costs.")
    return " ".join(parts)


def documents_explained(rec: dict) -> list[dict]:
    out = []
    for d in (rec.get("documents_required") or []):
        info = DOCUMENTS.get(d)
        if info:
            out.append({"document": d, **info})
        else:
            out.append({"document": d,
                        "label": d.replace("_", " ").capitalize(),
                        "what": "Required by this scheme.",
                        "where": "Check the official page for where to obtain it."})
    return out


def common_reasons_applications_fail(rec: dict) -> list[str]:
    return list(FAIL_REASONS.get(rec.get("application_mode") or "", []))


def renewal_note(rec: dict) -> str:
    if rec.get("renewable") is True:
        return ("This scholarship can continue into your next year of study. "
                "You normally have to re-apply each year and keep up your "
                "attendance and marks — it does not renew on its own.")
    if rec.get("renewable") is False:
        return "This is a one-time scholarship. It does not repeat next year."
    return ("The source does not say whether this repeats each year. Ask your "
            "school or check the official page before you count on it.")


# -------------------------------------------------------------------- entry

def _load_approvals() -> dict:
    if not APPROVALS.exists():
        return {}
    try:
        return json.loads(APPROVALS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def compose(rec: dict, approvals: dict | None = None) -> dict:
    """The content block for one record. Returns only the new keys."""
    out = {
        "what_it_is": what_it_is(rec),
        "who_its_for": who_its_for(rec),
        "eligibility_explained": eligibility_explained(rec),
        "how_it_helps": how_it_helps(rec),
        "documents_explained": documents_explained(rec),
        "common_reasons_applications_fail": common_reasons_applications_fail(rec),
        "renewal_note": renewal_note(rec),
        "content_status": "composed",
    }

    entry = (approvals or {}).get(rec.get("id") or "")
    if entry:
        for k, v in (entry.get("fields") or {}).items():
            if k in CONTENT_FIELDS:
                out[k] = v
        if entry.get("status") == "approved":
            out["content_status"] = "human_approved"
            out["content_approved_by"] = entry.get("by")
            out["content_approved_at"] = entry.get("at")
    return out


def augment_all(records: list[dict]) -> list[dict]:
    """Add content and relevance tags to every record, in place."""
    import sys
    sys.path.insert(0, str(ROOT / "bot"))
    import relevance                                    # noqa: E402

    approvals = _load_approvals()
    dropped = 0
    for r in records:
        # Blank an amount that is really a fragment of the guideline PDF, so no
        # downstream renderer can put a ₹ sign in front of it.
        if r.get("benefit_amount_text"):
            cleaned = clean_amount_text(r["benefit_amount_text"])
            if cleaned is None:
                dropped += 1
            r["benefit_amount_text"] = cleaned
        r.update(relevance.tag(r))
        r.update(compose(r, approvals))
    if dropped:
        print(f"    dropped {dropped} unusable benefit_amount_text values")
    return records
