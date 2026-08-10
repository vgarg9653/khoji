"""Verification stage — runs on the top 100 only.

Re-fetches each record's official_url and asks three questions:
  1. Is the link still alive, and does it still point where we think?
  2. Does the page still state the deadline and eligibility terms we stored?
  3. Does the page hedge — "tentative", "to be announced", portal closed, or a
     deadline that lives only inside a linked PDF?

A record that passes all three earns confidence=high and today's verification
date. Everything else goes to data/review_queue.csv with the reason and the
exact snippet that triggered it, so a human can adjudicate in under a minute.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from bs4 import BeautifulSoup

import normalize as N
from schema import Scholarship

AMBIGUITY_PATTERNS = [
    (re.compile(r"\btentative(?:ly)?\b", re.I), "deadline marked tentative"),
    (re.compile(r"to be announced|to be notified|will be announced|yet to be announced",
                re.I), "date not yet announced"),
    (re.compile(r"\bTBA\b|\bTBD\b"), "date placeholder (TBA/TBD)"),
    (re.compile(r"portal (?:is )?closed|registration closed|applications? closed|"
                r"link (?:is )?(?:now )?(?:closed|disabled)|closed for the year", re.I),
     "portal reported closed"),
    (re.compile(r"under maintenance|temporarily unavailable|site is down", re.I),
     "portal under maintenance"),
    (re.compile(r"last date .{0,40}extended|date extended", re.I),
     "deadline recently extended - stored value may be stale"),
]

DEADLINE_CTX = re.compile(
    r"(last date|deadline|closing date|apply (?:by|before)|open till|"
    r"application (?:closes|ends|last date))[^\n]{0,140}", re.I)

PDF_LINK = re.compile(r"\.pdf(?:[?#]|$)", re.I)


@dataclass
class Flag:
    reason: str
    snippet: str
    field: str = ""
    stored: str = ""
    found: str = ""


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))


def _snippet(text: str, match_start: int, width: int = 160) -> str:
    lo = max(0, match_start - width // 2)
    return re.sub(r"\s+", " ", text[lo:lo + width]).strip()


def build_nsp_deadline_index(renderer) -> dict[str, dict]:
    """Re-read the NSP listing and index current deadlines by normalized name.

    NSP schemes carry two different authorities: the listing page publishes this
    year's dates, while official_url points at a multi-year guidelines PDF that
    cannot contain them. Checking a listing-page deadline against that PDF would
    flag every record for a mismatch that is really a category error on our side.
    """
    import normalize as _N
    import sources.nsp as nsp

    index: dict[str, dict] = {}
    for kind, html in nsp.fetch_views(renderer).items():
        for rec in nsp.parse(html, kind):
            key = rec.name_normalized or _N.normalize_name(rec.name)
            if key:
                index[key] = {
                    "deadline": rec.application_deadline,
                    "start": rec.application_start_date,
                    "tentative": rec.deadline_is_tentative,
                }
    return index


def verify_deadline_against_nsp(s: Scholarship, index: dict[str, dict]) -> list[Flag]:
    """Confirm an NSP record's dates against a fresh read of the NSP listing."""
    key = s.name_normalized
    entry = index.get(key) if key else None
    if entry is None:
        return [Flag("scheme no longer listed on NSP for the current year",
                     f"searched NSP listing for '{s.name}'",
                     "application_deadline", s.application_deadline or "", "")]

    flags: list[Flag] = []
    live = entry.get("deadline")
    if s.application_deadline and live and s.application_deadline != live:
        flags.append(Flag("deadline changed on the NSP listing since extraction",
                          f"NSP now shows {live}", "application_deadline",
                          s.application_deadline, live))
    elif s.application_deadline and not live:
        flags.append(Flag("NSP listing no longer shows a deadline for this scheme",
                          f"'{s.name}' has no date badge", "application_deadline",
                          s.application_deadline, ""))
    if entry.get("tentative"):
        flags.append(Flag("NSP marks this scheme's dates as tentative",
                          f"'{s.name}' badge text flagged tentative"))
    return flags


def verify_record(fetcher, s: Scholarship,
                  nsp_index: dict[str, dict] | None = None) -> tuple[Scholarship, list[Flag]]:
    flags: list[Flag] = []
    url = s.official_url or s.source_url

    # Concerns raised at parse time (e.g. a guidelines PDF shared by several
    # schemes) are outside what verification examines. Passing the deadline and
    # eligibility checks says nothing about them, so they must survive a pass.
    parse_stage_reason = s.needs_review_reason

    # For NSP schemes the deadline is verified against the NSP listing, and the
    # official PDF is used only for the eligibility checks it can actually answer.
    nsp_checked = False
    if nsp_index is not None and s.application_mode == "NSP":
        flags.extend(verify_deadline_against_nsp(s, nsp_index))
        nsp_checked = True

    if not url:
        flags.append(Flag("no official_url stored", ""))
        s.needs_review = True
        s.confidence = "medium"
        s.verify_notes = "no official url"
        return s, flags

    is_pdf = PDF_LINK.search(url) is not None

    if is_pdf:
        import pdf_extract as P
        text, note = P.get_text(fetcher, url)
        s.verify_http_status = 200 if text else None
        if not text:
            flags.append(Flag(f"official PDF unreadable: {note}", url))
            s.needs_review = True
            s.confidence = "medium"
            s.verify_notes = note
            return s, flags
    else:
        r = fetcher.get(url, allow_cache=False)
        s.verify_http_status = r.status if isinstance(r.status, int) else None
        if r.blocked:
            flags.append(Flag(f"could not re-fetch: {r.skipped_reason}", url))
            s.needs_review = True
            s.confidence = "medium"
            s.verify_notes = r.skipped_reason
            return s, flags
        if not r.ok:
            flags.append(Flag(f"dead or erroring link (HTTP {r.status})", url))
            s.needs_review = True
            s.confidence = "medium"
            s.status = "unknown" if s.status == "active" else s.status
            s.verify_notes = f"HTTP {r.status}"
            return s, flags

        final = r.final_url or url
        if final and final.rstrip("/") != url.rstrip("/"):
            s.verify_redirected_to = final
            if urllib.parse.urlsplit(final).netloc != urllib.parse.urlsplit(url).netloc:
                flags.append(Flag("official_url redirects to a different domain",
                                  f"{url} -> {final}"))
        text = _visible_text(r.text)

    # ---- ambiguity signals ----
    for rx, reason in AMBIGUITY_PATTERNS:
        m = rx.search(text)
        if m:
            flags.append(Flag(reason, _snippet(text, m.start())))

    # ---- deadline cross-check ----
    page_deadlines: list[str] = []
    for m in DEADLINE_CTX.finditer(text):
        iso = N.parse_date(m.group(0))
        if iso:
            page_deadlines.append(iso)

    if nsp_checked:
        # Already verified against the listing that published the date; a
        # guidelines PDF is not expected to restate this year's deadline.
        pass
    elif s.application_deadline:
        if not page_deadlines:
            has_pdf = bool(PDF_LINK.search(text)) or is_pdf
            flags.append(Flag(
                "stored deadline not confirmed on official page"
                + (" (deadline may be inside a linked PDF)" if has_pdf else ""),
                _snippet(text, 0, 200), "application_deadline",
                s.application_deadline, ""))
        elif s.application_deadline not in page_deadlines:
            m = DEADLINE_CTX.search(text)
            flags.append(Flag(
                "deadline mismatch between stored value and official page",
                _snippet(text, m.start() if m else 0),
                "application_deadline", s.application_deadline,
                ", ".join(sorted(set(page_deadlines))[:3])))
    elif page_deadlines and not nsp_checked:
        flags.append(Flag("official page states a deadline we did not store",
                          _snippet(text, DEADLINE_CTX.search(text).start()),
                          "application_deadline", "", page_deadlines[0]))

    # ---- key eligibility cross-check ----
    if s.income_ceiling_inr:
        lo, hi = N.parse_amounts(
            " ".join(re.findall(r"[^\n]*income[^\n]*", text, re.I))[:2000])
        if hi and abs(hi - s.income_ceiling_inr) > max(1000, 0.02 * s.income_ceiling_inr):
            m = re.search(r"[^\n]*income[^\n]*", text, re.I)
            flags.append(Flag("income ceiling differs from official page",
                              _snippet(text, m.start() if m else 0),
                              "income_ceiling_inr", str(s.income_ceiling_inr), str(hi)))

    if s.categories:
        page_cats = set(N.detect_categories(text))
        stored = {c for c in s.categories if c not in ("all", "general")}
        if stored and page_cats and not (stored & page_cats):
            flags.append(Flag("category eligibility not corroborated on official page",
                              _snippet(text, 0, 200), "categories",
                              ", ".join(sorted(stored)), ", ".join(sorted(page_cats))))

    # ---- verdict ----
    if flags:
        s.needs_review = True
        reason = "; ".join(dict.fromkeys(f.reason for f in flags))[:400]
        s.needs_review_reason = (
            f"{s.needs_review_reason}; {reason}" if s.needs_review_reason else reason)
        s.confidence = "medium"
    else:
        # The source confirmed what we stored, so the record is verified — but a
        # parse-stage concern that verification never looked at still stands.
        s.confidence = "high"
        s.last_verified_date = N.today_iso()
        s.needs_review = bool(parse_stage_reason)
        s.needs_review_reason = parse_stage_reason
        if s.application_deadline:
            s.status = N.infer_status(s.application_deadline)

    return s, flags
