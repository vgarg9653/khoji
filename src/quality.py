"""Quality gate — decide which records the bot is allowed to serve.

A broad crawl inevitably picks up page furniture: "Overview", "Welcome",
"Navigation", a ministry's own name. Those are not scholarships, and one of them
outranking a real scheme in a student's results is both useless and embarrassing.

The gate is deliberately **auditable rather than destructive**: nothing is
deleted. Every record gets `servable` plus a `not_servable_reason`, so you can
see exactly what was withheld and why, and relax a rule without re-crawling.

It is also deliberately **conservative about rejecting**. A wrongly-rejected
scheme is invisible to students, which is worse than a slightly noisy catalogue,
so a record is withheld only when it clearly is not a scholarship — never merely
because it is sparse.
"""

from __future__ import annotations

import re

# Page furniture. These are whole-name matches: a scheme legitimately called
# "Overview of the Pragati Scholarship" must survive.
NAV_LABELS = re.compile(
    r"^\s*(?:"
    r"overview|welcome|home|about|about\s*us|contact|contact\s*us|navigation|"
    r"regulation[s]?|highlights|student\s*services|services|login|sign\s*in|"
    r"register|sitemap|site\s*map|faq[s]?|downloads?|gallery|notice\s*board|"
    r"tenders?|circulars?|archives?|news|events|photo\s*gallery|disclaimer|"
    r"privacy\s*policy|terms|help|helpdesk|dashboard|menu|search|links?|"
    r"general\s*instructions?|instructions?|guidelines?|introduction|"
    r"\d{4}\s*highlights?|batch\s*[\d-]+|our\s*scholars?\s*\d{4}"
    r")\s*$", re.I)

# Words that mark a name as describing a scheme rather than a page.
SCHEME_WORD = re.compile(
    r"scholar|scheme|yojana|yojna|chhatra|chatra|shishya|vritti|vriti|"
    r"fellow|stipend|grant|incentive|award|sambal|protsahan|bursary|"
    r"reimburs|assistance|help\s+to|support\s+to|aid\s+to|freeship|"
    r"pre\s*matric|post\s*matric|merit|means", re.I)

# An organisation's own name, with nothing scheme-like around it.
ORG_ONLY = re.compile(
    r"^\s*(?:ministry|department|directorate|मंत्रालय|विभाग|निदेशालय|"
    r"government|govt|commission|council|board|corporation|authority|trust|"
    r"foundation)\b", re.I)


# Sources that are, by construction, registries of schemes: every row on NSP's
# All-Scholarships page or Rajasthan's department table IS a scholarship. A
# record from one of these does not have to prove itself by its name — which is
# what rescues legitimately cryptic titles like "PM-USPY (SSSJKL)".
#
# The generic crawler reads arbitrary provider pages and has no such guarantee,
# so its records must look like schemes.
SCHEME_REGISTRY_SOURCES = {"NSP", "rajasthan"}


def assess(rec: dict) -> tuple[bool, str | None]:
    """Return (servable, reason_if_not).

    `rec` is a plain dict (works for both Scholarship.__dict__ and exported
    JSON), so this can run at export time or against a shipped file.
    """
    name = (rec.get("name") or "").strip()
    source = (rec.get("source_name") or "").strip()

    if not name or len(name) < 6:
        return False, "name missing or too short to identify a scheme"

    if NAV_LABELS.match(name):
        return False, f"page navigation label, not a scheme ({name!r})"

    has_scheme_word = bool(SCHEME_WORD.search(name))

    # Came from a list of schemes, so it is a scheme.
    if source in SCHEME_REGISTRY_SOURCES:
        if not (rec.get("official_url") or rec.get("application_url")):
            return False, "no official or application URL to send a student to"
        return True, None

    # "Ministry of Minority Affairs" is an organisation, not something to apply
    # for. Only reject when nothing scheme-like appears anywhere in the name.
    if ORG_ONLY.match(name) and not has_scheme_word:
        return False, f"organisation name, not a scheme ({name!r})"

    # A very short name with no scheme word is almost always a heading. Longer
    # descriptive names are allowed through even without a keyword, because real
    # schemes like "Opportunity Cost To Parents Of SC Girl Students" exist.
    if not has_scheme_word and len(name.split()) < 5:
        return False, f"no scheme-like wording and too short to judge ({name!r})"

    # Somewhere to send the student is the minimum useful payload.
    if not (rec.get("official_url") or rec.get("application_url")):
        return False, "no official or application URL to send a student to"

    return True, None


def apply(records: list) -> dict:
    """Stamp servable/not_servable_reason on each record. Returns a summary."""
    import collections
    kept, dropped = 0, collections.Counter()
    for r in records:
        d = r if isinstance(r, dict) else r.__dict__
        ok, reason = assess(d)
        if isinstance(r, dict):
            r["servable"] = ok
            r["not_servable_reason"] = reason
        else:
            r.servable = ok
            r.not_servable_reason = reason
        if ok:
            kept += 1
        else:
            dropped[(reason or "").split("(")[0].strip()] += 1
    return {"servable": kept, "withheld": sum(dropped.values()),
            "reasons": dict(dropped)}
