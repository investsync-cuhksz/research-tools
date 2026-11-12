"""WACC, DCF (FCFF) and DDM, computed in code from data and stated assumptions.

Design rules
* Every input is either data (statements, prices, bond yields, analyst consensus) or an
  assumption in config/valuation.json that the finance team owns. Nothing is made up here.
* Revenue: analyst consensus for the years it covers; after that the growth above the terminal rate
  halves each year (the same fade as the analyst scenarios, so the mechanical DCF and our base case agree on
  method; a linear fade from a hypergrowth year kept NVIDIA growing +19% in year 5 and put the two DCFs USD 65
  apart on the same data, 9 Nov 2026). Free-cash-flow margin: starts at the trailing-twelve-month margin when the latest
  interim period has complete cash flows, and moves halfway back to the median of the last three
  fiscal years by the final forecast year (the terminal year); otherwise the three-year median.
* When an interim balance sheet exists, the value is struck at that date: only the rest of the
  current fiscal year's cash flow is counted, net debt and minorities are taken from that balance
  sheet, and the result is rolled forward to the price date at WACC.
* Results are shown as a grid over the two most uncertain inputs, not a single target.
* Banks and insurers get a dividend discount model instead (FCFF is not meaningful).
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Optional

from ..schema import (DCF, DDM, EVBridge, ForecastYear, TearSheetData, Valuation, ValueGrid, WACC)

log = logging.getLogger(__name__)
CONFIG_FILE = Path(__file__).resolve().parents[2] / "config" / "valuation.json"
FINANCIAL_KEYWORDS = ("bank", "insurance", "capital markets", "银行", "保险", "证券")


def load_config(ticker: Optional[str] = None) -> dict:
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    over = (cfg.get("overrides") or {}).get(ticker or "", {})
    cfg["_override"] = over
    return cfg


def _pick(cfg: dict, key: str, ccy: str, default: float) -> float:
    if key in cfg["_override"]:
        return float(cfg["_override"][key])
    v = (cfg.get(key) or {}).get(ccy)
    return float(v) if isinstance(v, (int, float)) else default


# ---------------------------------------------------------------- inputs
def beta(stock: dict[date, float], bench: dict[date, float], years: int = 2) -> Optional[float]:
    """Weekly-return beta vs the market benchmark, Blume-adjusted (0.67 x raw + 0.33)."""
    common = sorted(set(stock) & set(bench))
    if not common:
        return None
    start = common[-1] - timedelta(days=round(365.25 * years))
    weekly: dict[tuple[int, int], date] = {}
    for d in common:
        if d >= start:
            weekly[d.isocalendar()[:2]] = d  # last trading day of each ISO week
    pts = [weekly[k] for k in sorted(weekly)]
    if len(pts) < 52:
        return None
    rs = [stock[b] / stock[a] - 1 for a, b in zip(pts, pts[1:])]
    rm = [bench[b] / bench[a] - 1 for a, b in zip(pts, pts[1:])]
    n = len(rs)
    mr, mm = sum(rs) / n, sum(rm) / n
    var = sum((x - mm) ** 2 for x in rm) / (n - 1)
    if var == 0:
        return None
    cov = sum((x - mr) * (y - mm) for x, y in zip(rs, rm)) / (n - 1)
    return min(max(0.67 * (cov / var) + 0.33, 0.3), 2.5)


def is_financial(data: TearSheetData) -> bool:
    sector = (data.profile.sector or "").lower()
    if any(k in sector for k in FINANCIAL_KEYWORDS):
        return True
    latest = data.financials.years[-1] if data.financials.years else None
    return bool(latest and latest.gross_profit is None and latest.total_debt is None)


def consensus_revenue(estimates, latest_revenue: float, reporting_ccy: str) -> list[float]:
    """Consensus revenue for the fiscal years after the latest reported one ([] if none)."""
    if estimates is None or len(estimates) == 0 or "avg" not in estimates.columns:
        return []
    est = estimates.copy()
    if "currency" in est.columns and str(est["currency"].iloc[0]) not in (reporting_ccy, "nan", "None"):
        return []
    out: list[float] = []
    prev = latest_revenue
    for period in ("0y", "+1y"):
        if period not in est.index:
            continue
        avg, ago = est.loc[period, "avg"], est.loc[period, "yearAgoRevenue"]
        if not avg or avg != avg or not ago or ago != ago:
            continue
        if abs(float(ago) / prev - 1) < 0.05:  # this estimate follows the year we already have
            out.append(float(avg))
            prev = float(avg)
    return out


# ---------------------------------------------------------------- models
def compute_wacc(data: TearSheetData, b: Optional[float], rf: float, rf_source: str,
                 erp: float, erp_source: str, statutory_tax: float, financial: bool) -> WACC:
    fy = data.financials.years
    cur = fy[-1]
    prev = fy[-2] if len(fy) >= 2 else None
    beta_used = b if b is not None else 1.0
    ke = rf + beta_used * erp

    tax = statutory_tax
    if cur.income_tax is not None and cur.pretax_income and cur.pretax_income > 0:
        tax = min(max(cur.income_tax / cur.pretax_income, 0.0), 0.40)

    debt = cur.total_debt or 0.0
    lt = data.financials.latest
    if lt is not None and lt.total_debt is not None and lt.period_end > cur.period_end:
        # capital weights at the latest balance sheet, as the EV and net cash are (round-6 review: debt weight 0.2%
        # from FY debt of 8.5bn while the same report used 33.4bn of debt at the latest quarter)
        debt = lt.total_debt
    kd = None
    fy_debt = cur.total_debt or debt  # the fiscal year's interest is divided by that year's average debt
    if debt > 0:
        avg_debt = (fy_debt + (prev.total_debt or fy_debt)) / 2 if prev else fy_debt
        if cur.interest_expense and avg_debt > 0:
            kd = min(max(cur.interest_expense / avg_debt, rf), rf + 0.08)
        else:
            kd = rf + 0.015
    q = data.quote
    equity = (q.market_cap or 0.0) * (q.fx_to_reporting or 1.0)
    total = equity + debt
    we = equity / total if total else 1.0
    wd = 1 - we
    wacc = None if financial else we * ke + wd * (kd or 0.0) * (1 - tax)
    return WACC(risk_free=rf, risk_free_source=rf_source, beta=b,
                beta_method="2-year weekly returns vs benchmark, Blume-adjusted" if b is not None
                else "unavailable; 1.0 assumed",
                equity_risk_premium=erp, erp_source=erp_source, cost_of_equity=ke,
                pre_tax_cost_of_debt=kd, tax_rate=tax, debt_weight=wd, equity_weight=we, wacc=wacc)


def fade_step(prev_growth: float, terminal: float) -> float:
    """Next year's growth after the forecast years: the growth above the terminal rate halves each year. Shared by
    the model DCF and the analyst scenarios (narrative/scenarios.py)."""
    return terminal + (prev_growth - terminal) * 0.5


def _shares(data: TearSheetData) -> Optional[float]:
    q = data.quote
    return q.market_cap / q.price if q.market_cap and q.price else None


def dcf_ev(revs: list[float], margins: list[float], w: float, g: float, stub: float = 1.0,
           roll: float = 0.0, cash_share: Optional[float] = None) -> tuple[float, float, list[float]]:
    """Enterprise value, PV of the terminal value and per-year discount factors. Year 1 ends after ``stub``
    years; ``cash_share`` (default ``stub``) is the share of its cash flow still to come; the value is rolled
    forward ``roll`` years."""
    fcfs = [r * m for r, m in zip(revs, margins)]
    times = [stub + k for k in range(len(fcfs))]
    factors = [(1 + w) ** -t for t in times]
    cash = [fcfs[0] * (stub if cash_share is None else cash_share)] + fcfs[1:]
    pv = sum(c * f for c, f in zip(cash, factors))
    pv_tv = fcfs[-1] * (1 + g) / (w - g) * factors[-1]
    grow = (1 + w) ** roll
    return (pv + pv_tv) * grow, pv_tv * grow, factors


def _dcf_value(revs: list[float], margins: list[float], w: float, g: float, claims: float,
               fx: float, shares: float, min_spread: float = 0.005, stub: float = 1.0,
               roll: float = 0.0, cash_share: Optional[float] = None) -> Optional[tuple[float, float, float]]:
    if w < g + min_spread - 1e-9:
        return None
    ev, _, _ = dcf_ev(revs, margins, w, g, stub, roll, cash_share)
    equity = ev - claims
    return ev, equity, equity / fx / shares


def margin_path(data: TearSheetData, years: int) -> tuple[Optional[list[float]], str]:
    """FCF margin per forecast year: TTM margin moving halfway back to the 3-year median, else the median."""
    fy = data.financials.years
    hist = [(y.operating_cash_flow - y.capex) / y.revenue for y in fy[-3:]
            if y.operating_cash_flow is not None and y.capex is not None and y.revenue]
    if not hist:
        return None, ""
    med = median(hist)
    ttm = data.financials.ttm
    if ttm is None or ttm.fcf_margin is None:
        return [med] * years, f"median of the last three fiscal years ({med:.1%})"
    start, end = ttm.fcf_margin, (ttm.fcf_margin + med) / 2
    path = [start + (end - start) * k / (years - 1) for k in range(years)] if years > 1 else [end]
    return path, (f"starts at the trailing-twelve-month margin ({start:.1%}, to {ttm.period_end:%d %b %Y}) and moves "
                  f"halfway back to the three-year median ({med:.1%}), reaching {end:.1%} in the final year")


def stub_cash_share(data: TearSheetData, rev1: float, stub: float) -> float:
    """Share of the current fiscal year's cash flow still to come: its forecast revenue minus the revenue already
    reported this year, so a fast grower's back-loaded second half is not cut to a time share (NVIDIA FY27: 57% of
    revenue in the last 6 months, not 50%). Bounded to 0.5x-1.5x the time share; the time share if unknown."""
    lt, fy = data.financials.latest, (data.financials.years[-1] if data.financials.years else None)
    if stub >= 1.0 or lt is None or fy is None or not lt.revenue or not rev1 or lt.period_end <= fy.period_end:
        return stub
    share = (rev1 - lt.revenue) / rev1
    return min(max(share, 0.5 * stub), min(1.0, 1.5 * stub)) if share > 0 else stub


def _stub(data: TearSheetData) -> tuple[float, float, float, float, Optional[date]]:
    """(stub years, roll-forward years, net debt, minorities, balance-sheet date) for the DCF."""
    fy = data.financials.years[-1]
    lt = data.financials.latest
    if lt is not None and lt.net_debt is not None and lt.period_end > fy.period_end:
        stub = max(12 - lt.months, 0) / 12 or 1.0
        roll = max((data.quote.as_of - lt.period_end).days, 0) / 365.25
        return stub, roll, lt.net_debt, lt.minority_interest or 0.0, lt.period_end
    return 1.0, 0.0, fy.net_debt or 0.0, fy.minority_interest or 0.0, fy.period_end


STAKE_HAIRCUT = 0.30


def stakes(data: TearSheetData) -> float:
    """Equity stakes outside cash, at the DCF's balance-sheet date, after a 30% haircut (illiquidity, tax and
    marks; the haircut a strong published note used for Tencent's stakes). Round-4/5 reviews: NVIDIA's DCF left
    out ~USD 90bn of listed and unlisted stakes. US: SEC XBRL; HK / A-shares: associates, JVs and non-current
    financial assets from the statements (adapters.HK_STAKES / CN_STAKES); 0 when not reported."""
    fy, lt = data.financials.years[-1], data.financials.latest
    src = lt if (lt is not None and lt.net_debt is not None and lt.period_end > fy.period_end) else fy
    v = getattr(src, "equity_investments", None)
    return v * (1 - STAKE_HAIRCUT) if v and v > 0 else 0.0


def compute_dcf(data: TearSheetData, wacc: float, g: float, years: int,
                estimates, min_spread: float = 0.03) -> tuple[Optional[DCF], list[str]]:
    notes: list[str] = []
    if wacc < g + min_spread:
        return None, [f"DCF not shown: WACC ({wacc:.1%}) is less than {min_spread:.0%} above terminal growth "
                      f"({g:.1%}), so the terminal value would dominate; the discount-rate inputs (risk-free "
                      "rate, beta) need review."]
    fy = data.financials.years
    cur = fy[-1]
    path, basis_text = margin_path(data, years)
    if not path or not cur.revenue:
        return None, ["DCF not shown: cash flow or capex history unavailable."]
    margin = path[-1]
    if margin <= 0:
        return None, ["DCF not shown: free cash flow has been negative."]
    shares = _shares(data)
    fx = data.quote.fx_to_reporting or 1.0
    if not shares:
        return None, ["DCF not shown: share count unavailable."]

    cons = consensus_revenue(estimates, cur.revenue, data.financials.currency)
    revs, growth, basis = [], [], []
    prev = cur.revenue
    for r in cons[:years]:
        revs.append(r); growth.append(r / prev - 1); basis.append("consensus"); prev = r
    if cons:
        g0 = growth[-1]
    else:
        notes.append("No analyst consensus found; growth starts from the historical revenue CAGR.")
        g0 = min(max(data.financials.revenue_cagr or g, -0.05), 0.20)
    gt = g0
    for _ in range(len(revs), years):
        gt = fade_step(gt, g)
        prev = prev * (1 + gt)
        revs.append(prev); growth.append(gt); basis.append("fade")

    stub, roll, net_debt, minorities, bs_date = _stub(data)
    cs = stub_cash_share(data, revs[0], stub)
    inv = stakes(data)
    claims = net_debt + minorities - inv
    base = _dcf_value(revs, path, wacc, g, claims, fx, shares, min_spread, stub, roll, cs)
    if base is None:
        return None, notes + ["DCF not shown: discount rate too close to terminal growth."]
    ev, equity, per_share = base
    rows = [wacc + d for d in (-0.01, 0.0, 0.01)]  # exact: centre = base case
    cols = [g + d for d in (-0.005, 0.0, 0.005)]
    values = [[(v[2] if (v := _dcf_value(revs, path, w, gg, claims, fx, shares, min_spread, stub, roll, cs)) else None)
               for gg in cols] for w in rows]
    _, pv_terminal, factors = dcf_ev(revs, path, wacc, g, stub, roll, cs)
    grow = (1 + wacc) ** roll
    forecast = [ForecastYear(fiscal_year=cur.fiscal_year + i + 1, revenue=r, growth=gr,
                             free_cash_flow=r * m * (cs if i == 0 else 1.0), basis=b, discount_factor=f * grow,
                             present_value=r * m * (cs if i == 0 else 1.0) * f * grow)
                for i, (r, gr, m, b, f) in enumerate(zip(revs, growth, path, basis, factors))]
    terminal = revs[-1] * margin * (1 + g) / (wacc - g)
    bridge = EVBridge(pv_forecast=sum(f.present_value for f in forecast), pv_terminal=pv_terminal,
                      enterprise_value=ev, net_debt=net_debt, equity_value=equity, shares=shares,
                      fx_to_reporting=fx, value_per_share=per_share, terminal_share=pv_terminal / ev,
                      minority_interest=minorities or None, balance_sheet_date=bs_date,
                      roll_forward_years=roll or None, investments=inv or None)
    notes.append(f"FCF margin {basis_text}.")
    if stub < 1.0:
        notes.append(f"Valued at the latest balance sheet ({bs_date:%d %b %Y}): only the remaining {stub * 12:.0f} months "
                     f"of FY{cur.fiscal_year + 1} are counted ({cs:.0%} of its forecast cash flow: the forecast revenue "
                     f"not yet reported), then the value is rolled forward to the price date at WACC.")
    lt = data.financials.latest
    if lt is not None and not lt.capex_complete:
        notes.append(f"The source lacks {lt.label} capex, so the FCF margin uses fiscal-year data only and may not "
                     "reflect this year's investment; check the interim report.")
    if minorities:
        notes.append("Minority (non-controlling) interests are deducted at book value.")
    if inv:
        notes.append(f"Equity stakes outside cash (associates, joint ventures and other equity investments as "
                     f"reported) are added at a {STAKE_HAIRCUT:.0%} haircut.")
        notes.append("The DCF is an illustration of the assumptions, not a price target.")
    else:
        notes.append("DCF excludes non-operating assets not in net debt (e.g. investment stakes); "
                     "it is an illustration of the assumptions, not a price target.")
    return DCF(method=f"FCFF, {years}-year explicit forecast + Gordon terminal value",
               fcf_margin=margin, terminal_growth=g, forecast=forecast, enterprise_value=ev,
               equity_value=equity, value_per_share=per_share,
               upside=per_share / data.quote.price - 1 if data.quote.price else None,
               grid=ValueGrid(row_label="WACC", col_label="Terminal growth", rows=rows, cols=cols,
                              values=values), bridge=bridge, terminal_value=terminal,
               margin_path=path, stub_years=stub, stub_cash_share=cs, margin_basis=basis_text), notes


def compute_ddm(data: TearSheetData, ke: float, g: float, min_spread: float = 0.03) -> tuple[Optional[DDM], list[str]]:
    q = data.quote
    if not q.dividend_yield or not q.price:
        return None, ["DDM not shown: no dividend history."]
    dps = q.dividend_yield * q.price

    def val(k: float, gg: float) -> Optional[float]:
        return dps * (1 + gg) / (k - gg) if k >= gg + min_spread - 1e-9 else None

    base = val(ke, g)
    if base is None:
        return None, [f"DDM not shown: cost of equity ({ke:.1%}) is less than {min_spread:.0%} above growth ({g:.1%})."]
    rows = [ke + d for d in (-0.01, 0.0, 0.01)]
    cols = [g + d for d in (-0.005, 0.0, 0.005)]
    return DDM(method="Gordon growth on trailing dividend", dividend_per_share=dps, growth=g,
               value_per_share=base, upside=base / q.price - 1,
               grid=ValueGrid(row_label="Cost of equity", col_label="Dividend growth", rows=rows, cols=cols,
                              values=[[val(k, gg) for gg in cols] for k in rows])), \
        ["Banks and insurers are valued with a dividend discount model; WACC/DCF is not meaningful."]


def rf_label(data: TearSheetData) -> str:
    """Which 10-year yield is the risk-free rate: risk_free_by_currency in config/valuation.json, by reporting
    currency (the pipeline fetches backups for this label only)."""
    cfg = load_config(data.profile.ticker)
    return (cfg.get("risk_free_by_currency") or {}).get(data.financials.currency, "US 10Y")


def build(data: TearSheetData, stock: dict[date, float], bench: dict[date, float],
          yields: dict[str, float], estimates) -> Optional[Valuation]:
    if not data.financials.years or not data.quote.price:
        return None
    cfg = load_config(data.profile.ticker)
    rc = data.financials.currency
    label = rf_label(data)
    rf = yields.get(label)
    if rf is None:
        return None
    erp = _pick(cfg, "equity_risk_premium", rc, 0.05)
    erp_src = "InvestSync override" if "equity_risk_premium" in cfg["_override"] else \
        "Damodaran, January 2026"
    g = _pick(cfg, "terminal_growth", rc, 0.02)
    years = int(cfg.get("explicit_years", 5))
    min_spread = float(cfg["_override"].get("min_spread", cfg.get("min_spread", 0.03)))
    financial = is_financial(data)
    b = beta(stock, bench, int(cfg.get("beta_years", 2)))
    w = compute_wacc(data, b, rf, f"{label} government bond", erp, erp_src,
                     _pick(cfg, "statutory_tax", rc, 0.25), financial)
    notes: list[str] = []
    dcf = ddm = None
    if financial:
        ddm, n = compute_ddm(data, w.cost_of_equity, g, min_spread)
    else:
        dcf, n = compute_dcf(data, w.wacc, g, years, estimates, min_spread)
    notes += n
    if b is None:
        notes.append("Beta unavailable (short price history); 1.0 assumed.")
    val = Valuation(currency=data.quote.currency, wacc=w, dcf=dcf, ddm=ddm, notes=notes)
    from . import sensitivity  # full-report extras: grids, reverse DCF, Monte Carlo
    sensitivity.extend(val, data, min_spread)
    return val
