"""View-model for the full report (pages 2+).

Like viewmodel.py, every number is formatted here and every chart is laid out here: chart
specs carry positions already normalised to 0..1, so the Typst template only draws.

Chart rules (see the dataviz guidance): one y-axis per chart (no dual axes), validated
categorical colours in fixed order, solid hairline grids, a legend whenever there are two or
more series, and the exact values always available in a table on the same page.
"""
from __future__ import annotations

import contextvars
import logging
import math
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

from ..narrative.evidence import reader_text
from ..schema import FiscalYear, RatioYear, TearSheetData
from ..quant.valuation import STAKE_HAIRCUT
from .viewmodel import _nice_ticks, big, ccy, latest_vm, mn, mult, num, pct, trim_name

# Validated categorical order (light surface): blue, orange, aqua, yellow
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
REST = "#b9bfca"   # de-emphasised marks (peers, volume)
INK = "#1d2433"

log = logging.getLogger(__name__)

# run 2 (12 Nov 2026): row limits for the page fit (render.render_pdf rebuilds the report at compact 1, then 2, when
# it runs over its page limit). Level 0 is the full report.
COMPACT = {
    0: {"research": None, "news": 12, "announcements": 16, "broker_notes": 10, "excerpt": 700},
    1: {"research": 14, "news": 8, "announcements": 8, "broker_notes": 6, "excerpt": 700},
    2: {"research": 8, "news": 8, "announcements": 8, "broker_notes": 6, "excerpt": 350},
    3: {"research": 6, "news": 6, "announcements": 6, "broker_notes": 4, "excerpt": 250},  # run 4: room for the deciding year
}


def _limits(compact: int) -> dict:
    return COMPACT[min(max(int(compact or 0), 0), max(COMPACT))]


# ---------------------------------------------------------------- formatting helpers
def _short(v: Optional[float]) -> str:
    """Compact amount without currency: 751.8bn, 12.3mn, 1.25tn."""
    if v is None:
        return "–"
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:,.2f}tn"
    if a >= 1e9:
        return f"{v / 1e9:,.1f}bn"
    if a >= 1e6:
        return f"{v / 1e6:,.1f}mn"
    return f"{v:,.0f}"


def _days(v: Optional[float]) -> str:
    return "–" if v is None else f"{v:.0f}"


def _signed_pct(v: Optional[float], dp: int = 1) -> str:
    return pct(v, dp, signed=True)


def _axis(values: list[float], include_zero: bool = True, n: int = 4) -> tuple[float, float, list[float]]:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return 0.0, 1.0, [0.0, 1.0]
    lo, hi = min(vals), max(vals)
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi = lo + (abs(lo) or 1.0)
    ticks = _nice_ticks(lo, hi, n)
    step = ticks[1] - ticks[0] if len(ticks) > 1 else (hi - lo) or 1.0
    while ticks[-1] < hi - 1e-12:  # make sure the axis covers the data
        ticks.append(round(ticks[-1] + step, 9))
    while ticks[0] > lo + 1e-12:
        ticks.insert(0, round(ticks[0] - step, 9))
    return ticks[0], ticks[-1], ticks


def _norm(v: Optional[float], lo: float, hi: float) -> Optional[float]:
    if v is None:
        return None
    return round((v - lo) / (hi - lo), 4) if hi != lo else 0.5


def _tick_label(t: float, kind: str) -> str:
    if kind == "pct":
        return f"{t * 100:.0f}%"
    if kind == "amount":
        if not t:
            return "0"
        for div, unit in ((1e12, "tn"), (1e9, "bn"), (1e6, "mn")):
            if abs(t) >= div:
                x = t / div
                return f"{x:,.0f}{unit}" if abs(x - round(x)) < 1e-9 else f"{x:,.1f}{unit}"
        return f"{t:,.0f}"
    if kind == "x":
        return f"{t:g}x"
    return f"{t:,.0f}" if abs(t) >= 100 else f"{t:g}"


# ---------------------------------------------------------------- chart specs
def bar_chart(cats: list[str], series: list[tuple[str, str, list[Optional[float]]]], kind: str,
              title: str) -> Optional[dict]:
    """Grouped vertical bars on one axis. ``series``: (name, colour, values)."""
    allv = [v for _, _, vals in series for v in vals if v is not None]
    if not allv:
        return None
    lo, hi, ticks = _axis(allv)
    zero = _norm(0.0, lo, hi)
    return {
        "title": title, "cats": cats, "zero": zero,
        "yticks": [[_norm(t, lo, hi), _tick_label(t, kind)] for t in ticks],
        "series": [{"name": name, "color": col,
                    "bars": [None if v is None else sorted([zero, _norm(v, lo, hi)]) for v in vals]}
                   for name, col, vals in series],
        "legend": [[name, col] for name, col, _ in series] if len(series) > 1 else [],
    }


def line_chart(cats: list[str], series: list[tuple[str, str, list[Optional[float]]]], kind: str,
               title: str, include_zero: bool = False) -> Optional[dict]:
    """Lines over categories (fiscal years) on one axis, labelled at the last point."""
    allv = [v for _, _, vals in series for v in vals if v is not None]
    if not allv:
        return None
    lo, hi, ticks = _axis(allv, include_zero=include_zero or min(allv) < 0)
    n = len(cats)
    fmt = (lambda v: pct(v, 0)) if kind == "pct" else (lambda v: mult(v, 1)) if kind == "x" else _short
    out = []
    for name, col, vals in series:
        pts = [[round((i + 0.5) / n, 4), _norm(v, lo, hi)] for i, v in enumerate(vals) if v is not None]
        if not pts:
            continue
        last = next(v for v in reversed(vals) if v is not None)
        out.append({"name": name, "color": col, "points": pts, "end_label": f"{name} {fmt(last)}", "end_y": pts[-1][1]})
    # nudge end labels apart so they never overlap (min gap ~ one text line)
    gap = 0.11
    order = sorted(out, key=lambda s: s["end_y"])
    for i in range(1, len(order)):
        order[i]["end_y"] = max(order[i]["end_y"], order[i - 1]["end_y"] + gap)
    over = (order[-1]["end_y"] - 1.0) if order else 0
    if over > 0:
        for s in order:
            s["end_y"] = round(s["end_y"] - over, 4)
    return {"title": title, "cats": cats, "yticks": [[_norm(t, lo, hi), _tick_label(t, kind)] for t in ticks],
            "zero": _norm(0.0, lo, hi) if lo < 0 < hi else None, "series": out,
            "legend": [[s["name"], s["color"]] for s in out] if len(out) > 1 else []}


def _time_x(d: date, d0: date, d1: date) -> float:
    return round((d - d0).days / max((d1 - d0).days, 1), 4)


def _year_labels(d0: date, d1: date) -> list[list]:
    out = []
    for y in range(d0.year + 1, d1.year + 1):
        jan = date(y, 1, 1)
        if d0 < jan <= d1:
            out.append([_time_x(jan, d0, d1), str(y)])
    return out


# ---------------------------------------------------------------- AI sections
AI_SECTIONS = {
    "tagline": ("Tagline", "One sentence that sums up the investment case."),
    "thesis": ("Investment thesis", "A paragraph on why the stock is interesting now: growth drivers, "
               "profitability and valuation, using only the figures in this report."),
    "key_takeaways": ("Key takeaways", "Four to six one-line findings (revenue, margins, cash flow, valuation)."),
    "company_overview": ("Company overview", "Two paragraphs on the business model, main products, customers "
                         "and competitive position, drawn from the annual report."),
    "financial_analysis": ("Financial analysis", "What changed over five years and why: growth, margin "
                           "drivers (DuPont), cash conversion and balance-sheet strength."),
    "valuation_overview": ("Valuation commentary", "How the DCF, peer multiples, the stock's own P/E history "
                           "and the reverse DCF fit together, and what the market is pricing in."),
    "competitive_analysis": ("Competitive analysis", "How the company compares with its peers on growth, "
                             "margins, returns and valuation, and where its edge lies."),
    "news_summary": ("News summary", "Themes in recent news, sorted into earnings, products, regulation and "
                     "market, with what each means for the company."),
    "events_to_monitor": ("Events to monitor", "Dated upcoming events (results, product launches, "
                          "regulatory decisions) and why each matters."),
    "report_summary": ("Latest report summary", "A summary of management's discussion, outlook and risk "
                       "factors from the latest annual / interim report."),
    "rating_rationale": ("Why this rating", "Two or three sentences explaining which valuation methods drive "
                         "the rule-based rating and how confident it is."),
}


# The data-only edition (12 Nov 2026): every AI section becomes a "Your analysis" box with the question the reader
# answers there and ruled lines to write on: (title, question, lines). Fewer lines when the report is shortened to
# fit its page limit (compact 1, 2).
DATA_ASK = {
    "thesis": ("Investment thesis", "Is the stock worth owning now, or not? Weigh growth, profitability and valuation "
               "with the figures in this report, say where you come out and what would change your mind.", 9),
    "key_takeaways": ("Key takeaways", "Your four to six one-line findings: revenue, margins, cash flow, balance "
                      "sheet, valuation.", 9),
    "company_overview": ("Company overview", "How does the company make money: main products, customers, where it "
                         "sells and how it competes? Start from the business description, the revenue breakdown and "
                         "the latest report.", 5),
    "financial_analysis": ("Financial analysis", "What changed over five years and why: growth, margin drivers "
                           "(DuPont), cash conversion and balance-sheet strength? Does the latest period fit the "
                           "trend?", 6),
    "valuation_overview": ("Your valuation view", "How do the DCF, the peer multiples, the stock's own P/E history "
                           "and the reverse DCF fit together? What is the price assuming, and which calculation do "
                           "you trust most?", 7),
    "competitive_analysis": ("Competitive analysis", "How does the company compare with its peers on growth, "
                             "margins, returns and valuation? Where is its edge, and is the premium or discount "
                             "deserved?", 10),
    "news_summary": ("News summary", "Which themes run through the recent news and announcements, and what does "
                     "each mean for the company?", 5),
    "events_to_monitor": ("Events to monitor", "Which dated events (results, product launches, regulatory "
                          "decisions) matter most, and why?", 5),
    "report_summary": ("Latest report summary", "What does management say about the business, the outlook and the "
                       "risks in the latest report (excerpts above)?", 6),
    "catalysts": ("Catalysts", "What could lift the share price over the next 12 months? Use the events, "
                  "announcements and news below.", 4),
    "risks": ("Key risks", "What could go wrong, and how much would it hurt the value?", 4),
    # not printed in this edition (it has no rating section); kept so every AI section has a box
    "rating_rationale": ("Your view on value", "Is the share price below or above what you think the company is "
                         "worth, and why?", 4),
}
STREET_ASK = ("Street view", "Where do the brokers agree and differ? Do their targets and EPS forecasts look "
              "reasonable against the figures in this report?", 4)


def _ask(key: str, compact: int = 0, ask: Optional[tuple] = None) -> dict[str, Any]:
    title, question, lines = ask or DATA_ASK.get(key) or (AI_SECTIONS[key][0], AI_SECTIONS[key][1], 4)
    return {"title": title, "desc": question, "value": None, "lines": max(3, lines - 2 * int(compact or 0))}


def _ai(data: TearSheetData, data_only: bool = False, compact: int = 0) -> dict[str, Any]:
    """The AI sections; ``data_only``: the data-only edition's writing boxes instead (status "data_only")."""
    if data_only:
        out: dict[str, Any] = {"status": "data_only", "model": ""}
        for key in [*AI_SECTIONS, "catalysts", "risks"]:
            out[key] = _ask(key, compact)
        return out
    n = data.narrative
    status = n.status if n else "placeholder"
    out = {"status": status, "model": (n.model if n and n.model else "")}
    for key, (title, desc) in AI_SECTIONS.items():
        val = getattr(n, key, None) if n else None
        if isinstance(val, list):
            val = [b.model_dump() if hasattr(b, "model_dump") else b for b in val]
        out[key] = {"title": title, "desc": desc, "value": val if val else None}
    # chapter 9 prints the catalysts and risks themselves; these boxes show only when there are none
    out["catalysts"] = {"title": "Investment catalysts", "value": None,
                        "desc": "Three forward-looking catalysts from the latest report and news."}
    out["risks"] = {"title": "Downside risks", "value": None, "desc": "The two most important downside risks."}
    return out


# ---------------------------------------------------------------- chapters
def _summary(data: TearSheetData) -> dict:
    q, cons = data.quote, data.consensus
    latest_ratio = data.ratios[-1] if data.ratios else None
    cur = ccy(q.currency)
    tiles = [["Share price", f"{cur} {num(q.price, 2)}"], ["Market cap", big(q.market_cap, q.currency)],
             ["Enterprise value", big(q.enterprise_value, q.currency)], ["P/E (TTM)", mult(q.pe_ttm)],
             ["Forward P/E", mult(cons.forward_pe) if cons else "–"], ["P/B", mult(q.pb)],
             ["ROE (latest FY)", pct(latest_ratio.roe) if latest_ratio else "–"],
             ["Dividend yield (fwd)" if q.currency == "USD" else "Dividend yield", pct(q.dividend_yield)]]
    ff = None
    if data.football_field and data.football_field.bars:
        f = data.football_field
        vals = [b.low for b in f.bars] + [b.high for b in f.bars] + [f.price]
        lo, hi = min(vals), max(vals)
        ticks = _nice_ticks(max(lo - (hi - lo) * 0.05, 0), hi + (hi - lo) * 0.05, 5)
        a, b_ = ticks[0], ticks[-1]
        ff = {"currency": ccy(f.currency), "price_x": _norm(f.price, a, b_),
              "price_label": f"Price {ccy(f.currency)} {num(f.price, 2)}",
              "ticks": [[_norm(t, a, b_), f"{t:,.0f}" if t >= 100 else f"{t:g}"] for t in ticks],
              "bars": [{"label": b.label, "basis": b.basis, "x0": _norm(b.low, a, b_), "x1": _norm(b.high, a, b_),
                        "mid": _norm(b.mid, a, b_), "low": num(b.low, 2), "high": num(b.high, 2),
                        "mid_label": num(b.mid, 2) if b.mid is not None else ""} for b in f.bars]}
    if ff is not None and data.rating and data.rating.fair_value:
        f = data.football_field
        vals = [b.low for b in f.bars] + [b.high for b in f.bars] + [f.price]
        lo, hi = min(vals), max(vals)
        tk = _nice_ticks(max(lo - (hi - lo) * 0.05, 0), hi + (hi - lo) * 0.05, 5)
        fv = data.rating.fair_value
        if tk[0] <= fv <= tk[-1]:
            ff["fair_x"] = _norm(fv, tk[0], tk[-1])
            ff["fair_label"] = f"Fair value {ccy(f.currency)} {num(fv, 2)}"
    a = data.audit
    audit = {"status": a.status, "checks": [c.model_dump() for c in a.checks]} if a else None
    return {"tiles": tiles, "football": ff, "audit": audit, "rating": _safe("AI rating", lambda: _rating(data))}


def _rating(data: TearSheetData) -> Optional[dict]:
    rt = data.rating
    if not rt:
        return None
    cur = ccy(rt.currency)
    scen = rt.basis == "scenarios"
    # "risks to the fair value" (round-5 review: the paragraph a published note carries), from our scenarios
    risks_fv = ""
    sc = data.valuation.scenarios if data.valuation else None
    if scen and sc and rt.fair_value:
        by = {x.name: x for x in sc.scenarios}

        def drv(x) -> str:
            # round 8: cutting at 28 words left sentences hanging ("to turn…"); whole sentences only
            t = (x.drivers or "").strip()
            if not t:
                return ""
            import re as _re
            sents = _re.split(r"(?<=[.!?])\s+", t)
            out = sents[0]
            for nxt in sents[1:]:
                if len((out + " " + nxt).split()) > 45:
                    break
                out += " " + nxt
            return " " + (out if out.endswith((".", "!", "?")) else out + ".")
        parts = []
        if "bear" in by:
            parts.append(f"Downside: the bear case ({cur} {num(by['bear'].value_per_share, 2)}, "
                         f"{pct(by['bear'].probability, 0)} probability).{drv(by['bear'])}")
        if "bull" in by:
            parts.append(f"Upside: the bull case ({cur} {num(by['bull'].value_per_share, 2)}, "
                         f"{pct(by['bull'].probability, 0)}).{drv(by['bull'])}")
        if rt.buy_below and rt.sell_above:
            parts.append(f"At today's fair value the rating would be Buy at or below {cur} {num(rt.buy_below, 2)} and "
                         f"Sell at or above {cur} {num(rt.sell_above, 2)}; a shift in the scenario probabilities moves "
                         f"the fair value itself.")
        from ..narrative.scenarios import flip_text
        ft = flip_text(data, rt.buy_threshold, rt.sell_threshold)
        if ft:
            parts.append("Rating sensitivity at today's price: " + ft + ".")
        risks_fv = " ".join(parts)
    return {
        "risks_fv": risks_fv,
        "note": ("from our bear / base / bull scenarios; peer multiples and the model DCF are cross-checks" if scen
                 else "set by a fixed rule from the valuation below; the AI only explains it"),
        "fv_label": "Fair value (our scenarios)" if scen else "Fair value (blended)",
        "rating": rt.rating, "confidence": rt.confidence or "",
        "fair_value": f"{cur} {num(rt.fair_value, 2)}" if rt.fair_value else "–",
        "upside": pct(rt.upside, signed=True) if rt.upside is not None else "–",
        "price": f"{cur} {num(data.quote.price, 2)}",
        "methods": [[m.label, f"{cur} {num(m.value, 2)}", pct(m.weight, 0) if m.included else "–",
                     "used" if m.included else (m.note or "excluded")] for m in rt.methods],
        "cross_check": scen,
        "rule": (f"Buy if fair value is ≥ {pct(rt.buy_threshold, 0)} above the price, Sell if ≥ "
                 f"{pct(-rt.sell_threshold, 0)} below, otherwise Hold."),
        "reason": rt.reason or "",
        "buy_below": f"{cur} {num(rt.buy_below, 2)}" if rt.buy_below else "",
        "sell_above": f"{cur} {num(rt.sell_above, 2)}" if rt.sell_above else "",
        "definitions": [
            ["Buy", f"Model fair value at least {pct(rt.buy_threshold, 0)} above the share price"
                    + (f" (today: price at or below {cur} {num(rt.buy_below, 2)})" if rt.buy_below else "")],
            ["Hold", f"Fair value between {pct(rt.sell_threshold, 0, signed=True)} and "
                     f"{pct(rt.buy_threshold, 0, signed=True)} of the price"],
            ["Sell", f"Fair value at least {pct(-rt.sell_threshold, 0)} below the share price"
                     + (f" (today: price at or above {cur} {num(rt.sell_above, 2)})" if rt.sell_above else "")],
            ["Not rated", "No scenario value could be computed" if scen else
                          "Fewer than two valuation methods agree within ±50% of their median"],
        ],
    }


def _overall(data: TearSheetData) -> Optional[dict]:
    ov = data.overall
    if not ov:
        return None
    cur = ccy(data.quote.currency)
    rows = [[i.source, i.rating or "–", f"{i.score:.2f}" if i.score is not None else "–",
             pct(i.weight, 0) if i.weight else ("reference" if "reference" in i.source else "0%"), i.detail]
            for i in ov.inputs]
    votes = [f"{v.broker} {v.rating} ({v.on.strftime('%-d %b')}" + ("" if v.weight >= 1 else f", ×{v.weight:g}")
             + (f", TP {num(v.target, 0)}" if v.target else "") + ")" for v in ov.votes]
    method = (f"Scores: Sell 1 · Underperform 2 · Hold 3 · Outperform 4 · Buy 5 (the model's Buy / Hold / Sell = "
              f"5 / 3 / 1). Each broker's latest rating counts only if it is at most {ov.fresh_days} days old: fully "
              f"up to {ov.full_weight_days} days, ×{ov.older_weight:g} after that; older views are left out. A Hong "
              f"Kong news write-up newer than etnet's table updates that broker's view. The model and the brokers "
              f"share the score as shown (house weights); with few recent brokers their share "
              f"shrinks, and a model that is not rated is left out. Yahoo's consensus is shown as a cross-check only. "
              f"This summarises all views; it does not replace the AI rating below.")
    return {"rating": ov.rating, "score": f"{ov.score:.2f}", "basis": ov.basis, "rows": rows,
            "votes": " · ".join(votes), "stale": ", ".join(ov.stale), "split": ov.split_note or "",
            "targets": (f"Recent targets: median {cur} {num(ov.target_median, 2)} "
                        f"({pct(ov.target_upside, 1, signed=True)} vs the price, {ov.targets_n} "
                        f"target{'s' * (ov.targets_n != 1)})") if ov.target_median else "",
            "method": method}


def _overview(data: TearSheetData) -> dict:
    c = data.company
    facts = []
    if c:
        for label, val in (("Headquarters", c.headquarters), ("Incorporated in", c.incorporated_in),
                           ("Founded", c.founded), ("Listed / first trade", c.listed),
                           ("Chairman", c.chairman), ("Employees", f"{c.employees:,}" if c.employees else None),
                           ("Fiscal year end", c.fiscal_year_end), ("Website", c.website),
                           ("Index membership", c.index_membership)):
            if val:
                facts.append([label, str(val)])
    p = data.profile
    facts = [["Exchange", f"{p.exchange} · {p.ticker}"], ["Sector", p.sector or "–"]] + facts
    segs = []
    for s in data.segments:
        tot = sum(x.revenue for x in s.segments if x.revenue) or None
        items = []
        for x in sorted(s.segments, key=lambda x: -(x.revenue or 0))[:8]:
            share = x.share if x.share is not None else (x.revenue / tot if tot and x.revenue else None)
            items.append({"name": x.name, "frac": round(max(share, 0), 4) if share else 0,
                          "share": pct(share), "revenue": _short(x.revenue),
                          "gm": pct(x.gross_margin) if x.gross_margin is not None else "–"})
        segs.append({"title": {"business": "By business segment", "product": "By product",
                               "region": "By region"}[s.kind],
                     "period": s.period, "currency": ccy(s.currency), "source": s.source, "items": items,
                     "has_gm": any(x.gross_margin is not None for x in s.segments)})
    return {"description": (c.description if c and c.description else p.description) or "",
            "facts": facts, "segments": segs,
            "sources": ", ".join(c.sources) if c and c.sources else ""}


def _year_rows(years: list, rows: list[tuple[str, Callable, str]]) -> list[dict]:
    """Table rows, skipping any row with no data at all."""
    out = []
    for label, fn, style in rows:
        vals = [fn(y) for y in years]
        if all(v in ("–", "") for v in vals):
            continue
        out.append({"label": label, "values": vals, "style": style})
    return out


def _financial_sector(data: TearSheetData) -> bool:
    from ..quant.valuation import is_financial
    return is_financial(data)


def _financials(data: TearSheetData) -> dict:
    f = data.financials
    years = f.years[-5:]
    ry = {r.fiscal_year: r for r in data.ratios}
    cats = [f"FY{y.fiscal_year}" for y in years]
    rc = ccy(f.currency)
    r = [ry.get(y.fiscal_year, RatioYear(fiscal_year=y.fiscal_year)) for y in years]
    bank = _financial_sector(data)  # cash-flow measures are not meaningful for banks and insurers
    margins = [("Gross", S1, [x.gross_margin for x in r]), ("Operating", S2, [x.operating_margin for x in r]),
               ("Net", S3, [x.net_margin for x in r])] + ([] if bank else [("FCF", S4, [x.fcf_margin for x in r])])
    charts = [
        bar_chart(cats, [("Revenue", S1, [y.revenue for y in years]),
                         ("Net profit", S2, [y.net_income for y in years])], "amount",
                  f"Revenue and net profit ({rc})"),
        line_chart(cats, margins, "pct", "Margins (% of revenue)"),
        None if bank else bar_chart(cats, [("Operating cash flow", S1, [y.operating_cash_flow for y in years]),
                                           ("Capex", S2, [-y.capex if y.capex is not None else None for y in years]),
                                           ("Free cash flow", S3, [y.free_cash_flow for y in years])], "amount",
                                    f"Cash flow ({rc}; capex shown negative)"),
        line_chart(cats, [("ROE", S1, [x.roe for x in r]), ("ROA", S2, [x.roa for x in r]),
                          ("ROIC", S3, [x.roic for x in r])], "pct", "Returns on capital"),
    ]
    if bank:  # keep the 2x2 grid: show dividends paid instead of cash flow
        charts[2] = bar_chart(cats, [("Net profit", S1, [y.net_income for y in years]),
                                     ("Dividends paid", S2, [y.dividends_paid for y in years])], "amount",
                              f"Net profit and dividends paid ({rc})")
    dupont = _year_rows(r, [
        ("Net margin", lambda x: pct(x.net_margin), "normal"),
        ("× Asset turnover", lambda x: mult(x.asset_turnover, 2), "normal"),
        ("× Equity multiplier", lambda x: mult(x.equity_multiplier, 2), "normal"),
        ("= ROE", lambda x: pct(x.roe), "bold"),
        *([] if bank else [("Cash conversion (CFO / net profit)", lambda x: mult(x.cash_conversion, 2), "muted"),
                           ("Accruals ratio", lambda x: pct(x.accruals_ratio, signed=True), "muted")]),
    ])
    eps = bar_chart(cats, [("Diluted EPS", S1, [y.diluted_eps for y in years])], "plain",
                    f"Diluted EPS ({rc}, restated for splits)")
    return {"charts": [c for c in charts if c], "eps": eps, "years": cats, "dupont": dupont}


def _statements(data: TearSheetData) -> dict:
    f = data.financials
    years = f.years[-5:]
    ry = {r.fiscal_year: r for r in data.ratios}
    rs = [ry.get(y.fiscal_year, RatioYear(fiscal_year=y.fiscal_year)) for y in years]
    Y = FiscalYear

    def neg(attr: str) -> Callable[[Y], str]:
        return lambda y: mn(-getattr(y, attr)) if getattr(y, attr) is not None else "–"

    income = _year_rows(years, [
        ("Revenue", lambda y: mn(y.revenue), "bold"),
        ("  YoY growth", lambda y: pct(y.revenue_growth, signed=True), "sub"),
        ("Gross profit", lambda y: mn(y.gross_profit), "normal"),
        ("  Gross margin", lambda y: pct(y.gross_margin), "sub"),
        ("Selling, general & admin.", neg("sga_expense"), "normal"),
        ("Research & development", neg("rnd_expense"), "normal"),
        ("Operating profit", lambda y: mn(y.operating_income), "bold"),
        ("EBITDA", lambda y: mn(y.ebitda), "normal"),
        ("Interest expense", neg("interest_expense"), "normal"),
        ("Pre-tax profit", lambda y: mn(y.pretax_income), "normal"),
        ("Income tax", lambda y: mn(-y.income_tax) if y.income_tax is not None else "–", "normal"),
        ("Net profit to shareholders", lambda y: mn(y.net_income), "bold"),
        ("Diluted EPS", lambda y: num(y.diluted_eps, 2), "normal"),
    ])
    balance = _year_rows(years, [
        ("Cash & short-term investments", lambda y: mn(y.cash_and_equivalents), "normal"),
        ("Receivables", lambda y: mn(y.receivables), "normal"),
        ("Inventory", lambda y: mn(y.inventory), "normal"),
        ("Current assets", lambda y: mn(y.current_assets), "normal"),
        ("Total assets", lambda y: mn(y.total_assets), "bold"),
        ("Current liabilities", lambda y: mn(y.current_liabilities), "normal"),
        ("Total debt (excl. leases)", lambda y: mn(y.total_debt), "normal"),
        ("Total liabilities", lambda y: mn(y.total_liabilities), "normal"),
        ("Shareholders' equity", lambda y: mn(y.total_equity), "bold"),
        ("Net debt / (cash)", lambda y: mn(y.net_debt), "normal"),
    ])
    cash = _year_rows(years, [
        ("Operating cash flow", lambda y: mn(y.operating_cash_flow), "bold"),
        ("Capital expenditure", neg("capex"), "normal"),
        ("Free cash flow", lambda y: mn(y.free_cash_flow), "bold"),
        ("Depreciation & amortisation", lambda y: mn(y.depreciation_amortization), "normal"),
        ("Dividends paid", neg("dividends_paid"), "normal"),
        ("Share buybacks", neg("buybacks"), "normal"),
    ])
    ratio_groups = [
        ("Profitability", [("Gross margin", lambda x: pct(x.gross_margin)),
                           ("Operating margin", lambda x: pct(x.operating_margin)),
                           ("EBITDA margin", lambda x: pct(x.ebitda_margin)),
                           ("Net margin", lambda x: pct(x.net_margin)),
                           ("FCF margin", lambda x: pct(x.fcf_margin)),
                           ("SG&A / revenue", lambda x: pct(x.sga_ratio)),
                           ("R&D / revenue", lambda x: pct(x.rnd_ratio))]),
        ("Returns", [("ROE", lambda x: pct(x.roe)), ("ROA", lambda x: pct(x.roa)),
                     ("ROIC", lambda x: pct(x.roic))]),
        ("Growth", [("Revenue growth", lambda x: pct(x.revenue_growth, signed=True)),
                    ("EPS growth", lambda x: pct(x.eps_growth, signed=True))]),
        ("Balance sheet", [("Current ratio", lambda x: mult(x.current_ratio, 2)),
                           ("Debt / equity", lambda x: mult(x.debt_to_equity, 2)),
                           ("Liabilities / assets", lambda x: pct(x.liabilities_to_assets)),
                           ("Net debt / EBITDA", lambda x: mult(x.net_debt_to_ebitda, 2)),
                           ("Interest cover (EBIT / interest)", lambda x: mult(x.interest_coverage, 1))]),
        ("Efficiency", [("Asset turnover", lambda x: mult(x.asset_turnover, 2)),
                        ("Receivable days", lambda x: _days(x.receivable_days)),
                        ("Inventory days", lambda x: _days(x.inventory_days)),
                        ("Capex / revenue", lambda x: pct(x.capex_ratio))]),
        ("Cash & payout", [("Cash conversion (CFO / NP)", lambda x: mult(x.cash_conversion, 2)),
                           ("Accruals ratio", lambda x: pct(x.accruals_ratio, signed=True)),
                           ("Effective tax rate", lambda x: pct(x.effective_tax)),
                           ("Dividend payout", lambda x: pct(x.payout_ratio)),
                           ("Total payout (div. + buybacks)", lambda x: pct(x.total_payout_ratio))]),
    ]
    if _financial_sector(data):  # cash-flow and working-capital ratios mislead for banks and insurers
        drop = {"FCF margin", "Capex / revenue", "Cash conversion (CFO / NP)", "Accruals ratio", "Current ratio",
                "Receivable days", "Inventory days", "Gross margin", "Interest cover (EBIT / interest)",
                "Net debt / EBITDA", "EBITDA margin"}
        ratio_groups = [(g, [(lab, fn) for lab, fn in rows if lab not in drop]) for g, rows in ratio_groups]
    ratios = []
    for group, rows in ratio_groups:
        body = _year_rows(rs, [(label, fn, "normal") for label, fn in rows])
        if body:
            ratios.append({"group": group, "rows": body})
    return {"years": [f"FY{y.fiscal_year}" for y in years], "unit": f"{ccy(f.currency)} mn",
            "standard": f.accounting_standard or "", "income": income, "balance": balance, "cash": cash,
            "ratios": ratios}


def _grid_vm(g, price: float, fmt_row: Callable[[float], str], fmt_col: Callable[[float], str]) -> Optional[dict]:
    if g is None:
        return None
    mid_r, mid_c = len(g.rows) // 2, len(g.cols) // 2
    rows = []
    for i, (r, vals) in enumerate(zip(g.rows, g.values)):
        cells = []
        for j, x in enumerate(vals):
            tone = "na" if x is None else ("up" if x >= price else "down")
            cells.append({"text": num(x, 2) if x is not None else "–", "tone": tone,
                          "base": i == mid_r and j == mid_c})
        rows.append({"label": fmt_row(r), "cells": cells})
    return {"row_label": g.row_label, "col_label": g.col_label, "cols": [fmt_col(c) for c in g.cols], "rows": rows}


def _held_years(r, dcf) -> Optional[tuple[int, Optional[int], Optional[int]]]:
    """(held years, first solved fiscal year, last) when the reverse DCF holds the leading consensus years."""
    n = int(getattr(r, "hold_years", 0) or 0)
    if n <= 0:
        return None
    fc = list(dcf.forecast) if dcf and dcf.forecast else []
    y0 = getattr(r, "from_year", None) or (fc[n].fiscal_year if len(fc) > n else None)
    y1 = getattr(r, "to_year", None) or (fc[-1].fiscal_year if fc else None)
    return n, y0, y1


def _valuation(data: TearSheetData) -> Optional[dict]:
    v = data.valuation
    if not v:
        return None
    q = data.quote
    cur, rc = ccy(v.currency), ccy(data.financials.currency)
    out: dict[str, Any] = {"currency": cur, "notes": v.notes, "kind": "DCF" if v.dcf else "DDM" if v.ddm else None}
    w = v.wacc
    out["wacc"] = [["Risk-free rate", f"{pct(w.risk_free, 2)} ({w.risk_free_source})"],
                   ["Beta", f"{num(w.beta if w.beta is not None else 1.0, 2)} ({w.beta_method})"],
                   ["Equity risk premium", f"{pct(w.equity_risk_premium, 2)} ({w.erp_source})"],
                   ["Cost of equity", pct(w.cost_of_equity)]]
    if w.wacc is not None:
        if w.pre_tax_cost_of_debt is not None and w.debt_weight > 0:
            out["wacc"] += [["Pre-tax cost of debt", pct(w.pre_tax_cost_of_debt)], ["Tax rate", pct(w.tax_rate)]]
        out["wacc"] += [["Weights (equity / debt)", f"{pct(w.equity_weight)} / {pct(w.debt_weight)}"],
                        ["WACC", pct(w.wacc)]]
    d = v.dcf
    if d:
        out["forecast"] = {
            "years": [f"FY{x.fiscal_year}E" for x in d.forecast],
            "rows": [
                {"label": f"Revenue ({rc} mn)", "values": [mn(x.revenue) for x in d.forecast], "style": "bold"},
                {"label": "  Growth", "values": [pct(x.growth, signed=True) for x in d.forecast], "style": "sub"},
                {"label": "  Basis", "values": [x.basis for x in d.forecast], "style": "sub"},
                {"label": f"Free cash flow ({rc} mn)", "values": [mn(x.free_cash_flow) for x in d.forecast],
                 "style": "normal"},
                {"label": "Discount factor", "values": [num(x.discount_factor, 3) for x in d.forecast],
                 "style": "normal"},
                {"label": f"Present value ({rc} mn)", "values": [mn(x.present_value) for x in d.forecast],
                 "style": "bold"}]}
        b = d.bridge
        if b:
            out["bridge"] = [
                [f"PV of {len(d.forecast)}-year free cash flow", f"{rc} {mn(b.pv_forecast)} mn"],
                [f"PV of terminal value ({pct(b.terminal_share, 0)} of EV)", f"{rc} {mn(b.pv_terminal)} mn"],
                ["= Enterprise value" + (f" (rolled forward {b.roll_forward_years * 12:.0f} months at WACC)"
                                         if b.roll_forward_years else ""), f"{rc} {mn(b.enterprise_value)} mn"],
                [f"– Net debt (at {b.balance_sheet_date:%d %b %Y}; negative = net cash)" if b.balance_sheet_date
                 else "– Net debt (latest FY; negative = net cash)", f"{rc} {mn(b.net_debt)} mn"],
                *([["– Minority interests (book)", f"{rc} {mn(b.minority_interest)} mn"]] if b.minority_interest else []),
                # round-6 review: the bridge did not add up on the page (EV - net debt != equity) because the stakes
                # add-back was only in a footnote
                *([[f"+ Equity stakes outside cash (after a {STAKE_HAIRCUT:.0%} haircut)", f"{rc} {mn(b.investments)} mn"]]
                  if b.investments else []),
                ["= Equity value", f"{rc} {mn(b.equity_value)} mn"],
                ["÷ Shares (market cap / price)", f"{num(b.shares / 1e6, 1)} mn"],
                *([[f"FX ({rc} per {cur})", num(b.fx_to_reporting, 4)]] if b.fx_to_reporting != 1 else []),
                ["= Value per share", f"{cur} {num(b.value_per_share, 2)} ({pct(d.upside, signed=True)} vs price)"]]
        path = d.margin_path or [d.fcf_margin]
        out["assumptions"] = [["FCF margin" + (" (3-year median)" if len(set(round(x, 6) for x in path)) == 1
                                                else f" ({pct(path[0])} in year 1 → {pct(path[-1])} final year)"),
                               pct(d.fcf_margin)],
                              ["Terminal growth", pct(d.terminal_growth)]]
        if d.margin_basis:
            out["margin_basis"] = f"FCF margin {d.margin_basis}."
    elif v.ddm:
        m = v.ddm
        out["ddm"] = [["Dividend per share (TTM)", f"{cur} {num(m.dividend_per_share, 2)}"],
                      ["Perpetual dividend growth", pct(m.growth)], ["Cost of equity", pct(w.cost_of_equity)],
                      ["Value per share", f"{cur} {num(m.value_per_share, 2)} ({pct(m.upside, signed=True)} vs price)"]]

    s = v.sensitivity
    if s:
        out["grid1"] = _grid_vm(s.discount_growth, q.price, pct, pct)
        out["grid2"] = _grid_vm(s.margin_growth, q.price, pct, lambda c: pct(c, 0, signed=True))
    r = v.reverse
    if r:
        from ..narrative.facts import base_scenario_cagr
        _base_cagr = base_scenario_cagr(data)
        if r.model == "DCF":
            head = (f"{pct(r.implied_growth, 1)} a year" if r.implied_growth is not None else "n/a")
            held = _held_years(r, v.dcf)
            if held:
                # run 2: the reverse DCF holds the consensus years and solves only for the later ones
                n, y0, y1 = held
                span = f"FY{y0} to FY{y1}" if y0 and y1 else f"the next {r.horizon_years} years"
                headline = (f"After the {n} consensus year{'s' if n != 1 else ''}, today's price implies revenue "
                            f"growth of {head} from {span}")
                rows = [[f"Implied revenue growth, {span.replace(' to ', '–')} (constant, per year)",
                         pct(r.implied_growth, signed=True)],
                        ["Model DCF revenue growth over the same years (CAGR)", pct(r.model_growth, signed=True)]]
                note = r.note or (f"The first {n} year{'s' if n != 1 else ''} keep{'' if n != 1 else 's'} the "
                                  f"consensus revenue; WACC, terminal growth, net debt and share count stay at the "
                                  f"base case.")
            else:
                headline = f"Today's price implies revenue growth of {head} for {r.horizon_years} years"
                rows = [["Implied revenue growth (constant, per year)", pct(r.implied_growth, signed=True)],
                        ["Model DCF revenue growth (CAGR; consensus, then fade)", pct(r.model_growth, signed=True)]]
                note = r.note or "Holding WACC, terminal growth, net debt and share count at the base case."
            out["reverse"] = {
                "headline": headline,
                "rows": rows
                        + ([["Our base scenario's revenue growth (CAGR, same years)", pct(_base_cagr[0], signed=True)]]
                           if _base_cagr else [])
                        + [["Implied FCF margin at the model DCF's growth", pct(r.implied_fcf_margin)],
                           ["Model DCF FCF margin", pct(r.model_fcf_margin)]],
                "note": note}
        else:
            out["reverse"] = {
                "headline": f"Today's price implies perpetual dividend growth of {pct(r.implied_growth)}",
                "rows": [["Implied dividend growth", pct(r.implied_growth)],
                         ["Base case dividend growth", pct(r.model_growth)]],
                "note": "Holding the trailing dividend and the cost of equity at the base case."}
    mc = v.monte_carlo
    if mc:
        lo, hi = mc.bins[0], mc.bins[-1]
        top = max(mc.counts) or 1
        ticks = _nice_ticks(lo, hi, 5)
        ticks = [t for t in ticks if lo <= t <= hi] or [lo, hi]
        out["mc"] = {
            "bars": [round(c / top, 4) for c in mc.counts],
            "price_x": _norm(min(max(q.price, lo), hi), lo, hi),
            "price_inside": lo <= q.price <= hi,
            "p50_x": _norm(mc.percentiles["p50"], lo, hi),
            "ticks": [[_norm(t, lo, hi), f"{t:,.0f}" if abs(t) >= 100 else f"{t:g}"] for t in ticks],
            "rows": [["Draws (valid / total)", f"{mc.n_valid:,} / {mc.n_draws:,}"],
                     ["10th percentile", f"{cur} {num(mc.percentiles['p10'], 2)}"],
                     ["25th percentile", f"{cur} {num(mc.percentiles['p25'], 2)}"],
                     ["Median", f"{cur} {num(mc.percentiles['p50'], 2)}"],
                     ["75th percentile", f"{cur} {num(mc.percentiles['p75'], 2)}"],
                     ["90th percentile", f"{cur} {num(mc.percentiles['p90'], 2)}"],
                     ["Share of draws above today's price", pct(mc.prob_above_price, 0)]],
            "assumptions": "; ".join(
                f"{k.replace('_sd', ' s.d.').replace('_half_range', ' ± range').replace('_', ' ')} {pct(val, 2)}"
                for k, val in mc.assumptions.items()),
            "model": mc.model, "seed": mc.seed}
    band = data.pe_band
    if band:
        d0, d1 = band.series[0].d, band.series[-1].d
        vals = [p.v for p in band.series]
        # round 8: a 555x reading (EPS near zero) flattened the whole chart; the axis stops at 3x the median and
        # higher readings are drawn at the top edge (the table keeps the true range)
        cap = band.median * 3 if band.median and band.median > 0 else None
        shown = [min(v, cap) if cap else v for v in vals]
        lo, hi, ticks = _axis(shown + [band.median], include_zero=False)
        clipped = cap is not None and any(v > cap for v in vals)
        out["band"] = {
            "points": [[_time_x(p.d, d0, d1), _norm(min(p.v, hi), lo, hi)] for p in band.series],
            "median_y": _norm(band.median, lo, hi),
            "sd_lo": _norm(max(band.median - band.std, lo), lo, hi), "sd_hi": _norm(min(band.median + band.std, hi), lo, hi),
            "yticks": [[_norm(t, lo, hi), f"{t:g}x"] for t in ticks], "xlabels": _year_labels(d0, d1),
            "rows": [["Current (price / last fiscal-year EPS)", mult(band.current)], ["5-year median", mult(band.median)],
                     ["Range", f"{mult(band.low)} – {mult(band.high)}"],
                     ["Percentile of history", pct(band.percentile, 0)]],
            "rerating": _rerating(data),
            "reading": ("above" if band.current > band.median * 1.15 else
                        "below" if band.current < band.median * 0.85 else "near"),
            "note": (band.note or "") + (f" Readings above {mult(cap)} (earnings near zero) are drawn at the top of "
                                          f"the chart." if clipped else "")}
    c = data.consensus
    if c:
        ec = ccy(c.estimate_currency or data.financials.currency)
        dist = c.distribution
        total = sum(dist.values()) if dist else 0
        out["consensus"] = {
            "targets": [["Mean target", f"{cur} {num(c.target_mean, 2)}" if c.target_mean else "–"],
                        ["Median target", f"{cur} {num(c.target_median, 2)}" if c.target_median else "–"],
                        ["Range", f"{num(c.target_low, 2)} – {num(c.target_high, 2)}" if c.target_low else "–"],
                        ["Analysts", str(c.analysts) if c.analysts else "–"],
                        ["Implied vs price", pct(c.target_mean / q.price - 1, signed=True)
                         if c.target_mean and q.price else "–"]],
            "dist": [{"label": lab, "n": dist.get(k, 0), "frac": round(dist.get(k, 0) / total, 4) if total else 0}
                     for k, lab in (("strong_buy", "Strong buy"), ("buy", "Buy"), ("hold", "Hold"),
                                    ("sell", "Sell"), ("strong_sell", "Strong sell"))] if total else [],
            "estimates": [[e.period, num(e.eps_avg, 2), f"{num(e.eps_low, 2)} – {num(e.eps_high, 2)}",
                           pct(e.eps_growth, signed=True), _short(e.revenue_avg), pct(e.revenue_growth, signed=True),
                           str(e.analysts or "–")] for e in c.estimates],
            "estimate_ccy": ec, "source": c.source}
    return out


def _competitive(data: TearSheetData) -> Optional[dict]:
    c = data.comps
    if not c:
        return None

    def op_row(r, bold=False):
        rev = f"{ccy(r.revenue_currency)} {_short(r.revenue)}" if r.revenue else "–"
        return {"cells": [trim_name(r.name, 22), r.ticker if r.ticker != "MEDIAN" else "", rev,
                          pct(r.revenue_growth, signed=True), pct(r.gross_margin), pct(r.operating_margin),
                          pct(r.net_margin), pct(r.roe)], "bold": bold}
    rows = [op_row(c.target, True)] + [op_row(p) for p in c.peers] + [op_row(c.median, True)]
    # Scatter: P/E vs ROE (target highlighted, peers de-emphasised)
    pts = [(r, r.pe_ttm, r.roe) for r in [c.target] + c.peers if r.pe_ttm is not None and r.roe is not None]
    scatter = None
    if len(pts) >= 3:
        xs, ys = [p[2] for p in pts], [p[1] for p in pts]
        xlo, xhi, xt = _axis(xs, include_zero=min(xs) < 0)
        ylo, yhi, yt = _axis(ys, include_zero=False)
        scatter = {"points": [{"x": _norm(r.roe, xlo, xhi), "y": _norm(r.pe_ttm, ylo, yhi),
                               "label": trim_name(r.name, 14), "target": r is c.target} for r, _, _ in pts],
                   "xticks": [[_norm(t, xlo, xhi), f"{t * 100:.0f}%"] for t in xt],
                   "yticks": [[_norm(t, ylo, yhi), f"{t:g}x"] for t in yt],
                   "median_x": _norm(c.median.roe, xlo, xhi) if c.median.roe is not None else None,
                   "median_y": _norm(c.median.pe_ttm, ylo, yhi) if c.median.pe_ttm is not None else None}
    return {"rows": rows, "scatter": scatter, "method": c.method}


def _technical(data: TearSheetData) -> Optional[dict]:
    t = data.technicals
    if not t:
        return None
    cur = ccy(data.quote.currency)
    chart = None
    if t.chart:
        d0, d1 = t.chart[0].d, t.chart[-1].d
        vals = [p.close for p in t.chart] + [p.sma50 for p in t.chart if p.sma50] + \
               [p.sma200 for p in t.chart if p.sma200]
        lo, hi, ticks = _axis(vals, include_zero=False)

        def line(attr):
            return [[_time_x(p.d, d0, d1), _norm(getattr(p, attr), lo, hi)] for p in t.chart
                    if getattr(p, attr) is not None]
        vmax = max((p.volume for p in t.chart if p.volume), default=None)
        chart = {"series": [{"name": "Close", "color": S1, "points": line("close"), "w": 1.0},
                            {"name": "50-day average", "color": S2, "points": line("sma50"), "w": 0.8},
                            {"name": "200-day average", "color": S3, "points": line("sma200"), "w": 0.8}],
                 "yticks": [[_norm(x, lo, hi), f"{x:,.0f}" if x >= 100 else f"{x:g}"] for x in ticks],
                 "xlabels": _year_labels(d0, d1),
                 "volume": [[_time_x(p.d, d0, d1), round(p.volume / vmax, 4)] for p in t.chart if p.volume]
                 if vmax else [],
                 "rsi": [[_time_x(p.d, d0, d1), round(p.rsi / 100, 4)] for p in t.chart if p.rsi is not None]}
    reading = {"bullish": "Positive", "bearish": "Negative", "neutral": "Neutral"}
    ind = [["Price", f"{cur} {num(t.price, 2)}"],
           ["50-day / 200-day average", f"{num(t.sma50, 2)} / {num(t.sma200, 2)}"],
           ["RSI (14)", num(t.rsi14, 1)],
           ["MACD / signal / histogram", f"{num(t.macd, 2)} / {num(t.macd_signal, 2)} / {num(t.macd_hist, 2)}"],
           ["Volume vs 20-day average", mult(t.volume_ratio, 2)],
           ["52-week high / low", f"{num(t.high_52w, 2)} / {num(t.low_52w, 2)}"],
           ["From 52-week high / low", f"{pct(t.price / t.high_52w - 1, signed=True) if t.high_52w else '–'} / "
                                       f"{pct(t.price / t.low_52w - 1, signed=True) if t.low_52w else '–'}"],
           ["3-month support / resistance", f"{num(t.support, 2)} / {num(t.resistance, 2)}"]]
    beta = data.valuation.wacc.beta if data.valuation else None
    risk = [["Volatility (1Y, annualised)", pct(t.volatility_1y)],
            ["Beta vs benchmark (2Y weekly, adjusted)", num(beta, 2) if beta is not None else "–"],
            ["Max drawdown, 1 year", pct(t.max_drawdown_1y)], ["Max drawdown, 3 years", pct(t.max_drawdown_3y)]]
    bench = data.benchmark.name if data.benchmark else "Benchmark"
    returns = [[r.period, pct(r.stock, signed=True), pct(r.benchmark, signed=True),
                f"{(r.stock - r.benchmark) * 100:+.1f}pp" if r.stock is not None and r.benchmark is not None else "–"]
               for r in t.returns]
    return {"chart": chart, "indicators": ind, "risk": risk, "returns": returns, "bench": bench,
            "signals": [[s.name, reading[s.reading], s.reading] for s in t.signals],
            "overall": reading[t.overall], "overall_key": t.overall, "as_of": t.as_of.strftime("%-d %b %Y")}


NEWS_DAYS = 45   # news window shown in the report
NEWS_MIN = 5     # below this many company stories, fill with general market stories (greyed)
NEWS_FEEDS = {"US": "Yahoo Finance (latest 100 items) + Finnhub company news, week by week",
              "HK": "EastMoney news search for the company name (latest 10 items)",
              "CN": "EastMoney news search for the stock code (latest 10 items)"}


def _title_names(n, terms: list[str]) -> bool:
    """Does the headline itself (as published or translated) name the company?"""
    head = f"{n.title or ''} {n.headline_en or ''}".lower()
    return any(t in head for t in terms)


def _news(data: TearSheetData, compact: int = 0) -> dict:
    lim = _limits(compact)
    events = [[e.on.strftime("%-d %b %Y") if e.on else "–", e.label] for e in data.events]
    from ..narrative.facts import company_terms
    terms = company_terms(data)

    def about(n) -> bool:
        # run 2: company news only when a company term is in the headline (a market wrap that names the company in
        # its summary read as company news); an AI tag of "not relevant" still leaves it out
        return _title_names(n, terms) and n.relevant is not False
    # Only stories about the company, from the last NEWS_DAYS days. General market stories (which
    # feeds attach to big tickers, e.g. Yahoo tags NVDA on articles that barely mention it) are
    # used only to fill the table when fewer than NEWS_MIN company stories exist.
    cutoff = data.generated_at.timestamp() - NEWS_DAYS * 86400
    recent = [n for n in data.news if n.published is not None and n.published.timestamp() >= cutoff]  # run 4
    from ..narrative.facts import spread_by_week
    own = spread_by_week([n for n in recent if about(n)], 14)
    filler = [n for n in recent if not about(n)][: max(0, NEWS_MIN - len(own))]
    shown_news = (own[:lim["news"]] + filler)[:max(lim["news"], NEWS_MIN)]
    news = [{"date": n.published.strftime("%-d %b %Y") if n.published else "–",
             "title": n.headline_en or n.title, "original": n.title if n.headline_en else "",
             "source": n.source or "", "category": n.category or "", "sentiment": n.sentiment or "",
             "relevant": about(n), "url": n.url or ""} for n in shown_news]
    span = [n.published for n in own if n.published]
    feed = NEWS_FEEDS.get(data.profile.market.value, "")
    n_own = sum(1 for n in shown_news if about(n))
    news_note = (f"{len(own)} {'story' if len(own) == 1 else 'stories'} naming the company in the headline in the "
                 f"last {NEWS_DAYS} days" + (f" ({min(span):%-d %b} – {max(span):%-d %b %Y})" if span else "")
                 + (f", {n_own} shown, spread across the weeks" if n_own < len(own) else "")
                 + (f"; {len(filler)} general market {'story' if len(filler) == 1 else 'stories'} added in grey"
                    if filler else "") + f". Feed: {feed}.")
    divs = None
    if data.dividends:
        cur = ccy(data.quote.currency)
        this_year = data.generated_at.year
        cats = [f"{d.year}{' YTD' if d.year == this_year else ''}" for d in data.dividends]
        divs = {"chart": bar_chart(cats, [("Dividend per share", S1, [d.dps for d in data.dividends])], "plain",
                                   f"Cash dividends per share by payment year ({cur})"),
                "rows": [[c, num(d.dps, 2 if d.dps >= 0.1 else 4)] for c, d in zip(cats, data.dividends)],
                "currency": cur}
    n = data.narrative
    cats_ = [b.model_dump() for b in n.catalysts] if n and n.catalysts else []
    risks = [b.model_dump() for b in n.risks] if n and n.risks else []
    ann = sorted(data.announcements, key=lambda a: (not a.important, -a.on.toordinal()))[:lim["announcements"]]
    ann.sort(key=lambda a: a.on, reverse=True)
    left = len(data.announcements) - len(ann) + data.announcements_routine
    announcements = {"rows": [{"date": a.on.strftime("%-d %b %Y"), "kind": a.kind,
                               "title": a.title if a.title != a.kind else "Open the filing", "url": a.url,
                               "important": a.important, "source": a.source} for a in ann],
                     "note": (f"{len(data.announcements)} filings in the last 90 days; the most important "
                              f"{len(ann)} shown" + (f", {left} routine or older ones left out" if left else "")
                              + ". Bold = results, dividends, buybacks, deals, management changes or warnings.")}
    return {"events": events, "news": news, "news_note": news_note, "dividends": divs, "catalysts": cats_,
            "risks": risks, "announcements": announcements}


def _ownership(data: TearSheetData) -> dict:
    o = data.ownership
    out: dict[str, Any] = {"officers": [[x.name, x.title, str(x.age) if x.age else "–",
                                         f"{ccy(x.currency)} {_short(x.total_pay)}" if x.total_pay else "–"]
                                        for x in data.officers],
                           "pay": any(x.total_pay for x in data.officers)}
    if not o:
        return out
    split = []
    if o.insiders_pct is not None:
        split.append(["Insiders", o.insiders_pct])
    if o.institutions_pct is not None:
        split.append(["Institutions", o.institutions_pct])
    if split:
        other = max(1 - sum(x[1] for x in split), 0)
        split.append(["Other / public", other])
    out["split"] = [{"label": lab, "frac": round(v, 4), "text": pct(v)} for lab, v in split]
    out["holders_title"] = o.holders_title
    out["as_of"] = o.as_of.strftime("%-d %b %Y") if o.as_of else ""
    out["holders"] = [[trim_name(h.name, 40), HOLDER_EN.get(h.kind or "", h.kind or ""),
                       _short(h.shares) if h.shares else "–",
                       "<0.01%" if h.pct is not None and 0 < h.pct < 0.00005 else pct(h.pct, 2),
                       (_short(h.change) if h.change else "–") if h.change is None or h.change <= 0
                       else "+" + _short(h.change)] for h in o.holders[:10]]
    out["insiders"] = [[x.on.strftime("%-d %b %Y") if x.on else "–", trim_name(x.name, 26),
                        HOLDER_EN.get(x.position or "", x.position or ""),
                        x.action, _short(x.shares), _short(x.value) if x.value else "–"]
                       for x in o.insider_transactions[:10]]
    names = {"overallRisk": "Overall", "auditRisk": "Audit", "boardRisk": "Board",
             "compensationRisk": "Compensation", "shareHolderRightsRisk": "Shareholder rights"}
    out["governance"] = [{"label": names[k], "score": v, "frac": round(v / 10, 2)}
                         for k, v in sorted(o.governance_risk.items(), key=lambda kv: list(names).index(kv[0]))]
    out["short"] = (f"Short interest: {pct(o.short_pct_float, 1)} of the free float"
                    + (f", {num(o.short_ratio, 1)} days to cover" if o.short_ratio is not None else "")
                    + (f" ({pct(o.short_change, 0, signed=True)} vs the prior month)" if o.short_change is not None else "")
                    + (f", as of {o.short_as_of.strftime('%-d %b %Y')}" if o.short_as_of else "")
                    + " (exchange data via Yahoo Finance).") if o.short_pct_float is not None else ""
    out["sources"] = ", ".join(o.sources)
    return out


HOLDER_EN = {"实益拥有人": "Beneficial owner", "受控法团权益": "Controlled corporation", "投资经理": "Investment manager",
             "核准借出代理人": "Approved lending agent", "保管人": "Custodian", "配偶权益": "Interest of spouse",
             "信托受益人": "Trust beneficiary", "受托人": "Trustee", "大股东所控制的法团的权益": "Controlled corporation",
             "对股份持有保证权益的人": "Security interest holder", "全权信托成立人": "Founder of trust",
             "流通A股": "Tradable A-shares", "流通H股": "Tradable H-shares", "限售流通A股": "Restricted A-shares",
             "流通受限股份": "Restricted shares"}


def _prose(text: str) -> bool:
    """True for running text; False for table-of-contents or list fragments (mostly short lines)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False

    def width(ln: str) -> int:  # a CJK character is about two Latin characters wide
        return len(ln) + sum(1 for ch in ln if "\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef")
    short = sum(1 for ln in lines if width(ln) < 45)
    return short / len(lines) < 0.5


def _excerpt(text: str, limit: int = 700) -> str:
    text = " ".join(ln.strip() for ln in text.splitlines() if ln.strip())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut.rsplit(" ", 1)[0] if " " in cut[-40:] else cut) + " …"


def _filings(data: TearSheetData, compact: int = 0) -> list[dict]:
    out = []
    limit = _limits(compact)["excerpt"]
    for f in data.filings:
        sections = [[name, _excerpt(text, limit)] for name, text in f.sections.items() if _prose(text)]
        skipped = [name for name, text in f.sections.items() if not _prose(text)]
        out.append({"source": f.source, "title": f.title, "filed": f.filed.strftime("%-d %b %Y") if f.filed else "",
                    "url": f.url, "sections": sections, "skipped": skipped})
    return out


_TOPIC_LABEL = {"guidance": "Guidance", "results": "Results", "quality": "Earnings quality", "policy": "Policy",
                "events": "Event", "capital": "Capex", "competition": "Competition", "street": "Street",
                "catalysts": "Upcoming", "other": "Other"}


RESEARCH_ROWS = 24


def _research(data: TearSheetData, compact: int = 0) -> dict:
    b = data.research
    if not b or not b.facts:
        return {"rows": [], "gaps": [], "note": ""}
    from ..research.desk import TOPIC_ORDER, source_en
    # the brief lists facts round-robin by topic, most important first: the first RESEARCH_ROWS cover every topic;
    # shown grouped by topic (round 3 reviewers: "cut the research-notes dump to what supports the thesis")
    # round 8: every note the text cites must be in the table (readers could not look up R37, R51, ...), with the key
    # facts from the latest results documents; the rest fill up to RESEARCH_ROWS
    import json as _json
    import re as _re
    blob = _json.dumps(data.narrative.model_dump(mode="json") if data.narrative else {})
    if data.forecast:
        blob += _json.dumps(data.forecast.model_dump(mode="json"))
    if data.valuation and data.valuation.scenarios:
        blob += _json.dumps(data.valuation.scenarios.model_dump(mode="json"))
    aq = data.analyst_questions
    if aq is not None:  # 12 Nov 2026: the notes the why-now lines (and, in the deep report, the answers) cite
        deep_ = bool(data.narrative and data.narrative.deep)
        blob += " ".join(f"{q.why_now} {q.answer if deep_ else ''}" for q in aq.questions)
    cited = set(_re.findall(r"\bR\d{1,3}\b", blob))
    must = [f for f in b.facts if f.id in cited or getattr(f, "key", "")]
    cap = _limits(compact)["research"]
    if cap is None:
        rest = [f for f in b.facts if f not in must][:max(0, RESEARCH_ROWS - len(must))]
    else:
        # page fit (run 2): cited and key notes only, cited and key first, then cited, then key, in the brief's order
        must = sorted(must, key=lambda f: (0 if f.id in cited and getattr(f, "key", "") else
                                           1 if f.id in cited else 2))[:cap]
        rest = []
    shown = sorted(must + rest, key=lambda f: (TOPIC_ORDER.index(f.topic) if f.topic in TOPIC_ORDER else 99,
                                               int(f.id[1:]) if f.id[1:].isdigit() else 0))
    rows = [[f.id, f.published.strftime("%-d %b %Y") if f.published else "", _TOPIC_LABEL.get(f.topic, "Other"),
             f.text, source_en(f.source, f.url or ""), f.url or ""] for f in shown]
    gaps = [g.split(" (")[0].split(",")[0].rstrip("?") for g in b.gaps]
    if len(b.facts) <= len(shown):
        more = ""
    elif cap is None:
        more = (f" Shown: the {len(shown)} cited in the text, the key facts and the most important others; all "
                f"{len(b.facts)} are in the data pack.")
    else:
        more = (f" Shown: {len(shown)} of the notes cited in the text and the key facts; all {len(b.facts)} are in "
                f"the data pack.")
    note = (f"{len(b.facts)} facts from {b.docs_read} documents ({b.chunks_read} excerpts read by the AI).{more} Each fact's "
            f"quote was found verbatim in its document and every figure in it appears in the quote; "
            f"{b.facts_dropped} extracted facts failed that check and were dropped.")
    return {"rows": rows, "gaps": gaps, "note": note}


METHODOLOGY = [
    "Numbers are computed in code from the sources listed; the AI model only writes words and every figure "
    "it quotes is checked against the data (number guardrail).",
    "Wording checks in code (adapted from FinRobot V2's audit operators) run on every AI draft: a rise / fall verb "
    "must match the figures it describes, statement amounts must carry the reporting currency and prices the trading "
    "currency, fiscal years must be covered by the data, a rating against a large one-year share-price move must be "
    "explained, and bank / loss-maker metrics must suit the company. Problems are sent back for a rewrite.",
    "Deep mode (when shown): an analyst step, a bull and a bear case, rebuttals, a judge and a reviewer, each an "
    "AI model call (the analysis, debate, judge and reviewer reason step by step first). Every argument must cite "
    "numbered "
    "evidence; code removes arguments that cite nothing, quote figures not in the data, or rest only on evidence whose "
    "sign supports the other side. The judge says which side the evidence favours but never sets the rating. The "
    "reviewer must quote the draft; the writer then revises its own draft. Bull / bear / judge rules adapted from "
    "FinRobot (AI4Finance Foundation, Apache-2.0).",
    "Fiscal-year label = calendar year of the period end. EPS is restated onto today's share basis after splits "
    "and bonus issues.",
    "Total debt = borrowings + bonds/notes, excluding lease liabilities. Cash includes short-term deposits and "
    "investments. Enterprise value = market cap + net debt + minority interests from the latest reported balance "
    "sheet (the latest interim period where available), at spot FX.",
    "Ratios use average opening and closing balances; the oldest year has no opening balance, so its return and "
    "turnover ratios are left blank. ROIC = operating profit × (1 – tax rate) "
    "÷ (equity + debt – cash). Accruals ratio = (net profit – operating cash flow) ÷ average assets.",
    "WACC: risk-free rate (10-year government bond) + beta (2-year weekly, Blume-adjusted) × equity risk premium "
    "(Damodaran) for the cost of equity; after-tax cost of debt = interest ÷ average debt.",
    "DCF (FCFF): analyst-consensus revenue for the years covered, then the growth above the terminal rate halves "
    "each year (the same fade as our scenarios); FCF margin starts at the trailing-twelve-month margin and moves "
    "halfway back to the 3-year median; Gordon terminal value. Banks and insurers use a dividend discount model.",
    "Reverse DCF holds every other input at the base case and solves for the constant revenue growth (or FCF margin) "
    "that equals today's price. Monte Carlo: 5,000 seeded draws of growth, margin, WACC and terminal growth; draws "
    "where WACC is within 3pp of terminal growth are discarded.",
    "Football field: peer multiples' interquartile range applied to the company's own TTM EPS (price ÷ P/E), latest "
    "EBITDA and book value (price ÷ P/B). Analyst targets are third-party consensus, not an InvestSync view.",
    "{RATING_METHOD}",
    "Buy-below / sell-above: the price levels at which the same rule would give Buy or Sell (fair value ÷ 1.15 and "
    "fair value ÷ 0.90 with today's thresholds).",
    "Overall view (page 1): the AI rating and every broker's latest view combined on one 1–5 score (Sell 1 … Buy 5; "
    "model Buy / Hold / Sell = 5 / 3 / 1). Only recent broker views count: fully up to 30 days old, half weight to 90 "
    "days, older ones left out and listed. The model counts one third and the brokers two thirds; with fewer than "
    "three recent brokers their share shrinks in proportion, and a model that is not rated is left out. When the model "
    "and the brokers are two or more steps apart the view is flagged as split. Yahoo's analyst consensus is shown as a "
    "cross-check only. The weights are fixed house settings. The overall view summarises all views; it is not a "
    "separate InvestSync rating.",
    "Broker research: A-share reports from EastMoney's research centre (rating, EPS forecasts, price target, the "
    "broker's own summary and PDF); HK brokers' latest ratings, targets and EPS forecasts from etnet; US rating "
    "actions from Yahoo Finance. HK and US reports are not public, so the text summarised for them is a news "
    "write-up of each note: AAStocks' 《大行》 articles (HK; kept when the article's first sentence names the company "
    "or it covers no other stock; rating and target read only when stated once, in the trading currency) and, for "
    "US actions, a same-day article naming the firm and the company (Finnhub / Yahoo news; template lines that only "
    "repeat the action are skipped). Write-ups are shown and summarised but never counted. Ratings are mapped onto "
    "Buy / Outperform / Hold / Underperform / Sell. Comparisons use each broker's latest note; targets more than 5× "
    "or less than 0.2× the price are ignored. Estimate trend = median forecast in the last 30 days vs 31–120 days "
    "ago. English summaries are AI-written from each broker's own summary or the write-up and may only quote "
    "figures that appear in it.",
    "History: each run saves headline figures (price, rating, fair value, brokers' median target and EPS) so the "
    "next report can show what changed and how long the rating has held.",
    "Technical indicators are standard formulas on adjusted daily closes (SMA, Wilder RSI, MACD 12/26/9) and a simple "
    "rule vote; they describe price behaviour and are not trading signals.",
    "Data audit: automatic cross-checks (freshness, balance-sheet coherence, P/E and share count against independent "
    "sources, cash backing of earnings, peer count, valuation stability, commentary guardrail).",
]


SECTION_TOPICS = {
    "summary": ("market", "prices", "consensus", "peers", "rates"),
    "overview": ("profile", "market", "segments"),
    "financials": ("statements",),
    "valuation": ("statements", "rates", "assumptions", "market", "consensus", "prices"),
    "competitive": ("peers", "market"),
    "technical": ("prices",),
    "news": ("news", "events", "dividends", "announcements"),
    "ownership": ("ownership", "market"),
    "filings": ("filings",),
    "street": ("research", "consensus"),
}


def _short_url(u: str, limit: int = 58) -> str:
    u = u.replace("https://", "").replace("http://", "")
    return u if len(u) <= limit else u[: limit - 1] + "…"


def _citations(data: TearSheetData) -> dict[str, Any]:
    rows = [{"n": c.n, "what": c.what, "publisher": c.publisher, "via": c.via, "url": c.url,
             "url_short": _short_url(c.url),
             "retrieved": c.retrieved.strftime("%-d %b %Y %H:%M") if c.retrieved else "at report time"}
            for c in data.citations]
    refs = {}
    for section, topics in SECTION_TOPICS.items():
        ns = [c.n for c in data.citations if c.topic in topics]
        refs[section] = "Sources: " + " ".join(f"[{n}]" for n in ns) + " (see the last chapter)" if ns else ""
    return {"rows": rows, "refs": refs}


# ---------------------------------------------------------------- 1.5: scorecard, street view, since last
def _scorecard(data: TearSheetData) -> Optional[dict]:
    sc = data.scorecard
    if not sc:
        return None

    def area(a):
        return {"title": a.title, "score": a.score, "available": a.available, "note": a.note or "",
                "frac": a.score / a.available if a.available else 0.0,
                "checks": [{"name": c.name, "status": "na" if c.passed is None else "pass" if c.passed else "fail",
                            "detail": c.detail} for c in a.checks]}
    return {"areas": [area(a) for a in sc.areas], "piotroski": area(sc.piotroski) if sc.piotroski else None}


ACTION_LABEL = {"upgrade": "▲ upgrade", "downgrade": "▼ downgrade", "initiate": "● initiate", "maintain": "maintain"}


def _street(data: TearSheetData, compact: int = 0, data_only: bool = False) -> Optional[dict]:
    st = data.street
    if not st or not st.notes:
        return None
    cur, ecur = ccy(st.currency), ccy(st.eps_currency)
    rated = sum(st.rating_counts.values()) or 1
    order = ["Buy", "Outperform", "Hold", "Underperform", "Sell"]
    mix = [{"label": k, "frac": st.rating_counts.get(k, 0) / rated, "text": str(st.rating_counts.get(k, 0))}
           for k in order if k in st.rating_counts or k in ("Buy", "Hold", "Sell")]
    # price-target strip: one dot per broker, the price, the brokers' median and the model fair value
    strip = None
    tg = {}
    for n in st.notes:
        if n.target and n.broker not in tg and data.quote.price and 0.2 <= n.target / data.quote.price <= 5:
            tg[n.broker] = n.target
    if len(tg) >= 2:
        vals = list(tg.values()) + [data.quote.price] + ([st.model_fair_value] if st.model_fair_value else [])
        lo, hi = min(vals), max(vals)
        ticks = _nice_ticks(lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06, 5)
        a, b = ticks[0], ticks[-1]
        strip = {"dots": [_norm(v, a, b) for v in tg.values()],
                 "ticks": [[_norm(t, a, b), f"{t:,.0f}" if t >= 100 else f"{t:g}"] for t in ticks],
                 "refs": [[_norm(data.quote.price, a, b), f"Price {num(data.quote.price, 2)}", "#B3261E"]]
                 + ([[_norm(st.target_median, a, b), f"Brokers' median {num(st.target_median, 2)}", S1]]
                    if st.target_median else [])
                 + ([[_norm(st.model_fair_value, a, b), f"InvestSync model {num(st.model_fair_value, 2)}", INK]]
                    if st.model_fair_value else []),
                 "currency": cur}
    eps_rows = [[e.period, str(e.n), f"{num(e.low, 2)} – {num(e.high, 2)}", num(e.median, 2), pct(e.spread, 0),
                 pct(e.vs_last_actual, 1, signed=True) if e.vs_last_actual is not None else "–",
                 pct(e.vs_consensus, 1, signed=True) if e.vs_consensus is not None else "–"] for e in st.eps]
    periods = [e.period for e in st.eps][:2]
    notes = []
    for n in st.notes[:_limits(compact)["broker_notes"]]:  # round 8: the full list read as padding; all are in the data pack
        tgt = "–"
        if n.target:
            tgt = (f"{num(n.previous_target, 0)} → {num(n.target, 0)}"
                   if n.previous_target and n.previous_target != n.target else num(n.target, 2))
        orig = f" ({n.rating_original})" if n.rating_original and n.rating_original != n.rating else ""
        notes.append({"date": n.on.strftime("%-d %b %Y"), "broker": trim_name(n.broker, 24),
                      "rating": (n.rating or "–") + orig, "action": ACTION_LABEL.get(n.action or "", ""),
                      "target": tgt, "eps": [num(n.eps[p], 2) if p in n.eps else "–" for p in periods],
                      "url": n.url or "", "link": "PDF" if (n.url or "").lower().endswith(".pdf") else "source"})
    summaries = []
    for n in st.texts()[:4]:
        w = any(n is x for x in st.writeups)
        summaries.append({"date": n.on.strftime("%-d %b %Y"), "broker": n.broker, "local": n.broker_local or "",
                          "rating": n.rating or "", "title": n.title or "", "summary_en": n.summary_en or "",
                          # the data-only edition has no AI summary: a longer excerpt as published
                          "excerpt": "" if n.summary_en else _excerpt(n.abstract or "", 280 if data_only else 150),
                          "url": n.url or "", "analysts": n.analysts or "", "via": n.source if w else "",
                          "link": "article" if w else "report",
                          "target": (f"TP {num(n.previous_target, 0)} → {num(n.target, 0)}"
                                     if n.previous_target and n.target and n.previous_target != n.target
                                     else f"TP {num(n.target, 2)}" if n.target else "")})
    via = sorted({n.source for n in st.writeups})
    if st.market.value == "HK":
        credit = ("Hong Kong brokers sell their reports to clients, so the text is not public: the notes summarised "
                  "here are AAStocks' 《大行》 news write-ups of each broker's note, linked; ratings, targets and EPS "
                  "in the counts come from etnet's table. ")
    elif st.market.value == "US":
        credit = ("US brokers sell their reports to clients: the counts use rating actions compiled by Yahoo Finance, "
                  "and the notes summarised here are news articles about the same actions"
                  + (f" ({', '.join(via)})" if via else "") + ", linked. ")
    else:
        credit = ""
    if data_only:  # nothing is summarised in the data-only edition
        credit = credit.replace("summarised here", "shown here")
    rev = st.revision
    return {
        "source": st.source, "source_url": st.source_url or "", "market": st.market.value,
        "findings": st.findings, "mix": mix, "strip": strip, "agreement": st.agreement or "",
        "agreement_reason": st.agreement_reason or "", "eps_currency": ecur, "currency": cur,
        "eps_rows": eps_rows, "periods": periods, "notes": notes, "summaries": summaries,
        "summaries_title": "What the latest reports argue" if not st.writeups else "What the latest notes argue",
        "summaries_note": ((("each broker's own summary" if not st.writeups
                             else "news write-ups of each broker's note (" + ", ".join(via) + ")")
                            + (", first lines as published" if data_only else ", condensed"))),
        "writeups_from": ", ".join(via), "credit": credit,
        "revision": (f"{rev.period}: {ecur} {num(rev.earlier_median, 2)} ({rev.earlier_n} brokers, 31–120 days ago) → "
                     f"{num(rev.recent_median, 2)} ({rev.recent_n} brokers, last {rev.recent_days} days), "
                     f"{pct(rev.change, 1, signed=True)}") if rev else "",
        "synthesis": _ask("street", compact, STREET_ASK) if data_only else
                     {"title": "Street view", "value": st.synthesis or None,
                      "desc": "Where the brokers agree and differ, and how their view compares with the InvestSync "
                              "model, written from the comparisons above and the "
                              + ("brokers' own summaries." if not st.writeups else "write-ups of their notes.")},
    }


def _since_last(data: TearSheetData) -> Optional[dict]:
    s = data.since_last
    if not s:
        return None
    return {"date": s.previous_date.strftime("%-d %b %Y"), "changes": s.changes,
            "since": (f"{data.rating.rating} since {s.rating_since.strftime('%-d %b %Y')}"
                      if s.rating_since and data.rating else "")}


def _rerating(data: TearSheetData) -> str:
    from ..quant.ranges import rerating
    try:
        return rerating(data) or ""
    except Exception:
        return ""


def _preview(data: TearSheetData) -> Optional[dict]:
    """Results preview box when results are due within 45 days (round-5 reviews: "a 17 Nov earnings-preview box"):
    consensus for the quarter to be reported and the one after (third party), and what our forecast implies for
    the rest of the year against the same quarters. Figures from code; no AI."""
    q, c = data.quote, data.consensus
    ne, asof = q.next_earnings_date, q.as_of
    asof = asof.date() if hasattr(asof, "date") and callable(asof.date) else asof
    if not (ne and asof and 0 <= (ne - asof).days <= 45 and c and c.quarters):
        return None
    cur = ccy(c.estimate_currency or data.financials.currency)
    rows = [[x.period + (f" (results {ne.strftime('%-d %b')})" if i == 0 else ""),
             mn(x.revenue_avg) if x.revenue_avg else "–",
             pct(x.revenue_growth, 1, signed=True) if x.revenue_growth is not None else "–",
             num(x.eps_avg, 2) if x.eps_avg is not None else "–",
             pct(x.eps_growth, 1, signed=True) if x.eps_growth is not None else "–",
             str(x.analysts) if x.analysts else "–"] for i, x in enumerate(c.quarters)]
    ours = data.forecast.remainder if data.forecast and data.forecast.remainder else ""
    opt = (f"Options expiring {q.implied_move_expiry.strftime('%-d %b')} price a move of about "
           f"±{q.implied_move:.1%} from the {asof.strftime('%-d %b')} close (at-the-money call + put ÷ price; last "
           f"trades, Yahoo Finance). It includes ordinary volatility to that date, not only the results."
           if q.implied_move and q.implied_move_expiry else "")
    return {"title": f"Results preview · {ne.strftime('%-d %b %Y')}", "rows": rows, "ours": ours, "options": opt,
            "rev_head": f"Revenue (consensus, {cur} mn)",
            "note": "Consensus: Yahoo Finance (third party; EPS on the analysts' adjusted basis). Management's guidance "
                    "for the quarter is in the research notes and the report text."}


def _disclosures(data: TearSheetData) -> dict:
    """Who produced the report and the rating history for this stock (round-4/5 reviews: no certification,
    rating history or conflicts statement). Honest for an automated note: there is no analyst to certify."""
    from .. import history
    ai = data.narrative.model if data.narrative and data.narrative.model else ""
    producer = ("Produced automatically by InvestSync Research Tools" + (f", with the AI model {ai} setting the "
                "forecast and scenario assumptions and writing the text" if ai else "") + ". No individual analyst "
                "wrote or reviewed it before release, so it carries no analyst certification. The tool holds no "
                "positions and does not know the holdings of club members; readers should state their own positions "
                "when they discuss it.")
    rows = []
    try:
        runs = [r for r in history._load(data.profile.ticker) if r.get("date")][-6:]
    except Exception:
        runs = []
    cur = ccy(data.quote.currency)
    for r in runs:
        rows.append([r["date"], r.get("rating") or "–",
                     f"{cur} {num(r['fair_value'], 2)}" if r.get("fair_value") else "–",
                     f"{cur} {num(r['price'], 2)}" if r.get("price") else "–",
                     {"scenarios": "our scenarios", "rule": "rule blend"}.get(r.get("basis") or "",
                                                                             "rule blend (before tracking)")])
    # rating distribution: the latest saved rating of every stock this tool has rated
    dist = {}
    try:
        import os
        base = Path(os.getenv("INVESTSYNC_HISTORY_DIR", str(history.ROOT / "data" / "history")))
        for d in (base.iterdir() if base.exists() else []):
            runs = [r for r in history._load(d.name) if r.get("rating") in ("Buy", "Hold", "Sell")]
            if runs:
                k = runs[-1]["rating"]
                dist[k] = dist.get(k, 0) + 1
    except Exception:
        dist = {}
    n = sum(dist.values())
    distribution = (f"Rating distribution (latest saved rating of each of the {n} stocks this tool has rated): "
                    + " · ".join(f"{k} {dist.get(k, 0)} ({dist.get(k, 0) / n:.0%})" for k in ("Buy", "Hold", "Sell"))
                    + ".") if n else ""
    return {"producer": producer, "history": rows, "distribution": distribution}


def _disclosures_data_only() -> dict:
    """The data-only edition: who produced it, without the rating history and distribution (it has no rating)."""
    return {"producer": "Produced automatically by InvestSync Research Tools from the sources listed above. This "
                        "data-only edition contains no AI-written text and no rating. No analyst wrote or reviewed "
                        "it before release, so it carries no analyst certification. The tool holds no positions and "
                        "does not know the holdings of club members; readers should state their own positions when "
                        "they discuss it.",
            "history": [], "distribution": ""}


# methodology paragraphs about the AI steps, the rating or its history: left out of the data-only edition
_AI_METHOD = ("Numbers are computed in code", "Wording checks", "Deep mode", "{RATING_METHOD}", "Buy-below",
              "Overall view", "History:")


def _methodology_data_only() -> list[str]:
    out = ["Numbers are computed in code from the sources listed. This data-only edition contains no AI-written text "
           "and no rating: the valuation figures are calculations from the stated assumptions, not a recommendation "
           "or a price target, and the boxes marked Your analysis are for the reader's own view."]
    for m in METHODOLOGY:
        if m.startswith(_AI_METHOD):
            continue
        m = m.replace(" (the same fade as our scenarios)", "").replace(", commentary guardrail)", ")")
        m = m.replace("the text summarised for them", "the text shown for them")
        m = m.replace("Write-ups are shown and summarised but never counted.",
                      "Write-ups are shown (first lines, as published) but never counted.")
        out.append(m.split(" English summaries are AI-written")[0])
    return out


def _methodology(data: TearSheetData) -> list[str]:
    """The fixed paragraphs, with the rating paragraph for this report's basis; the overall view's only when shown."""
    from ..quant.rating import method_note
    rt = data.rating
    th = (rt.buy_threshold, rt.sell_threshold) if rt else (0.15, -0.10)
    out = []
    for m in METHODOLOGY:
        if m == "{RATING_METHOD}":
            out.append(method_note(rt, *th))
        elif m.startswith("Overall view (page 1)") and data.overall is None:
            continue
        elif m.startswith("Buy-below / sell-above") and rt and rt.basis == "scenarios":
            out.append(m.replace("the same rule", "the same thresholds"))
        else:
            out.append(m)
    return out


def _methodology_extra(data: TearSheetData) -> list[str]:
    out = [data.research.method] if data.research and data.research.facts else []
    if data.forecast:
        out.append("Our forecast: the AI analyst sets revenue growth, gross and operating margins, the tax rate and "
                   "the share-count change for each of the next three fiscal years, citing the research notes; code "
                   "builds revenue, operating and net profit and EPS, compares them with consensus, and checks what the "
                   "first year implies for the months not yet reported (an implausible gap is sent back once).")
    if data.rating and any("analyst scenarios" in (m.label or "") for m in data.rating.methods):
        out.append("In this report the DCF method in the rating blend is the probability-weighted value of the "
                   "analyst's bear / base / bull scenarios (base case = our forecast; assumptions set by the AI with "
                   "cited evidence, bounded and computed in code with the model's DCF), in place of the model's "
                   "mechanical DCF.")
    return out


def _forecast(data: TearSheetData) -> Optional[dict]:
    """1.9: the house forecast table (AI drivers, figures computed in code) with consensus alongside."""
    f = data.forecast
    if not f or not f.years:
        return None
    rc, ys = ccy(f.currency), f.years
    has_c = any(y.consensus_revenue for y in ys)
    rows = [{"label": f"Revenue ({rc} mn)", "values": [mn(y.revenue) for y in ys], "style": "bold"},
            {"label": "  Growth", "values": [pct(y.revenue_growth, signed=True) for y in ys], "style": "sub"}]
    if has_c:
        rows += [{"label": f"  Consensus ({rc} mn)", "values": [mn(y.consensus_revenue) if y.consensus_revenue else "–"
                                                                for y in ys], "style": "muted"},
                 {"label": "  Ours vs consensus", "values": [pct(y.revenue_vs_consensus, signed=True)
                                                              if y.revenue_vs_consensus is not None else "–" for y in ys],
                  "style": "sub"}]
    if any(y.gross_margin is not None for y in ys):
        rows.append({"label": "Gross margin", "values": [pct(y.gross_margin) if y.gross_margin is not None else "–"
                                                         for y in ys], "style": "normal"})
    rows += [{"label": "Operating margin", "values": [pct(y.operating_margin) for y in ys], "style": "normal"}]
    if any(y.other_income_share is not None for y in ys):
        rows.append({"label": "  Below operating line (% of rev.)",
                     "values": [pct(y.other_income_share, signed=True) if y.other_income_share is not None else "–"
                                for y in ys], "style": "sub"})
    rows += [{"label": f"Net profit ({rc} mn)", "values": [mn(y.net_income) for y in ys], "style": "normal"},
             {"label": f"EPS ({rc})", "values": [num(y.eps, 2) for y in ys], "style": "bold"},
             {"label": "  Growth", "values": [pct(y.eps_growth, signed=True) if y.eps_growth is not None else "–"
                                              for y in ys], "style": "sub"}]
    if any(y.consensus_eps for y in ys):
        rows.append({"label": "  Consensus EPS" + (" (adjusted basis)" if f.consensus_note else ""),
                     "values": [(num(y.consensus_eps, 2) + (f" ({pct(y.consensus_eps_growth, signed=True)})"
                                                            if y.consensus_eps_growth is not None else ""))
                                if y.consensus_eps else "–" for y in ys], "style": "muted"})
    drivers = [[k, label_ids(v, data.research)] for k, v in (("Revenue", f.revenue_drivers), ("Margins", f.margin_drivers),
                                   ("Versus consensus", f.vs_consensus), ("Key risk", f.key_risk)) if v]
    notes = [x for x in (f.remainder, f.consensus_note, f.note,
                         "Consensus: Yahoo Finance (third-party)." if has_c else None) if x]
    return {"years": [y.period for y in ys], "rows": rows, "drivers": drivers, "note": " ".join(notes)}


def _bridge(data: TearSheetData) -> list:
    from ..narrative.scenarios import bridge
    try:
        return bridge(data)
    except Exception:  # a display aid; never fail a report over it
        return []


_ID_CITE = re.compile(r"\[((?:[A-Z]+-?\d+)(?:\s*[,;]\s*[A-Z]+-?\d+)*)\]")


def _note_start(text: str, n: int = 10) -> str:
    """The start of a note, for a label: up to the first comma or colon, at most ``n`` words."""
    w = re.split(r"[,;:(]", re.sub(r"\s+", " ", text or ""), maxsplit=1)[0].strip().rstrip(".").split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


_LABELS = contextvars.ContextVar("report_id_labels", default=True)  # off in a compact build (build_report)


def label_ids(text: str, research) -> str:
    """Run 3 (12 Nov 2026): "... [R57]" -> "... [R57: board probe of CEO Jane Smith]", so a reader sees what a cited
    note is without turning to the notes table. Research-note ids only (E/S codes and debate ids are left as they
    are); only a note with its own label (AI-written, no figures, names checked) is labelled. Not in a compact build:
    the labels are the first thing to go when a report is over its page limit (run 3's standard report: 16 pages
    with them, 15 without)."""
    if not isinstance(text, str):  # e.g. the forecast's vs-consensus figure
        return text
    if not _LABELS.get():
        return text
    facts = getattr(research, "facts", None) if research is not None else None
    if not text or not facts:
        return text
    by = {f.id: f for f in facts}
    done: set[str] = set()

    def one(i: str) -> str:  # labelled the first time it is cited in this text only
        f = by.get(i)
        # only the note's own short label (new runs): printing the start of an older note instead made run 2's
        # standard report a page longer than its limit for little gain
        t = (getattr(f, "label", "") or "") if f is not None and i not in done else ""
        done.add(i)
        return f"{i}: {t}" if t else i

    return _ID_CITE.sub(lambda m: "[" + "; ".join(one(x.strip()) for x in re.split(r"[,;]", m.group(1))) + "]", text)


def _scenarios(s, data: Optional[TearSheetData] = None, research=None) -> Optional[dict]:
    if not s:
        return None
    c = ccy(s.currency)
    research = research if research is not None else (data.research if data is not None else None)
    rows = [[x.name.title(), pct(x.probability, 0), " · ".join(pct(g, 1, signed=True) for g in x.revenue_growth),
             pct(x.fcf_margin, 1), f"{c} {num(x.value_per_share, 2)}", pct(x.upside, 1, signed=True),
             label_ids(x.drivers, research)]
            for x in s.scenarios]
    return {"rows": rows, "weighted": f"{c} {num(s.weighted_value, 2)}",
            "weighted_upside": pct(s.weighted_upside, 1, signed=True), "note": s.note,
            "bridge": [[k, (f"{c} {num(v, 2)}" if i in (0, len(b) - 1) else f"{v:+,.2f}")]
                       for b in [_bridge(data)] for i, (k, v) in enumerate(b)] if data is not None else []}


_CHECK_NO = re.compile(r"\s*\(check\s*\d+\)", re.I)


def _get(d: dict, *keys, default=None):
    """The first of ``keys`` present in ``d`` (the scenario model's field names, read tolerantly)."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def _scenario_model(data: TearSheetData) -> Optional[dict]:
    """Deep-only exhibit (run 2): each scenario's revenue path and how its value splits between the forecast years
    and the terminal value, from ``scenarios.paths``. None (exhibit omitted) when that is missing or fails."""
    try:
        from ..narrative import scenarios as _sc
        fn = getattr(_sc, "paths", None)
        ps = fn(data) if fn is not None else None
    except Exception as e:  # a display aid; never fail a report over it
        log.warning("scenario model exhibit omitted: %s", e)
        return None
    if not ps or not isinstance(ps, (list, tuple)):
        return None
    sc = data.valuation.scenarios if data.valuation else None
    cur = ccy(sc.currency if sc and sc.currency else data.quote.currency)
    rc = ccy(data.financials.currency)
    rows = [p for p in ps if isinstance(p, dict) and _get(p, "name")]
    growths = [list(_get(p, "revenue_growth", "growth", default=[]) or []) for p in rows]
    if len(rows) < 2 or not all(growths) or len({len(g) for g in growths}) != 1:
        return None
    n = len(growths[0])
    dcf = data.valuation.dcf if data.valuation else None
    fc = list(dcf.forecast) if dcf and dcf.forecast else []
    years = [f"FY{x.fiscal_year}E" for x in fc] if len(fc) == n else [f"Year {i}" for i in range(1, n + 1)]

    def label(p):
        pr = _get(p, "probability", "prob")
        return str(_get(p, "name")).title() + (f" ({pct(pr, 0)})" if pr is not None else "")
    growth_rows = [{"label": label(p), "values": [pct(g, 1, signed=True) if g is not None else "–" for g in gs],
                    "style": "normal"} for p, gs in zip(rows, growths)]

    def margin(p) -> str:
        m = _get(p, "fcf_margin", "fcf_margins", "margin")
        if isinstance(m, (list, tuple)):
            m = [x for x in m if x is not None]
            return (pct(m[0]) if len(set(round(x, 6) for x in m)) == 1 else f"{pct(m[0])} → {pct(m[-1])}") if m else "–"
        return pct(m) if m is not None else "–"
    vals = [_get(p, "value_per_share", "value") for p in rows]
    pv_e = [_get(p, "pv_explicit", "pv_forecast", "pv_years", "pv_fcf") for p in rows]
    pv_t = [_get(p, "pv_terminal", "pv_tv") for p in rows]
    # PVs as totals (reporting currency) or per share: a total is many times the value per share
    amounts = all(e is not None and t is not None and vps for e, t, vps in zip(pv_e, pv_t, vals)) and all(
        abs(e + t) > 1000 * abs(vps) for e, t, vps in zip(pv_e, pv_t, vals))
    fmt_pv = mn if amounts else (lambda x: num(x, 2) if x is not None else "–")
    unit = f"{rc} mn" if amounts else f"{cur} / share"
    price = data.quote.price
    summary = []
    for p, vps, e, t in zip(rows, vals, pv_e, pv_t):
        share = _get(p, "terminal_share", "tv_share")
        if share is None and e is not None and t is not None and (e + t):
            share = t / (e + t)
        summary.append([str(_get(p, "name")).title(), pct(_get(p, "probability", "prob"), 0), margin(p), fmt_pv(e),
                        fmt_pv(t), pct(share, 0) if share is not None else "–",
                        f"{cur} {num(vps, 2)}" if vps is not None else "–",
                        pct(vps / price - 1, 1, signed=True) if vps is not None and price else "–"])
    return {"years": years, "growth": growth_rows, "summary": summary,
            "head": ["Scenario", "Prob.", "FCF margin", f"PV of years 1–{n} ({unit})",
                     f"PV of terminal value ({unit})", "Terminal share of value", "Value / share", "vs price"],
            "note": (f"Revenue growth by year in each scenario and how its value splits between the {n} forecast years "
                     f"and the terminal value; computed in code with the model DCF's discount rate, terminal growth, "
                     f"net debt and share count.")}


def _flip_grid(data: TearSheetData) -> Optional[dict]:
    """Deep-only exhibit (run 2): the fair value and rating for other bear / bull probabilities, from
    ``scenarios.fragility``. None (exhibit omitted) when that is missing, fails or is malformed."""
    rt = data.rating
    buy = rt.buy_threshold if rt and rt.buy_threshold is not None else 0.15
    sell = rt.sell_threshold if rt and rt.sell_threshold is not None else -0.10
    try:
        from ..narrative import scenarios as _sc
        fn = getattr(_sc, "fragility", None)
        if fn is None:
            return None
        try:
            f = fn(data, buy, sell)
        except TypeError:
            f = fn(data)
    except Exception as e:  # a display aid; never fail a report over it
        log.warning("rating-flip exhibit omitted: %s", e)
        return None
    if not isinstance(f, dict):
        return None
    bear, bull, cells = list(f.get("bear") or []), list(f.get("bull") or []), f.get("cells") or []
    if not bear or not bull or not cells:
        return None
    cur_ij = f.get("current")
    if len(cells) != len(bear) or any(len(r) != len(bull) for r in cells):
        if len(bear) != len(bull) and len(cells) == len(bull) and all(len(r) == len(bear) for r in cells):
            cells = [list(x) for x in zip(*cells)]  # given bull-major: turn to bear rows, bull columns
            cur_ij = list(reversed(cur_ij)) if cur_ij else None
        else:
            return None
    cur = ccy(data.quote.currency)
    rows = []
    for i, (bp, row) in enumerate(zip(bear, cells)):
        out = []
        for j, c in enumerate(row):
            c = c if isinstance(c, dict) else {}
            val, rating = c.get("value"), c.get("rating") or ""
            out.append({"text": num(val, 2) if val is not None else "–", "rating": rating,
                        "current": bool(cur_ij) and list(cur_ij) == [i, j]})
        rows.append({"label": pct(bp, 0), "cells": out})
    price = data.quote.price
    return {"cols": [pct(x, 0) for x in bull], "rows": rows, "currency": cur,
            "note": (f"Probability-weighted fair value per share ({cur}) for other weights on the bear (rows) and bull "
                     f"(columns) cases; the base case takes the rest. Each cell shows the rating at today's price "
                     f"({cur} {num(price, 2)}): Buy if the value is at least {pct(buy, 0)} above it, Sell if at least "
                     f"{pct(-sell, 0)} below, otherwise Hold."
                     + (" Outlined: today's weights." if any(c["current"] for r in rows for c in r["cells"]) else ""))}


def _deep(data: TearSheetData) -> Optional[dict]:
    """Deep mode: the investment debate chapter."""
    n = data.narrative
    da = n.deep if n else None
    if not da or not (da.bull or da.bear or da.verdict):
        return None
    ev = {e.id: e for e in da.evidence}

    def refs(ids):  # signals in full; fact lines (often whole tables) shortened to their label
        out = []
        for i in ids:
            e = ev.get(i)
            if e:
                v = reader_text(e.value)
                v = v if i.startswith("S") or len(v) <= 36 else ""
                out.append({"id": i, "label": e.label.split(" · ")[-1], "value": v, "stance": e.stance})
        return out

    def arg(a):
        return {"id": a.id, "claim": a.claim, "reasoning": a.reasoning, "assumption": a.assumption,
                "breaks_if": a.breaks_if, "refs": refs(a.evidence)}

    rt = data.rating.rating if data.rating else "Not rated"
    kind = "scenario-based" if data.rating and data.rating.basis == "scenarios" else "rule-based"
    align = {
        "agrees": f"The debate agrees with the {kind} AI rating ({rt}).",
        "disagrees": f"The debate points the other way from the {kind} AI rating ({rt}). The rating does not "
                     f"change here: it follows {'our scenarios' if kind == 'scenario-based' else 'a fixed rule from the valuation'}, "
                     f"and the debate is shown so readers can weigh both.",
        "partly": f"The debate partly supports the {kind} AI rating ({rt}).",
        "not rated": "The model gives no AI rating for this stock, so the debate stands on its own.",
    }[da.rating_alignment]
    # round-7 review: "the debate judged the bull case stronger, yet the rating is Hold" was left unexplained; when
    # they differ, say which valuation step drives the gap (the value bridge, computed in code)
    side_vs = ((da.stronger_side == "bull" and rt in ("Hold", "Sell")) or (da.stronger_side == "bear" and rt in ("Hold", "Buy")))
    if side_vs and kind == "scenario-based" and data.rating and data.rating.fair_value:
        b = _bridge(data)
        steps = [x for x in b[1:-1] if x[1] != 0]
        if steps:
            big = max(steps, key=lambda x: abs(x[1]))
            cur = ccy(data.rating.currency)
            align += (f" Why the rating is {rt} although the debate favours the {da.stronger_side} side: the debate weighs "
                      f"the business evidence, the rating weighs the price. Our probability-weighted value "
                      f"({cur} {num(data.rating.fair_value, 2)}) is {pct(data.rating.upside, 1, signed=True)} against the "
                      f"price; the largest step from the model DCF to it is \"{big[0].lower()}\" ({big[1]:+,.2f} a share).")
    issues = (n.guardrail.text_issues if n and n.guardrail else [])
    return {
        "verdict": {"side": {"bull": "Bull case stronger", "bear": "Bear case stronger",
                             "balanced": "Balanced"}[da.stronger_side],
                    "key": da.stronger_side, "conviction": da.conviction, "text": da.verdict,
                    "swing": da.swing_factor, "change": da.change_my_mind, "alignment": align,
                    "divergences": da.divergences},
        "bull": [arg(a) for a in da.bull], "bear": [arg(a) for a in da.bear],
        "rebuttals": [{"side": r.side.title(), "target": r.target, "response": r.response} for r in da.rebuttals],
        "concessions": [["Bull", c] for c in da.concessions_bull] + [["Bear", c] for c in da.concessions_bear],
        # round 8: S/E evidence codes the reader cannot look up were called padding; only research-note ids (listed
        # in the notes table) are printed
        "findings": [{"area": f.area[:1].upper() + f.area[1:], "finding": f.finding, "stance": f.stance,
                      "ids": ", ".join(i for i in f.evidence if i.startswith("R"))} for f in da.findings],
        # the bridge needs the model DCF and the same scenario set the rating uses
        "scenarios": _scenarios(da.scenarios, data if (data.valuation and data.valuation.scenarios is not None and
                                                      da.scenarios is not None and
                                                      abs(data.valuation.scenarios.weighted_value -
                                                          da.scenarios.weighted_value) < 1e-6) else None,
                                research=data.research),
        # run 2: deep-only exhibits from the scenario model (each omitted on its own when it cannot be built)
        "model": _scenario_model(data), "flip": _flip_grid(data),
        "priced_in": da.priced_in, "questions": da.key_questions,
        "variant": da.variant_view, "pre_mortem": da.pre_mortem,
        # the "(Removed in code …)" marker drives the status; the reader sees "removed", not the pipeline message
        # run 2: "wrong (check 3): ..." printed as "wrong: ..." (the check number is the pipeline's, not the reader's)
        "review": [{"section": r.section, "quote": r.quote, "problem": _CHECK_NO.sub("", r.problem or ""),
                    "fix": (r.fix or "").split(" (Removed in code")[0],
                    "status": ("removed" if "(Removed in code" in (r.fix or "") else
                               "fixed" if r.resolved else "open")} for r in da.review],
        "review_summary": da.review_summary, "dropped": da.dropped, "checks": issues,
        # only the evidence an argument, finding or verdict actually cites, printed as an appendix index (round-7
        # review: ~8 pages of evidence dumps read as "length, not analysis")
        "evidence": [{"id": e.id, "label": e.label, "value": reader_text(e.value), "stance": e.stance}
                     for e in da.evidence if e.id in _cited_ids(da)],
        "review_line": (f"An AI reviewer checked the draft before publication: {len(da.review)} issue(s) raised, "
                        f"{sum(1 for r in da.review if r.resolved or '(Removed in code' in (r.fix or ''))} fixed in the "
                        f"final text." if da.review else "An AI reviewer checked the draft and raised no issues."),
        "method": (f"{da.calls} AI calls: analyst, bull and bear (in parallel), rebuttals, judge, writer, reviewer and "
                   f"revision" + ("; the analyst, debate, judge and reviewer reason step by step before answering"
                                  if da.thinking else "") + ". Every argument must cite the numbered evidence; code drops arguments "
                   "that cite nothing, quote figures not in the data, or rest only on evidence whose sign supports the "
                   "other side. The judge never sets the rating."),
    }


def _cited_ids(da) -> set[str]:
    import re as _r
    ids: set[str] = set()
    for a in list(da.bull) + list(da.bear):
        ids.update(a.evidence)
    for f in da.findings:
        ids.update(f.evidence)
    text = " ".join([da.verdict or "", da.swing_factor or "", da.change_my_mind or "", da.priced_in or "",
                     da.variant_view or "", da.pre_mortem or "", *(da.divergences or [])])
    ids.update(_r.findall(r"\b[ES]\d{1,3}\b", text))
    return ids


def _numbers(data: TearSheetData, debate: Optional[bool] = None, street: Optional[bool] = None) -> dict[str, str]:
    """Chapter numbers for the chapters this report actually has (``debate`` / ``street``: whether those chapters
    were built; by default, whether the data has them)."""
    deep_ = bool(data.narrative and data.narrative.deep and (data.narrative.deep.bull or data.narrative.deep.bear))
    deep_ = deep_ if debate is None else debate
    street_ = bool(data.street and data.street.notes) if street is None else street
    # round 8 (both reviewers): the scorecard / Piotroski appendix, 13F holders, insider trades and raw filing text
    # were "generic machine output" and "mostly length"; they stay in the JSON data pack, not in the report
    keys = ["summary", "debate" if deep_ else None, "overview", "financials", "statements", "valuation",
            "street" if street_ else None, "competitive", "technical", "news", "ownership",
            "filings", "methodology"]
    return {k: str(i) for i, k in enumerate((k for k in keys if k), 1)}


# ---------------------------------------------------------------- 12 Nov 2026: questions an analyst would ask
CHAPTER_TITLES = {"overview": "Company overview", "financials": "Financial analysis", "statements": "Financial statements",
                  "valuation": "Valuation", "street": "Broker research", "competitive": "Competitive landscape",
                  "technical": "Share price", "news": "News & events", "ownership": "Ownership & governance",
                  "filings": "Latest report & research notes"}
_BRACKETS = re.compile(r"\[([^\[\]]{1,200})\]")
_NEWS_ID = re.compile(r"\bN(\d{1,3})\b")


def news_labels(text: str, refs: dict) -> str:
    """"[R57; N3]" -> "[R57; news: Reuters, 11 Nov 2026]": a news item the AI cited by its number, named for the
    reader (the report's news list has no numbers)."""
    if not text or not refs or "N" not in text:
        return text

    def group(m: re.Match) -> str:
        return "[" + _NEWS_ID.sub(lambda k: f"news: {refs[k.group(0)]}" if k.group(0) in refs else k.group(0),
                                  m.group(1)) + "]"
    return _BRACKETS.sub(group, text)


def _short_labels(text: str, research) -> str:
    """Like label_ids, but only with a note's own short label (1.11+): a note without one keeps its bare id (its
    first ten words made the question table hard to read)."""
    facts = getattr(research, "facts", None) if research is not None else None
    if not text or not facts:
        return text
    by = {f.id: f for f in facts if getattr(f, "label", "")}
    done: set[str] = set()

    def one(i: str) -> str:
        f = by.get(i)
        if f is None or i in done:
            return i
        done.add(i)
        return f"{i}: {f.label}"
    return _ID_CITE.sub(lambda m: "[" + "; ".join(one(x.strip()) for x in re.split(r"[,;]", m.group(1))) + "]", text)


def _questions(data: TearSheetData, num: dict, answers: bool = False, data_only: bool = False,
               compact: int = 0) -> Optional[dict]:
    """The analyst questions (narrative/questions.py): the reader's homework in the standard report and the data-only
    edition (with lines to write on), answered in the deep report. Answers are printed only in the deep report, even
    when the data carries them (the standard report built from the deep run's data)."""
    from ..narrative import questions as qmod
    qs = qmod.for_report(data, data_only=data_only)
    if not qs.questions:
        return None
    answers = answers and not data_only and qs.answered
    rows, first = [], {}
    limit = (6 if compact >= 3 else 8) if compact >= 2 and not answers else None
    for i, q in enumerate(qs.questions[:limit], 1):
        fig = q.computed if q.data_key else ""
        if fig and q.data_key in first:
            fig = f"see question {first[q.data_key]}"
        elif fig:
            first[q.data_key] = i
        look = q.look or qmod.DATA_LOOK.get(q.data_key, "")
        title = CHAPTER_TITLES.get(look, "")
        if look == "filings" and (data_only or not (data.research and data.research.facts)):
            title = "Latest report"
        where = f"ch. {num[look]} {title}" if look in num and title else ""
        why = "" if data_only else news_labels(_short_labels(q.why_now, data.research), qs.news_refs)
        ans = news_labels(q.answer, qs.news_refs) if answers else ""
        is_open = answers and (q.answer_status == "open" or not ans)
        if is_open:  # the template prints an OPEN chip in place of the "Open:" the answer starts with
            ans = re.sub(r"^\s*open\s*[:.\-–]\s*", "", ans, flags=re.I)
            ans = ans[:1].upper() + ans[1:]
        rows.append({"n": str(i), "theme": qmod.theme_label(q.theme), "new": q.source == "new", "text": q.text,
                     "why": why, "data": fig, "where": where, "answer": ans, "open": is_open})
    scope = "general and " + qs.sector_label + " questions" if qs.sector_label else "general questions"
    if data_only or qs.method == "code":
        how = f"chosen in code from the InvestSync question bank ({scope}) · figures computed in code"
    else:
        how = (f"chosen by AI from the InvestSync question bank ({scope}) and the recent evidence · figures computed in "
               "code")
    if answers:
        note = how + " · answered by the lead analyst (AI) from the evidence and the debate; each answer is checked in code"
    else:
        note = "the reader's homework: work through them with this report · " + how
    if len(rows) < len(qs.questions):
        note += f" · the first {len(rows)} of {len(qs.questions)} shown, to fit the page (all are in the JSON data)"
    return {"title": "Questions an analyst would ask" + (", answered" if answers else ""), "note": note,
            "rows": rows, "answers": answers, "lines": 2 if not compact else 1,
            "open_text": "Not settled by the sources we read."}


# ---------------------------------------------------------------- run 2: the thesis pillars
_QUESTION_RX = re.compile(r"^\s*-\s*Central question\s*:\s*(?P<q>.+?)\s*$", re.I)
_PILLAR_RX = re.compile(r"^\s*-\s*Pillar\s+\d+\s*:\s*(?P<claim>.+?)\s+Evidence\s*:\s*(?P<ev>.+?)"
                        r"\s+Breaks if\s*:\s*(?P<brk>.+?)\s*$", re.I)


def _tidy(s: str) -> str:
    """One line, without the trailing full stops the brief's own format adds ("claim.. Evidence: ...")."""
    return re.sub(r"[\s.]+$", "", re.sub(r"\s+", " ", s or "")).strip()


def parse_brief(text: Optional[str]) -> Optional[dict]:
    """The saved analyst brief ("- Central question: ...", "- Pillar i: <claim>. Evidence: <...>. Breaks if: <...>.")
    as {"question", "rows": [[claim, evidence, breaks if], ...]}. None when it is missing or has fewer than two
    complete pillars (the brief always has two or three)."""
    if not text:
        return None
    question, rows = "", []
    for ln in text.splitlines():
        m = _QUESTION_RX.match(ln)
        if m and not question:
            question = re.sub(r"\s+", " ", m["q"]).strip()
            continue
        m = _PILLAR_RX.match(ln)
        if m:
            parts = [_tidy(m[k]) for k in ("claim", "ev", "brk")]
            if all(parts):
                rows.append(parts)
    if len(rows) < 2:
        return None
    return {"question": question, "rows": rows[:3]}


def _pillars(data: TearSheetData, rvm: Optional[dict] = None) -> Optional[dict]:
    """"What our view rests on": the lead analyst's pillars under the thesis (run 2: the falsifiable thesis the
    reviewers asked for; the brief was saved but never printed). Only for a generated narrative. The brief keeps its
    best attempt even when a figure check failed, so each row's figures are checked again here against the data and
    the report's own figures (``rvm``); a row with a figure found nowhere is left out."""
    n = data.narrative
    if not n or n.status != "generated":
        return None
    p = parse_brief(n.brief)
    if p is None:
        return None
    from ..narrative import guardrail
    allowed = guardrail.build_allowed(data.model_dump(mode="json", exclude={"narrative"}), rvm or {})
    rows = []
    for r in p["rows"]:
        bad = [tok for x in r for tok in guardrail.unmatched(x, allowed)]
        if bad:
            log.warning("thesis pillar left out, figures not in the data: %s", ", ".join(bad[:6]))
        else:
            rows.append(r)
    if len(rows) < 2:
        return None
    q = p["question"] if not guardrail.unmatched(p["question"], allowed) else ""
    return {"question": q, "rows": rows}


def _deciding(data: TearSheetData) -> Optional[dict]:
    """Run 4: "What decides FY2029E": the judgement model's drivers of revenue in the third forecast year, each with
    its evidence and whether it supports our base case (narrative/deciding.py; checked in code there)."""
    dy = getattr(data, "deciding_year", None)
    n = data.narrative
    if not dy or not dy.drivers or not n or n.status != "generated":
        return None
    eff = {"supports": "Supports", "risks": "At risk", "unclear": "Unclear"}
    g = f" · our base case: revenue {pct(dy.base_growth, 1, signed=True)}" if dy.base_growth is not None else ""
    return {"period": dy.period, "note": "the year our valuation rests on · the lead analyst's view" + g,
            "rows": [[d.driver, d.evidence, eff.get(d.effect, "Unclear")] for d in dy.drivers],
            "verdict": dy.verdict}


def _safe(name: str, fn: Callable[[], Any], default: Any = None) -> Any:
    """One optional section: on any error it is omitted and logged, and the rest of the report still renders
    (run 2, audit item 5b: a crash in one view model lost the whole PDF)."""
    try:
        return fn()
    except Exception as e:
        log.warning("report section '%s' omitted: %s: %s", name, type(e).__name__, e)
        return default


def build_report(data: TearSheetData, compact: int = 0, data_only: bool = False) -> dict[str, Any]:
    """The full report's view model. ``compact`` (0 full, 1, 2) drops the id labels and shortens the long tables
    (research notes, news, announcements, broker notes, filing excerpts) so the report fits its page limit
    (render.render_pdf).
    ``data_only``: the data-only edition (the data is stripped first, render/dataonly.py): no AI text, rating or
    rating history; "Your analysis" boxes in place of the AI sections."""
    token = _LABELS.set(not compact)
    try:
        return _build_report(data, compact, data_only)
    finally:
        _LABELS.reset(token)


def _build_report(data: TearSheetData, compact: int, data_only: bool) -> dict[str, Any]:
    out = {
        "scorecard": None,  # round 8: not printed (see _numbers); data.scorecard stays in the JSON
        "deep": None if data_only else _safe("investment debate", lambda: _deep(data)),
        "street": _safe("broker research", lambda: _street(data, compact, data_only)),
        "since_last": None if data_only else _safe("since the last report", lambda: _since_last(data)),
        "overall": None if data_only else _safe("overall view", lambda: _overall(data)),
        "citations": _citations(data),
        "summary": _summary(data),
        "overview": _overview(data),
        "financials": {**_financials(data), "latest": latest_vm(data)},
        "statements": _statements(data),
        "valuation": _safe("valuation", lambda: _valuation(data)),
        "competitive": _safe("competitive landscape", lambda: _competitive(data)),
        "technical": _safe("technical indicators", lambda: _technical(data)),
        "news": _news(data, compact),
        "ownership": _ownership(data),
        "filings": _safe("filing excerpts", lambda: _filings(data, compact), []),
        "research": _safe("research notes", lambda: _research(data, compact), {"rows": [], "gaps": [], "note": ""}),
        "forecast": _safe("our forecast", lambda: _forecast(data)),
        "preview": _safe("results preview", lambda: _preview(data)),
        "analyst_scenarios": _safe("scenarios", lambda: (_scenarios(data.valuation.scenarios, data)
                                                         if data.valuation and data.valuation.scenarios else None)),
        "methodology": _methodology_data_only() if data_only else _methodology(data) + _methodology_extra(data),
        "disclosures": _disclosures_data_only() if data_only else _safe("disclosures", lambda: _disclosures(data)),
        "ai": _ai(data, data_only, compact),
        "compact": int(compact or 0),
        "data_only": data_only,
    }
    if data_only:  # no AI text and no verdict, even if the data was not stripped: no rating box, no fair-value line
        out["forecast"] = out["analyst_scenarios"] = None
        out["research"] = {"rows": [], "gaps": [], "note": ""}
        if out["preview"]:
            out["preview"]["ours"] = ""
        out["summary"]["rating"] = None
        if out["summary"]["football"]:
            out["summary"]["football"].pop("fair_x", None)
            out["summary"]["football"].pop("fair_label", None)
    out["pillars"] = None if data_only else _safe("thesis pillars", lambda: _pillars(data, out))
    out["deciding"] = None if data_only else _safe("deciding year", lambda: _deciding(data))
    out["num"] = _numbers(data, debate=out["deep"] is not None, street=out["street"] is not None)
    out["questions"] = _safe("analyst questions", lambda: _questions(data, out["num"], answers=out["deep"] is not None,
                                                                     data_only=data_only, compact=compact))
    return out
