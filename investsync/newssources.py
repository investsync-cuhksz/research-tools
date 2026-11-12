"""Which news outlets we keep (config/news_sources.json, owned by the team).

Why (12 Nov 2026): run 2's bear case leaned on a CEO-investigation note from a minor tech site, and the report's
news list (179 items) was mostly Motley Fool, newsletter and auto-generated stories that the writers then read.
A block list of content farms (research/desk.py LOW_TIER) kept missing new ones, so news is now kept only from
a list of outlets we trust: wires, major business papers and, for China and Hong Kong, the main financial press.
Company documents and broker reports are not news and are never filtered here.

Most news reaches us through aggregators (finnhub, Yahoo Finance, EastMoney, MSN, Bing) that also carry
low-quality sites, so the publisher's name decides; the website only counts for a direct link.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from functools import lru_cache
from urllib.parse import urlparse

from .config import ROOT, settings

log = logging.getLogger(__name__)

CONFIG = ROOT / "config" / "news_sources.json"


def key(name: str) -> str:
    """Comparison form of a publisher name: "Bing News: The Wall Street Journal" -> "wallstreetjournal",
    "Barrons.com" -> "barrons", "证券时报网" -> "证券时报网"."""
    s = unicodedata.normalize("NFKC", name or "").strip()
    s = re.sub(r"^(?:bing news|news feed):\s*", "", s, flags=re.I)
    s = re.sub(r"\s*\(via [^)]*\)\s*$", "", s, flags=re.I).strip().lower()
    s = re.sub(r"\.(?:com|co\.uk|com\.cn|cn|net|org)$", "", s)
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[\W_]+", "", s)


def host(url: str) -> str:
    try:
        h = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _on(h: str, domains: tuple[str, ...]) -> bool:
    return any(h == d or h.endswith("." + d) for d in domains)


@lru_cache(maxsize=1)
def _lists() -> tuple[frozenset, tuple, tuple]:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # a missing or broken list must not silently let everything through
        log.warning("news source list unreadable (%s): no news is kept", e)
        cfg = {}
    names = frozenset(k for k in (key(n) for n in cfg.get("names", [])) if k)
    domains = tuple(d.lower().lstrip(".") for d in cfg.get("domains", []) if d)
    aggregators = tuple(d.lower().lstrip(".") for d in cfg.get("aggregators", []) if d)
    return names, domains, aggregators


def enabled() -> bool:
    return bool(getattr(settings, "news_allowlist", True))


def allowed(source: str, url: str = "") -> bool:
    """True if the news item comes from an outlet on the list (always True when the list is switched off)."""
    if not enabled():
        return True
    names, domains, aggregators = _lists()
    if key(source) in names:
        return True
    h = host(url)
    return bool(h) and not _on(h, aggregators) and _on(h, domains)
