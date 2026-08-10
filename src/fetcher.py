"""Polite HTTP layer for the Khoji.AI crawl.

Every outbound request in this project goes through Fetcher. It enforces, in
order: the robots policy produced by fetch_robots.py, a per-domain rate limit,
and an on-disk cache so development never re-fetches a page we already have.

Nothing here logs in, submits forms, or sends cookies. It reads public pages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import random
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from urllib.robotparser import RobotFileParser

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROBOTS_DIR = ROOT / "data" / "raw" / "robots"
HTML_DIR = ROOT / "data" / "raw" / "html"
LOG_DIR = ROOT / "data" / "logs"
POLICY_FILE = ROBOTS_DIR / "robots_policy.json"

UA = (
    "Khoji.AIResearchBot/0.1 (student scholarship discovery research; "
    "non-commercial; contact: khoji-crawler@example.org)"
)

MIN_INTERVAL = 3.0          # seconds between requests to the same domain
JITTER = (0.5, 2.0)         # added on top, so we never hit a fixed cadence
TIMEOUT = 45
MAX_BYTES = 8 * 1024 * 1024

CRAWLABLE_DECISIONS = {
    "ALLOW_NO_ROBOTS", "ALLOW_FULL", "ALLOW_WITH_EXCLUSIONS", "ALLOW_ROBOTS_403",
}

log = logging.getLogger("fetcher")


class _LegacyTLSAdapter(requests.adapters.HTTPAdapter):
    """Talk to old government web servers.

    Several state portals (scholarship.up.gov.in among them) run TLS stacks that
    OpenSSL 3 refuses by default: legacy renegotiation is disabled and the
    minimum security level rejects their key sizes. Without this, those hosts
    are simply unreachable and their schemes silently vanish from the dataset.

    This loosens transport-level strictness only. It does not bypass any
    authentication or access control — the pages fetched are public either way.
    """

    _OP_LEGACY_RENEG = 0x4          # SSL_OP_LEGACY_SERVER_CONNECT

    def _ctx(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.options |= self._OP_LEGACY_RENEG
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            pass
        return ctx

    def init_poolmanager(self, *a, **kw):
        kw["ssl_context"] = self._ctx()
        return super().init_poolmanager(*a, **kw)

    def proxy_manager_for(self, *a, **kw):
        kw["ssl_context"] = self._ctx()
        return super().proxy_manager_for(*a, **kw)


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | str | None = None
    text: str = ""
    from_cache: bool = False
    skipped_reason: str | None = None
    final_url: str | None = None
    cache_path: str | None = None
    content_type: str | None = None
    fetched_at: str | None = None

    @property
    def blocked(self) -> bool:
        return self.skipped_reason is not None


@dataclass
class _DomainState:
    last_request: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


class Fetcher:
    """Robots-aware, rate-limited, caching HTTP client."""

    def __init__(self, cache_dir: pathlib.Path = HTML_DIR, offline: bool = False,
                 force_refresh: bool = False):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.force_refresh = force_refresh

        self.policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        self.domains: dict = self.policy["domains"]
        self._robots: dict[str, RobotFileParser | None] = {}
        self._state: dict[str, _DomainState] = {}
        self._state_lock = threading.Lock()

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        })
        self.session.mount("https://", _LegacyTLSAdapter())

        self.stats = {"fetched": 0, "cached": 0, "skipped_robots": 0,
                      "skipped_policy": 0, "errors": 0}
        self._skip_log = (LOG_DIR / "robots_skips.jsonl").open("a", encoding="utf-8")
        # Domains are crawled concurrently, but the per-domain rate limit is
        # enforced by _DomainState.lock, so no host ever sees a burst.
        self._io_lock = threading.Lock()

    # ---------- robots ----------

    def _domain_state(self, host: str) -> _DomainState:
        with self._state_lock:
            return self._state.setdefault(host, _DomainState())

    def _robots_for(self, host: str) -> RobotFileParser | None:
        """Parsed robots.txt from the cached body, or None if the domain has none."""
        if host in self._robots:
            return self._robots[host]
        path = ROBOTS_DIR / f"{host}.robots.txt"
        rp = None
        if path.exists():
            rp = RobotFileParser()
            rp.parse(path.read_text(encoding="utf-8", errors="replace").splitlines())
        self._robots[host] = rp
        return rp

    def allowed(self, url: str) -> tuple[bool, str | None]:
        """Two gates: the domain-level policy decision, then the path-level rule."""
        host = urllib.parse.urlsplit(url).netloc.lower()
        entry = self.domains.get(host)
        if entry is None:
            return False, f"domain {host} not in robots policy (unvetted)"
        if entry["decision"] not in CRAWLABLE_DECISIONS:
            return False, f"domain policy = {entry['decision']}: {entry['reason']}"
        rp = self._robots_for(host)
        if rp is not None and not rp.can_fetch(UA, url):
            return False, "path disallowed by robots.txt"
        return True, None

    def _log_skip(self, url: str, reason: str) -> None:
        with self._io_lock:
            self._skip_log.write(json.dumps({
                "url": url, "reason": reason,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }) + "\n")
            self._skip_log.flush()
        log.info("SKIP %s -- %s", url, reason)

    def _bump(self, key: str) -> None:
        with self._io_lock:
            self.stats[key] += 1

    # ---------- cache ----------

    def cache_path_for(self, url: str) -> pathlib.Path:
        host = urllib.parse.urlsplit(url).netloc.lower() or "unknown"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        d = self.cache_dir / host
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{digest}.html"

    def _meta_path(self, p: pathlib.Path) -> pathlib.Path:
        return p.with_suffix(".meta.json")

    # ---------- rate limit ----------

    def _throttle(self, host: str) -> None:
        st = self._domain_state(host)
        with st.lock:
            wait = MIN_INTERVAL - (time.monotonic() - st.last_request)
            wait = max(0.0, wait) + random.uniform(*JITTER)
            if wait > 0:
                time.sleep(wait)
            st.last_request = time.monotonic()

    # ---------- fetch ----------

    def get(self, url: str, *, allow_cache: bool = True) -> FetchResult:
        cache = self.cache_path_for(url)
        meta_p = self._meta_path(cache)

        if allow_cache and not self.force_refresh and cache.exists():
            meta = {}
            if meta_p.exists():
                try:
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                except Exception:
                    pass
            self._bump("cached")
            return FetchResult(
                url=url, ok=True, status=meta.get("status", 200),
                text=cache.read_text(encoding="utf-8", errors="replace"),
                from_cache=True, final_url=meta.get("final_url", url),
                cache_path=str(cache), content_type=meta.get("content_type"),
                fetched_at=meta.get("fetched_at"),
            )

        ok, reason = self.allowed(url)
        if not ok:
            self._bump("skipped_robots" if "robots" in (reason or "") else "skipped_policy")
            self._log_skip(url, reason or "unknown")
            return FetchResult(url=url, ok=False, skipped_reason=reason)

        if self.offline:
            return FetchResult(url=url, ok=False, skipped_reason="offline mode, not cached")

        host = urllib.parse.urlsplit(url).netloc.lower()
        self._throttle(host)

        try:
            resp = self.session.get(url, timeout=TIMEOUT, allow_redirects=True,
                                    stream=True, verify=False)
            body = resp.raw.read(MAX_BYTES + 1, decode_content=True)
            if len(body) > MAX_BYTES:
                body = body[:MAX_BYTES]
            # requests falls back to ISO-8859-1 for text/* when the server sends
            # no charset, which mangles every Devanagari page into mojibake
            # ("विभाग" -> "à¤µà¤¿à¤­à¤¾à¤"). Indian government portals frequently
            # omit the charset, so prefer what the bytes actually decode as.
            enc = resp.encoding
            declared = "charset=" in (resp.headers.get("Content-Type") or "").lower()
            if not declared or (enc or "").lower() in ("iso-8859-1", "latin-1"):
                enc = resp.apparent_encoding or "utf-8"
            try:
                text = body.decode(enc, "strict")
            except (UnicodeDecodeError, LookupError):
                text = body.decode("utf-8", "replace")
        except Exception as e:
            self._bump("errors")
            log.warning("ERROR %s -- %s: %s", url, type(e).__name__, e)
            return FetchResult(url=url, ok=False, status=f"ERR:{type(e).__name__}")

        # A redirect can cross a domain boundary; re-check the destination.
        if resp.url != url:
            ok2, reason2 = self.allowed(resp.url)
            if not ok2:
                self._bump("skipped_policy")
                self._log_skip(resp.url, f"redirect target blocked: {reason2}")
                return FetchResult(url=url, ok=False, status=resp.status_code,
                                   skipped_reason=f"redirect target blocked: {reason2}")

        fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        if resp.status_code == 200 and text.strip():
            cache.write_text(text, encoding="utf-8")
            meta_p.write_text(json.dumps({
                "url": url, "final_url": resp.url, "status": resp.status_code,
                "content_type": resp.headers.get("Content-Type"),
                "fetched_at": fetched_at, "bytes": len(body),
            }, indent=2), encoding="utf-8")
            self._bump("fetched")
        else:
            self._bump("errors")

        return FetchResult(
            url=url, ok=resp.status_code == 200, status=resp.status_code, text=text,
            final_url=resp.url, cache_path=str(cache) if resp.status_code == 200 else None,
            content_type=resp.headers.get("Content-Type"), fetched_at=fetched_at,
        )

    def crawlable_domains(self, group: str | None = None) -> list[str]:
        return [d for d, e in self.domains.items()
                if e["decision"] in CRAWLABLE_DECISIONS
                and (group is None or e["group"] == group)]

    def close(self) -> None:
        try:
            self._skip_log.close()
        except Exception:
            pass
        self.session.close()


# requests warns loudly about verify=False; we disable verification only because
# several .gov.in hosts ship incomplete certificate chains, and this crawler
# reads exclusively public, non-sensitive pages.
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass
