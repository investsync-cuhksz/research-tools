"""Deterministic financial metrics. No LLM ever computes any of these."""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median
from typing import Iterable, Optional

from ..schema import (BenchmarkPeriod, CompRow, Comps, DuPont, EarningsQuality, Financials,
                      FiscalYear, SeriesPoint, TTMFigures)


def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _avg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None:
        return b
    if b is None:
        return a
    return (a + b) / 2


def fill_derived(years: list[FiscalYear]) -> list[FiscalYear]:
    """Fill growth, margins, net debt and EBITDA in place (years oldest -> newest)."""
    prev: Optional[FiscalYear] = None
    for y in years:
        if prev and prev.revenue and y.revenue is not None and prev.revenue > 0:
            y.revenue_growth = y.revenue / prev.revenue - 1
        y.gross_margin = _div(y.gross_profit, y.revenue)
        y.net_margin = _div(y.net_income, y.revenue)
        if y.total_debt is not None and y.cash_and_equivalents is not None:
            y.net_debt = y.total_debt - y.cash_and_equivalents
        if y.operating_income is not None and y.depreciation_amortization is not None:
            y.ebitda = y.operating_income + y.depreciation_amortization
        if y.operating_cash_flow is not None and y.capex is not None:
            y.free_cash_flow = y.operating_cash_flow - y.capex
        prev = y
    return years


def cagr(first: Optional[float], last: Optional[float], years: int) -> Optional[float]:
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


_SPLIT_FACTORS = (2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50, 100)


def restate_eps_for_splits(years: list[FiscalYear],
                           events: Optional[list[tuple[date, float]]] = None) -> list[str]:
    """Put historical EPS on the latest share basis when a source has not adjusted for splits.

    Implied share count = net income / EPS. For each earlier year, the candidate adjustment
    factors are either the known corporate actions after that year (``events``: ex-date and
    share multiplier, e.g. 1.8 for a 10-for-8 bonus issue; a source may already have applied
    some of them) or, if none are known, standard split ratios. The candidate that brings the
    implied share count closest to the latest year's is applied. Returns notes.
    """
    notes = []
    base = next((y for y in reversed(years) if y.diluted_eps and y.net_income), None)
    if not base:
        return notes
    base_shares = base.net_income / base.diluted_eps
    for y in years:
        if y is base or not y.diluted_eps or not y.net_income or y.net_income * base.net_income <= 0:
            continue
        ratio = base_shares / (y.net_income / y.diluted_eps)
        if events is not None:
            later = [f for d, f in sorted(events) if d > y.period_end and f > 1.0]
            # the source may already have applied the earliest of these actions
            cands = [1.0] + [math.prod(later[k:]) for k in range(len(later))]
            factor = min(cands, key=lambda f: abs(math.log(ratio / f)))
            if factor > 1.0 and abs(math.log(ratio / factor)) < abs(math.log(ratio)):
                y.diluted_eps = y.diluted_eps / factor
                notes.append(f"FY{y.fiscal_year} EPS restated for bonus shares / splits (x{factor:g}).")
            continue
        factor = min(_SPLIT_FACTORS, key=lambda f: abs(ratio - f) / f)
        if ratio > 1.6 and abs(ratio - factor) / factor < 0.12:
            y.diluted_eps = y.diluted_eps / factor
            notes.append(f"FY{y.fiscal_year} EPS restated for a {factor}-for-1 share split.")
    return notes


def _growth(now: Optional[float], prior: Optional[float]) -> Optional[float]:
    return now / prior - 1 if now is not None and prior is not None and prior > 0 else None


def fill_latest(fin: Financials) -> None:
    """Derived fields of the latest interim period, and trailing twelve months (FY + YTD - prior YTD)."""
    lt = fin.latest
    if lt is None:
        return
    lt.revenue_growth = _growth(lt.revenue, lt.prior_revenue)
    lt.net_income_growth = _growth(lt.net_income, lt.prior_net_income)
    lt.gross_margin = _div(lt.gross_profit, lt.revenue)
    lt.prior_gross_margin = _div(lt.prior_gross_profit, lt.prior_revenue)
    if lt.capex_complete:
        if lt.operating_cash_flow is not None and lt.capex is not None:
            lt.free_cash_flow = lt.operating_cash_flow - lt.capex
        if lt.prior_operating_cash_flow is not None and lt.prior_capex is not None:
            lt.prior_free_cash_flow = lt.prior_operating_cash_flow - lt.prior_capex
    if lt.total_debt is not None and lt.cash_and_equivalents is not None:
        lt.net_debt = lt.total_debt - lt.cash_and_equivalents
    lt.quarter_revenue_growth = _growth(lt.quarter_revenue, lt.quarter_revenue_prior)
    lt.quarter_net_income_growth = _growth(lt.quarter_net_income, lt.quarter_net_income_prior)
    lt.quarter_gross_margin = _div(lt.quarter_gross_profit, lt.quarter_revenue)
    lt.quarter_gross_margin_prior = _div(lt.quarter_gross_profit_prior, lt.quarter_revenue_prior)
    fy = fin.years[-1] if fin.years else None
    if fy is None or not (0 < (lt.period_end - fy.period_end).days < 366):
        return

    def roll(a, b, c):
        return a + b - c if None not in (a, b, c) else None
    rev = roll(fy.revenue, lt.revenue, lt.prior_revenue)
    ocf = roll(fy.operating_cash_flow, lt.operating_cash_flow, lt.prior_operating_cash_flow)
    capex = roll(fy.capex, lt.capex, lt.prior_capex) if lt.capex_complete else None
    fcf = ocf - capex if ocf is not None and capex is not None else None
    fin.ttm = TTMFigures(period_end=lt.period_end, basis=f"FY{fy.fiscal_year} + {lt.label} - the same period a year earlier",
                         revenue=rev, net_income=roll(fy.net_income, lt.net_income, lt.prior_net_income),
                         operating_cash_flow=ocf, capex=capex, free_cash_flow=fcf, fcf_margin=_div(fcf, rev))


def finalize_financials(fin: Financials) -> Financials:
    fin.years = fill_derived(sorted(fin.years, key=lambda y: y.fiscal_year))
    if len(fin.years) >= 2:
        first, last = fin.years[0], fin.years[-1]
        n = last.fiscal_year - first.fiscal_year
        fin.cagr_years = n
        fin.revenue_cagr = cagr(first.revenue, last.revenue, n)
        fin.net_income_cagr = cagr(first.net_income, last.net_income, n)
    fill_latest(fin)
    return fin


def dupont(fin: Financials) -> Optional[DuPont]:
    """ROE = net margin x asset turnover x equity multiplier, on average balances."""
    if not fin.years:
        return None
    cur = fin.years[-1]
    prev = fin.years[-2] if len(fin.years) >= 2 else None
    avg_assets = _avg(cur.total_assets, prev.total_assets if prev else None)
    avg_equity = _avg(cur.total_equity, prev.total_equity if prev else None)
    nm = _div(cur.net_income, cur.revenue)
    at = _div(cur.revenue, avg_assets)
    em = _div(avg_assets, avg_equity)
    roe = nm * at * em if None not in (nm, at, em) else _div(cur.net_income, avg_equity)
    return DuPont(fiscal_year=cur.fiscal_year, net_margin=nm, asset_turnover=at,
                  equity_multiplier=em, roe=roe)


def earnings_quality(fin: Financials) -> Optional[EarningsQuality]:
    """Accrual check: earnings well above operating cash flow are lower quality."""
    if not fin.years:
        return None
    cur = fin.years[-1]
    prev = fin.years[-2] if len(fin.years) >= 2 else None
    avg_assets = _avg(cur.total_assets, prev.total_assets if prev else None)
    accruals = None
    if cur.net_income is not None and cur.operating_cash_flow is not None:
        accruals = _div(cur.net_income - cur.operating_cash_flow, avg_assets)
    return EarningsQuality(fiscal_year=cur.fiscal_year,
                           cfo_to_net_income=_div(cur.operating_cash_flow, cur.net_income),
                           accruals_ratio=accruals)


COMP_METRICS = ("pe_ttm", "pe_fwd", "ev_ebitda", "pb", "dividend_yield")
OPERATING_METRICS = ("revenue_growth", "gross_margin", "operating_margin", "net_margin", "roe")
_POSITIVE_ONLY = {"pe_ttm", "pe_fwd", "ev_ebitda", "pb"}  # negative multiples are not meaningful
# Values beyond these are treated as data errors or "not meaningful" (NM)
_CEILING = {"pe_ttm": 1000.0, "pe_fwd": 1000.0, "ev_ebitda": 500.0, "pb": 200.0, "dividend_yield": 0.25}


def _clean(metric: str, v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    if metric in _POSITIVE_ONLY and v <= 0:
        return None
    if v > _CEILING[metric] or v < 0:
        return None
    return v


def build_comps(target: CompRow, peers: list[CompRow], method: str) -> Comps:
    target = target.model_copy(update={m: _clean(m, getattr(target, m)) for m in COMP_METRICS})
    peers = [p.model_copy(update={m: _clean(m, getattr(p, m)) for m in COMP_METRICS}) for p in peers]
    med: dict[str, Optional[float]] = {}
    prem: dict[str, Optional[float]] = {}
    for m in COMP_METRICS:
        vals = [getattr(p, m) for p in peers if getattr(p, m) is not None]
        med[m] = median(vals) if vals else None
        t = getattr(target, m)
        prem[m] = (t / med[m] - 1) if (t is not None and med[m]) else None
    mcaps = [p.market_cap for p in peers if p.market_cap is not None]
    for m in OPERATING_METRICS:  # medians only; no premium/discount for operating metrics
        vals = [getattr(p, m) for p in peers if getattr(p, m) is not None]
        med[m] = median(vals) if vals else None
    median_row = CompRow(ticker="MEDIAN", name="Peer median",
                         market_cap=median(mcaps) if mcaps else None, **med)
    return Comps(method=method, target=target, peers=peers, median=median_row, premium_discount=prem)


def _downsample(points: list[tuple[date, float]], max_points: int) -> list[tuple[date, float]]:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    out = [points[int(i * step)] for i in range(max_points)]
    if out[-1] != points[-1]:
        out[-1] = points[-1]
    return out


def rebase_periods(stock: dict[date, float], bench: dict[date, float],
                   periods: Iterable[tuple[str, int]] = (("1Y", 1), ("3Y", 3), ("5Y", 5)),
                   max_points: int = 160) -> list[BenchmarkPeriod]:
    """Rebase both series to 100 at the first common date on/after each period start."""
    common = sorted(set(stock) & set(bench))
    if not common:
        return []
    end = common[-1]
    out = []
    for label, years in periods:
        start = end - timedelta(days=round(365.25 * years))
        window = [d for d in common if d >= start]
        if len(window) < 20 or (window[0] - start).days > 45:
            continue  # not enough history for this period
        s0, b0 = stock[window[0]], bench[window[0]]
        pts = _downsample([(d, 0.0) for d in window], max_points)
        s_series = [SeriesPoint(d=d, v=round(stock[d] / s0 * 100, 2)) for d, _ in pts]
        b_series = [SeriesPoint(d=d, v=round(bench[d] / b0 * 100, 2)) for d, _ in pts]
        out.append(BenchmarkPeriod(
            period=label, start=window[0], stock=s_series, benchmark=b_series,
            stock_return=stock[window[-1]] / s0 - 1, benchmark_return=bench[window[-1]] / b0 - 1))
    return out


def warranty_break(fin, market) -> "Optional[str]":
    """A-shares: CAS Interpretation No. 18 (Dec 2024) moved assurance-type warranty costs from selling expenses into
    cost of sales, restating only the prior year. Data sources then show earlier years on the old basis, so their
    gross margins are overstated against later years (round-3 review of CATL: "restate gross-margin history on a
    consistent basis, or flag the warranty reclassification"). Detected from the data: selling and admin costs as a
    share of revenue drop by at least 1.5pp into FY2023 or FY2024."""
    from ..schema import Market
    if market != Market.CN:
        return None
    ys = {y.fiscal_year: y for y in fin.years if y.revenue and y.sga_expense is not None}
    for t in (2023, 2024):
        a, b = ys.get(t - 1), ys.get(t)
        if not a or not b:
            continue
        ra, rb = a.sga_expense / a.revenue, b.sga_expense / b.revenue
        if ra - rb >= 0.015:
            return (f"Gross margins for FY{t - 1} and earlier are probably on the old basis: from FY{t}, warranty costs "
                    f"sit in cost of sales, not selling expenses (CAS Interpretation No. 18; selling and admin costs fell "
                    f"from {ra:.1%} to {rb:.1%} of revenue). Compare gross margins only from FY{t} on; operating margin "
                    f"is unaffected.")
    return None
