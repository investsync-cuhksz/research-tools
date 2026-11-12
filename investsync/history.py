"""A small record of every report run, so the next report can say what changed.

One JSON file per ticker and day: data/history/<ticker>/<YYYY-MM-DD>.json (git-ignored with data/).
It holds only headline figures (price, rating, fair value, broker median target, scorecard), never
third-party text. Over time this gives a rating history ("Buy since ...") and, later, a track record.
Saving is on by default; set INVESTSYNC_HISTORY=0 to turn it off (tests do).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

from .config import ROOT
from .render.viewmodel import ccy, num, pct
from .schema import SinceLast, TearSheetData

log = logging.getLogger(__name__)


def _dir(ticker: str) -> Path:
    base = Path(os.getenv("INVESTSYNC_HISTORY_DIR", str(ROOT / "data" / "history")))
    return base / ticker.replace("/", "_")


def enabled() -> bool:
    return os.getenv("INVESTSYNC_HISTORY", "1") == "1"


def basis(data: TearSheetData) -> Optional[str]:
    """How the rating's DCF value was set: "scenarios" (the analyst's probability-weighted scenarios) or "rule"."""
    rt = data.rating
    if not rt or not rt.methods:
        return None
    return "scenarios" if any(m.key == "dcf" and "scenario" in m.label.lower() for m in rt.methods) else "rule"


def snapshot(data: TearSheetData) -> dict:
    rt, st, sc = data.rating, data.street, data.scorecard
    return {
        "date": data.quote.as_of.isoformat(), "generated_at": data.generated_at.isoformat(),
        "price": data.quote.price, "currency": data.quote.currency,
        "rating": rt.rating if rt else None, "fair_value": rt.fair_value if rt else None,
        "upside": rt.upside if rt else None,
        "street_target_median": st.target_median if st else None,
        "street_ratings": st.rating_counts if st else None,
        "street_eps": {e.period: e.median for e in st.eps} if st else None,
        "scores": {a.key: [a.score, a.available] for a in sc.areas} if sc else None,
        "overall": data.overall.rating if data.overall else None,
        "overall_score": data.overall.score if data.overall else None,
        "schema_version": data.schema_version,
        # what the fair value was built from, so a big change can be traced to a method or input change
        "methods": {m.key: round(m.value, 4) for m in rt.methods if m.included} if rt else None,
        "basis": basis(data),
        "peers": [p.ticker for p in data.comps.peers] if data.comps else None,
        "pe_basis": next((b.label for b in (data.football_field.bars if data.football_field else [])
                          if b.label.startswith("Peer P/E")), None),
    }


def save(data: TearSheetData) -> Optional[Path]:
    if not enabled():
        return None
    try:
        d = _dir(data.profile.ticker)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{data.quote.as_of.isoformat()}.json"
        f.write_text(json.dumps(snapshot(data), indent=1), encoding="utf-8")
        return f
    except OSError as e:  # history is a convenience; never fail a report over it
        log.warning("could not save history: %s", e)
        return None


def _load(ticker: str) -> list[dict]:
    d = _dir(ticker)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def compare(data: TearSheetData) -> Optional[SinceLast]:
    """Changes since the most recent saved report from an earlier day."""
    today = data.quote.as_of
    runs = [r for r in _load(data.profile.ticker) if r.get("date") and date.fromisoformat(r["date"]) < today]
    if not runs:
        return None
    prev = runs[-1]
    rt, st = data.rating, data.street
    cur = ccy(data.quote.currency)
    out = SinceLast(previous_date=date.fromisoformat(prev["date"]), previous_price=prev.get("price"),
                    previous_rating=prev.get("rating"), previous_fair_value=prev.get("fair_value"),
                    previous_street_target=prev.get("street_target_median"))
    now_rating = rt.rating if rt else None
    if now_rating:  # unbroken run of the same rating, going back from the latest saved report
        since = today
        for r in reversed(runs):
            if r.get("rating") != now_rating:
                break
            since = date.fromisoformat(r["date"])
        out.rating_since = since
    ch = []
    if prev.get("price") and data.quote.price:
        ch.append(f"Share price {cur} {num(prev['price'], 2)} → {num(data.quote.price, 2)} "
                  f"({pct(data.quote.price / prev['price'] - 1, 1, signed=True)}).")
    # A different valuation method (or a report from before methods were recorded) makes the old rating and fair
    # value a different measurement, not news: say so instead of printing "Sell → Buy, +164%" (round-4 review).
    same_method = prev.get("methods") is not None and (prev.get("basis") or "rule") == (basis(data) or "rule")
    if not same_method:  # nor does the writer have to explain a "rating change"
        out.previous_rating = out.previous_fair_value = None
        ch.append(f"Not comparable with the {out.previous_date.strftime('%-d %b')} report: the valuation method "
                  f"changed since then (that report: {prev.get('rating') or 'no rating'}), so rating and fair-value "
                  "changes are not shown.")
    elif prev.get("rating") != now_rating:
        ch.append(f"Model rating changed: {prev.get('rating') or 'none'} → {now_rating or 'none'}.")
    else:
        ch.append(f"Model rating unchanged ({now_rating}).")
    ov = data.overall
    if same_method and ov and prev.get("overall"):
        if prev["overall"] != ov.rating:
            ch.append(f"Overall view changed: {prev['overall']} ({prev.get('overall_score') or 0:.2f}) → "
                      f"{ov.rating} ({ov.score:.2f}).")
        elif prev.get("overall_score") is not None and abs(ov.score - prev["overall_score"]) >= 0.05:
            ch.append(f"Overall view unchanged ({ov.rating}); score {prev['overall_score']:.2f} → {ov.score:.2f}.")
    if same_method and prev.get("fair_value") and rt and rt.fair_value:
        ch.append(f"Model fair value {cur} {num(prev['fair_value'], 2)} → {num(rt.fair_value, 2)} "
                  f"({pct(rt.fair_value / prev['fair_value'] - 1, 1, signed=True)}).")
    if prev.get("street_target_median") and st and st.target_median:
        ch.append(f"Brokers' median target {cur} {num(prev['street_target_median'], 2)} → "
                  f"{num(st.target_median, 2)}.")
    pe, ne = prev.get("street_eps") or {}, ({e.period: e.median for e in st.eps} if st else {})
    for k in sorted(set(pe) & set(ne))[:1]:
        if pe[k]:
            ch.append(f"Brokers' median {k} EPS {num(pe[k], 2)} → {num(ne[k], 2)} "
                      f"({pct(ne[k] / pe[k] - 1, 1, signed=True)}).")
    # why the fair value moved: method / input changes (recorded from schema 1.8 on)
    why = []
    if rt and prev.get("methods") is not None:
        now_m = {m.key: m.value for m in rt.methods if m.included}
        for k in sorted(set(now_m) | set(prev["methods"])):
            a, b = prev["methods"].get(k), now_m.get(k)
            if a and b and abs(b / a - 1) >= 0.15:
                why.append(f"{k} value {num(a, 2)} → {num(b, 2)}")
            elif bool(a) != bool(b):
                why.append(f"{k} {'added' if b else 'dropped'}")
    if prev.get("peers") is not None and data.comps:
        old, new = set(prev["peers"]), {p.ticker for p in data.comps.peers}
        if old != new:
            why.append("peer set changed (out: " + (", ".join(sorted(old - new)) or "none") + "; in: "
                       + (", ".join(sorted(new - old)) or "none") + ")")
    pe_basis = next((b.label for b in (data.football_field.bars if data.football_field else [])
                     if b.label.startswith("Peer P/E")), None)
    if prev.get("pe_basis") and pe_basis and prev["pe_basis"] != pe_basis:
        why.append(f"peer P/E basis {prev['pe_basis']} → {pe_basis}")
    if why and same_method:
        ch.append("Method / input changes behind the fair value: " + "; ".join(why) + ".")
    out.changes = ch
    return out
