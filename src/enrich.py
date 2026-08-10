"""Extract structured eligibility from official guideline prose.

Scheme guidelines follow a loose but recognisable house style: numbered sections
titled ELIGIBILITY, VALUE OF SCHOLARSHIP, DURATION, DOCUMENTS. We locate those
sections and read values only from within the section that should contain them,
which is what keeps an award amount from being mistaken for an income ceiling.

Every extractor returns None when it is not confident. A field left None is a
field the pipeline will honestly report as missing.
"""

from __future__ import annotations

import re

import normalize as N
from schema import Scholarship

# --------------------------------------------------------------- section split

SECTIONS = {
    "objective": re.compile(r"\b(?:objective|purpose|about the scheme)\b", re.I),
    "eligibility": re.compile(r"\b(?:eligibilit|who can apply|eligible students?)\b", re.I),
    "income": re.compile(r"\b(?:income (?:criteri|ceiling|limit)|family income)\b", re.I),
    "value": re.compile(r"\b(?:value of (?:the )?scholarship|rate of scholarship|"
                        r"quantum|amount of scholarship|financial assistance)\b", re.I),
    "duration": re.compile(r"\b(?:duration|tenure|period of (?:the )?(?:award|scholarship))\b", re.I),
    "awards": re.compile(r"\b(?:number of (?:scholarships?|awards?|slots?)|no\. of scholarships?)\b", re.I),
    "documents": re.compile(r"\b(?:documents?\s+(?:required|to be|needed)|"
                            r"enclosures?|list of documents)\b", re.I),
    "renewal": re.compile(r"\b(?:renewal|continuation|renewed)\b", re.I),
    "selection": re.compile(r"\b(?:selection (?:process|procedure|criteri)|mode of selection)\b", re.I),
}

_HEADING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s*)?([A-Z][A-Z \-/&(),.']{6,80})\s*:?\s*$")


def split_sections(text: str) -> dict[str, str]:
    """Map our canonical section keys onto spans of the document.

    Returns {key: text}. Keys absent from the document are simply absent here.
    """
    lines = text.splitlines()
    marks: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        probe = ln.strip()
        if not probe or len(probe) > 120:
            continue
        looks_headingish = bool(_HEADING.match(probe)) or bool(
            re.match(r"^\s*\d+(?:\.\d+)*\s+\S", probe))
        for key, rx in SECTIONS.items():
            if rx.search(probe) and (looks_headingish or len(probe) < 90):
                marks.append((i, key))
                break

    out: dict[str, str] = {}
    for idx, (start, key) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else min(start + 60, len(lines))
        chunk = "\n".join(lines[start:end]).strip()
        if chunk and len(chunk) > len(out.get(key, "")):
            out[key] = chunk
    return out


# ------------------------------------------------------------------ extractors

_CLASS_WORDS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12,
}
_CLASS_RX = re.compile(
    r"class(?:es)?\s*([IVXivx]+|\d{1,2})\s*(?:to|-|–|and|&)\s*([IVXivx]+|\d{1,2})", re.I)
_CLASS_SINGLE = re.compile(r"class(?:es)?\s*([IVXivx]+|\d{1,2})\b", re.I)


def _class_num(tok: str) -> int | None:
    tok = tok.strip().lower()
    if tok.isdigit():
        v = int(tok)
        return v if 1 <= v <= 12 else None
    return _CLASS_WORDS.get(tok)


def parse_class_range(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    m = _CLASS_RX.search(text)
    if m:
        a, b = _class_num(m.group(1)), _class_num(m.group(2))
        if a and b and a <= b:
            return a, b
    hits = [c for c in (_class_num(x) for x in _CLASS_SINGLE.findall(text)) if c]
    if hits:
        return min(hits), max(hits)
    return None, None


# Split on sentence ends and newlines, but not after "Rs."/"No." and not on the
# colon in "Number of scholarships: 5,000" — that colon joins a label to its value.
_SENT_SPLIT = re.compile(r"(?:\n+|(?<!\bRs)(?<!\bNo)(?<![A-Z])[.;]\s+)")

# A count is only trustworthy when the number and the word "scholarships"/"awards"
# are adjacent. Looser phrasings ("... to 500 students ...") too often describe
# something other than the slot count, so we decline them.
_AWARDS_ADJACENT = re.compile(
    r"\b(\d[\d,]{2,8})\s*(?:\([^)]{0,40}\)\s*)?(?:fresh\s+|new\s+)?"
    r"(?:scholarships?|awards?|slots?|fellowships?)\b", re.I)
_AWARDS_LABELLED = re.compile(
    r"(?:number|no\.?)\s+of\s+(?:scholarships?|awards?|slots?|fellowships?)"
    r"[^.\n]{0,60}?\b(\d[\d,]{2,8})\b", re.I)


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s.strip()]


def _unwrap(text: str) -> str:
    """Join lines that a PDF wrapped mid-sentence.

    PDF text extraction preserves the visual line breaks, so a figure and its
    unit routinely land on different lines:

        "... family income from all sources up to Rs. 8.00
         lakh per annum ..."

    Treating a newline as a sentence end then splits "Rs. 8.00" from "lakh", and
    a bare 8.00 is not a plausible rupee amount — so the ceiling was silently
    lost. Joining wrapped lines first fixes a whole class of these. Blank lines
    are kept as real paragraph breaks.
    """
    text = re.sub(r"\n{2,}", "\n\n", text)
    return re.sub(r"(?<!\n)\n(?!\n)", " ", text)


def parse_awards(text: str | None) -> int | None:
    """Number of slots, read only from a sentence that explicitly counts awards.

    Guideline PDFs are full of stray figures (page numbers, file numbers, years,
    rupee amounts). Requiring the count and the noun to sit together, and
    rejecting anything that reads as money, is what keeps this honest.
    """
    if not text:
        return None
    for sent in _sentences(text):
        if re.search(r"\brs\.?\b|₹|per annum|per month|amount", sent, re.I) \
                and not re.search(r"number\s+of", sent, re.I):
            continue                      # this sentence is about money, not counts
        for rx in (_AWARDS_LABELLED, _AWARDS_ADJACENT):
            m = rx.search(sent)
            if not m:
                continue
            try:
                v = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if 1 <= v <= 5_000_000 and not (1900 <= v <= 2100):
                return v
    return None


_DURATION_RX = re.compile(
    r"(\d(?:\.\d)?)\s*(?:\(.*?\)\s*)?(?:academic\s+)?years?\b", re.I)


def parse_duration(text: str | None) -> float | None:
    if not text:
        return None
    m = _DURATION_RX.search(text)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if 0 < v <= 10 else None


_AGE_RX = re.compile(
    r"age\D{0,30}?(?:between\s*)?(\d{1,2})\s*(?:to|-|–|and)\s*(\d{1,2})\s*years", re.I)
_AGE_MAX = re.compile(
    r"(?:not (?:more than|exceed(?:ing)?)|below|under|upto|up to|maximum)\D{0,20}?"
    r"(\d{1,2})\s*years", re.I)
_AGE_MIN = re.compile(
    r"(?:not less than|minimum|at least|above)\D{0,20}?(\d{1,2})\s*years", re.I)


def parse_age(text: str | None) -> tuple[int | None, int | None]:
    """Age bounds, read only from sentences that are actually about age.

    Without that scoping, "maximum 4 years duration" reads as an age ceiling of
    four — a wrong value is far worse here than a missing one.
    """
    if not text:
        return None, None
    lo = hi = None
    for sent in _sentences(text):
        if not re.search(r"\bage[ds]?\b|\byears? of age\b|\bborn (?:on|after|before)\b",
                         sent, re.I):
            continue
        if re.search(r"\bduration\b|\bcourse\b|\bstudy\b|\btenure\b", sent, re.I) \
                and not re.search(r"\bage[ds]?\b", sent, re.I):
            continue
        m = _AGE_RX.search(sent)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 3 <= a < b <= 60:
                return a, b
        if lo is None and (m := _AGE_MIN.search(sent)):
            v = int(m.group(1))
            lo = v if 3 <= v <= 60 else None
        if hi is None and (m := _AGE_MAX.search(sent)):
            v = int(m.group(1))
            hi = v if 3 <= v <= 60 else None
    return lo, hi


_RENEW_YES = re.compile(
    r"\b(?:renewal|renewed|renewable|continuation of the scholarship|"
    r"may be continued|shall be continued)\b", re.I)
_RENEW_NO = re.compile(r"\b(?:one[- ]time|non[- ]renewable|not renewable)\b", re.I)


def parse_renewable(text: str | None) -> bool | None:
    if not text:
        return None
    if _RENEW_NO.search(text):
        return False
    if _RENEW_YES.search(text):
        return True
    return None


_EXAM_RX = re.compile(
    r"\b(JEE(?:\s*Main|\s*Advanced)?|NEET|CUET|GATE|NET|CAT|CLAT|NDA|"
    r"common entrance (?:test|exam)|entrance (?:test|exam(?:ination)?))\b", re.I)


def parse_entrance_exam(text: str | None) -> tuple[bool | None, str | None]:
    if not text:
        return None, None
    m = _EXAM_RX.search(text)
    if not m:
        return None, None
    if re.search(r"\bno entrance\b|without (?:any )?entrance", text, re.I):
        return False, None
    return True, m.group(1)


_ORPHAN_RX = re.compile(
    r"\borphan|single parent|both parents (?:are )?(?:dead|deceased|expired)|"
    r"father(?:'s)? (?:is )?(?:dead|deceased|expired)|widow", re.I)

_OCCUPATION_RX = [
    (re.compile(r"\bbeedi\b|\bbidi\b", re.I), "beedi workers"),
    (re.compile(r"\bcine\b\s*workers?", re.I), "cine workers"),
    (re.compile(r"iron ore|manganese|chrome ore|mine workers?|\bmining\b", re.I), "mine workers"),
    (re.compile(r"armed forces|ex-?servicemen|defence personnel|paramilitary|"
                r"central armed police|assam rifles", re.I), "armed forces / ex-servicemen"),
    (re.compile(r"police personnel|martyred", re.I), "police personnel"),
    (re.compile(r"\bfarmers?\b|agricultur(?:e|al) (?:labour|worker)", re.I), "farmers"),
    (re.compile(r"construction workers?|building (?:and )?other construction", re.I),
     "construction workers"),
    (re.compile(r"safai karamchari|manual scaveng|sanitation workers?", re.I),
     "safai karamcharis"),
    (re.compile(r"weavers?|handloom", re.I), "weavers"),
    (re.compile(r"\brailway\b employees|railway servants", re.I), "railway employees"),
]


def parse_occupation(text: str | None) -> str | None:
    if not text:
        return None
    for rx, label in _OCCUPATION_RX:
        if rx.search(text):
            return label
    return None


_TUITION = re.compile(r"tuition fee|course fee|academic fee", re.I)
_MAINT = re.compile(r"maintenance allowance|living allowance|hostel|boarding|"
                    r"monthly stipend", re.I)
_ONETIME = re.compile(r"one[- ]time (?:grant|assistance|payment)", re.I)
_MENTOR = re.compile(r"mentor(?:ship|ing)|coaching|career guidance", re.I)


def parse_benefit_type(text: str | None) -> str | None:
    if not text:
        return None
    flags = {
        "tuition": bool(_TUITION.search(text)),
        "maintenance": bool(_MAINT.search(text)),
        "one-time": bool(_ONETIME.search(text)),
        "mentorship": bool(_MENTOR.search(text)),
    }
    on = [k for k, v in flags.items() if v]
    if not on:
        return None
    if len(on) > 1:
        return "mixed"
    return on[0]


# ------------------------------------------- scheme-aware document slicing

def _name_probe(name: str) -> re.Pattern | None:
    """A loose matcher for a scheme title inside a document.

    Titles in the body rarely match the listing verbatim — punctuation, case and
    filler words drift — so we key on the distinctive words and allow anything
    between them.
    """
    # Keep short words: "Pre" vs "Post" is often the ONLY thing separating two
    # schemes in the same document, and dropping them collapses both to the
    # same probe.
    stop = {"the", "for", "of", "and", "to", "in", "a", "an", "on", "by", "with"}
    tokens = [w for w in re.split(r"[^A-Za-z0-9]+", name or "")
              if len(w) >= 2 and w.lower() not in stop][:5]
    if len(tokens) < 2:
        return None
    return re.compile(r"[^\n]{0,80}?".join(re.escape(w) for w in tokens), re.I)


def slice_by_scheme(text: str, names: list[str]) -> dict[str, str]:
    """Split a shared guidelines document into per-scheme spans.

    Returns {name: span} only for schemes we located unambiguously. A scheme
    absent from the result could not be isolated, and the caller must keep
    treating the document as ambiguous for it rather than guessing.
    """
    if not text or len(names) < 2:
        return {}
    hits: list[tuple[int, str]] = []
    for nm in names:
        rx = _name_probe(nm)
        if rx is None:
            continue
        found = [m.start() for m in rx.finditer(text)]
        if len(found) != 1:
            # Absent, or mentioned repeatedly (cross-references) — not a clean
            # section boundary either way.
            continue
        hits.append((found[0], nm))

    if len(hits) < 2:
        return {}
    hits.sort()
    bounds = [h[0] for h in hits] + [len(text)]
    out: dict[str, str] = {}
    for i, (start, nm) in enumerate(hits):
        span = text[start:bounds[i + 1]]
        # Too short to hold eligibility detail; treat as a mention, not a section.
        if len(span) >= 400:
            out[nm] = span
    return out


# ------------------------------------------------------- income ceiling

# Scheme guidelines state the income cap in a sentence, not under a reliable
# heading, so scoping this to a detected section loses most of them. Instead we
# scan the whole document for sentences that both mention income and impose a
# ceiling, which is specific enough to stay safe.

_INCOME_SUBJECT = re.compile(
    r"\b(?:family|parent(?:s|al)?|guardian|household|parental)\b[^.\n]{0,40}\bincome\b"
    r"|\bincome\b[^.\n]{0,40}\b(?:from all sources|of the (?:family|parents?|guardian))\b"
    r"|\bannual\s+income\b|\bincome\s+of\s+(?:the\s+)?(?:student|candidate|applicant)\b",
    re.I)

_CEILING_VERB = re.compile(
    r"\b(?:should\s+not\s+exceed|shall\s+not\s+exceed|does\s+not\s+exceed|"
    r"not\s+exceed(?:ing)?|not\s+(?:be\s+)?more\s+than|less\s+than|below|"
    r"up\s?to|upto|maximum\s+of|within|ceiling\s+of|limit\s+of|"
    r"not\s+exceeding)\b", re.I)

# Indian PDFs frequently render ₹ as a stray glyph ({, `, Rs, INR).
_RUPEE_GLYPH = re.compile(r"[₹`{}]\s*(?=\d)")

_WORD_LAKH = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+lakhs?\b", re.I)
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# Plausible band for an Indian scholarship family-income ceiling.
INCOME_MIN, INCOME_MAX = 10_000, 20_000_000


def _amounts_in(sent: str) -> list[int]:
    """Rupee figures in one sentence, handling lakh/crore and Indian grouping."""
    s = _RUPEE_GLYPH.sub("Rs ", sent)
    out: list[int] = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(?:lakh|lac)s?\b", s, re.I):
        try:
            out.append(int(round(float(m.group(1).replace(",", "")) * 100_000)))
        except ValueError:
            pass
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*crores?\b", s, re.I):
        try:
            out.append(int(round(float(m.group(1).replace(",", "")) * 10_000_000)))
        except ValueError:
            pass
    for m in _WORD_LAKH.finditer(s):
        out.append(_WORD_NUM[m.group(1).lower()] * 100_000)
    # Bare grouped figures like "Rs. 2,50,000/-" — require a currency marker so
    # a stray year or serial number cannot be mistaken for money.
    for m in re.finditer(r"(?:rs\.?|inr)\s*(\d[\d,]{4,})", s, re.I):
        try:
            out.append(int(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return [v for v in out if INCOME_MIN <= v <= INCOME_MAX]


# Income ceilings in Indian scholarship schemes cluster tightly on these round
# figures. The list is a sanity check for OCR output only: a misread digit is
# very unlikely to land exactly on one of them, whereas a correct read almost
# always does.
STANDARD_INCOME_CEILINGS = {
    100_000, 120_000, 150_000, 200_000, 250_000, 300_000, 350_000, 400_000,
    450_000, 500_000, 600_000, 700_000, 800_000, 1_000_000, 1_200_000,
    1_500_000, 2_000_000, 2_500_000,
}


def distinct_income_ceilings(text: str | None) -> list[int]:
    """Every distinct ceiling the document states.

    Used to decide whether a shared guidelines PDF can safely hand its ceiling
    to all the schemes it covers: one figure means one policy for the document;
    several means they differ and we cannot tell which belongs to which.
    """
    if not text:
        return []
    found = set()
    for sent in _sentences(_unwrap(text)):
        if len(sent) > 600:
            continue
        if not _INCOME_SUBJECT.search(sent) or not _CEILING_VERB.search(sent):
            continue
        found.update(_amounts_in(sent))
    return sorted(found)


def extract_income_ceiling(text: str | None) -> tuple[int | None, str | None]:
    """Return (ceiling_inr, evidence_sentence).

    Requires the same sentence to name an income subject AND impose a ceiling.
    "Scholarship of Rs 50,000 per annum" has neither and is correctly ignored.
    When a document lists several caps (different categories often differ), the
    lowest is taken: it is the one a student must clear to be eligible at all,
    so erring low never tells someone they qualify when they do not.
    """
    if not text:
        return None, None
    candidates: list[tuple[int, str]] = []
    for sent in _sentences(_unwrap(text)):
        if len(sent) > 600:
            continue
        if not _INCOME_SUBJECT.search(sent) or not _CEILING_VERB.search(sent):
            continue
        # A sentence about what the scholarship pays is not an income ceiling.
        if re.search(r"\b(?:scholarship|stipend|award)\s+(?:of|amount)\b", sent, re.I) \
                and not _INCOME_SUBJECT.search(sent):
            continue
        for v in _amounts_in(sent):
            candidates.append((v, re.sub(r"\s+", " ", sent).strip()[:240]))
    if not candidates:
        return None, None
    val, evidence = min(candidates, key=lambda c: c[0])
    return val, evidence


# ---------------------------------------------------------------- main entry

# Fields that describe one specific scheme rather than a family of them. When a
# guidelines document covers several schemes at once, these cannot be attributed
# to any single one of them without inventing a fact.
SCHEME_SPECIFIC_FIELDS = {
    "class_min", "class_max", "benefit_amount_min_inr", "benefit_amount_max_inr",
    "benefit_amount_text", "number_of_awards", "duration_years",
    "min_marks_percent", "age_min", "age_max", "income_ceiling_inr",
}


def enrich_from_text(s: Scholarship, text: str, *, source_url: str | None = None,
                     overwrite: bool = False, shared_with: int = 1,
                     low_confidence_text: bool = False) -> Scholarship:
    """Fill empty fields of `s` from guideline prose.

    `shared_with` is the number of distinct schemes this document covers. When it
    is greater than one, the scheme-specific numbers in the document belong to
    some scheme but we cannot tell which, so we decline to assign them and flag
    the record instead. Guessing here would put a wrong class range or award
    amount in front of a student.
    """
    if not text or len(text) < 100:
        return s

    ambiguous = shared_with > 1

    sec = split_sections(text)
    elig = sec.get("eligibility", "")
    value = sec.get("value", "")
    income_sec = sec.get("income", "") or elig
    docs_sec = sec.get("documents", "")
    dur_sec = sec.get("duration", "")
    awards_sec = sec.get("awards", "")
    renew_sec = sec.get("renewal", "")
    # Fall back to the whole document only for fields that are unambiguous
    # wherever they appear.
    whole = text

    def setf(field: str, val) -> None:
        if val is None or (isinstance(val, (list, tuple)) and not val):
            return
        if ambiguous and field in SCHEME_SPECIFIC_FIELDS:
            return
        if overwrite or getattr(s, field, None) in (None, [], ""):
            setattr(s, field, val)

    # --- money ---
    # Income ceiling is read from the whole document, not a detected section:
    # guidelines state it in a sentence, rarely under a dependable heading.
    ceiling, ceiling_evidence = extract_income_ceiling(whole)
    if ceiling is None:
        ceiling = N.parse_income_ceiling(income_sec)
        ceiling_evidence = None

    # A shared guidelines document normally states ONE income policy covering
    # every scheme in it. Blocking the ceiling along with the genuinely
    # scheme-specific fields cost ~30 records a value that was plainly stated,
    # e.g. "family income ... should not exceed Rs.2.50 lakh per annum". So we
    # allow it back when the document is unambiguous: exactly one distinct
    # figure. Two or more and we still decline, because they differ per scheme.
    if ambiguous and ceiling is not None:
        if len(distinct_income_ceilings(whole)) == 1:
            if overwrite or s.income_ceiling_inr in (None, ""):
                s.income_ceiling_inr = ceiling
                if ceiling_evidence:
                    s.income_evidence = ceiling_evidence

    if ceiling is not None and low_confidence_text:
        # OCR misreads digits. A wrong ceiling is worse than no ceiling: it
        # silently tells a student they are ineligible, or that they qualify
        # when they do not. A real scan produced "Rs 24,000" here, which would
        # have excluded almost everyone. So from OCR text we accept only the
        # standard figures these schemes actually use.
        if ceiling not in STANDARD_INCOME_CEILINGS:
            ceiling, ceiling_evidence = None, None
    setf("income_ceiling_inr", ceiling)
    # The evidence sentence is what lets anyone confirm the number in seconds.
    # It was previously gated on `other_criteria` being empty, which is an
    # unrelated field — so the audit trail vanished on many records.
    if ceiling is not None and ceiling_evidence:
        s.income_evidence = ceiling_evidence
    lo, hi = N.parse_amounts(value)
    setf("benefit_amount_min_inr", lo)
    setf("benefit_amount_max_inr", hi)
    if value:
        snippet = re.sub(r"\s+", " ", value)[:300]
        setf("benefit_amount_text", snippet)
    setf("benefit_type", parse_benefit_type(value or whole))

    # --- eligibility ---
    cmin, cmax = parse_class_range(elig or whole)
    setf("class_min", cmin)
    setf("class_max", cmax)
    amin, amax = parse_age(elig or whole)
    setf("age_min", amin)
    setf("age_max", amax)
    setf("min_marks_percent", N.parse_percent(elig))
    setf("categories", N.detect_categories(elig))
    setf("education_levels", N.detect_levels(elig or whole))
    setf("gender", N.detect_gender(elig))
    setf("parent_occupation_specific", parse_occupation(elig or whole))
    if _ORPHAN_RX.search(elig or whole):
        setf("orphan_or_single_parent", True)
    exam, exam_name = parse_entrance_exam(elig)
    setf("entrance_exam_required", exam)
    setf("entrance_exam_name", exam_name)

    # --- benefit shape ---
    setf("duration_years", parse_duration(dur_sec))
    setf("renewable", parse_renewable(renew_sec or dur_sec))
    if renew_sec:
        setf("renewal_criteria", re.sub(r"\s+", " ", renew_sec)[:300])
    setf("number_of_awards", parse_awards(awards_sec or value))

    # --- documents ---
    docs, other = N.detect_documents(docs_sec or whole)
    setf("documents_required", docs)
    if other:
        setf("documents_other", other)

    # --- selection ---
    if s.selection_process is None:
        sel = sec.get("selection", "")
        if sel:
            if re.search(r"interview", sel, re.I):
                setf("selection_process", "interview")
            elif re.search(r"merit[- ]cum[- ]means", sel, re.I):
                setf("selection_process", "merit_cum_means")
            elif re.search(r"\bmerit\b", sel, re.I):
                setf("selection_process", "merit")

    if source_url and source_url not in s.source_urls:
        s.source_urls.append(source_url)

    if ambiguous:
        s.needs_review = True
        reason = (f"guidelines PDF covers {shared_with} schemes; scheme-specific "
                  f"values (class range, amounts, award count) left null "
                  f"pending manual attribution")
        s.needs_review_reason = (
            f"{s.needs_review_reason}; {reason}" if s.needs_review_reason else reason)

    s.field_completeness_percent = s.completeness()
    return s
