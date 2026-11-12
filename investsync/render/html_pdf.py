"""Web-page filings as PDFs for the student source pack (11 Nov 2026: students read a PDF more easily than the SEC's
.htm pages, which are the official copies of every US 10-K, 10-Q and 8-K).

A headless Chromium-family browser prints the page, as "Print > Save as PDF" would. The filing's images (logo,
charts) are downloaded first with the caller's fetch function (for the SEC: the declared User-Agent the SEC asks
for) and embedded, because the browser itself would fetch them anonymously. No browser found, or a failure: the
caller keeps the original web page. The Docker image installs Chromium; set CHROME_PATH to use another binary.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin

log = logging.getLogger(__name__)

CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium")
MAX_IMAGES = 40
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_IMG = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])([^"\']+)\2', re.I)
_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "svg": "image/svg+xml",
         "webp": "image/webp"}


def browser() -> Optional[str]:
    for c in (os.getenv("CHROME_PATH"), *CANDIDATES):
        if c and (shutil.which(c) or Path(c).is_file()):
            return shutil.which(c) or c
    return None


def is_html(name: str, content: bytes) -> bool:
    head = content[:2048].lstrip().lower()
    return name.lower().endswith((".htm", ".html")) or head.startswith((b"<!doctype html", b"<html", b"<?xml"))


def inline_images(html: str, base_url: str, fetch: Callable[[str], bytes]) -> str:
    """Embed the page's images as data URIs (at most MAX_IMAGES; any that fail are left as they are)."""
    done: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        src = m.group(3)
        if src.startswith("data:") or len(done) >= MAX_IMAGES and src not in done:
            return m.group(0)
        if src not in done:
            url = urljoin(base_url, src)
            ext = url.rsplit(".", 1)[-1].lower().split("?")[0]
            try:
                raw = fetch(url)
                if len(raw) > MAX_IMAGE_BYTES:
                    raise ValueError("image too large")
                done[src] = f"data:{_MIME.get(ext, 'image/png')};base64,{base64.b64encode(raw).decode()}"
            except Exception as e:  # a missing logo must not stop the document
                log.info("image not embedded: %s (%s)", url, type(e).__name__)
                done[src] = src
        return f"{m.group(1)}{m.group(2)}{done[src]}{m.group(2)}"
    return _IMG.sub(repl, html)


def _decode(content: bytes) -> str:
    m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', content[:4096])
    for enc in ((m.group(1).decode(),) if m else ()) + ("utf-8", "latin-1"):
        try:
            return content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace")


def html_to_pdf(content: bytes, url: str, fetch: Callable[[str], bytes], timeout: float = 180) -> Optional[bytes]:
    """The page printed to PDF, or None (no browser, a timeout, or not a PDF)."""
    exe = browser()
    if not exe:
        return None
    html = inline_images(_decode(content), url, fetch)
    base = f'<base href="{url.rsplit("/", 1)[0]}/">'
    html = re.sub(r"(<head\b[^>]*>)", lambda m: m.group(1) + base, html, count=1, flags=re.I) \
        if re.search(r"<head\b", html, re.I) else base + html
    with tempfile.TemporaryDirectory(prefix="investsync-pdf-") as tmp:
        src, out = Path(tmp) / "doc.html", Path(tmp) / "doc.pdf"
        src.write_text(html, encoding="utf-8")
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--hide-scrollbars",
               f"--user-data-dir={Path(tmp) / 'profile'}", "--virtual-time-budget=10000",
               f"--print-to-pdf={out}", src.as_uri()]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")  # Chromium refuses to run as root (Docker) without it
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError) as e:
            log.warning("PDF conversion failed for %s: %s", url, type(e).__name__)
            return None
        pdf = out.read_bytes() if out.exists() else b""
    return pdf if pdf.startswith(b"%PDF") else None
