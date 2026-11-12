"""Turn TearSheetData into display strings for the Typst template.

All number formatting happens here, in one place, so the PDF, the JSON API and
the guardrail agree on exactly which figures appear on the tear sheet.
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Optional

from ..schema import TearSheetData

CCY_LABEL = {"CNY": "RMB", "HKD": "HKD", "USD": "USD"}

DISCLAIMER = (
    "This tear sheet is produced automatically by InvestSync Research Tools for educational "
    "purposes within the InvestSync Student Investment Organization (CUHK-Shenzhen). It is not "
    "investment advice or a recommendation to buy or sell any security. Figures come from the "
    "sources listed and may contain errors or delays; commentary is AI-generated and checked "
    "only for numerical consistency with the data above. Verify before relying on it.")
# the data-only edition (12 Nov 2026): no AI text and no rating, so the disclaimer says so instead
DISCLAIMER_DATA = (
    "This data-only edition is produced automatically by InvestSync Research Tools for educational purposes within "
    "the InvestSync Student Investment Organization (CUHK-Shenzhen). It contains no AI-written text and no rating, "
    "and it is not investment advice or a recommendation to buy or sell any security. Figures come from the sources "
    "listed and may contain errors or delays; the valuation figures are calculations from stated assumptions, not "
    "price targets. Verify before relying on them.")

# The data-only edition's page-1 writing boxes: the section, and the question the reader answers in it
DATA_ASK = {
    "valuation": {"title": "Valuation view", "lines": 3,
                  "desc": "Cheap or expensive against its peers, its own P/E history and the DCF? What does the "
                          "price assume?"},
    "catalysts": {"title": "Key catalysts", "lines": 6,
                  "desc": "What could lift the shares over the next 12 months? (Events, news and the latest report "
                          "are in the full report.)"},
    "risks": {"title": "Key downside risks", "lines": 6,
              "desc": "What could go wrong, and which figure on this page would show it first?"},
}


def ccy(code: Optional[str]) -> str:
    return CCY_LABEL.get(code or "", code or "")


def num(v: Optional[float], dp: int = 0) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    return f"{v:,.{dp}f}"


def pct(v: Optional[float], dp: int = 1, signed: bool = False) -> str:
    if v is None:
        return "–"
    return f"{v * 100:+.{dp}f}%" if signed else f"{v * 100:.{dp}f}%"


def mult(v: Optional[float], dp: int = 1) -> str:
    return "–" if v is None else f"{v:.{dp}f}x"


def mn(v: Optional[float]) -> str:
    """Amount in millions; negatives in parentheses (accounting style)."""
    if v is None:
        return "–"
    if v == 0:
        return "0"
    m = v / 1e6
    dp = 0 if abs(m) >= 100 else 1
    s = f"{abs(m):,.{dp}f}"
    return f"({s})" if m < 0 else s


def big(v: Optional[float], currency: Optional[str] = None) -> str:
    """Headline amount: 4,523.1bn / 812.4mn / 1.25tn."""
    if v is None:
        return "–"
    a = abs(v)
    if a >= 1e12:
        s = f"{v / 1e12:,.2f}tn"
    elif a >= 1e9:
        s = f"{v / 1e9:,.1f}bn"
    else:
        s = f"{v / 1e6:,.1f}mn"
    return f"{ccy(currency)} {s}".strip()


_NAME_NOISE = re.compile(r"\b(Joint[- ]Stock|Company|Co\.?|Ltd\.?|Limited|Corporation|Corp\.?|Inc\.?|"
                         r"Incorporated|plc|Group|Holdings?|Technology|Technologies)\b\.?,?", re.IGNORECASE)


def trim_name(name: str, limit: int = 18) -> str:
    """Short display name for tables: drop legal suffixes, then truncate."""
    if len(name) <= limit:
        return name
    short = re.sub(r"\s{2,}", " ", _NAME_NOISE.sub("", name)).strip(" ,.&")
    short = short or name
    return short if len(short) <= limit else short[: limit - 1].rstrip() + "…"


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    span = max(hi - lo, 1e-9)
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 0.5:
        ticks.append(round(t, 6))
        t += step
    return ticks


def _chart(data: TearSheetData) -> Optional[dict[str, Any]]:
    b = data.benchmark
    if not b or not b.periods:
        return None
    main = b.periods[-1]  # longest available period
    d0, d1 = main.stock[0].d, main.stock[-1].d
    span = max((d1 - d0).days, 1)

    def xy(series):
        return [[round((p.d - d0).days / span, 4), p.v] for p in series]

    values = [p.v for p in main.stock] + [p.v for p in main.benchmark]
    ticks = _nice_ticks(min(values), max(values))
    years = sorted({p.d.year for p in main.stock})
    x_labels = []
    for y in years:
        jan = date(y, 1, 1)
        if d0 < jan <= d1:
            x_labels.append([round((jan - d0).days / span, 4), str(y)])
    return {
        "period": main.period, "bench_name": b.name,
        "stock": xy(main.stock), "bench": xy(main.benchmark),
        "ymin": ticks[0], "ymax": ticks[-1],
        "yticks": [[t, f"{t:g}"] for t in ticks],
        "xlabels": x_labels,
        "returns": [[p.period, pct(p.stock_return, signed=True), pct(p.benchmark_return, signed=True),
                     _pp(p.stock_return, p.benchmark_return)] for p in b.periods],
    }


def _pp(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None:
        return "–"
    return f"{(a - b) * 100:+.1f}pp"


def _valuation(data: TearSheetData, data_only: bool = False) -> Optional[dict[str, Any]]:
    v = data.valuation
    if not v:
        return None
    w, cur = v.wacc, ccy(v.currency)
    rf_label = w.risk_free_source.replace(" government bond", "")
    rows = [[f"Risk-free rate ({rf_label})", pct(w.risk_free, 2)],
            ["Beta (2Y weekly, adjusted)" if w.beta is not None else "Beta (assumed)", f"{(w.beta or 1.0):.2f}"],
            ["Equity risk premium", pct(w.equity_risk_premium, 2)],
            ["Cost of equity", pct(w.cost_of_equity)]]
    if w.wacc is not None:
        if w.pre_tax_cost_of_debt is not None and w.debt_weight > 0:
            rows.append(["Cost of debt (after tax)", pct(w.pre_tax_cost_of_debt * (1 - w.tax_rate))])
        rows += [["Debt / capital", pct(w.debt_weight)], ["WACC", pct(w.wacc)]]
    model = v.dcf or v.ddm
    if model is None:
        return {"kind": None, "wacc_rows": rows, "notes": v.notes}
    g = model.grid
    grid = {"row_label": g.row_label, "col_label": g.col_label, "cols": [pct(c) for c in g.cols],
            "rows": [[pct(r)] + [num(x, 2) if x is not None else "–" for x in vals]
                     for r, vals in zip(g.rows, g.values)]} if g else None
    if v.dcf:
        d = v.dcf
        cons = [f for f in d.forecast if f.basis == "consensus"]
        rev = (f"consensus FY{cons[0].fiscal_year}" + (f"–{cons[-1].fiscal_year}" if len(cons) > 1 else "")
               + ", then fades") if cons else "historical CAGR, fading"
        kind, assumptions = "DCF", [["FCF margin (3Y median)", pct(d.fcf_margin)],
                                    ["Terminal growth", pct(d.terminal_growth)], ["Revenue path", rev]]
        short = [["FCF margin", pct(d.fcf_margin)], ["terminal growth", pct(d.terminal_growth)],
                 ["revenue", rev.replace("consensus ", "consensus ").replace(", then fades", " then fade")]]
    else:
        d = v.ddm
        kind, assumptions = "DDM", [["Dividend per share (TTM)", f"{cur} {num(d.dividend_per_share, 2)}"],
                                    ["Dividend growth", pct(d.growth)]]
        short = assumptions
    out = {"kind": kind, "wacc_rows": rows, "assumptions": assumptions, "short_assumptions": short, "grid": grid,
           "value": f"{cur} {num(model.value_per_share, 2)}", "price": f"{cur} {num(data.quote.price, 2)}",
           "upside": pct(model.upside, signed=True), "notes": v.notes,
           "title": f"{kind} (illustrative)", "value_label": "Base-case value per share"}
    if data_only:  # a calculation from stated assumptions, not a conclusion
        out.update({"title": f"{kind} calculation (illustrative)",
                    "value_label": f"{kind} value per share (a calculation, not a target)"})
        return out
    sc = v.scenarios
    if kind == "DCF" and sc and data.rating and any("analyst scenarios" in (m.label or "") for m in data.rating.methods):
        # the rating's DCF method is the scenario value: show it here, the mechanical DCF only as a cross-check
        sc_cur = ccy(sc.currency)
        out.update({
            "title": "DCF · our scenarios", "value_label": "Probability-weighted value per share",
            "value": f"{sc_cur} {num(sc.weighted_value, 2)}", "upside": pct(sc.weighted_upside, signed=True),
            "model_value": out["value"],
            "short_assumptions": [[x.name + (" (our forecast)" if x.name == "base" and data.forecast else ""),
                                   f"{sc_cur} {num(x.value_per_share, 2)} ({pct(x.probability, 0)})"]
                                  for x in sc.scenarios]
                                 + [["model DCF, consensus then fade (cross-check)", out["value"]]]})
    return out


def build(data: TearSheetData, data_only: bool = False) -> dict[str, Any]:
    """``data_only``: the data-only edition (render/dataonly.py strips the data first): no rating, no AI text, a
    "Your analysis" box in place of each AI section, and its own disclaimer."""
    p, q, f = data.profile, data.quote, data.financials
    rc = ccy(f.currency)
    years = f.years[-5:]

    def row(label, attr, fmt, cagr=None, style="normal"):
        return {"label": label, "values": [fmt(getattr(y, attr)) for y in years],
                "cagr": cagr or "", "style": style}

    fin_rows = [
        row("Revenue", "revenue", mn, pct(f.revenue_cagr) if f.revenue_cagr is not None else "", "bold"),
        row("  YoY growth", "revenue_growth", lambda v: pct(v, signed=True), style="sub"),
        row("Gross margin", "gross_margin", pct),
        row("Net profit", "net_income", mn, pct(f.net_income_cagr) if f.net_income_cagr is not None else "", "bold"),
        row("Net margin", "net_margin", pct),
        row("Diluted EPS", "diluted_eps", lambda v: num(v, 2)),
        row("Cash & ST investments", "cash_and_equivalents", mn),
        row("Total debt", "total_debt", mn),
        row("Net debt / (cash)", "net_debt", mn, style="bold"),
    ]

    week52 = "–"
    if q.week52_low is not None and q.week52_high is not None:
        week52 = f"{num(q.week52_low, 2)} – {num(q.week52_high, 2)}"
    quote_items = [
        ["Share price", f"{ccy(q.currency)} {num(q.price, 2)}"],
        ["Market cap", big(q.market_cap, q.currency)],
        ["Enterprise value", big(q.enterprise_value, q.currency)],
        ["52-week range", week52],
        ["P/E (TTM) · P/B", f"{mult(q.pe_ttm)} · {mult(q.pb)}"],
        ["Dividend yield (fwd)" if q.currency == "USD" else "Dividend yield", pct(q.dividend_yield)],
    ]
    if q.h_share and q.h_share_price and q.h_premium is not None:  # dual-listed A-share: the H line beside it
        quote_items.append([f"H-share {q.h_share}", f"HKD {num(q.h_share_price, 2)} ({pct(q.h_premium, 1, signed=True)} vs A)"])

    rating = None
    if data.rating and not data_only:
        rt = data.rating
        rating = {"rating": rt.rating, "confidence": rt.confidence or "",
                  "fair_value": f"{ccy(rt.currency)} {num(rt.fair_value, 2)}" if rt.fair_value else "–",
                  "upside": pct(rt.upside, signed=True) if rt.upside is not None else "",
                  "reason": rt.reason or "",
                  "buy_below": f"{ccy(rt.currency)} {num(rt.buy_below, 2)}" if rt.buy_below else "",
                  "sell_above": f"{ccy(rt.currency)} {num(rt.sell_above, 2)}" if rt.sell_above else ""}

    comps = None
    if data.comps:
        c = data.comps

        # long tickers (A-share / HK codes such as 300750.SZ) leave less room for the name: keep names to one line
        name_len = 13 if max(len(x.ticker) for x in [c.target, *c.peers]) > 6 else 16

        def crow(r, bold=False):
            return {"cells": [trim_name(r.name, name_len), r.ticker if r.ticker != "MEDIAN" else "",
                              big(r.market_cap, None) if r.market_cap is not None else "–",
                              mult(r.pe_ttm), mult(r.pe_fwd), mult(r.ev_ebitda), mult(r.pb),
                              pct(r.dividend_yield)],
                    "bold": bold}
        pd_ = c.premium_discount
        comps = {
            "currency": ccy(c.target.currency or q.currency),
            "target": crow(c.target, True),
            "peers": [crow(r) for r in c.peers],
            "median": crow(c.median, True),
            "premium": ["Premium / (discount)", "", "",
                        pct(pd_.get("pe_ttm"), signed=True), pct(pd_.get("pe_fwd"), signed=True),
                        pct(pd_.get("ev_ebitda"), signed=True),
                        pct(pd_.get("pb"), signed=True), pct(pd_.get("dividend_yield"), signed=True)],
            "method": short_peer_method(c.method),
        }

    dupont = None
    if data.dupont:
        d = data.dupont
        dupont = {"fy": f"FY{d.fiscal_year}", "items": [
            ["Net margin", pct(d.net_margin)], ["Asset turnover", mult(d.asset_turnover, 2)],
            ["Equity multiplier", mult(d.equity_multiplier, 2)], ["ROE", pct(d.roe)]]}
    quality = None
    if data.earnings_quality:
        e = data.earnings_quality
        quality = [["Cash conversion (CFO / net profit)", mult(e.cfo_to_net_income, 2)],
                   ["Accruals ratio", pct(e.accruals_ratio, signed=True)]]

    n = None if data_only else data.narrative
    narrative = None
    if n:
        narrative = {"status": n.status, "dupont": n.dupont_commentary, "comps": n.comps_commentary,
                     "catalysts": [b.model_dump() for b in n.catalysts],
                     "risks": [b.model_dump() for b in n.risks], "model": n.model or "",
                     # page 1 carries the argument, not only catalysts (9 Nov 2026: the writer's headline and thesis
                     # were printed only on page 2 of the full report, so the tear sheet had no view of its own)
                     "tagline": n.tagline or "", "thesis": n.thesis or ""}

    gen = data.generated_at
    return {
        "date": gen.strftime("%-d %b %Y"),
        # the local-language name only where it is the listing's own (HK, A-shares); a US listing's Chinese name
        # from a mainland data source read as an error (round-9 review, final check 11 Nov 2026)
        "company": {"name": p.name, "name_local": (p.name_local or "") if p.market.value in ("HK", "CN") else "",
                    "ticker": p.ticker,
                    "exchange": p.exchange, "sector": p.sector or "", "description": p.description or ""},
        "quote_items": quote_items,
        "rating": rating,
        "quote_asof": q.as_of.strftime("%-d %b %Y"),
        "chart": _chart(data),
        "fin": {"unit": f"{rc} mn (EPS in {rc})", "standard": f.accounting_standard or "",
                "years": [f"FY{y.fiscal_year}" for y in years], "rows": fin_rows,
                "cagr_label": f"{f.cagr_years}Y CAGR" if f.cagr_years else "CAGR"},
        "comps": comps,
        "valuation": _valuation(data, data_only),
        "dupont": dupont,
        "quality": quality,
        "narrative": narrative,
        # no scorecard on page 1 (9 Nov 2026): blind reviewers read the yes/no checks as templated filler; the
        # full scorecard is an appendix chapter of the report
        "street": street(data),
        "since_last": None if data_only else since_last(data),
        "overall": None if data_only else overall(data),
        "street_line": street_line(data) if data.overall is None or data_only else None,
        "debate": None if data_only else debate(data),
        "data_only": data_only,
        "ask": DATA_ASK if data_only else None,
        "footer": {
            "sources": "; ".join(s for s in data.sources if not s.startswith("Research desk:")),
            "generated": gen.strftime("%-d %b %Y %H:%M UTC"),
            "disclaimer": DISCLAIMER_DATA if data_only else DISCLAIMER,
            "warnings": data.warnings,
        },
    }


SHORT_AREA = {"value": "Value", "future": "Growth", "past": "Past", "health": "Health", "dividend": "Div."}


def short_peer_method(method: str) -> str:
    """Page 1: the peer method without the per-peer reasons (printed in full in the report's competitive chapter)."""
    head, sep, rest = (method or "").partition(" Why each: ")
    if not sep:
        return method or ""
    left = ""
    if "Left out by the code's screens:" in rest:
        import re
        names = re.findall(r"(?:^|; )\s*([A-Z0-9][A-Z0-9.]*) \(", rest.split("Left out by the code's screens:", 1)[1])
        if names:
            left = f" Left out by the code's screens: {', '.join(names)}."
    return head + " The reason for each peer is in the full report (competitive landscape)." + left


def scorecard(data: TearSheetData) -> Optional[dict[str, Any]]:
    sc = data.scorecard
    if not sc:
        return None
    areas = [{"key": a.key, "title": a.title, "short": SHORT_AREA[a.key],
              "score": f"{a.score}/{a.available}" if a.available else "n/a",
              "frac": round(a.score / a.available, 3) if a.available else None} for a in sc.areas]
    return {"areas": areas, "piotroski": f"{sc.piotroski.score}/{sc.piotroski.available}" if sc.piotroski else ""}


def _date(d) -> str:
    return d.strftime("%-d %b") if d else ""


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def street(data: TearSheetData, notes: int = 2, clip: int = 125) -> Optional[dict[str, Any]]:
    """Page-1 broker block: counts, target range vs our model, and the newest notes (one line each)."""
    st = data.street
    if not st or not st.notes:
        return None
    cur = ccy(st.currency)
    mix = " · ".join(f"{v} {k}" for k, v in st.rating_counts.items())
    who = f"{st.brokers} brokers' latest notes" + (f", {st.reports} reports" if st.market.value == "CN" else "")
    c = data.consensus
    if c is not None and c.analysts and c.analysts != st.brokers:
        # round-6 review: page 1 said "30 brokers, all positive" while the report's consensus had 58 analysts
        # including Hold and Sell; name both sources so the counts are not read as a contradiction (the agreement
        # label stays in the full report's broker chapter)
        extra = f"; Yahoo: {c.analysts} analysts)"
    else:
        extra = f"; agreement {st.agreement})" if st.agreement else ")"
    stats = [["Ratings", f"{mix or 'no ratings'} ({who}{extra}"]]
    if st.targets_n:
        if st.targets_n > 1:
            stats.append(["Targets", f"{cur} {num(st.target_low, 0)}–{num(st.target_high, 0)}, median "
                          f"{num(st.target_median, 2)} ({pct(st.target_upside, 0, signed=True)})"])
        else:
            stats.append(["Target", f"{cur} {num(st.target_median, 2)} from 1 broker "
                          f"({pct(st.target_upside, 0, signed=True)})"])
    if st.eps:
        e = st.eps[0]
        stats.append([f"{e.period} EPS", f"{ccy(st.eps_currency)} {num(e.median, 2)} median "
                      f"(range {num(e.low, 2)}–{num(e.high, 2)})"])
    if st.model_fair_value:
        where = ""
        if st.targets_n and st.targets_above_model is not None:
            # round 8: "below every target" read as every analyst's (Yahoo's wider range went lower); name the set
            where = (f" · below all {st.targets_n} dated broker targets" if st.targets_above_model == st.targets_n
                     and st.targets_n > 1
                     else f" · above all {st.targets_n} dated broker targets" if st.targets_above_model == 0
                     and st.targets_n > 1
                     else f" · {st.targets_above_model} of {st.targets_n} dated broker targets higher")
        stats.append(["Our model", f"{cur} {num(st.model_fair_value, 2)}{where}"])
    rows = []
    shown = st.texts() or st.notes  # notes with text first (HK / US: the news write-ups)
    for n in shown[:notes]:
        text = n.summary_en or n.title or ""
        tgt = f" · TP {num(n.target, 0)}" if n.target else ""
        if n.action in ("upgrade", "downgrade", "initiate") and n.source == "Yahoo Finance":
            text = text or f"{n.action.capitalize()}s" + (f" (from {n.previous_rating})" if n.previous_rating else "")
        if not text and n.previous_target and n.target and n.previous_target != n.target:
            text = f"Target {num(n.previous_target, 0)} → {num(n.target, 0)}"
        rows.append({"date": _date(n.on), "broker": trim_name(n.broker, 22), "rating": n.rating or "",
                     "target": tgt, "text": _clip(text, clip), "translated": bool(n.summary_en)})
    source = st.source.split(":")[0].split(" (")[0].replace(" research centre", "")
    via = sorted({n.source for n in shown[:notes] if any(n is w for w in st.writeups)})
    if via:
        source += " + " + (via[0] if len(via) == 1 else "news")
    return {"stats": stats, "notes": rows, "source": source,
            "synthesis": st.synthesis or "", "agreement": st.agreement or ""}


def debate(data: TearSheetData) -> Optional[dict[str, Any]]:
    """Deep mode: one line for page 1 (the full debate is a report chapter)."""
    da = data.narrative.deep if data.narrative else None
    if not da or not da.verdict:
        return None
    side = {"bull": "Bull case stronger", "bear": "Bear case stronger", "balanced": "Balanced debate"}[da.stronger_side]
    return {"side": side, "key": da.stronger_side, "conviction": f"debate conviction {da.conviction}",
            "alignment": {"agrees": "agrees with the AI rating", "disagrees": "differs from the AI rating",
                          "partly": "partly supports the AI rating", "not rated": ""}[da.rating_alignment]}


def overall(data: TearSheetData) -> Optional[dict[str, Any]]:
    """Page-1 verdict box: overall view, then the model and the brokers on one line each."""
    ov = data.overall
    if not ov:
        return None
    cur = ccy(data.quote.currency)
    rows = []
    for i in ov.inputs:
        if i.weight <= 0 and not i.source.startswith("InvestSync"):
            continue  # reference-only inputs are listed in the report, not on page 1
        if i.source.startswith("InvestSync"):
            rt = data.rating
            rated = rt and rt.fair_value and rt.rating != "Not rated"
            rows.append({"label": "AI rating", "rating": i.rating or "",
                         "strong": f"FV {cur} {num(rt.fair_value, 2)}" if rated else "",
                         "text": pct(rt.upside, 1, signed=True) if rated else "not rated, so not counted"})
        else:
            n = len(ov.votes)
            rows.append({"label": "Brokers", "rating": i.rating or "", "strong": f"{i.score:.1f}/5",
                         "text": (f"{n} broker{'s' * (n != 1)}"
                                  + (f" · target {num(ov.target_median, 0)} {pct(ov.target_upside, 0, signed=True)}"
                                     if ov.target_median else ""))})
    return {"rating": ov.rating, "score": f"{ov.score:.1f}", "basis": ov.basis, "rows": rows,
            "split": ("views split" if ov.split else ""),
            "range": (f"broker views {ov.oldest.strftime('%-d %b')}–{ov.newest.strftime('%-d %b')}"
                      if ov.oldest and ov.newest and ov.oldest != ov.newest else
                      f"broker views {ov.newest.strftime('%-d %b')}" if ov.newest else "")}


def street_line(data: TearSheetData) -> Optional[dict[str, Any]]:
    """Page 1 without the blended overall view: the brokers' view on its own line, beside (never mixed into) ours."""
    st = data.street
    if not st or not st.rating_counts:
        return None
    rated = sum(st.rating_counts.values())
    pos = sum(st.rating_counts.get(r, 0) for r in ("Buy", "Outperform"))
    neg = sum(st.rating_counts.get(r, 0) for r in ("Underperform", "Sell"))
    lean = "Buy" if pos / rated >= 0.6 else "Sell" if neg / rated >= 0.6 else "Hold"
    mix = " · ".join(f"{v} {k}" for k, v in st.rating_counts.items())
    cur = ccy(st.currency)
    tgt = (f"median target {cur} {num(st.target_median, 2)} ({pct(st.target_upside, 0, signed=True)})"
           if st.target_median and st.target_upside is not None else "")
    ours = ""
    rt = data.rating
    if rt and rt.fair_value and st.target_median:
        gap = rt.fair_value / st.target_median - 1
        ours = (f"Our fair value ({cur} {num(rt.fair_value, 2)}) is {pct(abs(gap), 0)} "
                f"{'below' if gap < 0 else 'above'} the brokers' median target")
    return {"lean": lean, "n": rated, "mix": mix, "target": tgt, "ours": ours}


def since_last(data: TearSheetData) -> Optional[dict[str, Any]]:
    s = data.since_last
    if not s:
        return None
    return {"date": s.previous_date.strftime("%-d %b %Y"), "changes": s.changes,
            "since": s.rating_since.strftime("%-d %b %Y") if s.rating_since else ""}


def latest_vm(data) -> Optional[dict]:
    """1.7: latest interim period vs a year earlier (year to date, latest quarter, balance sheet, TTM)."""
    lt = data.financials.latest
    if lt is None:
        return None
    rc = ccy(data.financials.currency)

    def chg(now, prior, kind):
        if now is None or prior is None:
            return "–"
        if kind == "pp":
            return f"{(now - prior) * 100:+.1f}pp"
        return pct(now / prior - 1, signed=True) if prior > 0 else "–"
    rows = [("Revenue", mn(lt.revenue), mn(lt.prior_revenue), chg(lt.revenue, lt.prior_revenue, "g")),
            ("Gross margin", pct(lt.gross_margin), pct(lt.prior_gross_margin), chg(lt.gross_margin, lt.prior_gross_margin, "pp")),
            ("Operating profit", mn(lt.operating_income), mn(lt.prior_operating_income),
             chg(lt.operating_income, lt.prior_operating_income, "g")),
            ("Net profit (attributable)", mn(lt.net_income), mn(lt.prior_net_income),
             chg(lt.net_income, lt.prior_net_income, "g")),
            ("Operating cash flow", mn(lt.operating_cash_flow), mn(lt.prior_operating_cash_flow),
             chg(lt.operating_cash_flow, lt.prior_operating_cash_flow, "g")),
            ("Capex", mn(lt.capex) if lt.capex_complete else "n/a", mn(lt.prior_capex) if lt.capex_complete else "n/a",
             chg(lt.capex, lt.prior_capex, "g") if lt.capex_complete else "–"),
            ("Free cash flow", mn(lt.free_cash_flow) if lt.capex_complete else "n/a",
             mn(lt.prior_free_cash_flow) if lt.capex_complete else "n/a", "–")]
    rows = [r for r in rows if r[1] not in ("–",) or r[2] not in ("–",)]
    quarter = None
    if lt.quarter_label and lt.quarter_revenue is not None:
        quarter = {"label": lt.quarter_label, "rows": [
            ("Revenue", mn(lt.quarter_revenue), mn(lt.quarter_revenue_prior),
             chg(lt.quarter_revenue, lt.quarter_revenue_prior, "g")),
            ("Gross margin", pct(lt.quarter_gross_margin), pct(lt.quarter_gross_margin_prior),
             chg(lt.quarter_gross_margin, lt.quarter_gross_margin_prior, "pp")),
            ("Net profit (attributable)", mn(lt.quarter_net_income), mn(lt.quarter_net_income_prior),
             chg(lt.quarter_net_income, lt.quarter_net_income_prior, "g"))]}
        quarter["rows"] = [r for r in quarter["rows"] if r[1] != "–"]
    nd = lt.net_debt
    balance = [("Cash and liquid investments" if not data.financials.cash_definition else "Cash and marketable securities",
                mn(lt.cash_and_equivalents)), ("Total debt", mn(lt.total_debt)),
               ("Net cash" if nd is not None and nd < 0 else "Net debt", mn(abs(nd)) if nd is not None else "–"),
               ("Minority interests", mn(lt.minority_interest))]
    if lt.total_debt is not None and lt.total_equity:
        # the latest date's own ratio, so the fiscal-year one is not quoted for this date (round-5 review: "debt/
        # equity 0.05x at 26 Jul", the FY2026 figure; at 26 Jul it was 0.15x)
        balance.append(("Debt / equity", f"{lt.total_debt / lt.total_equity:.2f}x"))
    balance = [b for b in balance if b[1] != "–"]
    t = data.financials.ttm
    ttm = None
    if t is not None:
        ttm = [(k, v) for k, v in (("Revenue", mn(t.revenue)), ("Net profit", mn(t.net_income)),
                                   ("Operating cash flow", mn(t.operating_cash_flow)),
                                   ("Free cash flow", mn(t.free_cash_flow)), ("FCF margin", pct(t.fcf_margin)))
               if v != "–"]
    head, _, yr = lt.label.rpartition(" ")
    fy = yr.removeprefix("FY")
    prior_label = (f"{head} {'FY' if yr.startswith('FY') else ''}{int(fy) - 1}" if head and fy.isdigit()
                   else f"{lt.label} a year earlier")
    return {"label": lt.label, "prior_label": prior_label, "period_end": lt.period_end.strftime("%-d %b %Y"),
            "unit": f"{rc} mn", "rows": rows, "quarter": quarter, "balance": balance, "ttm": ttm,
            "ttm_basis": t.basis if t else "", "capex_note": None if lt.capex_complete else
            "The data source lacks this period's property-and-equipment capex, so free cash flow is not shown."}
