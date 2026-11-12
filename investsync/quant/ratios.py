"""Per-year financial ratios for the full report (profitability, returns, liquidity, leverage,
efficiency, cash flow and shareholder returns). Computed in code from reported statements;
averages use the opening and closing balance of each year; without an opening balance (the oldest year)
those ratios are left blank.
"""
from __future__ import annotations

from typing import Optional

from ..schema import FiscalYear, RatioYear


def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _avg(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    # no opening balance -> no average (shown as "–"): the oldest year used to fall back to its closing balance under an
    # "average balances" label, which a blind reviewer counted as an error (NVIDIA FY2022 ROE 36.6% vs 44.8%)
    if cur is None or prev is None:
        return None
    return (cur + prev) / 2


def _positive(v: Optional[float]) -> Optional[float]:
    return v if v is not None and v > 0 else None


def ratio_years(years: list[FiscalYear], statutory_tax: float = 0.25) -> list[RatioYear]:
    """One RatioYear per fiscal year (oldest -> newest)."""
    out: list[RatioYear] = []
    prev: Optional[FiscalYear] = None
    for y in years:
        p = prev
        avg_assets = _avg(y.total_assets, p.total_assets if p else None)
        avg_equity = _avg(y.total_equity, p.total_equity if p else None)
        avg_recv = _avg(y.receivables, p.receivables if p else None)
        avg_inv = _avg(y.inventory, p.inventory if p else None)

        tax = _div(y.income_tax, _positive(y.pretax_income))
        tax_used = min(max(tax, 0.0), 0.40) if tax is not None else statutory_tax
        # ROIC = NOPAT / invested capital (equity + debt - cash), closing balances
        invested = None
        if y.total_equity is not None and y.total_debt is not None and y.cash_and_equivalents is not None:
            invested = y.total_equity + y.total_debt - y.cash_and_equivalents
        nopat = y.operating_income * (1 - tax_used) if y.operating_income is not None else None
        cost_of_revenue = (y.revenue - y.gross_profit) if y.revenue is not None and y.gross_profit is not None else None
        returned = None
        if y.dividends_paid is not None or y.buybacks is not None:
            returned = (y.dividends_paid or 0.0) + (y.buybacks or 0.0)

        out.append(RatioYear(
            fiscal_year=y.fiscal_year,
            roe=_div(y.net_income, _positive(avg_equity)),
            roa=_div(y.net_income, _positive(avg_assets)),
            roic=_div(nopat, _positive(invested)),
            gross_margin=y.gross_margin if y.gross_margin is not None else _div(y.gross_profit, y.revenue),
            operating_margin=_div(y.operating_income, y.revenue),
            ebitda_margin=_div(y.ebitda, y.revenue),
            net_margin=y.net_margin if y.net_margin is not None else _div(y.net_income, y.revenue),
            fcf_margin=_div(y.free_cash_flow, y.revenue),
            revenue_growth=y.revenue_growth,
            eps_growth=(y.diluted_eps / p.diluted_eps - 1) if (p and p.diluted_eps and p.diluted_eps > 0
                                                               and y.diluted_eps is not None) else None,
            sga_ratio=_div(y.sga_expense, y.revenue),
            rnd_ratio=_div(y.rnd_expense, y.revenue),
            capex_ratio=_div(y.capex, y.revenue),
            effective_tax=tax,
            current_ratio=_div(y.current_assets, y.current_liabilities),
            debt_to_equity=_div(y.total_debt, _positive(y.total_equity)),
            liabilities_to_assets=_div(y.total_liabilities, y.total_assets),
            net_debt_to_ebitda=_div(y.net_debt, _positive(y.ebitda)),
            interest_coverage=_div(y.operating_income, _positive(y.interest_expense)),
            asset_turnover=_div(y.revenue, _positive(avg_assets)),
            equity_multiplier=_div(avg_assets, _positive(avg_equity)),
            receivable_days=_div(avg_recv, y.revenue) * 365 if _div(avg_recv, y.revenue) is not None else None,
            inventory_days=_div(avg_inv, _positive(cost_of_revenue)) * 365
            if _div(avg_inv, _positive(cost_of_revenue)) is not None else None,
            cash_conversion=_div(y.operating_cash_flow, _positive(y.net_income)),
            accruals_ratio=_div(y.net_income - y.operating_cash_flow, _positive(avg_assets))
            if y.net_income is not None and y.operating_cash_flow is not None else None,
            payout_ratio=_div(y.dividends_paid, _positive(y.net_income)),
            total_payout_ratio=_div(returned, _positive(y.net_income)),
        ))
        prev = y
    return out
