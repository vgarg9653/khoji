"""Buddy4Study — discovery index + detail-page extraction.

Historically this module only reconstructed scholarship *names* from sitemap
slugs, because we treated Buddy4Study's authored copy as off-limits.

The pilot crawl (tools/crawl_b4s_pilot.py) deliberately takes the structured
fields Buddy4Study already embeds in each page's `__NEXT_DATA__` JSON — title,
eligibility, benefits, documents, deadlines, applicable-for — so we can build a
richer catalogue for intent-style matching. Official apply links are preserved
when present; provenance is always marked `source_name: Buddy4Study`.

Robots: www.buddy4study.com allows `/scholarship` (see robots_policy.json).
All fetches still go through Fetcher (cache + per-domain rate limit).
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from datetime import date, datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

import enrich as E
import normalize as N
from schema import Scholarship

SOURCE_NAME = "Buddy4Study"
SITEMAP_INDEX = "https://www.buddy4study.com/sitemap.xml"

# Slug tails that carry no scheme identity.
_JUNK_TAIL = re.compile(r"-(?:scholarship|scholarships|\d{4}-\d{2}|\d{4})$", re.I)
_NON_SCHEME = re.compile(
    r"^(?:page|faq|article|application|about|contact|team|career|login|blog|"
    r"educationloan|scholarships?)$", re.I)

# Words that, alone, mean the slug is a category listing rather than a scheme.
_CATEGORY_ONLY = re.compile(
    r"^(?:scholarships? (?:for|in|by) [a-z ]+|"
    r"(?:ug|pg|school|college|engineering|medical|law|mba|girls|women|sc|st|obc|"
    r"minority|international|abroad|government|private) scholarships?)$", re.I)

# --- pilot targeting ---------------------------------------------------------

_PRIVATE_CSR = re.compile(
    r"foundation|trust|\bcsr\b|reliance|tata|aditya\s*birla|birla\s+capital|"
    r"hdfc|sbi|sbif|axis|icici|kotak|bajaj|mahindra|infosys|wipro|\bhcl\b|"
    r"samsung|google|microsoft|amazon|colgate|jaquar|schneider|siemens|"
    r"vedanta|jindal|ongc|ntpc|gail|yes\s*bank|indusind|pnb|canara|"
    r"buddy4study|keep\s+india|fair\s+and\s+lovely|hindustan\s+unilever|"
    r"larsen|l&t|\blnt\b|tech\s*mahindra|persistent|zoho|freshworks|"
    r"sitaram|jaipur\s+rugs|ullas|edumize|boehringer|abbvie|novartis|"
    r"scholarship\s+program",
    re.I,
)

_SCHOOL_UG = re.compile(
    r"class\s*(?:[9ix]|1[0-2]|ix|x|xi|xii)\b|classes?\s*9|"
    r"school|matric|intermediate|higher\s+secondary|"
    r"undergraduate|\bug\b|graduation|bachelor|first[- ]year|"
    r"\biti\b|diploma|polytechnic|b\.?\s*tech|b\.?\s*sc|b\.?\s*com|"
    r"b\.?\s*a\b|mbbs|bds|nursing|paramedical",
    re.I,
)

_RAJASTHAN = re.compile(
    r"rajasthan|jaipur|jodhpur|udaipur|kota|ajmer|bikaner|alwar|barmer|tonk",
    re.I,
)

_EXCLUDE = re.compile(
    r"\babroad\b|overseas|international\s+master|foreign\s+universit|"
    r"chevening|commonwealth\s+scholarship|fulbright|"
    r"\boxford\b|\bharvard\b|\bcambridge\b|stanford|mit\b|"
    r"\busa\b|\buk\b|canada|australia|germany|france|europe|"
    r"study\s+in\s+(?:the\s+)?(?:uk|usa|us|canada|australia|germany|europe)",
    re.I,
)

_NA_HTML = re.compile(r"^\s*(?:NA|N/?A|None|null|-)\s*$", re.I)


def _slug_to_name(slug: str) -> str | None:
    """Turn 'aicte-pragati-scholarship-2026-27' into 'Aicte Pragati Scholarship'."""
    s = urllib.parse.unquote(slug).strip("/").split("/")[-1]
    if not s or _NON_SCHEME.match(s):
        return None
    s = _JUNK_TAIL.sub("", s)
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 6 or len(s.split()) < 2:
        return None
    if _CATEGORY_ONLY.match(s):
        return None
    return s.title()


def discover_names(fetcher, max_sitemaps: int = 12) -> list[dict]:
    """Return [{'name', 'slug', 'source_url'}] harvested from sitemap slugs."""
    idx = fetcher.get(SITEMAP_INDEX)
    if not idx.ok:
        print(f"  [B4S] sitemap index unavailable ({idx.status or idx.skipped_reason})")
        return []

    sitemaps = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", idx.text)
    sitemaps = [s for s in sitemaps if s.endswith(".xml")][:max_sitemaps]
    print(f"  [B4S] {len(sitemaps)} sitemap files to read (names only)")

    seen: set[str] = set()
    out: list[dict] = []
    for sm in sitemaps:
        r = fetcher.get(sm)
        if not r.ok:
            continue
        urls = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text)
        added = 0
        for u in urls:
            if "/scholarship/" not in u:
                continue
            path = urllib.parse.urlsplit(u).path
            if "/page" in path:
                continue
            name = _slug_to_name(path)
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "slug": path, "source_url": u})
            added += 1
        print(f"    {sm.split('/')[-1]}: +{added} names")
    print(f"  [B4S] {len(out)} distinct scholarship names discovered")
    return out


def pilot_score(name: str) -> tuple[int, list[str]]:
    """Score a discovered name for the private/CSR + school/UG + Rajasthan pilot."""
    tags: list[str] = []
    score = 0
    if _EXCLUDE.search(name):
        return -10, ["exclude_abroad"]
    if _PRIVATE_CSR.search(name):
        score += 5
        tags.append("private_csr")
    if _SCHOOL_UG.search(name):
        score += 3
        tags.append("school_ug")
    if _RAJASTHAN.search(name):
        score += 3
        tags.append("rajasthan")
    if re.search(r"2025|2026", name):
        score += 1
        tags.append("recent_cycle")
    return score, tags


def select_pilot_targets(names: list[dict], limit: int = 280) -> list[dict]:
    """Pick ~limit discovery rows most useful for the pilot."""
    scored: list[tuple[int, dict, list[str]]] = []
    for row in names:
        score, tags = pilot_score(row.get("name") or "")
        if score <= 0:
            continue
        scored.append((score, row, tags))
    scored.sort(key=lambda t: (-t[0], t[1].get("name") or ""))
    out = []
    for score, row, tags in scored[:limit]:
        item = dict(row)
        item["pilot_score"] = score
        item["pilot_tags"] = tags
        out.append(item)
    return out


# --- HTML / JSON helpers -----------------------------------------------------

def html_to_text(html: str | None) -> str:
    if not html or _NA_HTML.match(str(html).strip()):
        return ""
    soup = BeautifulSoup(str(html), "lxml")
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _none_if_blank(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if not s or _NA_HTML.match(s):
        return None
    return s


def _parse_date(s: str | None) -> str | None:
    if not s or str(s).lower() in {"none", "null", "na"}:
        return None
    s = str(s).strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _deadline_status(deadline: str | None, today: date | None = None) -> str:
    today = today or date.today()
    if not deadline:
        return "unknown"
    try:
        d = datetime.strptime(deadline, "%Y-%m-%d").date()
    except ValueError:
        return "unknown"
    return "active" if d >= today else "expired"


def _shorten(text: str | None, n: int = 280) -> str | None:
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    cut = text[: n - 1].rsplit(" ", 1)[0]
    return cut + "…"


def _stable_id(*parts: str) -> str:
    raw = "|".join(p for p in parts if p)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"b4s-{h}"


def _official_url(links: list[dict] | None, fallback: str | None = None) -> str | None:
    for link in links or []:
        url = (link.get("url") or "").strip()
        if not url or "buddy4study.com" in url.lower():
            continue
        type_name = ((link.get("type") or {}).get("name") or "").lower()
        if "apply" in type_name or "official" in type_name or "website" in type_name:
            return url
    for link in links or []:
        url = (link.get("url") or "").strip()
        if url and "buddy4study.com" not in url.lower():
            return url
    return fallback


def _rules_summary(rules: list[dict] | None) -> list[dict]:
    out = []
    for rule in rules or []:
        rt = rule.get("ruletype") or {}
        if isinstance(rt, dict):
            rtype = rt.get("ruleType")
        else:
            rtype = None
        val = rule.get("ruleValue")
        if not rtype and not val:
            continue
        status = rule.get("status")
        if status in (0, "0", False):
            continue
        out.append({"type": rtype, "value": val})
    return out


def _infer_structured(rec: dict) -> None:
    """Fill controlled fields from the rich text blobs. Never invent values."""
    blob = "\n\n".join(
        filter(
            None,
            [
                rec.get("name"),
                rec.get("applicable_for"),
                rec.get("description_long"),
                rec.get("eligibility_text"),
                rec.get("benefits_text"),
                rec.get("more_details_text"),
                rec.get("purpose_award"),
            ],
        )
    )
    docs_blob = rec.get("documents_text") or ""

    levels = N.detect_levels(blob)
    if levels:
        rec["education_levels"] = levels

    cats = N.detect_categories(blob)
    if cats:
        rec["categories"] = cats

    states = N.detect_states(blob)
    if states:
        rec["states"] = states
    elif re.search(r"\bacross india\b|\ball india\b|\bindian (?:citizen|national|student)",
                   blob, re.I):
        rec["states"] = ["all"]

    gender = N.detect_gender(blob)
    if gender:
        rec["gender"] = gender

    docs, _ = N.detect_documents(docs_blob or blob)
    if docs:
        rec["documents_required"] = docs

    # Class range + income + marks via the shared enricher on a throwaway record.
    s = Scholarship(name=rec.get("name"), description_short=rec.get("description_short"))
    E.enrich_from_text(s, blob, source_url=rec.get("source_url"))
    if s.class_min is not None:
        rec["class_min"] = s.class_min
    if s.class_max is not None:
        rec["class_max"] = s.class_max
    if s.income_ceiling_inr is not None:
        rec["income_ceiling_inr"] = s.income_ceiling_inr
        rec["income_evidence"] = s.income_evidence
    if s.min_marks_percent is not None:
        rec["min_marks_percent"] = s.min_marks_percent
    if s.benefit_amount_min_inr is not None:
        rec["benefit_amount_min_inr"] = s.benefit_amount_min_inr
    if s.benefit_amount_max_inr is not None:
        rec["benefit_amount_max_inr"] = s.benefit_amount_max_inr
    if s.benefit_amount_text:
        rec["benefit_amount_text"] = s.benefit_amount_text
    elif rec.get("purpose_award"):
        rec["benefit_amount_text"] = rec["purpose_award"]
        lo, hi = N.parse_amounts(rec["purpose_award"])
        if lo is not None:
            rec["benefit_amount_min_inr"] = lo
        if hi is not None:
            rec["benefit_amount_max_inr"] = hi

    # Course types from levels vocabulary used by the bot.
    course = []
    for lvl in rec.get("education_levels") or []:
        if lvl in {"school", "ITI", "diploma", "UG", "PG", "PhD", "professional"}:
            course.append(lvl)
    if course:
        rec["course_types"] = sorted(set(course))

    # Provider type heuristic for the pilot review file.
    prov = (rec.get("provider_name") or "") + " " + (rec.get("name") or "")
    if re.search(r"ministry|government of|dept\.|department of|nsp\b|state\s+gov",
                 prov, re.I):
        rec["provider_type"] = "state_govt" if states and "all" not in states else "central_govt"
        if re.search(r"ministry|government of india|national scholarship|nsp\b",
                     prov, re.I):
            rec["provider_type"] = "central_govt"
    elif re.search(r"foundation|trust|limited|ltd|pvt|corp|bank|group", prov, re.I):
        rec["provider_type"] = "private"
    elif "private_csr" in (rec.get("pilot_tags") or []):
        rec["provider_type"] = "private"


def _base_record(*, source_url: str, pilot_tags: list[str] | None = None) -> dict:
    return {
        "id": None,
        "name": None,
        "slug": None,
        "bsid": None,
        "scholarship_id": None,
        "provider_name": None,
        "provider_type": None,
        "administering_body": None,
        "applicable_for": None,
        "purpose_award": None,
        "description_short": None,
        "description_long": None,
        "eligibility_text": None,
        "benefits_text": None,
        "documents_text": None,
        "how_to_apply_text": None,
        "important_dates_text": None,
        "selection_criteria_text": None,
        "more_details_text": None,
        "education_levels": [],
        "course_types": [],
        "class_min": None,
        "class_max": None,
        "categories": [],
        "gender": None,
        "states": [],
        "income_ceiling_inr": None,
        "income_evidence": None,
        "min_marks_percent": None,
        "benefit_amount_min_inr": None,
        "benefit_amount_max_inr": None,
        "benefit_amount_text": None,
        "documents_required": [],
        "application_mode": "provider_website",
        "application_url": None,
        "application_start_date": None,
        "application_deadline": None,
        "official_url": None,
        "status": "unknown",
        "confidence": "medium",
        "source_name": SOURCE_NAME,
        "source_url": source_url,
        "source_urls": [source_url],
        "page_format": None,
        "pilot_tags": list(pilot_tags or []),
        "rules": [],
        "extraction_date": date.today().isoformat(),
        "intent_blob": None,  # concatenated text for later intent matching
    }


def _finalize(rec: dict) -> dict:
    _infer_structured(rec)
    parts = [
        rec.get("name"),
        rec.get("applicable_for"),
        rec.get("purpose_award"),
        rec.get("description_long"),
        rec.get("eligibility_text"),
        rec.get("benefits_text"),
        rec.get("more_details_text"),
        rec.get("selection_criteria_text"),
        rec.get("documents_text"),
    ]
    rec["intent_blob"] = "\n\n".join(p for p in parts if p)
    if not rec.get("description_short"):
        rec["description_short"] = _shorten(
            rec.get("description_long") or rec.get("eligibility_text") or rec.get("applicable_for")
        )
    if not rec.get("id"):
        rec["id"] = _stable_id(rec.get("bsid") or "", rec.get("slug") or "", rec.get("name") or "")
    rec["status"] = _deadline_status(rec.get("application_deadline"))
    # Drop empty lists that stayed unused? Keep for schema stability.
    return rec


def _record_from_brand_item(
    item: dict,
    *,
    source_url: str,
    about_program: str | None,
    brand_name: str | None,
    pilot_tags: list[str] | None = None,
) -> dict:
    rec = _base_record(source_url=source_url, pilot_tags=pilot_tags)
    rec["page_format"] = "brand"
    rec["name"] = _none_if_blank(item.get("title")) or brand_name
    rec["slug"] = _none_if_blank(item.get("slug"))
    rec["bsid"] = _none_if_blank(item.get("bsid"))
    rec["scholarship_id"] = str(item.get("scholarshipId")) if item.get("scholarshipId") else None
    rec["applicable_for"] = _none_if_blank(item.get("applicableFor"))
    rec["purpose_award"] = _none_if_blank(item.get("purposeAward"))
    rec["eligibility_text"] = html_to_text(item.get("eligibility")) or None
    rec["benefits_text"] = html_to_text(item.get("benefits")) or None
    rec["documents_text"] = html_to_text(item.get("requiredDocument")) or None
    rec["how_to_apply_text"] = html_to_text(item.get("howToApply")) or None
    rec["important_dates_text"] = html_to_text(item.get("importantDates")) or None
    rec["selection_criteria_text"] = html_to_text(item.get("selectionCriteria")) or None
    offered = html_to_text(item.get("offeredBy"))
    if offered and offered.upper() != "NA":
        rec["provider_name"] = offered
    elif brand_name:
        rec["provider_name"] = re.sub(r"\s+scholarship.*$", "", brand_name, flags=re.I).strip() or brand_name
    about = html_to_text(about_program) if about_program else ""
    rec["description_long"] = about or rec["eligibility_text"]
    rec["application_deadline"] = _parse_date(item.get("deadline"))
    rec["application_start_date"] = _parse_date(item.get("applicationLaunchDate"))
    apply = _none_if_blank(item.get("applyLink"))
    rec["application_url"] = apply
    if apply and "buddy4study.com" not in apply.lower():
        rec["official_url"] = apply
    if rec.get("scholarship_id") or rec.get("bsid"):
        rec["id"] = _stable_id(rec.get("scholarship_id") or "", rec.get("bsid") or "")
    return _finalize(rec)


def _record_from_standard(
    sch: dict,
    *,
    source_url: str,
    pilot_tags: list[str] | None = None,
) -> dict:
    rec = _base_record(source_url=source_url, pilot_tags=pilot_tags)
    rec["page_format"] = "standard"
    multi = (sch.get("scholarshipMultilinguals") or [{}])[0] or {}
    body = (sch.get("scholarshipBodyMultilinguals") or [{}])[0] or {}
    meta = (sch.get("scholarshipMetaTags") or [{}])[0] or {}
    providers = sch.get("scholarshipProviders") or []

    rec["name"] = (
        _none_if_blank(multi.get("title"))
        or _none_if_blank(sch.get("scholarshipName"))
    )
    rec["slug"] = _none_if_blank(sch.get("slug"))
    rec["bsid"] = _none_if_blank(sch.get("bsid"))
    rec["scholarship_id"] = str(sch.get("id")) if sch.get("id") else None
    rec["applicable_for"] = _none_if_blank(multi.get("applicableFor"))
    rec["purpose_award"] = _none_if_blank(multi.get("purposeAward"))
    if providers:
        rec["provider_name"] = _none_if_blank(providers[0].get("providerName"))
        rec["administering_body"] = rec["provider_name"]
    if not rec["provider_name"]:
        rec["provider_name"] = _none_if_blank(multi.get("providerName"))

    rec["description_long"] = html_to_text(body.get("introduction")) or None
    rec["eligibility_text"] = html_to_text(body.get("eligibility")) or None
    rec["benefits_text"] = html_to_text(body.get("benifit") or body.get("benefit")) or None
    rec["documents_text"] = html_to_text(body.get("required_document")) or None
    rec["how_to_apply_text"] = html_to_text(body.get("howToApply")) or None
    rec["important_dates_text"] = html_to_text(body.get("importantDates")) or None
    rec["selection_criteria_text"] = html_to_text(body.get("selectionCriteria")) or None
    rec["more_details_text"] = html_to_text(body.get("moreDetails")) or None
    rec["description_short"] = _shorten(
        _none_if_blank(meta.get("description")) or rec["description_long"]
    )

    rec["application_deadline"] = _parse_date(
        sch.get("deadlineDate") or sch.get("onlineDeadline") or sch.get("offlineDeadline")
    )
    rec["application_start_date"] = _parse_date(
        sch.get("applicationLaunchDate") or sch.get("announcementDate")
    )
    links = sch.get("scholarshipWebsiteLinks") or []
    rec["official_url"] = _official_url(links)
    # Prefer non-B4S apply link; else keep B4S apply if that is all they offer.
    apply = None
    for link in links:
        type_name = ((link.get("type") or {}).get("name") or "").lower()
        url = (link.get("url") or "").strip()
        if url and "apply" in type_name:
            apply = url
            break
    rec["application_url"] = apply or rec["official_url"] or source_url
    if apply and "buddy4study.com" not in apply.lower():
        rec["application_mode"] = (
            "NSP" if "scholarships.gov.in" in apply.lower() else "provider_website"
        )

    rec["rules"] = _rules_summary(sch.get("scholarshipRules"))
    # Family income structured list when present.
    for inc in sch.get("scholarshipFamilyIncomes") or []:
        # Keep raw; enricher will still try the prose.
        if isinstance(inc, dict):
            rec.setdefault("family_income_raw", []).append(inc)

    if rec.get("scholarship_id") or rec.get("bsid"):
        rec["id"] = _stable_id(rec.get("scholarship_id") or "", rec.get("bsid") or "")
    return _finalize(rec)


def extract_next_data(html: str) -> dict | None:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parse_scholarship_page(
    html: str,
    source_url: str,
    *,
    pilot_tags: list[str] | None = None,
) -> list[dict]:
    """Parse one Buddy4Study scholarship URL into one or more records."""
    data = extract_next_data(html)
    if not data:
        return []
    wrap = (
        data.get("props", {})
        .get("pageProps", {})
        .get("scholarship")
    )
    if not isinstance(wrap, dict):
        return []

    records: list[dict] = []
    brand = wrap.get("brandPage")
    sch = wrap.get("scholarship")

    if isinstance(brand, dict) and (brand.get("scholarships") or brand.get("attachedScholarships")):
        about = brand.get("aboutProgram")
        brand_name = brand.get("programName") or brand.get("name")
        # Prefer the full scholarships list; fall back to attached.
        items = brand.get("scholarships") or brand.get("attachedScholarships") or []
        seen_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("scholarshipId") or item.get("bsid") or item.get("slug") or "")
            if key and key in seen_ids:
                continue
            if key:
                seen_ids.add(key)
            records.append(
                _record_from_brand_item(
                    item,
                    source_url=source_url,
                    about_program=about,
                    brand_name=brand_name,
                    pilot_tags=pilot_tags,
                )
            )
        return records

    if isinstance(sch, dict) and (sch.get("scholarshipName") or sch.get("slug")):
        records.append(
            _record_from_standard(sch, source_url=source_url, pilot_tags=pilot_tags)
        )
        return records

    return []


def is_pilot_relevant(rec: dict) -> bool:
    """Keep private/CSR, school/UG/ITI/diploma, or Rajasthan-tagged rows."""
    tags = set(rec.get("pilot_tags") or [])
    if "private_csr" in tags or "rajasthan" in tags:
        return True
    levels = set(rec.get("education_levels") or [])
    if levels & {"school", "ITI", "diploma", "UG", "professional"}:
        return True
    blob = (rec.get("applicable_for") or "") + " " + (rec.get("name") or "")
    if _SCHOOL_UG.search(blob):
        return True
    if _RAJASTHAN.search(blob):
        return True
    return False


def crawl_pilot(
    fetcher,
    names: list[dict],
    *,
    limit: int = 280,
    keep_expired: bool = True,
) -> dict[str, Any]:
    """Fetch and parse a pilot subset. Returns a review payload (not merged)."""
    targets = select_pilot_targets(names, limit=limit)
    print(f"  [B4S] pilot targets: {len(targets)} of {len(names)} discovered names")

    records: list[dict] = []
    errors: list[dict] = []
    seen_ids: set[str] = set()

    for i, target in enumerate(targets, 1):
        url = target["source_url"]
        print(f"  [{i}/{len(targets)}] {target.get('name', '')[:70]}")
        r = fetcher.get(url)
        if not r.ok:
            errors.append({
                "url": url,
                "name": target.get("name"),
                "status": r.status,
                "reason": r.skipped_reason,
            })
            continue
        try:
            parsed = parse_scholarship_page(
                r.text, url, pilot_tags=target.get("pilot_tags") or []
            )
        except Exception as exc:  # noqa: BLE001 — keep crawl going
            errors.append({"url": url, "name": target.get("name"), "reason": str(exc)})
            continue
        if not parsed:
            errors.append({
                "url": url,
                "name": target.get("name"),
                "reason": "no_next_data_or_empty",
            })
            continue
        for rec in parsed:
            if not is_pilot_relevant(rec):
                continue
            if not keep_expired and rec.get("status") == "expired":
                continue
            rid = rec.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            # Carry discovery tags forward if parser didn't.
            for t in target.get("pilot_tags") or []:
                if t not in rec["pilot_tags"]:
                    rec["pilot_tags"].append(t)
            records.append(rec)

    records.sort(key=lambda x: (
        0 if x.get("status") == "active" else 1,
        0 if "private_csr" in (x.get("pilot_tags") or []) else 1,
        x.get("name") or "",
    ))

    return {
        "meta": {
            "source": SOURCE_NAME,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "discovered_names": len(names),
            "targets_fetched": len(targets),
            "records": len(records),
            "errors": len(errors),
            "note": (
                "Review file only — not merged into bot_matching.json. "
                "Provenance is Buddy4Study page JSON (__NEXT_DATA__)."
            ),
        },
        "scholarships": records,
        "errors": errors,
    }
