"""Rajasthan — the V1 beachhead (PRD §7.3).

Three official sources, none of which needs a login:

  scholarship.rajasthan.gov.in   a department/scheme table covering every
                                 participating department — the master list
  sjmsnew.rajasthan.gov.in       Social Justice & Empowerment portal, with
                                 scheme guideline PDFs
  sje.rajasthan.gov.in           the department site, for guideline documents

The master table gives each scheme's name in English and Hindi plus the owning
department. It does not publish deadlines or eligibility, so those stay null
here and are filled only if a guideline PDF states them. A Rajasthan scheme with
a name and an official link is worth far more to a student than an invented
deadline.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

import normalize as N
from schema import Scholarship

SOURCE_NAME = "rajasthan"

MASTER_URL = "https://scholarship.rajasthan.gov.in/"
SJMS_URL = "https://sjmsnew.rajasthan.gov.in/scholarship/"
SJE_URL = "https://sje.rajasthan.gov.in/Scholarship_Portal.aspx"

# Department -> who actually administers it, for provider_name.
DEPT_NAMES = {
    "COLLEGE EDUCATION": "Department of College Education, Rajasthan",
    "MINORITY": "Minorities Affairs Department, Rajasthan",
    "SOCIAL JUSTICE": "Social Justice and Empowerment Department, Rajasthan",
    "TAD": "Tribal Area Development Department, Rajasthan",
    "TRIBAL AREA DEVELOPMENT": "Tribal Area Development Department, Rajasthan",
    "TECHNICAL EDUCATION": "Department of Technical Education, Rajasthan",
    "SANSKRIT EDUCATION": "Department of Sanskrit Education, Rajasthan",
    "SECONDARY EDUCATION": "Department of Secondary Education, Rajasthan",
    "DEVASTHAN": "Devasthan Department, Rajasthan",
    "AYURVED": "Department of Ayurved, Rajasthan",
}

# NOTE: we deliberately do NOT infer eligibility from the administering
# department. Rajasthan lists "Anuprati Scheme" under the Minority department,
# but Anuprati is open to SC, ST, OBC, EBC and minority students alike. Reading
# the department as a category restriction excluded OBC students from a scheme
# they qualify for — the exact harm this project exists to avoid. A department
# says who runs a scheme, not who may apply. Categories come only from what the
# scheme's own name states.

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _split_bilingual(cell: str) -> tuple[str, str | None]:
    """The table puts 'ENGLISH NAME हिंदी नाम' in one cell. Split on the first
    Devanagari character so each language stays intact."""
    m = _DEVANAGARI.search(cell)
    if not m:
        return cell.strip(), None
    return cell[:m.start()].strip(" -–—"), cell[m.start():].strip()


# Only these stay capitalised. Length-based acronym detection turned ordinary
# words into shouting ("Economic HELP TO Tribal Girls"), which reads badly on a
# phone and looks like a bug to anyone watching a demo.
ACRONYMS = {
    "SC", "ST", "OBC", "EBC", "EWS", "DNT", "SBC", "PWD", "BPL",
    "IIT", "IIM", "AIIMS", "NIT", "NITS", "CLAT", "IIS", "UPSC", "RPSC",
    "NEET", "JEE", "BSTC", "CM", "MBBS", "ITI", "RAS", "IAS", "IPS",
    "UG", "PG", "PHD", "B.ED", "BED", "M.ED", "TAD", "SJE",
}
_SMALL = {"and", "of", "for", "in", "the", "to", "cum", "at", "on", "with",
          "like", "a", "an", "or", "as", "by"}


def _title_case(s: str) -> str:
    """The source shouts in caps; students read mixed case better."""
    words = []
    for i, w in enumerate(s.split()):
        bare = w.strip("().,/&").upper()
        # Compound acronyms like "SC/ST" or "OBC/EBC" must survive intact.
        parts = [p for p in re.split(r"[/&]", bare) if p]
        if parts and all(p in ACRONYMS for p in parts):
            words.append(w.upper())
        elif bare in ACRONYMS:
            words.append(w.replace(bare.lower(), bare) if not w.isupper() else w)
        elif w.lower() in _SMALL and i > 0:
            words.append(w.lower())
        elif w.isupper():
            words.append(w.capitalize())
        else:
            words.append(w)
    out = " ".join(words)
    # Capitalise after an opening bracket: "(admission in ..." -> "(Admission in ..."
    return re.sub(r"\(\s*([a-z])", lambda m: "(" + m.group(1).upper(), out)


def parse_master(html: str) -> list[Scholarship]:
    """Parse the department/scheme table into records."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Scholarship] = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 5:
            continue
        header = " ".join(c.get_text(" ", strip=True).lower()
                          for c in rows[0].find_all(["td", "th"]))
        if "scheme" not in header or "department" not in header:
            continue

        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            dept_raw, scheme_raw = cells[1], cells[2]
            if not scheme_raw or len(scheme_raw) < 6:
                continue

            dept_en, _ = _split_bilingual(dept_raw)
            name_en, name_hi = _split_bilingual(scheme_raw)
            if not name_en or len(name_en) < 6:
                continue

            s = Scholarship()
            s.name = _title_case(N.clean_name(name_en) or name_en)
            s.name_normalized = N.normalize_name(s.name)
            if name_hi:
                s.aliases = [name_hi]

            key = dept_en.upper().strip()
            provider = next((v for k, v in DEPT_NAMES.items() if k in key), None)
            s.provider_name = provider or f"{_title_case(dept_en)}, Rajasthan"
            s.administering_body = s.provider_name
            s.provider_type = "state_govt"
            s.states = ["Rajasthan"]

            s.source_name = SOURCE_NAME
            s.source_url = MASTER_URL
            s.source_urls = [MASTER_URL]
            s.official_url = MASTER_URL
            s.application_url = MASTER_URL
            s.application_mode = "state_portal"
            s.extraction_date = N.today_iso()
            s.languages_of_official_page = ["en", "hi"]

            # Only what the name and department actually state.
            s.categories = N.detect_categories(s.name)
            s.education_levels = N.detect_levels(s.name)
            s.gender = N.detect_gender(s.name)

            # No deadline is published on this page. Leaving it null is correct;
            # status stays unknown rather than claiming the scheme is open.
            s.status = "unknown"
            s.confidence = "medium"
            s.description_short = (
                f"{s.name} is listed on the Rajasthan Scholarship Portal under "
                f"{_title_case(dept_en)}. Apply through the state portal.")
            s.field_completeness_percent = s.completeness()
            out.append(s)

    return out


def parse_guideline_links(html: str, base: str) -> dict[str, str]:
    """Map scheme-ish link text to its guideline PDF, so records can be enriched
    from the document that actually states eligibility."""
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        href = a["href"].strip()
        if not label or len(label) < 8:
            continue
        if not href.lower().endswith(".pdf"):
            continue
        if not re.search(r"guideline|scheme|scholarship|niyam|yojana", f"{label} {href}", re.I):
            continue
        if href.startswith("/"):
            from urllib.parse import urljoin
            href = urljoin(base, href)
        found.setdefault(label, href)
    return found


def crawl(fetcher) -> list[Scholarship]:
    records: list[Scholarship] = []

    r = fetcher.get(MASTER_URL)
    if r.ok:
        records = parse_master(r.text)
        print(f"  [Rajasthan] master table: {len(records)} schemes")
    else:
        print(f"  [Rajasthan] master table unavailable "
              f"({r.status or r.skipped_reason})")

    # Attach guideline PDFs where a scheme name plausibly matches a link label.
    guidelines: dict[str, str] = {}
    for url in (SJMS_URL, SJE_URL):
        g = fetcher.get(url)
        if g.ok:
            guidelines.update(parse_guideline_links(g.text, url))
    if guidelines:
        print(f"  [Rajasthan] {len(guidelines)} guideline PDF link(s) found")

    attached = 0
    for s in records:
        key = set((s.name_normalized or "").split())
        if not key:
            continue
        for label, href in guidelines.items():
            words = set((N.normalize_name(label) or "").split())
            # Require a real overlap; a single shared word like "scholarship"
            # would attach the wrong document to almost everything.
            if len(key & words) >= 2:
                s.official_url = href
                if href not in s.source_urls:
                    s.source_urls.append(href)
                attached += 1
                break
    if attached:
        print(f"  [Rajasthan] {attached} scheme(s) linked to a guideline PDF")

    return records
