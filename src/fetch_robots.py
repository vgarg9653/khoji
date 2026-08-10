"""Phase 0 — robots.txt reconnaissance and crawl-policy generation.

Fetches robots.txt from every target domain, caches the raw text under
data/raw/robots/, and emits data/raw/robots/robots_policy.json — the single
source of truth the crawler consults before touching any URL.

Design notes:
  * Stdlib only, so this runs before any dependency install.
  * Many Indian government sites serve an HTML "page not found" body with a
    200 status for /robots.txt. Treating that as a rules file would be wrong
    in both directions, so we sniff for HTML and reclassify it as absent.
  * We FAIL CLOSED: if robots.txt cannot be retrieved at all (timeout, TLS
    failure, WAF 403), the domain is marked do-not-crawl. An unreadable
    robots.txt is not permission.
  * `curl` is used as a fallback transport because several of these hosts
    negotiate TLS in ways Python's urllib rejects outright.
"""

from __future__ import annotations

import concurrent.futures as cf
import csv
import json
import pathlib
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from urllib.robotparser import RobotFileParser

UA = (
    "Khoji.AIResearchBot/0.1 (student scholarship discovery research; "
    "non-commercial; contact: khoji-crawler@example.org)"
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROBOTS_DIR = ROOT / "data" / "raw" / "robots"
DOMAINS_FILE = ROBOTS_DIR / "domains.txt"

PROBE_PATHS = ["/", "/scholarship", "/scholarships", "/schemes", "/search", "/en"]
TIMEOUT = 40

# Crawl decisions, in order of decreasing freedom.
ALLOW_NO_ROBOTS = "ALLOW_NO_ROBOTS"        # no robots.txt served -> nothing disallowed
ALLOW_FULL = "ALLOW_FULL"                  # robots.txt present, no relevant restrictions
ALLOW_WITH_EXCLUSIONS = "ALLOW_WITH_EXCLUSIONS"
ALLOW_ROBOTS_403 = "ALLOW_ROBOTS_403"      # robots.txt 403s but content serves our UA
BLOCKED_ROBOTS = "BLOCKED_ROBOTS"          # blanket Disallow: /
BLOCKED_WAF = "BLOCKED_WAF"                # server refuses our UA on content too
UNREACHABLE = "UNREACHABLE"                # cannot verify -> fail closed

CRAWLABLE = {ALLOW_NO_ROBOTS, ALLOW_FULL, ALLOW_WITH_EXCLUSIONS, ALLOW_ROBOTS_403}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_HTML_RE = re.compile(r"<\s*(!doctype|html|head|body|script|meta)\b", re.I)


def looks_like_html(body: str) -> bool:
    """A robots.txt that is actually a rendered web page is a soft 404."""
    return bool(_HTML_RE.search(body[:2000]))


def load_domains() -> list[tuple[str, str, str]]:
    rows, seen = [], set()
    for line in DOMAINS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        group, domain, note = (line.split("|", 2) + ["", ""])[:3]
        if not domain or domain in seen:
            continue
        seen.add(domain)
        rows.append((group, domain, note))
    return rows


def _fetch_urllib(url: str) -> tuple[object, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return f"ERR:{type(e).__name__}", ""


def _fetch_curl(url: str) -> tuple[object, str]:
    """Fallback transport: curl tolerates TLS quirks urllib refuses."""
    if not shutil.which("curl"):
        return "ERR:NoCurl", ""
    try:
        p = subprocess.run(
            ["curl", "-skL", "-A", UA, "--max-time", str(TIMEOUT),
             "-w", "\n__STATUS__%{http_code}", url],
            capture_output=True, text=True, timeout=TIMEOUT + 15,
        )
    except subprocess.TimeoutExpired:
        return "ERR:Timeout", ""
    out = p.stdout
    m = re.search(r"\n__STATUS__(\d+)$", out)
    if not m:
        return "ERR:CurlNoStatus", ""
    code = int(m.group(1))
    return (code if code else "ERR:ConnFail"), out[: m.start()]


def fetch_robots(domain: str) -> tuple[object, str, str]:
    """Return (status, body, transport). Tries urllib then curl, https then http."""
    for transport, fn in (("urllib", _fetch_urllib), ("curl", _fetch_curl)):
        for scheme in ("https", "http"):
            status, body = fn(f"{scheme}://{domain}/robots.txt")
            if status == 200 and body.strip():
                return status, body, f"{transport}/{scheme}"
            if status in (403, 404):
                return status, body, f"{transport}/{scheme}"
    return status, body, "none"


def blanket_disallow(body: str) -> bool:
    """True if the User-agent: * group contains a bare `Disallow: /`."""
    in_star = False
    for ln in body.splitlines():
        s = ln.split("#", 1)[0].strip().lower()
        if s.startswith("user-agent:"):
            in_star = s.split(":", 1)[1].strip() == "*"
        elif in_star and s.startswith("disallow:"):
            if s.split(":", 1)[1].strip() == "/":
                return True
    return False


def probe(group: str, domain: str, note: str) -> dict:
    status, body, transport = fetch_robots(domain)
    r: dict = {
        "group": group, "domain": domain, "note": note,
        "status": status, "transport": transport,
        "crawl_delay": None, "sitemaps": [], "disallowed_paths": [],
        "allowed": {}, "decision": None, "reason": None,
    }

    if status == 200 and body.strip() and not looks_like_html(body):
        (ROBOTS_DIR / f"{domain}.robots.txt").write_text(body, encoding="utf-8")
        rp = RobotFileParser()
        rp.parse(body.splitlines())
        for p in PROBE_PATHS:
            r["allowed"][p] = rp.can_fetch(UA, f"https://{domain}{p}")
        try:
            r["crawl_delay"] = rp.crawl_delay(UA) or rp.crawl_delay("*")
        except Exception:
            pass
        r["sitemaps"] = [ln.split(":", 1)[1].strip()
                         for ln in body.splitlines()
                         if ln.lower().startswith("sitemap:")][:10]
        r["disallowed_paths"] = [
            ln.split(":", 1)[1].strip()
            for ln in body.splitlines()
            if ln.split("#", 1)[0].strip().lower().startswith("disallow:")
            and ln.split(":", 1)[1].strip()
        ]
        if blanket_disallow(body):
            r["decision"], r["reason"] = BLOCKED_ROBOTS, "User-agent: * -> Disallow: /"
        elif r["disallowed_paths"]:
            r["decision"] = ALLOW_WITH_EXCLUSIONS
            r["reason"] = f"{len(r['disallowed_paths'])} disallowed path prefix(es)"
        else:
            r["decision"], r["reason"] = ALLOW_FULL, "robots.txt present, no restrictions"

    elif status == 404 or (status == 200 and looks_like_html(body)):
        r["decision"] = ALLOW_NO_ROBOTS
        r["reason"] = ("no robots.txt (404)" if status == 404
                       else "soft-404: robots.txt served HTML, treated as absent")
        r["allowed"] = {p: True for p in PROBE_PATHS}

    elif status == 403:
        # RFC 9309 s2.3.1.4 treats a 4xx robots.txt as "unavailable", meaning no
        # restrictions are known. But a 403 specifically can also be a WAF telling
        # us to go away. Disambiguate by asking for the homepage with the same
        # honest UA: if content serves, the 403 was a path rule on /robots.txt,
        # not a bot ban. We never spoof a browser UA to change this answer.
        home_status, _ = _fetch_curl(f"https://{domain}/")
        r["content_probe_status"] = home_status
        if home_status == 200:
            r["decision"] = ALLOW_ROBOTS_403
            r["reason"] = ("robots.txt 403s but homepage serves 200 to our UA; "
                           "RFC 9309 treats 4xx robots.txt as unavailable")
            r["allowed"] = {p: True for p in PROBE_PATHS}
        else:
            r["decision"] = BLOCKED_WAF
            r["reason"] = (f"robots.txt 403 and homepage returned {home_status}; "
                           "server refuses our UA outright")
            r["allowed"] = {p: False for p in PROBE_PATHS}

    else:
        r["decision"] = UNREACHABLE
        r["reason"] = f"could not retrieve robots.txt ({status}); failing closed"
        r["allowed"] = {p: False for p in PROBE_PATHS}

    r["crawlable"] = r["decision"] in CRAWLABLE
    return r


def main() -> None:
    domains = load_domains()
    print(f"Probing robots.txt for {len(domains)} domains (fail-closed)...\n")
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda a: probe(*a), domains))
    results.sort(key=lambda r: (r["group"], r["domain"]))

    policy = {
        "user_agent": UA,
        "min_seconds_between_requests_per_domain": 3.0,
        "jitter_seconds": [0.5, 2.0],
        "generated_by": "src/fetch_robots.py",
        "domains": {r["domain"]: r for r in results},
    }
    (ROBOTS_DIR / "robots_policy.json").write_text(
        json.dumps(policy, indent=2), encoding="utf-8")

    with (ROBOTS_DIR / "robots_report.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "domain", "status", "decision", "crawlable",
                    "crawl_delay", "n_disallow", "n_sitemaps", "reason", "note"])
        for r in results:
            w.writerow([r["group"], r["domain"], r["status"], r["decision"],
                        r["crawlable"], r["crawl_delay"] or "",
                        len(r["disallowed_paths"]), len(r["sitemaps"]),
                        r["reason"], r["note"]])

    for grp in sorted({r["group"] for r in results}):
        print(f"\n=== {grp.upper()} ===")
        print(f"{'DOMAIN':<44}{'HTTP':>6}  {'DECISION':<22}{'DELAY':>6}{'MAPS':>6}")
        print("-" * 86)
        for r in (x for x in results if x["group"] == grp):
            mark = " " if r["crawlable"] else "x"
            print(f"{mark}{r['domain']:<43}{str(r['status']):>6}  "
                  f"{r['decision']:<22}{str(r['crawl_delay'] or '-'):>6}"
                  f"{len(r['sitemaps']):>6}")

    n_ok = sum(1 for r in results if r["crawlable"])
    print(f"\n{n_ok}/{len(results)} domains crawlable. "
          f"Policy -> {ROBOTS_DIR/'robots_policy.json'}")
    for d in (BLOCKED_ROBOTS, BLOCKED_WAF, UNREACHABLE):
        bad = [r["domain"] for r in results if r["decision"] == d]
        if bad:
            print(f"  {d} ({len(bad)}): {', '.join(bad)}")


if __name__ == "__main__":
    main()
