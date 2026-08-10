"""Download and read official scheme guideline PDFs.

NSP publishes each scheme's authoritative eligibility rules as a PDF. Those PDFs
carry the income ceilings, class ranges, award counts and document lists that the
listing page omits, so reading them is what lifts a record from a name-and-date
stub to something a student can act on.

Extraction is text-only. A PDF that yields no extractable text (a pure scan) is
recorded as such and routed to needs_review rather than guessed at.
"""

from __future__ import annotations

import pathlib
import re
import time

from fetcher import Fetcher

PDF_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "pdf"
MIN_USEFUL_CHARS = 200
MAX_DOWNLOAD_SECONDS = 45      # hard wall-clock cap per document
MAX_PDF_BYTES = 25 * 1024 * 1024


def _cache_path(url: str) -> pathlib.Path:
    import hashlib
    import urllib.parse
    host = urllib.parse.urlsplit(url).netloc.lower() or "unknown"
    d = PDF_DIR / host
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{hashlib.sha256(url.encode()).hexdigest()[:20]}.pdf"


def download(fetcher: Fetcher, url: str) -> pathlib.Path | None:
    """Fetch a PDF through the same robots + rate-limit gate as everything else."""
    path = _cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        return path

    ok, reason = fetcher.allowed(url)
    if not ok:
        fetcher._log_skip(url, f"[pdf] {reason}")
        return None

    import urllib.parse
    fetcher._throttle(urllib.parse.urlsplit(url).netloc.lower())
    try:
        # (connect, read) timeouts. A read timeout alone is not enough: a server
        # that dribbles a few bytes at a time resets the read clock forever and
        # the download never returns. So we also cap total wall time below.
        resp = fetcher.session.get(url, timeout=(10, 20), allow_redirects=True,
                                   verify=False, stream=True)
        if resp.status_code != 200:
            return None
        deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
        chunks, total = [], 0
        for chunk in resp.iter_content(65536):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_PDF_BYTES:
                print(f"    [pdf] oversized, truncating {url[-60:]}")
                break
            if time.monotonic() > deadline:
                print(f"    [pdf] slow server, abandoning {url[-60:]}")
                return None
        content = b"".join(chunks)
    except Exception as e:
        print(f"    [pdf] error {type(e).__name__} for {url[-70:]}")
        return None
    finally:
        try:
            resp.close()
        except Exception:
            pass

    if not content:
        return None
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" not in ctype and not content[:5].startswith(b"%PDF"):
        return None
    path.write_bytes(content)
    return path


def extract_text(path: pathlib.Path, max_pages: int = 25) -> str:
    """Best-effort text. pypdf is fast; pdfminer is the fallback for the PDFs
    whose text layer pypdf cannot see."""
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        parts = []
        for pg in reader.pages[:max_pages]:
            try:
                parts.append(pg.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts)
    except Exception:
        pass

    if len(text.strip()) < MIN_USEFUL_CHARS:
        try:
            from pdfminer.high_level import extract_text as pm_extract
            text = pm_extract(str(path), maxpages=max_pages) or ""
        except Exception:
            pass

    return re.sub(r"[ \t]+", " ", text or "").strip()


def ocr_text(path: pathlib.Path, max_pages: int = 8) -> str:
    """Last resort for scanned guidelines: rasterise with pdftoppm, read with
    tesseract. Both are external binaries; if either is absent we return "" and
    the caller keeps the record flagged rather than inventing content.

    OCR output is noisier than a real text layer, so callers should treat what
    it yields as lower confidence than a native extraction.
    """
    import shutil
    import subprocess
    import tempfile

    # OCR costs 30-60s per document, so the result is cached beside the PDF.
    # Without this, every pipeline re-run pays the full bill again.
    cache = path.with_suffix(".ocr.txt")
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")

    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""

    with tempfile.TemporaryDirectory() as td:
        stem = pathlib.Path(td) / "pg"
        try:
            subprocess.run(
                ["pdftoppm", "-r", "300", "-gray", "-f", "1", "-l", str(max_pages),
                 "-png", str(path), str(stem)],
                capture_output=True, timeout=180, check=False)
        except (subprocess.TimeoutExpired, OSError):
            return ""

        parts = []
        for img in sorted(pathlib.Path(td).glob("pg*.png")):
            try:
                p = subprocess.run(["tesseract", str(img), "stdout", "-l", "eng"],
                                   capture_output=True, text=True, timeout=120)
                parts.append(p.stdout or "")
            except (subprocess.TimeoutExpired, OSError):
                continue
    out = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()
    try:
        cache.write_text(out, encoding="utf-8")
    except OSError:
        pass
    return out


_FUNCTION_WORDS = {
    "the", "of", "and", "to", "for", "in", "is", "be", "shall", "will", "or",
    "as", "by", "with", "that", "from", "on", "are", "this", "which", "has",
    "have", "not", "any", "such", "may", "been", "under", "per", "at", "an",
}

_OCR_KEYWORDS = ("scholarship", "scheme", "student", "eligib", "income",
                 "guideline", "application", "institute", "course", "annum")


def ocr_looks_usable(text: str) -> bool:
    """Reject OCR noise before it can reach an extractor.

    A poor scan yields thousands of characters of plausible-looking garbage that
    clears any length threshold. Two cheap signals separate it from real prose:
    the share of characters that are letters or spaces, and whether the words we
    would expect in a scholarship guideline appear at all.
    """
    if not text or len(text) < 400:
        return False
    letters = sum(1 for c in text if c.isalpha() or c.isspace())
    if letters / len(text) < 0.75:
        return False
    low = text.lower()
    if sum(1 for k in _OCR_KEYWORDS if k in low) < 3:
        return False
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) >= 4]
    if len(words) < 80:
        return False

    # The decisive test: English prose is full of function words, and OCR noise
    # is not. Letter-ratio alone passes garbage like "spancenenenontt we «CS",
    # because noise is mostly letters too.
    tokens = re.findall(r"[a-z]+", low)
    if not tokens:
        return False
    function_words = sum(1 for w in tokens if w in _FUNCTION_WORDS)
    return function_words / len(tokens) >= 0.12


def get_text(fetcher: Fetcher, url: str, *, allow_ocr: bool = True) -> tuple[str, str | None]:
    """Return (text, note). Empty text with a note means the PDF was
    unreadable — the caller must not fabricate values to fill the gap."""
    path = download(fetcher, url)
    if path is None:
        return "", "pdf not retrievable"
    text = extract_text(path)
    if len(text) >= MIN_USEFUL_CHARS:
        return text, None

    if allow_ocr:
        ocr = ocr_text(path)
        if ocr_looks_usable(ocr):
            # Usable, but say where it came from: OCR misreads digits often
            # enough that a reviewer should know before trusting an amount.
            return ocr, "text recovered by OCR (scanned document) - figures unverified"

    return text, "pdf has little or no extractable text (likely scanned)"
