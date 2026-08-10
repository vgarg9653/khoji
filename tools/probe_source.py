"""Reconnaissance: what does a source actually serve, and is it static or JS?

Run this BEFORE writing a parser for a new source — it is how the existing
ones were decided. Adding a state portal (Bihar, UP, Madhya Pradesh) starts
here: it tells you whether the scheme list is in the HTML or drawn by
JavaScript, which decides whether you need Playwright.

Run before writing parsers. Reports HTTP status, byte size, link/table counts and
whether the scholarship content appears in the static HTML at all — which tells
us exactly which sources need Playwright.
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from bs4 import BeautifulSoup                       # noqa: E402

from fetcher import Fetcher                         # noqa: E402

CANDIDATES = [
    ("NSP", "https://scholarships.gov.in/"),
    ("NSP", "https://scholarships.gov.in/allSchemes"),
    ("NSP", "https://scholarships.gov.in/schemeList"),
    ("NSP", "https://scholarships.gov.in/centralSchemes"),
    ("B4S", "https://www.buddy4study.com/scholarships"),
    ("B4S", "https://www.buddy4study.com/sitemap.xml"),
    ("AICTE", "https://www.aicte.gov.in/schemes/students-development-schemes"),
    ("UGC", "https://www.ugc.gov.in/Scholarship"),
    ("MoMA", "https://minorityaffairs.gov.in/"),
    ("MoTA", "https://tribal.nic.in/Scholarship.aspx"),
    ("MoSJE", "https://socialjustice.gov.in/schemes/33"),
    ("INSPIRE", "https://online-inspire.gov.in/"),
    ("KSB", "https://ksb.gov.in/pm-scholarship.htm"),
    ("MahaDBT", "https://mahadbt.maharashtra.gov.in/Scheme/Scheme"),
    ("Karnataka", "https://ssp.postmatric.karnataka.gov.in/"),
    ("Telangana", "https://telanganaepass.cgg.gov.in/"),
    ("Kerala", "https://egrantz.kerala.gov.in/"),
    ("Odisha", "https://scholarship.odisha.gov.in/"),
    ("Rajasthan", "https://sje.rajasthan.gov.in/Scholarship"),
    ("TataTrusts", "https://www.tatatrusts.org/our-work/individual-grants-programme"),
    ("Reliance", "https://www.reliancefoundation.org/scholarships"),
    ("SitaramJindal", "https://www.sitaramjindalfoundation.org/scholarships-for-students-in-india.php"),
    ("AdityaBirla", "https://www.adityabirlascholars.net/"),
    ("Santoor", "https://www.santoorscholarship.com/"),
    ("FFE", "https://www.northsouth.org/"),
    ("ONGC", "https://ongcindia.com/web/eng/csr/scholarship"),
    ("Legrand", "https://www.legrand.co.in/scholarship"),
    ("JSPL", "https://www.jindalsteelpower.com/foundation.html"),
]

KEYWORDS = re.compile(
    r"scholarship|scheme|eligib|stipend|fellowship|merit|scholar", re.I)


def main() -> None:
    f = Fetcher()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"{'SOURCE':<14}{'STATUS':>8}{'KB':>7}{'LINKS':>7}{'TBL':>5}{'KW':>6}  URL")
    print("-" * 118)
    for name, url in CANDIDATES:
        if only and only.lower() not in name.lower():
            continue
        r = f.get(url)
        if r.blocked:
            print(f"{name:<14}{'SKIP':>8}{'':>7}{'':>7}{'':>5}{'':>6}  {url}  <-- {r.skipped_reason}")
            continue
        if not r.ok:
            print(f"{name:<14}{str(r.status):>8}{'':>7}{'':>7}{'':>5}{'':>6}  {url}")
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        text = soup.get_text(" ", strip=True)
        kw = len(KEYWORDS.findall(text))
        cached = "*" if r.from_cache else " "
        print(f"{name:<14}{str(r.status):>7}{cached}{len(r.text)//1024:>7}"
              f"{len(soup.find_all('a')):>7}{len(soup.find_all('table')):>5}{kw:>6}  {url}")
    print("\n* = served from cache")
    print(f"stats: {f.stats}")
    f.close()


if __name__ == "__main__":
    main()
