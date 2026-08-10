"""Buddy4Study — DISCOVERY INDEX ONLY.

Constraint this module exists to enforce: we never take Buddy4Study's own
description of a scholarship. Their aggregated copy is their work product.

So we take the least we can while still learning what exists — scholarship
NAMES, reconstructed from the URL slugs in their public sitemap. That means we
fetch a handful of sitemap files rather than 1,200+ content pages: lighter on
their servers than a human browsing the site, and it copies nothing but titles,
which are facts about the world rather than authored content.

Everything downstream (eligibility, amounts, deadlines) is then fetched from the
scheme's own official provider page, never from here.
"""

from __future__ import annotations

import re
import urllib.parse

SOURCE_NAME = "Buddy4Study(discovery)"
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
            # Skip their paginated category listings.
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
