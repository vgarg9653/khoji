"""National Scholarship Portal (scholarships.gov.in).

The All-Scholarships page is server-rendered but only after a POST from one of
three public filter forms, so we drive it with a headless browser and read the
three views a visitor can reach:

  centralscheme   -> central sector schemes, grouped by ministry/department
  sponserscheme   -> centrally sponsored schemes, grouped by state
  statescheme     -> state's own schemes, grouped by state

Each scheme block yields a name, its open/close date badges, and links to the
official guideline and FAQ PDFs. Those PDFs are the authoritative source for
eligibility, so we record their URLs; we do not invent eligibility from a title.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

import normalize as N
from schema import Scholarship

SOURCE_NAME = "NSP"
BASE = "https://scholarships.gov.in"
LIST_URL = f"{BASE}/All-Scholarships"

VIEWS = [
    ("centralscheme", "central_sector"),
    ("sponserscheme", "centrally_sponsored"),
    ("statescheme", "state_scheme"),
]

# Badge text -> which date field it describes.
_BADGE_MAP = [
    (re.compile(r"scheme\s*open\s*from", re.I), "application_start_date"),
    (re.compile(r"student\s*application\s*open\s*till", re.I), "application_deadline"),
]

_NAV_HEADERS = {"Students", "Institute", "Officers", "Public"}
_STATE_HEADER = re.compile(r"^(?:State of|UT of)\s+(.*)$", re.I)


def _select_and_search(page, select_name: str, value: str) -> None:
    """Choose a public filter value and press its Search button — the same two
    actions a visitor performs. No hidden fields are touched."""
    page.select_option(f"select[name='{select_name}']", value)
    page.wait_for_timeout(600)
    handle = page.query_selector(f"select[name='{select_name}']") \
                 .evaluate_handle("e => e.closest('form')").as_element()
    handle.query_selector("button").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(4500)


def fetch_views(renderer) -> dict[str, str]:
    """Return {view_kind: rendered_html} for the three public filter views."""
    out: dict[str, str] = {}
    for value, kind in VIEWS:
        ok, html, note = renderer.render(
            LIST_URL,
            tag=f"nsp-{kind}",
            wait_ms=3000,
            actions=lambda pg, v=value: _select_and_search(
                pg, "central_sponsored_state", v),
        )
        if ok and html:
            out[kind] = html
        else:
            print(f"  [NSP] {kind}: render failed -- {note}")
    return out


def _canonical_state(header: str) -> str | None:
    m = _STATE_HEADER.match(header.strip())
    if not m:
        return None
    found = N.detect_states(m.group(1))
    return found[0] if found else None


def parse(html: str, kind: str) -> list[Scholarship]:
    """Parse one rendered view into Scholarship records."""
    soup = BeautifulSoup(html, "lxml")
    records: list[Scholarship] = []

    for item in soup.select(".accordion-item"):
        btn = item.select_one(".accordion-button")
        body = item.select_one(".accordion-body")
        if not btn or not body:
            continue
        header = btn.get_text(" ", strip=True)
        if not header or header in _NAV_HEADERS:
            continue

        state = _canonical_state(header)
        # For state-grouped views the header names the state; for the central
        # view it names the administering ministry.
        administering = None if state else header

        for block in body.select(".row"):
            h6 = block.find("h6")
            if not h6:
                continue
            raw_name = N.clean_name(h6.get_text(" ", strip=True))
            if not raw_name:
                continue
            name, selection = N.strip_basis_suffix(raw_name)

            s = Scholarship()
            s.name = name
            s.name_normalized = N.normalize_name(name)
            s.selection_process = selection
            s.source_name = SOURCE_NAME
            s.source_url = LIST_URL
            s.source_urls = [LIST_URL]
            s.extraction_date = N.today_iso()
            s.application_mode = "NSP"
            s.application_url = LIST_URL
            s.scheme_year = "2026-27"

            # --- dates from the coloured badges ---
            badge_text = []
            for span in block.find_all("span"):
                t = span.get_text(" ", strip=True)
                if not t:
                    continue
                badge_text.append(t)
                for rx, field in _BADGE_MAP:
                    if rx.search(t):
                        iso = N.parse_date(t)
                        if iso and getattr(s, field) is None:
                            setattr(s, field, iso)
            badges = " | ".join(badge_text)
            if badges:
                s.deadline_is_tentative = N.is_tentative(badges)

            # --- official guideline / FAQ PDFs ---
            for a in block.find_all("a", href=True):
                href, label = a["href"].strip(), a.get_text(" ", strip=True).lower()
                if not href or href == "null":
                    continue
                if href.startswith("/"):
                    href = BASE + href
                if "specification" in label or "guideline" in label:
                    s.official_url = s.official_url or href
                if href not in s.source_urls:
                    s.source_urls.append(href)

            # --- provenance-driven attribution ---
            if kind == "central_sector":
                s.provider_type = "central_govt"
                s.provider_name = administering
                s.administering_body = administering
                # Centrally funded does not mean nationally open. Schemes like
                # "PM USP Special Scholarship for Jammu Kashmir and Ladakh" are
                # run by a ministry but restricted to one region, and tagging
                # them "all" would surface them to students who cannot apply.
                named = N.detect_states(name)
                s.states = named if named else ["all"]
            elif kind == "centrally_sponsored":
                s.provider_type = "central_govt"
                s.administering_body = header
                s.states = [state] if state else []
            else:
                s.provider_type = "state_govt"
                s.provider_name = header
                s.administering_body = header
                s.states = [state] if state else []

            # --- what the title itself reliably states ---
            s.categories = N.detect_categories(name)
            s.education_levels = N.detect_levels(name)
            s.gender = N.detect_gender(name)
            if not s.states:
                s.states = N.detect_states(name)

            s.status = N.infer_status(s.application_deadline)
            s.confidence = "medium"
            s.field_completeness_percent = s.completeness()
            s.description_short = (
                f"{name} is listed on the National Scholarship Portal under "
                f"{header}. Applications are submitted through NSP."
            )
            s.languages_of_official_page = ["en"]
            records.append(s)

    return records


def crawl(renderer) -> list[Scholarship]:
    all_records: list[Scholarship] = []
    for kind, html in fetch_views(renderer).items():
        got = parse(html, kind)
        print(f"  [NSP] {kind}: {len(got)} schemes")
        all_records.extend(got)
    return all_records
