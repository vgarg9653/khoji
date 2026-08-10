"""Normalizers shared by every parser.

These convert what a page says into the schema's controlled values. They are
deliberately conservative: a normalizer that cannot confidently interpret its
input returns None so the field stays empty, rather than emitting a plausible
guess. Callers must treat None as "the source did not say".
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime

from schema import CATEGORIES, DOCUMENTS, INDIAN_STATES

# --------------------------------------------------------------------- naming

_NOISE = re.compile(
    r"\b(scheme|scholarship|scholarships|yojana|yojna|programme|program|for|of|the|"
    r"to|and|under|govt|government)\b", re.I)
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")

# Selection-basis suffix NSP appends to every scheme title.
_BASIS_SUFFIX = re.compile(
    r"\s*\((merit|welfare|means)[- ]?(?:cum[- ]?means\s*)?based\s+scheme\)\s*$", re.I)


def clean_name(raw: str | None) -> str | None:
    if not raw:
        return None
    s = unicodedata.normalize("NFKC", raw)
    s = _WS.sub(" ", s).strip(" -–—:|")
    return s or None


def strip_basis_suffix(name: str) -> tuple[str, str | None]:
    """NSP titles end with '(Merit Based Scheme)' etc. Split that off — it is
    selection-process information, not part of the scheme's name."""
    m = _BASIS_SUFFIX.search(name)
    if not m:
        return name, None
    basis = m.group(1).lower()
    mapped = {"merit": "merit", "welfare": "means", "means": "means"}.get(basis)
    if "cum" in m.group(0).lower():
        mapped = "merit_cum_means"
    return _BASIS_SUFFIX.sub("", name).strip(), mapped


def normalize_name(raw: str | None) -> str | None:
    """Aggressive key for dedup: lowercase, punctuation and filler words gone."""
    if not raw:
        return None
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    s = _PUNCT.sub(" ", s.lower())
    s = _NOISE.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s or None


def make_id(name_normalized: str | None, provider: str | None) -> str:
    key = f"{name_normalized or ''}|{(provider or '').lower().strip()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------- dates

_DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"), "ymd"),
]
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_TEXT_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
_TEXT_DATE_2 = re.compile(
    r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")

TENTATIVE_MARKERS = re.compile(
    r"tentative|to be announced|to be notified|expected|likely|coming soon|"
    r"will be (?:announced|notified|updated)|yet to be|TBA|TBD|not yet", re.I)


def parse_date(text: str | None) -> str | None:
    """Return an ISO date string, or None if the text holds no unambiguous date.

    Indian government pages are overwhelmingly DD-MM-YYYY, so an ambiguous
    numeric triple is read day-first.
    """
    if not text:
        return None
    t = str(text).strip()

    for rx, order in _DATE_PATTERNS:
        m = rx.search(t)
        if m:
            a, b, c = (int(x) for x in m.groups())
            y, mo, d = (c, b, a) if order == "dmy" else (a, b, c)
            if order == "dmy" and mo > 12 and d <= 12:
                mo, d = d, mo          # clearly MM-DD-YYYY after all
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                return None

    for rx, (di, mi, yi) in ((_TEXT_DATE, (0, 1, 2)), (_TEXT_DATE_2, (1, 0, 2))):
        m = rx.search(t)
        if m:
            g = m.groups()
            mon = _MONTHS.get(g[mi].lower()[:3])
            if not mon:
                continue
            try:
                return date(int(g[yi]), mon, int(g[di])).isoformat()
            except ValueError:
                return None
    return None


def is_tentative(text: str | None) -> bool:
    return bool(text and TENTATIVE_MARKERS.search(text))


# -------------------------------------------------------------------- amounts

_LAKH = re.compile(r"(\d[\d,]*\.?\d*)\s*lakh", re.I)
_CRORE = re.compile(r"(\d[\d,]*\.?\d*)\s*crore", re.I)
_PLAIN = re.compile(r"(?:rs\.?|inr|₹)\s*(\d[\d,]*\.?\d*)", re.I)
_BARE = re.compile(r"\b(\d[\d,]{3,})\b")


# Below this, a figure in a scholarship document is a serial number, a clause
# reference or a table row label — not a rupee value anyone is awarded.
MIN_PLAUSIBLE_INR = 100


def _to_int(s: str) -> int | None:
    try:
        return int(round(float(s.replace(",", ""))))
    except ValueError:
        return None


def parse_amounts(text: str | None) -> tuple[int | None, int | None]:
    """Extract (min, max) INR from free text. Returns (None, None) when the text
    carries no monetary figure — never a zero or a placeholder."""
    if not text:
        return None, None
    vals: list[int] = []
    for m in _CRORE.finditer(text):
        v = _to_int(m.group(1))
        if v is not None:
            vals.append(v * 10_000_000)
    for m in _LAKH.finditer(text):
        v = _to_int(m.group(1))
        if v is not None:
            vals.append(v * 100_000)
    for m in _PLAIN.finditer(text):
        v = _to_int(m.group(1))
        if v is not None:
            vals.append(v)
    if not vals:
        for m in _BARE.finditer(text):
            v = _to_int(m.group(1))
            # A bare 4+ digit number is only money if it is plausibly money and
            # not a year.
            if v is not None and 500 <= v <= 10_000_000 and not (1900 <= v <= 2100):
                vals.append(v)
    vals = [v for v in vals if v >= MIN_PLAUSIBLE_INR]
    if not vals:
        return None, None
    return min(vals), max(vals)


def parse_income_ceiling(text: str | None) -> int | None:
    """Family income ceiling, only when the text actually frames it as a limit."""
    if not text:
        return None
    if not re.search(r"income|annual|family|parental|guardian", text, re.I):
        return None
    lo, hi = parse_amounts(text)
    return hi if hi else None


def parse_percent(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
    if m:
        v = float(m.group(1))
        return v if 0 < v <= 100 else None
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:per\s*cent|percent)", text, re.I)
    if m:
        v = float(m.group(1))
        return v if 0 < v <= 100 else None
    return None


# ------------------------------------------------------------- classification

_CATEGORY_PATTERNS = [
    (re.compile(r"\bsc\b|scheduled caste", re.I), "SC"),
    (re.compile(r"\bst\b|scheduled tribe|\btribal\b|adivasi|janjati", re.I), "ST"),
    (re.compile(r"\bobc\b|other backward", re.I), "OBC"),
    (re.compile(r"\bews\b|economically weaker", re.I), "EWS"),
    (re.compile(r"minorit|muslim|christian|sikh|buddhist|parsi|jain", re.I), "minority"),
    (re.compile(r"divyang|disabilit|specially abled|handicap|\bpwd\b", re.I), "PwD"),
    (re.compile(r"denotified|nomadic|semi-nomadic|\bdnt\b", re.I), "DNT"),
]

_LEVEL_PATTERNS = [
    (re.compile(r"pre[- ]?matric|class (?:i|1)x|class 9|primary|elementary", re.I), "school"),
    (re.compile(r"post[- ]?matric|class (?:xi|11)|higher secondary", re.I), "school"),
    (re.compile(r"\biti\b|industrial training", re.I), "ITI"),
    (re.compile(r"diploma|polytechnic", re.I), "diploma"),
    (re.compile(r"under[- ]?graduat|\bug\b|bachelor|\bb\.?tech|\bb\.?a\b|\bb\.?sc", re.I), "UG"),
    (re.compile(r"post[- ]?graduat|\bpg\b|master|\bm\.?tech|\bm\.?a\b|\bm\.?sc", re.I), "PG"),
    (re.compile(r"\bph\.?d\b|doctoral|research fellow", re.I), "PhD"),
    (re.compile(r"medical|engineering|mbbs|law|management|professional|technical", re.I),
     "professional"),
]

_DOC_PATTERNS = [
    (re.compile(r"aadhaar|aadhar|uid", re.I), "aadhaar"),
    (re.compile(r"income cert|income proof", re.I), "income_certificate"),
    (re.compile(r"caste cert|community cert|category cert", re.I), "caste_certificate"),
    (re.compile(r"bonafide", re.I), "bonafide"),
    (re.compile(r"mark ?sheet|marks card|grade card|result", re.I), "marksheet"),
    (re.compile(r"bank (?:pass ?book|account|details)", re.I), "bank_passbook"),
    (re.compile(r"photograph|passport size|\bphoto\b", re.I), "photo"),
    (re.compile(r"domicile|residence cert|nativity", re.I), "domicile_certificate"),
    (re.compile(r"disabilit(?:y)? cert|udid", re.I), "disability_certificate"),
    (re.compile(r"admission (?:proof|letter)|allotment letter", re.I), "admission_proof"),
    (re.compile(r"fee ?receipt|fee ?slip", re.I), "fee_receipt"),
    (re.compile(r"signature", re.I), "signature"),
    (re.compile(r"ration card", re.I), "ration_card"),
    (re.compile(r"birth cert", re.I), "birth_certificate"),
    (re.compile(r"transfer cert|\btc\b", re.I), "transfer_certificate"),
    (re.compile(r"gap cert", re.I), "gap_certificate"),
    (re.compile(r"death cert", re.I), "parent_death_certificate"),
    (re.compile(r"minority cert", re.I), "minority_certificate"),
    (re.compile(r"self[- ]declaration|undertaking|affidavit", re.I), "self_declaration"),
    (re.compile(r"id proof|identity proof|voter id|pan card", re.I), "id_proof"),
    (re.compile(r"study cert", re.I), "study_certificate"),
    (re.compile(r"medical cert|fitness cert", re.I), "medical_certificate"),
]


def detect_categories(text: str | None) -> list[str]:
    if not text:
        return []
    found = {tag for rx, tag in _CATEGORY_PATTERNS if rx.search(text)}
    return sorted(found)


def detect_levels(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted({tag for rx, tag in _LEVEL_PATTERNS if rx.search(text)})


def detect_documents(text: str | None) -> tuple[list[str], list[str]]:
    """Return (controlled_docs, unmatched_phrases). Unmatched text is preserved
    so a normalizer gap never silently discards a requirement."""
    if not text:
        return [], []
    found = sorted({tag for rx, tag in _DOC_PATTERNS if rx.search(text)})
    return found, []


# Phrases that contain a state name but do not refer to the state. "Assam Rifles"
# is a paramilitary regiment recruiting nationally; reading it as the state of
# Assam would hide a national scheme from every other state's students.
_STATE_FALSE_POSITIVES = re.compile(
    r"Assam\s+Rifles|Bihar\s+Regiment|Punjab\s+Regiment|Madras\s+Regiment|"
    r"Maratha\s+Light|Sikkim\s+Scouts|Ladakh\s+Scouts|Naga\s+Regiment|"
    r"Bengal\s+Sappers|Delhi\s+Public\s+School",
    re.I)


def detect_states(text: str | None) -> list[str]:
    """Named states in the text. Empty list means the source named none, which
    is NOT the same as national scope — callers decide that separately."""
    if not text:
        return []
    text = _STATE_FALSE_POSITIVES.sub(" ", text)
    out = set()
    for st in INDIAN_STATES:
        if re.search(rf"\b{re.escape(st)}\b", text, re.I):
            out.add(st)
    for alias, canon in (("Chattisgarh", "Chhattisgarh"), ("Orissa", "Odisha"),
                         ("Pondicherry", "Puducherry"), ("Uttaranchal", "Uttarakhand"),
                         ("J&K", "Jammu and Kashmir"), ("NCT of Delhi", "Delhi"),
                         # Scheme titles routinely drop the conjunction, e.g.
                         # "PM USP Special Scholarship for Jammu Kashmir and Ladakh".
                         ("Jammu Kashmir", "Jammu and Kashmir"),
                         ("Jammu & Kashmir", "Jammu and Kashmir"),
                         ("Andaman", "Andaman and Nicobar Islands"),
                         ("Dadra", "Dadra and Nagar Haveli and Daman and Diu")):
        if re.search(rf"\b{re.escape(alias)}\b", text, re.I):
            out.add(canon)
    return sorted(out)


def detect_gender(text: str | None) -> str | None:
    if not text:
        return None
    if re.search(r"\bgirl|\bwomen\b|\bwoman\b|female|balika|chhatra?vriti for girl|kanya",
                 text, re.I):
        return "female"
    if re.search(r"\bboys? only\b|\bmale students? only\b", text, re.I):
        return "male"
    return None


def detect_provider_type(provider: str | None, url: str | None = None) -> str | None:
    blob = f"{provider or ''} {url or ''}".lower()
    if not blob.strip():
        return None
    if re.search(r"ministry|department|govt of india|government of india|"
                 r"\bugc\b|aicte|council|nsp|national scholarship", blob):
        if re.search(r"state of|govt\. of [a-z]+ state", blob):
            return "state_govt"
        return "central_govt"
    if re.search(r"state of|\but of\b|directorate|state govt", blob):
        return "state_govt"
    if re.search(r"ongc|ntpc|gail|sail|indianoil|bhel|coal india|psu|railway", blob):
        return "psu"
    if re.search(r"trust|foundation|samiti|society|ngo|charitable", blob):
        return "ngo"
    if re.search(r"university|institute of|college|iit|nit|iisc", blob):
        return "university"
    if re.search(r"ltd|limited|bank|pvt|private|corporation|industries", blob):
        return "private"
    return None


def today_iso() -> str:
    return date.today().isoformat()


def infer_status(deadline_iso: str | None, ref: date | None = None) -> str:
    """active if the deadline is still ahead, expired if it has passed,
    unknown when no deadline was published."""
    if not deadline_iso:
        return "unknown"
    try:
        d = datetime.fromisoformat(deadline_iso).date()
    except ValueError:
        return "unknown"
    return "active" if d >= (ref or date.today()) else "expired"
