"""Generic crawler for official provider sites.

One parser cannot understand every foundation's bespoke layout, and pretending
otherwise is how fabricated data gets into a dataset. So this module does two
honest things:

  1. Link discovery — from a seed page, follow same-domain links whose text or
     href suggests a scholarship, up to a shallow depth.
  2. Conservative extraction — pull only what is unambiguous (title, deadline
     when a date sits beside a deadline word, amounts under a benefit heading).

Anything that looks like a scholarship page but resists structured extraction is
written to data/needs_review/ as raw text, for a human to read. That is the
designed outcome, not a failure path.
"""

from __future__ import annotations

import pathlib
import re
import urllib.parse

from bs4 import BeautifulSoup

import enrich as E
import normalize as N
from schema import Scholarship

NEEDS_REVIEW_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "needs_review"

SCHOLARSHIP_HINT = re.compile(
    r"scholarship|scholar|scheme|fellowship|stipend|grant|financial assistance|"
    r"chhatravritti|shishyavritti|vidya|merit", re.I)

# Links that look topical but never hold scheme detail.
_LINK_NOISE = re.compile(
    r"login|signin|sign-in|register|apply-?online|payment|feedback|sitemap|privacy|"
    r"disclaimer|terms|contact|careers|tender|recruit|vacancy|rti|archive|gallery|"
    r"press|news-?letter|\.jpg|\.png|\.zip|\.doc|\.xls|mailto:|tel:|javascript:|#",
    re.I)

MIN_PAGE_TEXT = 400

# Headings that indicate the page describes one scheme rather than listing many.
_DETAIL_MARKERS = re.compile(
    r"eligib|who can apply|benefit|amount of|last date|deadline|how to apply|"
    r"documents required|selection", re.I)


def _same_site(a: str, b: str) -> bool:
    ha = urllib.parse.urlsplit(a).netloc.lower().removeprefix("www.")
    hb = urllib.parse.urlsplit(b).netloc.lower().removeprefix("www.")
    return ha == hb


def _clean_text(soup: BeautifulSoup) -> str:
    for t in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
        t.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


def discover_links(fetcher, seed: str, max_links: int = 25) -> list[str]:
    """Same-domain links from `seed` that plausibly describe a scheme."""
    r = fetcher.get(seed)
    if not r.ok:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    base = r.final_url or seed
    found: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or _LINK_NOISE.search(href):
            continue
        url = urllib.parse.urljoin(base, href)
        url, _ = urllib.parse.urldefrag(url)
        if not url.startswith("http") or not _same_site(url, base):
            continue
        label = a.get_text(" ", strip=True)
        score = 0
        if SCHOLARSHIP_HINT.search(label):
            score += 2
        if SCHOLARSHIP_HINT.search(url):
            score += 1
        if score and url != base:
            found[url] = max(found.get(url, 0), score)
    return [u for u, _ in sorted(found.items(), key=lambda kv: -kv[1])][:max_links]


def _dump_for_review(url: str, title: str | None, text: str, reason: str) -> str:
    NEEDS_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    import hashlib
    host = urllib.parse.urlsplit(url).netloc.lower()
    fn = f"{host}_{hashlib.sha256(url.encode()).hexdigest()[:12]}.txt"
    p = NEEDS_REVIEW_DIR / fn
    p.write_text(
        f"URL: {url}\nTITLE: {title or ''}\nREASON: {reason}\n"
        f"{'-'*70}\n{text[:20000]}\n", encoding="utf-8")
    return str(p)


_DEADLINE_CTX = re.compile(
    r"(last date|deadline|closing date|apply (?:by|before)|application (?:closes|ends)|"
    r"last day)[^\n]{0,120}", re.I)
_START_CTX = re.compile(
    r"(application (?:starts|opens|begins)|start date|opening date|open from)[^\n]{0,120}",
    re.I)


def parse_page(url: str, html: str, provider_hint: str | None = None,
               source_name: str = "official") -> Scholarship | None:
    """Extract a record from one official page, or None if it is not a scheme page."""
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("h1") or soup.find("h2") or soup.find("title")
    title = N.clean_name(title_tag.get_text(" ", strip=True)) if title_tag else None
    text = _clean_text(soup)

    if not title or len(text) < MIN_PAGE_TEXT:
        return None
    if not SCHOLARSHIP_HINT.search(f"{title} {text[:3000]}"):
        return None

    s = Scholarship()
    s.name, sel = N.strip_basis_suffix(title)
    s.name_normalized = N.normalize_name(s.name)
    s.selection_process = sel
    s.source_name = source_name
    s.source_url = url
    s.source_urls = [url]
    s.official_url = url
    s.application_url = url
    s.application_mode = "provider_website"
    s.extraction_date = N.today_iso()
    s.provider_name = provider_hint
    s.provider_type = N.detect_provider_type(provider_hint, url)
    s.languages_of_official_page = ["en"]

    # Dates only from text that names a deadline; a bare date is not a deadline.
    if (m := _DEADLINE_CTX.search(text)):
        iso = N.parse_date(m.group(0))
        if iso:
            s.application_deadline = iso
            s.deadline_is_tentative = N.is_tentative(m.group(0))
    if (m := _START_CTX.search(text)):
        iso = N.parse_date(m.group(0))
        if iso:
            s.application_start_date = iso

    E.enrich_from_text(s, text, source_url=url)

    s.states = s.states or N.detect_states(f"{s.name} {text[:2500]}")
    s.status = N.infer_status(s.application_deadline)

    para = next((p for p in text.split("\n")
                 if len(p) > 80 and SCHOLARSHIP_HINT.search(p)), None)
    if para:
        s.description_short = re.sub(r"\s+", " ", para)[:400]

    s.field_completeness_percent = s.completeness()

    # A scheme page that yielded almost nothing structured is a human's problem,
    # not a place to start inferring values.
    if s.field_completeness_percent < 20 or not _DETAIL_MARKERS.search(text):
        s.needs_review = True
        s.needs_review_reason = "unstructured page: too few fields extracted"
        s.raw_text_path = _dump_for_review(url, title, text, s.needs_review_reason)
    return s


def crawl_site(fetcher, seed: str, provider_hint: str | None = None,
               max_pages: int = 20) -> list[Scholarship]:
    """Discover and parse scheme pages under one provider domain."""
    out: list[Scholarship] = []
    seen: set[str] = set()

    seed_res = fetcher.get(seed)
    if seed_res.ok:
        rec = parse_page(seed_res.final_url or seed, seed_res.text, provider_hint)
        if rec:
            out.append(rec)
        seen.add(seed)

    for link in discover_links(fetcher, seed, max_links=max_pages):
        if link in seen or len(out) >= max_pages:
            continue
        seen.add(link)
        r = fetcher.get(link)
        if not r.ok:
            continue
        rec = parse_page(r.final_url or link, r.text, provider_hint)
        if rec:
            out.append(rec)
    return out
