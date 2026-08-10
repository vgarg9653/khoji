"""Read a student's profile out of one free-form sentence, without a model.

"I'm an OBC girl in class 12 in Rajasthan, income 2 lakh" contains every fact
the matcher needs, stated plainly. Sending that to a language model works, but
it is the single most impressive thing a student can type and it should not
depend on a quota, a network round-trip, or a provider being up.

So rules run first and the model becomes the fallback for genuinely unusual
phrasing. Same guarantee as everywhere else in this project: a field we cannot
read confidently is left None rather than guessed.
"""

from __future__ import annotations

import re

import copy_hi
from conversation import CATEGORIES, STATES, parse_income


# Order matters: longer names first, so "Uttar Pradesh" is not matched by a
# stray "Uttarakhand" prefix or vice versa.
_STATES_BY_LENGTH = sorted(STATES, key=len, reverse=True)

_CITY_TO_STATE = {
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan", "udaipur": "Rajasthan",
    "kota": "Rajasthan", "ajmer": "Rajasthan", "barmer": "Rajasthan",
    "bikaner": "Rajasthan", "sikar": "Rajasthan", "tonk": "Rajasthan",
    "patna": "Bihar", "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "bengaluru": "Karnataka", "bangalore": "Karnataka", "mysore": "Karnataka",
    "chennai": "Tamil Nadu", "madurai": "Tamil Nadu",
    "kolkata": "West Bengal", "hyderabad": "Telangana",
    "ahmedabad": "Gujarat", "surat": "Gujarat", "bhopal": "Madhya Pradesh",
    "indore": "Madhya Pradesh", "ranchi": "Jharkhand", "raipur": "Chhattisgarh",
    "guwahati": "Assam", "bhubaneswar": "Odisha", "thiruvananthapuram": "Kerala",
    "kochi": "Kerala", "chandigarh": "Chandigarh", "dehradun": "Uttarakhand",
}

# "class 12", "12th", "class XII", "कक्षा 10"
_CLASS = re.compile(
    r"(?:class|std|standard|कक्षा|klass)\s*([IVXivx]+|\d{1,2})\b"
    r"|\b(\d{1,2})\s*(?:th|st|nd|rd)\s*(?:class|standard|grade)?\b", re.I)
_ROMAN = {"i":1,"ii":2,"iii":3,"iv":4,"v":5,"vi":6,"vii":7,"viii":8,
          "ix":9,"x":10,"xi":11,"xii":12}

_LEVEL_WORDS = [
    (re.compile(r"\b(?:ph\.?d|doctorate|doctoral|research\s*scholar|"
                r"शोध|पीएचडी)\b", re.I), "PhD"),
    (re.compile(r"\b(?:m\.?tech|m\.?sc|m\.?a\b|m\.?com|m\.?ba|masters?|"
                r"post[- ]?grad(?:uation|uate)?|\bpg\b|स्नातकोत्तर)\b", re.I), "PG"),
    (re.compile(r"\b(?:b\.?tech|b\.?sc|b\.?a\b|b\.?com|b\.?ed|bachelor'?s?|"
                r"graduation|graduate|under[- ]?grad(?:uate)?|\bug\b|college|"
                r"स्नातक|कॉलेज)\b", re.I), "UG"),
    (re.compile(r"\b(?:mbbs|md\b|medical|engineering|law|llb|professional|"
                r"मेडिकल|इंजीनियरिंग)\b", re.I), "professional"),
    (re.compile(r"\b(?:diploma|polytechnic|डिप्लोमा|पॉलिटेक्निक)\b", re.I), "diploma"),
    (re.compile(r"\b(?:iti|i\.?t\.?i\.?|आईटीआई)\b", re.I), "ITI"),
    (re.compile(r"\b(?:school|class|std|standard|matric|inter|intermediate|"
                r"senior\s*secondar\w*|higher\s*secondar\w*|"
                r"स्कूल|कक्षा|विद्यालय)\b", re.I), "school"),
]

# Written to tolerate how people actually type these, not how the form spells
# them. "SC" is an abbreviation of "Scheduled Caste" — a student typing the
# words it stands for is not using unusual phrasing, and being told the bot did
# not understand is indefensible. The `\w*` endings absorb the common
# misspellings ("schedule caste", "scheduled cast") without a model call.
_CATEGORY_WORDS = [
    # The two-letter abbreviations need guarding, or the degree a student is
    # proud of becomes a caste they never claimed. "I joined B.Sc last year"
    # was read as Scheduled Caste, because the dot in "B.Sc" is a word boundary
    # — which would have shown a general-category student SC-only schemes.
    # Same shape as the "Assam Rifles" bug: a short token matching inside a
    # longer name that means something else entirely.
    (re.compile(r"(?<![bm]\.)\bsc\b|\b(?:schedul\w*\s+cast\w*|dalit|"
                r"anusuchit\s*jati|harijan)\b", re.I), "SC"),
    # "St. Xavier's College" is a school, not a Scheduled Tribe.
    (re.compile(r"\bst\b(?!\s*\.)|\b(?:schedul\w*\s+trib\w*|tribal|adivasi|"
                r"adiwasi|anusuchit\s*janjati|janjati)\b", re.I), "ST"),
    (re.compile(r"\b(?:obc|o\.?b\.?c\.?|other\s+backward\w*|backward\s+class\w*|"
                r"pichh?da|pichhda\s*varg|mbc)\b", re.I), "OBC"),
    (re.compile(r"\b(?:ews|e\.?w\.?s\.?|economically\s+weak\w*|"
                r"aarthik\s*roop)\b", re.I), "EWS"),
    (re.compile(r"\b(?:minority|minorit\w*|alpsankhyak|muslim|christian|sikh|"
                r"buddhist|parsi|jain)\b", re.I), "minority"),
    (re.compile(r"\b(?:pwd|p\.?w\.?d\.?|disabled|disabilit\w*|divyang|divyaang|"
                r"viklang|handicap\w*|blind|deaf)\b", re.I), "PwD"),
    (re.compile(r"\b(?:dnt|denotified|de-?notified|nomadic|vimukt|ghumantu)\b",
                re.I), "DNT"),
    (re.compile(r"\b(?:general\s*categor\w*|general|unreserved|samanya|"
                r"none\s+of\s+these)\b", re.I), "general"),
]

_GENDER = [
    (re.compile(r"\b(?:girl|female|woman|daughter|beti|लड़की|छात्रा|बेटी)\b", re.I),
     "female"),
    (re.compile(r"\b(?:boy|male|man|son|beta|लड़का|छात्र|बेटा)\b", re.I), "male"),
]

# Only read money that is framed as income, so a scholarship amount mentioned in
# passing is not mistaken for the family's earnings.
#
# The Roman-script Hindi words are not decoration. "ghar ki aay 2 lakh" is the
# single most common way this gets typed, and without "aay" here the sentence
# parsed perfectly except for the one number that decides eligibility — then
# asked for it again, which is exactly the re-asking this module exists to stop.
_INCOME_WORDS = (r"income|salary|earn(?:s|ing)?|kamai|kamaai|aay|aay?a|"
                 r"aamdani|amdani|tankhwah|tankhawah|"
                 r"आय|आमदनी|कमाई|तनख़्वाह|वेतन")
_AMOUNT = (r"[₹\d][\d,. ]*(?:lakh|lakhs|lac|l|k|thousand|crore|"
           r"लाख|हज़ार|हजार|करोड़)?")

_INCOME_CONTEXT = re.compile(
    rf"(?:{_INCOME_WORDS})[^\d₹]{{0,24}}({_AMOUNT})", re.I)
_INCOME_TRAILING = re.compile(
    rf"({_AMOUNT})[^\d]{{0,24}}(?:{_INCOME_WORDS})", re.I)


def find_state(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for hi_name, canonical in copy_hi.STATES_HI.items():
        if hi_name in raw:
            return canonical
    low = raw.lower()
    for s in _STATES_BY_LENGTH:
        if re.search(rf"\b{re.escape(s.lower())}\b", low):
            return s
    for city, state in _CITY_TO_STATE.items():
        if re.search(rf"\b{city}\b", low):
            return state
    return None


def find_class(text: str) -> int | None:
    t = (text or "").translate(copy_hi.DEVANAGARI_DIGITS)
    m = _CLASS.search(t)
    if not m:
        return None
    tok = (m.group(1) or m.group(2) or "").strip().lower()
    v = int(tok) if tok.isdigit() else _ROMAN.get(tok)
    return v if v and 1 <= v <= 12 else None


def find_level(text: str) -> str | None:
    for rx, level in _LEVEL_WORDS:
        if rx.search(text or ""):
            return level
    return None


def find_category(text: str) -> str | None:
    raw = text or ""
    for hi_word, cat in copy_hi.CATEGORIES_HI.items():
        if hi_word in raw:
            return cat
    for rx, cat in _CATEGORY_WORDS:
        if rx.search(raw):
            return cat
    return None


def find_gender(text: str) -> str | None:
    for rx, g in _GENDER:
        if rx.search(text or ""):
            return g
    return None


# People state amounts in words at least as often as in digits — "one lakh",
# "ढाई लाख". The regexes below expect the amount to begin with a digit, so the
# words are converted to digits first rather than complicating every pattern.
_WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "half": "0.5", "quarter": "0.25",
    "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पाँच": "5", "पांच": "5",
    "छह": "6", "सात": "7", "आठ": "8", "नौ": "9", "दस": "10",
    "ढाई": "2.5", "डेढ़": "1.5", "सवा": "1.25", "पौने": "0.75",
}


def _numeralise(text: str) -> str:
    t = (text or "").translate(copy_hi.DEVANAGARI_DIGITS)
    for word, digit in _WORD_NUMBERS.items():
        t = re.sub(rf"(?<![\w\u0900-\u097F]){re.escape(word)}(?![\w\u0900-\u097F])",
                   digit, t, flags=re.I)
    return t


def find_income(text: str) -> int | None:
    raw = _numeralise(text or "")
    for rx in (_INCOME_CONTEXT, _INCOME_TRAILING):
        m = rx.search(raw)
        if m:
            got = parse_income(m.group(1))
            if got:
                return got
    return None


# What a student says when asked what they want to do next. These map onto the
# same stream names the catalogue is tagged with (relevance.tag), so a stated
# interest and a scheme's subject can actually be compared.
_FIELDS = [
    (re.compile(r"\b(?:engineer(?:ing)?|b\.?tech|iit|jee|technical|computer|"
                r"software|coding|इंजीनियर|इंजीनियरिंग)\b", re.I), "engineering"),
    (re.compile(r"\b(?:doctor|medical|mbbs|neet|nurse|nursing|pharmac|dentist|"
                r"डॉक्टर|मेडिकल|नर्स)\b", re.I), "medical"),
    (re.compile(r"\b(?:law(?:yer)?|llb|advocate|judge|वकील|कानून)\b", re.I), "law"),
    (re.compile(r"\b(?:agricultur|farming|veterinary|कृषि|खेती)\b", re.I),
     "agriculture"),
    (re.compile(r"\b(?:ca\b|chartered accountant|commerce|mba|business|"
                r"वाणिज्य|कॉमर्स)\b", re.I), "commerce"),
    (re.compile(r"\b(?:art(?:s|ist)?|music|design|dance|कला|संगीत)\b", re.I), "arts"),
]


def find_field_of_interest(text: str) -> str | None:
    for rx, field in _FIELDS:
        if rx.search(text or ""):
            return field
    return None


def extract(text: str) -> dict:
    """Everything the sentence states, as a dict of non-None values only.

    A class number implies school level, but only when no stronger level word is
    present — "class 12 passed, now in B.Sc." is a UG student.
    """
    out: dict = {}
    for key, fn in (("state", find_state), ("class_level", find_class),
                    ("category", find_category), ("gender", find_gender),
                    ("family_income_inr", find_income)):
        v = fn(text)
        if v is not None:
            out[key] = v

    level = find_level(text)
    if level:
        out["education_level"] = level
    elif "class_level" in out:
        out["education_level"] = "school"

    # "I finished 12th and joined B.Sc" states both a class and a level, and
    # only one of them is where the student is now. A class number alongside a
    # college level is a leftover from the sentence, not a fact about them, and
    # showing "Class: 12 · Studying: UG" back to them reads as a bot that didn't
    # follow. Class only means something at school.
    if out.get("education_level") not in (None, "school"):
        out.pop("class_level", None)

    return out
