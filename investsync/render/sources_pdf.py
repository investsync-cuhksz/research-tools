"""The pack's source list as a PDF with clickable links (11 Nov 2026: students open a PDF, not a Markdown file).

``sources_pdf(text)`` turns the pack's plain source list (datapack.sources_md: "# " title, "## " sections, "- " and
"1. " items, "---", paragraphs) into blocks and renders them with template/sources.typ. Text travels as JSON data, so
nothing in a title or a quote can act as Typst markup.
"""
from __future__ import annotations

import json
import re
import uuid

from .render import BUILD_DIR, TEMPLATE, _compile

_URL = re.compile(r"https?://[^\s)\"'<>]+")
_CODE = re.compile(r"`([^`]+)`")


def _runs(text: str) -> list[dict]:
    """Plain text, `code` and links, in order (a trailing full stop is not part of a link)."""
    out: list[dict] = []
    for i, part in enumerate(_CODE.split(text)):
        if i % 2:
            out.append({"code": part})
            continue
        pos = 0
        for m in _URL.finditer(part):
            url = m.group(0).rstrip(".,;:")
            if m.start() > pos:
                out.append({"text": part[pos:m.start()]})
            out.append({"url": url})
            pos = m.start() + len(url)
        if pos < len(part):
            out.append({"text": part[pos:]})
    return out


def blocks(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == "---":
            out.append({"t": "hr"})
        elif s.startswith("## "):
            out.append({"t": "h2", "runs": _runs(s[3:])})
        elif s.startswith("# "):
            out.append({"t": "h1", "runs": _runs(s[2:])})
        elif s.startswith("- "):
            out.append({"t": "li", "runs": _runs(s[2:])})
        elif re.match(r"^\d+\. ", s):
            n, rest = s.split(". ", 1)
            out.append({"t": "ol", "n": n, "runs": _runs(rest)})
        else:
            out.append({"t": "p", "runs": _runs(s)})
    return out


def sources_pdf(text: str, title: str, footer: str = "InvestSync Research Tools · source list") -> bytes:
    BUILD_DIR.mkdir(exist_ok=True)
    job = BUILD_DIR / f"{uuid.uuid4().hex}.json"
    job.write_text(json.dumps({"title": title, "footer": footer, "blocks": blocks(text)}, ensure_ascii=False),
                   encoding="utf-8")
    try:
        return _compile(job, TEMPLATE.parent / "sources.typ", "sources")
    finally:
        job.unlink(missing_ok=True)
