"""Picture-first teaching devices for the learner's guide, all computed in code from the saved data (no AI, no
network): the business life-cycle phase, revenue by region on a world map, revenue by segment, 3- or 5-step scales
with one sentence of evidence, a P/E history chart and a one-page "at a glance" card.

Rules are general (any listed company: US, Hong Kong, A-shares; banks and insurers included) and never
ticker-specific. The scales compare the company with its peers or with its own past, never with a universal pass
mark, like the rest of the guide. The life-cycle phase needs two lines (what counts as "fast" growth and as returning
"most" of the profit); they are stated on the page, and a company near a line is called borderline.
"""
from __future__ import annotations

import math
import re
import statistics
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ..schema import TearSheetData
from .viewmodel import ccy, mult, num, pct

ASSETS = Path(__file__).resolve().parent / "assets"
MAP_FILE = ASSETS / "world-110m.svg"  # Natural Earth 1:110m, public domain; see assets/README.md

# ---------------------------------------------------------------------------------------------- life-cycle phase
PHASES = [
    {"n": 1, "name": "Start-up", "short": "Building the product; small sales and growing losses."},
    {"n": 2, "name": "Fast growth", "short": "Sales climb quickly; losses peak and then shrink."},
    {"n": 3, "name": "Operating leverage", "short": "Profitable, and profit rises faster than sales as costs are spread."},
    {"n": 4, "name": "Capital return", "short": "Growth slows; steady profit, much of it paid back to shareholders."},
    {"n": 5, "name": "Decline", "short": "Sales shrink; profit and payouts come under pressure."},
]
FAST = 0.10    # "fast" growth: about 10% a year or more, roughly twice the pace of a typical economy in money terms
MOST = 0.50    # returning "most" of the profit: dividends + buybacks at least half of net profit
NEAR = 0.02    # growth within 2 points of the FAST line counts as near the line (borderline)

# which valuation measure fits each phase (one plain sentence; the guide's step 5 teaches the measures)
MEASURE = {
    1: "With small sales and growing losses there are no profits to price, so P/E is meaningless; analysts look at "
       "how long the cash will last and how fast sales grow.",
    2: "There is no steady profit yet, so P/E does not work; price-to-sales (P/S) and the speed at which losses "
       "shrink are the usual yardsticks.",
    3: "Profit is positive and rising, so P/E becomes useful; because profit is still growing fast, also compare "
       "the forward P/E (on next year's expected profit).",
    4: "Profit is steady and much of it is paid out, so P/E and the dividend (plus buyback) yield are the natural "
       "measures.",
    5: "With sales shrinking, a low P/E can flatter (profit may keep falling); check cash flow, whether the dividend "
       "is covered and the value of the assets (P/B).",
}
BANK_MEASURE = ("For banks and insurers, price-to-book (P/B) and the dividend yield are the usual measures in every "
                "phase; P/E is a cross-check.")

RULES = [
    "Revenue lower than several years ago and still falling: phase 5.",
    "Loss-making: phase 1 if the losses are getting bigger, phase 2 if they are shrinking "
    "(phase 5 if revenue is not growing either).",
    "Profitable after a loss in the last three years: phase 3 (just past breakeven).",
    f"Profitable: phase 3 if revenue grows fast (about {FAST:.0%} a year or more over several years) and less than "
    f"half of profit goes back to shareholders; phase 4 if growth is slower and half or more is paid back.",
    "If the signals disagree (fast growth with big payouts, or recent growth on the other side of the line from the "
    "multi-year rate), we pick the closer phase and call it borderline.",
]


def _amt(v: Optional[float]) -> str:
    if v is None:
        return "–"
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:,.2f}tn"
    if a >= 1e9:
        return f"{v / 1e9:,.1f}bn"
    if a >= 1e6:
        return f"{v / 1e6:,.0f}mn"
    return f"{v:,.0f}"


def _growth(data: TearSheetData) -> dict:
    """Revenue growth: multi-year CAGR (up to five fiscal years), the latest fiscal year, and the current trend (the
    latest year-to-date vs a year earlier when the report has one, else the latest fiscal year)."""
    ys = [y for y in data.financials.years if y.revenue and y.revenue > 0]
    out: dict[str, Any] = {"cagr": None, "cagr_label": "", "fy": None, "fy_label": "", "cur": None, "cur_label": ""}
    if len(ys) >= 2:
        a, b = ys[0], ys[-1]
        n_ = b.fiscal_year - a.fiscal_year
        if n_ > 0:
            out["cagr"] = (b.revenue / a.revenue) ** (1 / n_) - 1
            out["cagr_label"] = f"FY{a.fiscal_year}–FY{b.fiscal_year}"
        p = ys[-2]
        if b.fiscal_year - p.fiscal_year == 1:
            out["fy"] = b.revenue / p.revenue - 1
            out["fy_label"] = f"FY{b.fiscal_year}"
    lt = data.financials.latest
    if lt is not None and lt.revenue_growth is not None:
        out["cur"], out["cur_label"] = lt.revenue_growth, f"{lt.label} vs a year earlier"
    else:
        out["cur"], out["cur_label"] = out["fy"], out["fy_label"]
    return out


def _profit(data: TearSheetData, bank: bool) -> dict:
    """Profit per fiscal year (operating profit; net profit for banks / insurers or when operating profit is
    missing) and over the last twelve months when the report has the latest period and a year earlier."""
    years = data.financials.years
    key = "net_income" if bank else "operating_income"
    if not bank and sum(getattr(y, "operating_income") is not None for y in years) < max(2, len(years) - 1):
        key = "net_income"
    label = "operating profit" if key == "operating_income" else "net profit"
    series = [(f"FY{y.fiscal_year}", getattr(y, key), y.revenue) for y in years]
    ttm = None
    lt, fin = data.financials.latest, data.financials
    if years and lt is not None:
        fy_p, cur_p, pri_p = getattr(years[-1], key), getattr(lt, key), getattr(lt, f"prior_{key}")
        rev = fin.ttm.revenue if fin.ttm and fin.ttm.revenue else (
            years[-1].revenue + lt.revenue - lt.prior_revenue
            if years[-1].revenue and lt.revenue is not None and lt.prior_revenue is not None else None)
        if key == "net_income" and fin.ttm and fin.ttm.net_income is not None:
            ttm = ("TTM", fin.ttm.net_income, rev)
        elif None not in (fy_p, cur_p, pri_p):
            ttm = ("TTM", fy_p + cur_p - pri_p, rev)
    return {"key": key, "label": label, "series": series, "ttm": ttm}


def _capital_return(data: TearSheetData) -> dict:
    """Dividends + buybacks over the last two fiscal years, as a share of net profit."""
    ys = [y for y in data.financials.years if y.dividends_paid is not None or y.buybacks is not None][-2:]
    out: dict[str, Any] = {"share": None, "any": None, "text": "", "dividends": None, "buybacks": None}
    if ys:
        div = sum(y.dividends_paid or 0 for y in ys)
        bb = sum(y.buybacks or 0 for y in ys)
        ni = sum(y.net_income or 0 for y in ys)
        last = ys[-1]
        out["dividends"], out["buybacks"] = last.dividends_paid, last.buybacks
        out["any"] = (last.dividends_paid or 0) + (last.buybacks or 0) > 0
        out["share"] = (div + bb) / ni if ni > 0 else None
        rep = ccy(data.financials.currency)
        parts = []
        if last.dividends_paid:
            parts.append(f"dividends {rep} {_amt(last.dividends_paid)}")
        if last.buybacks:
            parts.append(f"buybacks {rep} {_amt(last.buybacks)}")
        span = f"FY{ys[0].fiscal_year}–FY{ys[-1].fiscal_year}" if len(ys) == 2 else f"FY{last.fiscal_year}"
        joined = " + ".join(parts)
        out["text"] = ((joined[:1].upper() + joined[1:] + f" in FY{last.fiscal_year}") if parts else
                       f"no dividends or buybacks in FY{last.fiscal_year}")
        if out["share"] is not None and parts:
            out["text"] += f"; {pct(out['share'], 0)} of net profit over {span}"
        return out
    recent = [d for d in data.dividends if d.dps > 0][-2:]
    if recent:
        out["any"] = True
        out["text"] = (f"dividends paid ({ccy(data.quote.currency)} {num(recent[-1].dps, 2)} a share in "
                       f"{recent[-1].year}); buyback figures not in the data")
    elif data.dividends:
        out["any"] = False
        out["text"] = "no dividends in recent years; buyback figures not in the data"
    else:
        out["text"] = "dividend and buyback figures not in the data"
    return out


def _smooth(pts: list[tuple[float, float]], steps: int = 12) -> list[list[float]]:
    """Catmull-Rom spline through the points, sampled for drawing."""
    p = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for k in range(steps):
            t = k / steps
            t2, t3 = t * t, t * t * t
            out.append([round(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                     + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3), 4) for j in (0, 1)])
    out.append([round(pts[-1][0], 4), round(pts[-1][1], 4)])
    return out


def _diagram() -> dict:
    """The generic life-cycle picture (the same for every company): x = 0..1 across the five phases, y = -1..1
    around zero. Profit is split where it crosses zero so losses can be drawn in red."""
    rev = _smooth([(0.0, 0.04), (0.2, 0.12), (0.4, 0.36), (0.6, 0.72), (0.8, 0.9), (0.9, 0.88), (1.0, 0.66)])
    prof = _smooth([(0.0, -0.02), (0.14, -0.26), (0.28, -0.34), (0.4, 0.0), (0.6, 0.34), (0.8, 0.46), (0.9, 0.42),
                    (1.0, 0.16)])
    ret = _smooth([(0.6, 0.0), (0.7, 0.1), (0.8, 0.2), (0.9, 0.22), (1.0, 0.08)])
    loss = [q for q in prof if q[1] <= 0.0]
    gain = [q for q in prof if q[1] >= 0.0]
    return {"revenue": rev, "loss": loss, "profit": gain, "returned": ret}


def _margin_rising(prof: dict) -> Optional[bool]:
    m = [(p / r) for _, p, r in prof["series"] if p is not None and r]
    if len(m) < 3:
        return None
    return m[-1] > statistics.median(m[:-1]) + 0.01


def life_cycle(data: TearSheetData, bank: bool) -> Optional[dict]:
    """Place the company in one of five life-cycle phases with the documented RULES; None without the data."""
    gr, prof, cap = _growth(data), _profit(data, bank), _capital_return(data)
    vals = [(lab, p, r) for lab, p, r in prof["series"] if p is not None]
    if not vals or (gr["cagr"] is None and gr["cur"] is None):
        return None
    now = prof["ttm"] if prof["ttm"] and prof["ttm"][1] is not None else vals[-1]
    before = vals[-1] if now is prof["ttm"] else (vals[-2] if len(vals) >= 2 else None)
    p_now, p_before = now[1], (before[1] if before else None)
    cagr, cur = gr["cagr"], gr["cur"]
    pace = cagr if cagr is not None else cur
    rep = ccy(data.financials.currency)
    notes: list[str] = []
    alt = None

    # Q1: is revenue growing?
    signs = [x for x in (cagr, cur) if x is not None]
    growing = "yes" if all(x > 0 for x in signs) else ("no" if all(x <= 0 for x in signs) else "mixed")
    q1_fig = []
    if cur is not None:
        q1_fig.append(f"{pct(cur, 1, signed=True)} ({gr['cur_label']})")
    if cagr is not None:
        q1_fig.append(f"{pct(cagr, 1, signed=True)} a year over {gr['cagr_label']}")
    # Q2: is it profitable?
    trend = None
    if p_before is not None and p_before != 0:
        trend = "rising" if p_now > p_before else "falling"
    prev3 = [p for _, p, _ in (vals[-3:] if now is prof["ttm"] else vals[-4:-1])]
    recent_loss = p_now > 0 and any(p <= 0 for p in prev3)
    profitable = "yes" if p_now > 0 else "no"
    if p_now > 0 and vals[-1][1] <= 0 or p_now <= 0 and vals[-1][1] > 0:
        profitable = "mixed"
    when = ("over the last 12 months" if now is prof["ttm"] else now[0])
    q2_fig = (f"{rep} {_amt(p_now)} {prof['label']} {when}" + (f", {trend} from {_amt(p_before)} ({before[0]})"
                                                               if trend else ""))
    if recent_loss:
        q2_fig += "; a loss in one of the three years before"
    # Q3: is it returning capital?
    returning = {True: "yes", False: "no", None: "n/a"}[cap["any"]]
    big_return = cap["share"] is not None and cap["share"] >= MOST

    shrinking = (cagr is not None and cagr < 0) and (cur is not None and cur < 0)
    if p_now > 0:
        if shrinking:
            n_ = 5
            if trend == "rising":
                alt = 4
                notes.append("Revenue is shrinking but profit is still rising, so it sits between phases 4 and 5.")
        elif recent_loss:
            n_ = 3
            notes.append("It turned profitable only recently: just past breakeven.")
        else:
            fast = pace is not None and pace >= FAST
            mr = _margin_rising(prof)
            if fast and not big_return:
                n_ = 3
            elif not fast and big_return:
                n_ = 4
            else:
                # signals disagree: fast growth with big payouts, or slow growth with small payouts.
                # Rising margins (operating leverage at work) tip it to 3, otherwise 4.
                n_ = 3 if mr else 4
                alt = 4 if n_ == 3 else 3
                notes.append(("Growth is fast but half or more of profit is already paid back"
                              if fast else "Growth is slower but most of the profit is kept, not paid back")
                             + f"; {'rising' if mr else 'flat or falling'} margins tip it to phase {n_}.")
            # near the line: recent growth and the multi-year rate on different sides of it, or (with only one
            # growth figure) within 2 points of it
            near = (cagr is not None and cur is not None and (cagr >= FAST) != (cur >= FAST)) or (
                pace is not None and abs(pace - FAST) < NEAR and (cur is None or abs(cur - FAST) < NEAR))
            if near and alt is None:
                alt = 4 if n_ == 3 else 3
                notes.append(f"Recent growth ({pct(cur, 1, signed=True)}) and the multi-year rate "
                             f"({pct(cagr, 1, signed=True)}) sit on different sides of the {FAST:.0%} line, so it is "
                             f"borderline between phases 3 and 4." if cagr is not None and cur is not None and
                             (cagr >= FAST) != (cur >= FAST) else
                             f"Growth of {pct(pace, 1, signed=True)} a year is close to the {FAST:.0%} line, so it is "
                             f"borderline between phases 3 and 4.")
            if cur is not None and cur < 0 <= (cagr or 0):
                notes.append("Revenue fell in the latest period; one weak period is not yet a trend.")
    else:
        if pace is None or pace <= 0:
            n_ = 5
            notes.append("Loss-making and revenue not growing.")
        elif p_before is None or p_before > 0:
            n_, alt = 2, 1
            notes.append("Losses are new, so there is no trend in them yet: phase 1 or 2.")
        else:
            change = abs(p_now) / abs(p_before) - 1
            n_ = 1 if change > 0 else 2
            if abs(change) < 0.1:
                alt = 2 if n_ == 1 else 1
                notes.append("Losses are roughly unchanged, so it is between phases 1 and 2.")
    if bank:
        notes.append("Banks and insurers: we use net profit, and their revenue moves with interest rates and "
                     "markets, so the diagram fits them less well than an ordinary company.")
    ph = PHASES[n_ - 1]
    why = {
        1: "it makes losses and they are getting bigger while revenue grows",
        2: "revenue is growing and the losses are shrinking towards breakeven",
        3: ("it has just turned profitable" if recent_loss else
            "it is profitable and growing fast, and most of the profit is kept in the business"
            if not big_return else "it is profitable and growing, with margins still rising"),
        4: ("it is profitable, growth is slower, and half or more of profit goes back to shareholders"
            if big_return else "it is profitable but growth has slowed"),
        5: "revenue is shrinking",
    }[n_]
    pts = list(prof["series"]) + ([prof["ttm"]] if prof["ttm"] and prof["ttm"][2] else [])
    pts = [x for x in pts if x[1] is not None and x[2]][-6:]
    top = max([x[2] for x in pts] + [1])
    low = min([x[1] for x in pts] + [0])
    span = top - low or 1
    trend_pts = [{"label": lab, "rev": round(r / span, 4), "prof": round(p / span, 4), "rev_t": _amt(r),
                  "prof_t": _amt(p), "ttm": lab == "TTM"} for lab, p, r in pts]
    return {
        "n": n_, "name": ph["name"], "short": ph["short"], "alt": alt,
        "alt_name": PHASES[alt - 1]["name"] if alt else "",
        "why": f"{data.profile.name} is in phase {n_} because {why}.",
        "notes": notes, "measure": BANK_MEASURE if bank else MEASURE[n_],
        "questions": [
            {"q": "Is revenue growing?", "a": growing, "fig": "; ".join(q1_fig)},
            {"q": "Is it profitable?", "a": profitable, "fig": q2_fig},
            {"q": "Is it returning capital?", "a": returning, "fig": cap["text"]},
        ],
        "profit_label": prof["label"], "currency": rep,
        "trend": {"points": trend_pts, "zero": round(-low / span, 4)},
        "phases": PHASES, "rules": RULES, "bank": bank, "diagram": _diagram(),
    }


# ---------------------------------------------------------------------------------------------- 3- or 5-step scales
def _near(t: float, m: float) -> bool:
    """Close to a comparison figure: within 3 points or a fifth of it, whichever is wider."""
    return abs(t - m) <= max(0.03, 0.2 * abs(m))


def _three(t: float, m: float) -> int:
    return 1 if _near(t, m) else (2 if t > m else 0)


def scale_growth(data: TearSheetData) -> dict:
    c = data.comps
    if c and c.target.revenue_growth is not None and c.median.revenue_growth is not None:
        t, m = c.target.revenue_growth, c.median.revenue_growth
        return {"key": "growth", "title": "How fast is it growing?", "basis": "vs peers",
                "levels": ["Slower than peers", "In line with peers", "Faster than peers"], "chosen": _three(t, m),
                "evidence": f"Revenue grew {pct(t, 1, signed=True)} (latest quarter vs a year earlier) against a "
                            f"peer median of {pct(m, 1, signed=True)}."}
    gr = _growth(data)
    if gr["cur"] is not None and gr["cagr"] is not None and gr["cur_label"] != gr["cagr_label"]:
        t, m = gr["cur"], gr["cagr"]
        return {"key": "growth", "title": "Is growth speeding up?", "basis": "vs its own past",
                "levels": ["Slowing down", "Steady", "Speeding up"], "chosen": _three(t, m),
                "evidence": f"Revenue grew {pct(t, 1, signed=True)} ({gr['cur_label']}) against "
                            f"{pct(m, 1, signed=True)} a year over {gr['cagr_label']}."}
    return {"key": "growth", "title": "How fast is it growing?", "basis": "", "levels": ["Slower", "In line", "Faster"],
            "chosen": None, "evidence": "Not enough data to compare growth with peers or with its own past."}


def scale_profit(data: TearSheetData, bank: bool) -> dict:
    c = data.comps
    key, what = ("roe", "Return on equity") if bank else ("operating_margin", "Operating margin")
    if c and getattr(c.target, key) is not None and getattr(c.median, key) is not None:
        t, m = getattr(c.target, key), getattr(c.median, key)
        return {"key": "profit", "title": "How profitable is it?", "basis": "vs peers",
                "levels": ["Less than peers", "In line with peers", "More than peers"], "chosen": _three(t, m),
                "evidence": f"{what} {pct(t, 1)} against a peer median of {pct(m, 1)}."}
    rs = [(x.fiscal_year, getattr(x, key if bank else "operating_margin")) for x in sorted(data.ratios, key=lambda x: x.fiscal_year)]
    rs = [x for x in rs if x[1] is not None]
    if len(rs) >= 3:
        t, m = rs[-1][1], statistics.median(x[1] for x in rs[:-1])
        return {"key": "profit", "title": "How profitable is it?", "basis": "vs its own past",
                "levels": ["Below its usual", "About its usual", "Above its usual"], "chosen": _three(t, m),
                "evidence": f"{what} {pct(t, 1)} in FY{rs[-1][0]} against a median of {pct(m, 1)} in "
                            f"FY{rs[0][0]}–FY{rs[-2][0]}."}
    return {"key": "profit", "title": "How profitable is it?", "basis": "", "levels": ["Less", "In line", "More"],
            "chosen": None, "evidence": "Not enough data to compare profitability with peers or its own past."}


def scale_safety(data: TearSheetData, bank: bool) -> dict:
    levels = ["Debt growing vs profit", "Debt steady vs profit", "More cash than debt"]
    base = {"key": "safety", "title": "How safe is the balance sheet?", "basis": "vs its own past", "levels": levels}
    if bank:
        return {**base, "basis": "", "chosen": None,
                "evidence": "Not scored for banks and insurers: borrowing is their raw material, and their safety "
                            "depends on capital ratios and loan quality, which are not in this report."}
    fin, rep = data.financials, ccy(data.financials.currency)
    lt, ly = fin.latest, (fin.years[-1] if fin.years else None)
    src = lt if lt is not None and lt.total_debt is not None and lt.cash_and_equivalents is not None else ly
    if src is None or src.total_debt is None or src.cash_and_equivalents is None:
        return {**base, "chosen": None, "evidence": "Cash and debt figures are not in the data."}
    when = src.period_end.strftime("%-d %b %Y")
    nd = src.total_debt - src.cash_and_equivalents
    if nd <= 0:
        return {**base, "basis": "cash vs debt", "chosen": 2,
                "evidence": f"Cash of {rep} {_amt(src.cash_and_equivalents)} is more than debt of "
                            f"{rep} {_amt(src.total_debt)} at {when} (net cash {rep} {_amt(-nd)})."}
    rs = [x for x in sorted(data.ratios, key=lambda x: x.fiscal_year) if x.net_debt_to_ebitda is not None]
    ic = [x.interest_coverage for x in sorted(data.ratios, key=lambda x: x.fiscal_year) if x.interest_coverage is not None]
    if len(rs) >= 3:
        t, m = rs[-1].net_debt_to_ebitda, statistics.median(x.net_debt_to_ebitda for x in rs[:-1])
        falling_cover = len(ic) >= 3 and ic[-1] < ic[-2] < ic[-3]
        worse = t > m and not _near(t, m) or (falling_cover and t > m)
        return {**base, "chosen": 0 if worse else 1,
                "evidence": f"Net debt is {num(t, 2)}x EBITDA in FY{rs[-1].fiscal_year} against a median of "
                            f"{num(m, 2)}x in FY{rs[0].fiscal_year}–FY{rs[-2].fiscal_year}"
                            + (f"; profit covers interest {num(ic[-1], 1)}x" if ic else "")
                            + (", lower each year" if falling_cover else "") + "."}
    return {**base, "basis": "cash vs debt", "chosen": None,
            "evidence": f"Net debt of {rep} {_amt(nd)} at {when}; too little history to compare with its own past."}


def scale_cheap(data: TearSheetData) -> dict:
    b = data.pe_band
    levels = ["Much cheaper than usual", "Cheaper than usual", "About usual", "Dearer than usual", "Much dearer than usual"]
    base = {"key": "cheap", "title": "Cheap or expensive vs its own history?", "basis": "vs its own past",
            "levels": levels}
    if not b or b.percentile is None:
        return {**base, "chosen": None, "evidence": "No P/E history in the data (for example, after losses)."}
    p = b.percentile
    idx = min(int(p * 5), 4)
    rel = (f"lower than {pct(1 - p, 0)} of the last five years" if p < 0.5 else
           f"higher than {pct(p, 0)} of the last five years")
    return {**base, "chosen": idx,
            "evidence": f"P/E {mult(b.current)} against a 5-year median of {mult(b.median)}: {rel}.",
            "caveat": "Cheap against its own past is not the same as cheap: P/E also falls when profit jumps, so "
                      "check whether the profit can last."}


def scales(data: TearSheetData, bank: bool) -> dict[str, dict]:
    return {"growth": scale_growth(data), "profit": scale_profit(data, bank), "safety": scale_safety(data, bank),
            "cheap": scale_cheap(data)}


# ---------------------------------------------------------------------------------------------- segments
PALETTE = ["#1B3A8C", "#2a78d6", "#1baf7a", "#eda100", "#eb6834", "#8e6bd1", "#5B6475", "#b9bfca"]


def segment_bar(data: TearSheetData) -> Optional[dict]:
    """Revenue by business segment or product: shares of the latest period, plus 1-year growth when the data has the
    same split for the year before."""
    brk = [s for s in data.segments if s.kind in ("business", "product") and s.segments]
    if not brk:
        return None
    brk.sort(key=lambda s: s.period)
    cur = brk[-1]
    prev = next((s for s in reversed(brk[:-1]) if s.kind == cur.kind), None)
    prior = {x.name: x.revenue for x in prev.segments} if prev else {}
    pos = [x for x in cur.segments if x.revenue and x.revenue > 0]
    tot = sum(x.revenue for x in pos) or None
    if not tot:
        return None
    items = []
    for i, x in enumerate(sorted(pos, key=lambda x: -x.revenue)):
        pr = prior.get(x.name)
        items.append({"name": x.name, "share": round(x.revenue / tot, 4), "share_t": pct(x.revenue / tot, 0),
                      "rev_t": _amt(x.revenue),
                      "growth_t": pct(x.revenue / pr - 1, 0, signed=True) if pr and pr > 0 else "",
                      "color": PALETTE[min(i, len(PALETTE) - 1)]})
    neg = [f"{x.name} ({_amt(x.revenue)})" for x in cur.segments if x.revenue is not None and x.revenue <= 0]
    return {"period": cur.period, "currency": ccy(cur.currency), "total_t": _amt(tot), "items": items,
            "has_growth": any(i["growth_t"] for i in items),
            "note": ("Not in the bar (zero or negative, usually a corporate centre or adjustment line): "
                     + ", ".join(neg) + ".") if neg else ""}


# ---------------------------------------------------------------------------------------------- geography map
@lru_cache(maxsize=1)
def _world() -> tuple[str, dict[str, dict]]:
    svg = MAP_FILE.read_text(encoding="utf-8")
    shapes = {}
    for m in re.finditer(r'<(?:path|circle) id="([A-Z0-9]{3})" data-name="([^"]*)" data-continent="([^"]*)" '
                         r'data-subregion="([^"]*)"', svg):
        shapes[m.group(1)] = {"name": m.group(2), "continent": m.group(3), "subregion": m.group(4)}
    return svg, shapes


def _by(field: str, *values: str, minus: tuple = ()) -> set[str]:
    return {k for k, v in _world()[1].items() if v[field] in values and k not in minus}


ASIA_PACIFIC = ("Eastern Asia", "South-Eastern Asia", "Southern Asia", "Australia and New Zealand", "Melanesia")
# broad region names -> countries (Russia is left out of "Europe": company "Europe" segments are rarely about it, and
# its size would dominate the picture)
REGIONS = {
    "europe": lambda: _by("continent", "Europe", minus=("RUS",)),
    "emea": lambda: _by("continent", "Europe", "Africa", minus=("RUS",)) | _by("subregion", "Western Asia"),
    "middle east": lambda: _by("subregion", "Western Asia"),
    "africa": lambda: _by("continent", "Africa"),
    "asia": lambda: _by("continent", "Asia"),
    "asia pacific": lambda: _by("subregion", *ASIA_PACIFIC),
    "apac": lambda: _by("subregion", *ASIA_PACIFIC),
    "apj": lambda: _by("subregion", *ASIA_PACIFIC),
    "southeast asia": lambda: _by("subregion", "South-Eastern Asia"),
    "americas": lambda: _by("continent", "North America", "South America"),
    "north america": lambda: _by("subregion", "Northern America") | {"MEX"},
    "latin america": lambda: _by("subregion", "Central America", "Caribbean", "South America") | {"MEX"},
    "south america": lambda: _by("continent", "South America"),
    "oceania": lambda: _by("continent", "Oceania"),
}
ALIASES = {
    "united states": "USA", "us": "USA", "u.s.": "USA", "usa": "USA", "u.s.a.": "USA", "united states of america": "USA",
    "china": "CHN", "mainland china": "CHN", "mainland": "CHN", "prc": "CHN", "chinese mainland": "CHN",
    "people's republic of china": "CHN", "china mainland": "CHN",
    "hong kong": "HKG", "hong kong sar": "HKG", "hk": "HKG", "macau": "MAC", "macao": "MAC", "taiwan": "TWN",
    "japan": "JPN", "korea": "KOR", "south korea": "KOR", "republic of korea": "KOR", "singapore": "SGP",
    "united kingdom": "GBR", "uk": "GBR", "u.k.": "GBR", "britain": "GBR", "great britain": "GBR",
    "the netherlands": "NLD", "netherlands": "NLD", "holland": "NLD", "uae": "ARE", "united arab emirates": "ARE",
    "czech republic": "CZE", "russia": "RUS", "vietnam": "VNM", "viet nam": "VNM",
    # Chinese names used in A-share and HK filings
    "中国": "CHN", "中国大陆": "CHN", "中国内地": "CHN", "大陆": "CHN", "境内": "CHN", "国内": "CHN", "内地": "CHN",
    "香港": "HKG", "中国香港": "HKG", "澳门": "MAC", "台湾": "TWN", "中国台湾": "TWN", "美国": "USA", "日本": "JPN",
    "韩国": "KOR", "新加坡": "SGP", "英国": "GBR", "德国": "DEU", "法国": "FRA", "印度": "IND",
    "欧洲": "europe", "亚洲": "asia", "亚太": "asia pacific", "亚太地区": "asia pacific", "北美": "north america",
    "北美洲": "north america", "南美": "south america", "拉美": "latin america", "非洲": "africa", "中东": "middle east",
    "东南亚": "southeast asia", "美洲": "americas",
}
UNMAPPED = {"other", "others", "rest of world", "rest of the world", "row", "international", "overseas", "foreign",
            "other countries", "other regions", "all other", "unallocated", "其他", "其他地区", "境外", "海外",
            "国外", "其他国家和地区"}


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace("-", " ").replace("–", " ")
    s = re.sub(r"[()（）,，;；/]", " | ", s)
    return re.sub(r"\s+", " ", s).strip()


def region_codes(name: str) -> tuple[set[str], int]:
    """Map a reported region name to map shapes (ISO 3166 alpha-3 codes) and a specificity (0 = named countries,
    1 = a broad region). Names that cannot be placed (e.g. "Other", "Rest of world") give an empty set."""
    _, shapes = _world()
    names = {v["name"].lower(): k for k, v in shapes.items()}
    s = _norm(name)
    if s in UNMAPPED:
        return set(), 0
    parts = [p.strip() for p in re.split(r"\||\band\b|\bincluding\b|\bincl\.?|\bexcluding\b.*$|及|和|、|与", s)]
    codes: set[str] = set()
    broad = 0
    for p in parts:
        p = re.sub(r"^(the |other |rest of (the )?)", "", p).strip()
        p = re.sub(r"\b(region|regions|sar|area|地区)$", "", p).strip()
        if not p or p in UNMAPPED:
            continue
        hit = ALIASES.get(p, names.get(p))
        if hit is None and p.replace(" ", "") in ("asiapacific", "apac"):
            hit = "asia pacific"
        if hit in REGIONS or p in REGIONS:
            codes |= REGIONS[hit if hit in REGIONS else p]()
            broad = 1
        elif hit:
            codes.add(hit)
    return codes, broad


SHARE_STEPS = [(0.5, "#1B3A8C"), (0.3, "#3457A8"), (0.15, "#5F7DC4"), (0.05, "#93A8DA"), (0.0, "#C7D2EC")]


def _shade(share: float) -> str:
    return next(c for lo, c in SHARE_STEPS if share >= lo)


def geo_map(data: TearSheetData) -> Optional[dict]:
    """Revenue by region on a world map (darker = larger share) with a legend; None without a regional split."""
    reg = next((s for s in sorted(data.segments, key=lambda s: s.period, reverse=True)
                if s.kind == "region" and s.segments), None)
    if reg is None:
        return None
    pos = [x for x in reg.segments if x.revenue is not None and x.revenue > 0 or x.revenue is None and (x.share or 0) > 0]
    tot = sum(x.revenue for x in pos if x.revenue) or None
    rows = []
    for x in pos:
        sh = x.share if x.share is not None else (x.revenue / tot if tot else None)
        if sh is None:
            continue
        codes, broad = region_codes(x.name)
        rows.append({"name": x.name, "share": sh, "codes": codes, "broad": broad})
    if not rows:
        return None
    claimed: dict[str, str] = {}
    for r in sorted(rows, key=lambda r: (r["broad"], -r["share"])):  # named countries first, broad regions fill the rest
        col = _shade(r["share"])
        r["codes"] = {c for c in r["codes"] if c not in claimed}
        for c in r["codes"]:
            claimed[c] = col
    svg, _ = _world()
    for code, col in claimed.items():
        svg = re.sub(rf'(<(?:path|circle) id="{code}")', rf'\1 fill="{col}"', svg, count=1)
    small = [c for c in claimed if c in ("HKG", "MAC", "SGP")]
    for c in small:  # tiny places are dots: outline them so they show on top of a coloured neighbour
        svg = re.sub(rf'(<circle id="{c}")', r'\1 stroke="#E8590C" stroke-width="1.6"', svg, count=1)
    rings = []
    for c, col in claimed.items():  # shapes too small to see at this size (e.g. Taiwan) get a ringed dot as well
        m = re.search(rf'<path id="{c}"[^>]* d="([^"]*)"', svg)
        if not m:
            continue
        xy = [tuple(map(float, q.split(","))) for q in re.findall(r"-?[\d.]+,-?[\d.]+", m.group(1))]
        xs, ys = [a for a, _ in xy], [b for _, b in xy]
        if xy and (max(xs) - min(xs)) * (max(ys) - min(ys)) < 120:
            rings.append(f'<circle cx="{(min(xs) + max(xs)) / 2:.1f}" cy="{(min(ys) + max(ys)) / 2:.1f}" r="4.5" '
                         f'fill="{col}" stroke="#E8590C" stroke-width="1.6"/>')
            small.append(c)
    if rings:
        svg = svg.replace("</g>\n</svg>", "\n".join(rings) + "\n</g>\n</svg>")
    legend = [{"name": r["name"], "share_t": pct(r["share"], 0 if r["share"] >= 0.1 else 1),
               "color": _shade(r["share"]) if r["codes"] else "", "mapped": bool(r["codes"])}
              for r in sorted(rows, key=lambda r: -r["share"])]
    return {"svg": svg, "legend": legend, "period": reg.period, "source": reg.source,
            "dots": bool(small), "unmapped": [x["name"] for x in legend if not x["mapped"]]}


# ---------------------------------------------------------------------------------------------- P/E history chart
def pe_history(data: TearSheetData) -> Optional[dict]:
    """The P/E over the last five years against five bands of its own history (the same fifths as the 'cheap or
    expensive vs its own history' scale). Spikes (P/E jumps when profit collapses) are cut off at the top."""
    b = data.pe_band
    if not b or len(b.series) < 10:
        return None
    vals = sorted(p.v for p in b.series if p.v and p.v > 0)
    if len(vals) < 10:
        return None
    q = lambda f: vals[min(int(f * (len(vals) - 1) + 0.5), len(vals) - 1)]
    cuts = [q(0.2), q(0.4), q(0.6), q(0.8)]
    lo, hi = min(vals[0], b.current) * 0.9, max(vals[-1], b.current) * 1.08
    log = hi / lo > 4  # a P/E that swings a lot (profit collapsed for a while): use a doubling scale
    if log:
        y = lambda v: round(min(max(math.log(v / lo) / math.log(hi / lo), 0), 1), 4)
    else:
        lo = max(0.0, lo * 0.9)
        y = lambda v: round(min(max((v - lo) / ((hi - lo) or 1), 0), 1), 4)
    d0, d1 = b.series[0].d, b.series[-1].d
    days = (d1 - d0).days or 1
    pts = [[round((p.d - d0).days / days, 4), y(p.v)] for p in b.series]
    xl = []
    for yr in range(d0.year + 1, d1.year + 1):
        x = (date(yr, 1, 1) - d0).days / days
        if 0.02 < x < 0.98:
            xl.append([round(x, 4), str(yr)])
    ticks = []
    if log:
        t = _nice(lo)
        while t < hi:
            if t > lo:
                ticks.append([y(t), f"{t:g}x"])
            t *= 2
    else:
        step = _nice((hi - lo) / 4)
        t = (lo // step + 1) * step
        while t < hi:
            ticks.append([y(t), f"{t:g}x"])
            t += step
    return {"points": pts, "bands": [y(c) for c in cuts], "cuts_t": [mult(c) for c in cuts], "current": y(b.current),
            "current_t": mult(b.current), "median_t": mult(b.median), "xlabels": xl, "yticks": ticks, "log": log,
            "note": b.note or "", "metric": b.metric}


def _nice(x: float) -> float:
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    return next(m * e for m in (1, 2, 2.5, 5, 10) if m * e >= x)


# ---------------------------------------------------------------------------------------------- at a glance
def value_range(data: TearSheetData) -> Optional[dict]:
    """Price against the model's value: bear / base / bull scenarios when present, and the fair value."""
    q, rt, va = data.quote, data.rating, data.valuation
    marks = []
    if va and va.scenarios and va.scenarios.scenarios and va.scenarios.currency == q.currency:
        for s in sorted(va.scenarios.scenarios, key=lambda x: ["bear", "base", "bull"].index(x.name)):
            marks.append({"label": s.name.capitalize(), "v": s.value_per_share, "kind": "scen"})
    if rt and rt.fair_value and rt.currency == q.currency:
        marks.append({"label": "Fair value", "v": rt.fair_value, "kind": "fair"})
    if not marks or not q.price:
        return None
    vs = [m["v"] for m in marks] + [q.price]
    lo, hi = min(vs) * 0.92, max(vs) * 1.08
    x = lambda v: round((v - lo) / (hi - lo), 4)
    cur = ccy(q.currency)
    for m in marks:
        m["x"], m["t"] = x(m["v"]), f"{num(m['v'], 2)}"
    scen = [m for m in marks if m["kind"] == "scen"]
    return {"marks": marks, "price_x": x(q.price), "price_t": f"{cur} {num(q.price, 2)}", "currency": cur,
            "range": [scen[0]["x"], scen[-1]["x"]] if len(scen) >= 2 else None}


def glance(data: TearSheetData, phase: Optional[dict], sc: dict[str, dict]) -> dict:
    rt = data.rating
    rating = None
    if rt:
        rating = {"rating": rt.rating, "fair_t": f"{ccy(rt.currency)} {num(rt.fair_value, 2)}" if rt.fair_value else "",
                  "upside_t": pct(rt.upside, 1, signed=True) if rt.upside is not None else "",
                  "basis": ("probability-weighted bear / base / bull scenarios" if rt.basis == "scenarios" else
                            "weighted blend of valuation methods"),
                  "rule": f"Buy if the fair value is {pct(rt.buy_threshold, 0)} or more above the price, Sell if "
                          f"{pct(-rt.sell_threshold, 0)} or more below, otherwise Hold"}
    return {"rating": rating, "range": value_range(data), "scales": [sc[k] for k in ("growth", "profit", "safety", "cheap")],
            "phase": phase}


def build(data: TearSheetData, bank: bool) -> dict[str, Any]:
    ph = life_cycle(data, bank)
    sc = scales(data, bank)
    return {"phase": ph, "scales": sc, "segments": segment_bar(data), "map": geo_map(data), "pe": pe_history(data),
            "glance": glance(data, ph, sc)}
