"""Headless-browser rendering for JS-driven portals (NSP, MahaDBT, ...).

Same contract as Fetcher: consult the robots policy, respect the per-domain rate
limit, cache to disk. The only difference is that a real browser executes the
page's own scripts so client-rendered tables become readable HTML.

We never log in, dismiss paywalls, or fill forms other than the public
"show me the list" controls a visitor would click. The browser identifies itself
with the same Khoji.AI UA as the plain HTTP client.
"""

from __future__ import annotations

import json
import pathlib
import random
import time
import urllib.parse

from fetcher import UA, MIN_INTERVAL, JITTER, Fetcher

RENDER_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "rendered"


class Renderer:
    """Playwright wrapper that honours the crawl policy."""

    def __init__(self, fetcher: Fetcher | None = None, headless: bool = True,
                 force_refresh: bool = False):
        self.fetcher = fetcher or Fetcher()
        self.headless = headless
        self.force_refresh = force_refresh
        RENDER_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self._browser = None
        self._ctx = None
        self._last: dict[str, float] = {}

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._ctx = self._browser.new_context(
            user_agent=UA,
            locale="en-IN",
            viewport={"width": 1400, "height": 1000},
            ignore_https_errors=True,   # several .gov.in hosts ship broken chains
        )
        self._ctx.set_default_timeout(45000)
        return self

    def __exit__(self, *exc):
        for obj in (self._ctx, self._browser):
            try:
                obj and obj.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

    def _throttle(self, host: str) -> None:
        wait = MIN_INTERVAL - (time.monotonic() - self._last.get(host, 0.0))
        wait = max(0.0, wait) + random.uniform(*JITTER)
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def _cache_paths(self, url: str, tag: str) -> tuple[pathlib.Path, pathlib.Path]:
        import hashlib
        host = urllib.parse.urlsplit(url).netloc.lower() or "unknown"
        digest = hashlib.sha256(f"{url}|{tag}".encode()).hexdigest()[:20]
        d = RENDER_DIR / host
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{digest}.html", d / f"{digest}.meta.json"

    def render(self, url: str, *, wait_selector: str | None = None,
               wait_ms: int = 3500, actions=None, tag: str = "",
               scroll: bool = False) -> tuple[bool, str, str | None]:
        """Return (ok, html, note). `actions` is a callable(page) for public
        controls such as expanding a paginated list."""
        cache, meta_p = self._cache_paths(url, tag)
        if cache.exists() and not self.force_refresh:
            return True, cache.read_text(encoding="utf-8", errors="replace"), "cache"

        ok, reason = self.fetcher.allowed(url)
        if not ok:
            self.fetcher._log_skip(url, f"[render] {reason}")
            return False, "", f"blocked: {reason}"

        host = urllib.parse.urlsplit(url).netloc.lower()
        self._throttle(host)

        page = self._ctx.new_page()
        # Block heavy media we never parse; keeps load light on their servers.
        page.route("**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,mp4}",
                   lambda r: r.abort())
        note = None
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=20000)
                except Exception:
                    note = f"selector {wait_selector!r} never appeared"
            page.wait_for_timeout(wait_ms)
            if scroll:
                for _ in range(6):
                    page.mouse.wheel(0, 4000)
                    page.wait_for_timeout(700)
            if actions:
                try:
                    actions(page)
                except Exception as e:
                    note = f"{note + '; ' if note else ''}actions failed: {type(e).__name__}: {e}"
            html = page.content()
            final_url = page.url
        except Exception as e:
            page.close()
            return False, "", f"render error: {type(e).__name__}: {e}"
        page.close()

        cache.write_text(html, encoding="utf-8")
        meta_p.write_text(json.dumps({
            "url": url, "final_url": final_url, "tag": tag, "note": note,
            "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "bytes": len(html),
        }, indent=2), encoding="utf-8")
        return True, html, note
