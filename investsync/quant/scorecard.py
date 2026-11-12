"""Scorecard: yes/no checks in five areas (value, future growth, past performance, financial
health, dividend) plus the Piotroski F-score.

The five areas follow the checks in Simply Wall St's published analysis model
(github.com/SimplyWallSt/Company-Analysis-Model, CC BY-NC-SA 4.0), adapted to the data we have:
the company's peers stand in for "the market" (we have no market-wide data), and dividend-yield
cut-offs are fixed per market. Every check states the figures behind it. The scorecard is
descriptive and never feeds the rating.
"""
from __future__ import annotations

from typing import Optional

from ..render.viewmodel import ccy, mult, num, pct
from ..schema import ScoreArea, ScoreCheck, Scorecard, TearSheetData

# Dividend-yield cut-offs per market: (notable, high). Rough lower / upper quartiles of dividend payers.
YIELD_CUTS = {"CN": (0.015, 0.035), "HK": (0.03, 0.06), "US": (0.015, 0.04)}


def _c(name: str, passed: Optional[bool], detail: str) -> ScoreCheck:
    return ScoreCheck(name=name, passed=passed, detail=detail)


def _area(key, title, checks, note=None) -> ScoreArea:
    avail = [c for c in checks if c.passed is not None]
    return ScoreArea(key=key, title=title, score=sum(1 for c in avail if c.passed), available=len(avail),
                     checks=checks, note=note)


def _fwd_growth(data: TearSheetData) -> tuple[Optional[float], Optional[float], str, list[float]]:
    """(annual EPS growth, annual revenue growth, source label, EPS path) from brokers or consensus."""
    years = [y for y in data.financials.years if y.diluted_eps]
    last = years[-1] if years else None
    eps_path: list[float] = []
    g_eps, src = None, ""
    st = data.street
    if st and st.eps and last and last.diluted_eps and last.diluted_eps > 0:
        eps_path = [e.median for e in st.eps]
        n = len(eps_path)
        if eps_path[-1] > 0:
            g_eps = (eps_path[-1] / last.diluted_eps) ** (1 / n) - 1
            src = f"broker median EPS to {st.eps[-1].period}"
    c = data.consensus
    if g_eps is None and c and c.estimates and last and last.diluted_eps and last.diluted_eps > 0 \
            and c.estimate_currency in (None, data.financials.currency):
        fwd = [e for e in c.estimates if e.eps_avg and e.period.upper().startswith("FY")]
        if fwd:
            eps_path = [e.eps_avg for e in fwd]
            if eps_path[-1] > 0:
                g_eps = (eps_path[-1] / last.diluted_eps) ** (1 / len(eps_path)) - 1
                src = f"consensus EPS to {fwd[-1].period}"
    g_rev = None
    v = data.valuation
    if v and v.dcf:
        cons = [f for f in v.dcf.forecast if f.basis == "consensus"]
        if cons:
            g_rev = sum(f.growth for f in cons) / len(cons)
    if g_rev is None and c and c.estimates:
        rg = [e.revenue_growth for e in c.estimates if e.revenue_growth is not None]
        g_rev = sum(rg) / len(rg) if rg else None
    return g_eps, g_rev, src, eps_path


def _value(data: TearSheetData, g_eps: Optional[float], fin: bool) -> ScoreArea:
    q, rt, cp, band = data.quote, data.rating, data.comps, data.pe_band
    cur = ccy(q.currency)
    fv = rt.fair_value if rt and rt.fair_value else None
    pe, med = q.pe_ttm, cp.median if cp else None
    checks = [
        _c("Below fair value", None if fv is None else q.price < fv,
           f"Price {cur} {num(q.price, 2)} vs model fair value {cur} {num(fv, 2)}" if fv else "No model fair value"),
        _c("Well below fair value (≥ 20%)", None if fv is None else q.price <= 0.8 * fv,
           f"Needs a price at or below {cur} {num(0.8 * fv, 2)}" if fv else "No model fair value"),
        _c("P/E below peers", None if not (pe and med and med.pe_ttm) else pe < med.pe_ttm,
           f"P/E {mult(pe)} vs peer median {mult(med.pe_ttm)}" if pe and med and med.pe_ttm else "Peer P/E unavailable"),
        _c("P/E below its own 5-year median", None if not (pe and band) else pe < band.median,
           f"P/E {mult(pe)} vs 5-year median {mult(band.median)}" if pe and band else "P/E history unavailable"),
    ]
    if fin:
        pb, mpb = q.pb, med.pb if med else None
        checks.append(_c("P/B below peers", None if not (pb and mpb) else pb < mpb,
                         f"P/B {mult(pb)} vs peer median {mult(mpb)}" if pb and mpb else "Peer P/B unavailable"))
    else:
        ev, mev = (cp.target.ev_ebitda if cp else None), (med.ev_ebitda if med else None)
        checks.append(_c("EV/EBITDA below peers", None if not (ev and mev) else ev < mev,
                         f"EV/EBITDA {mult(ev)} vs peer median {mult(mev)}" if ev and mev else "EV/EBITDA unavailable"))
    peg = pe / (g_eps * 100) if pe and g_eps and g_eps > 0 else None
    checks.append(_c("PEG below 1", None if peg is None else peg < 1,
                     f"P/E {mult(pe)} ÷ forecast EPS growth {pct(g_eps)} a year = PEG {num(peg, 2)}" if peg
                     else "Needs positive forecast EPS growth"))
    return _area("value", "Value", checks)


def _future(data: TearSheetData, g_eps, g_rev, src, eps_path) -> ScoreArea:
    rf = data.valuation.wacc.risk_free if data.valuation else None
    med = data.comps.median if data.comps else None
    peer_g = med.revenue_growth if med else None
    ys = data.financials.years
    last = ys[-1] if ys else None
    bvps = (last.total_equity / (last.net_income / last.diluted_eps)
            if last and last.total_equity and last.net_income and last.diluted_eps else None)
    roe_f = eps_path[0] / bvps if eps_path and bvps and bvps > 0 else None
    rising = None
    if eps_path and last and last.diluted_eps:
        path = [last.diluted_eps] + eps_path
        rising = all(b > a for a, b in zip(path, path[1:]))
    checks = [
        _c("EPS growth beats the bond yield", None if g_eps is None or rf is None else g_eps > rf,
           f"Forecast {pct(g_eps)} a year ({src}) vs 10-year bond {pct(rf, 2)}" if g_eps is not None and rf is not None
           else "No EPS forecasts"),
        _c("High EPS growth (> 20% a year)", None if g_eps is None else g_eps > 0.20,
           f"Forecast {pct(g_eps)} a year" if g_eps is not None else "No EPS forecasts"),
        _c("Revenue growth beats peers", None if g_rev is None or peer_g is None else g_rev > peer_g,
           f"Forecast {pct(g_rev)} a year vs peers' latest {pct(peer_g)}" if g_rev is not None and peer_g is not None
           else "Revenue forecast or peer growth unavailable"),
        _c("High revenue growth (> 20% a year)", None if g_rev is None else g_rev > 0.20,
           f"Forecast {pct(g_rev)} a year (consensus)" if g_rev is not None else "No revenue forecast"),
        _c("EPS expected to rise every year", rising,
           "Forecast path " + " → ".join(num(x, 2) for x in ([last.diluted_eps] + eps_path)) if rising is not None
           else "No EPS forecasts"),
        _c("Forward ROE above 20%", None if roe_f is None else roe_f > 0.20,
           f"Next-year EPS ÷ today's book value per share = {pct(roe_f)}" if roe_f is not None else "Not enough data"),
    ]
    return _area("future", "Future growth", checks)


def _past(data: TearSheetData) -> ScoreArea:
    ys = [y for y in data.financials.years if y.net_income is not None]
    rcur = ccy(data.financials.currency)
    r = data.ratios[-1] if data.ratios else None
    med = data.comps.median if data.comps else None
    last, first = (ys[-1], ys[0]) if len(ys) >= 4 else (None, None)
    prev = ys[-2] if len(ys) >= 2 else None
    yoy = (last.net_income / prev.net_income - 1) if last and prev and prev.net_income and prev.net_income > 0 else None
    cagr = data.financials.net_income_cagr
    eq = data.earnings_quality
    nm_now = ys[-1].net_margin if ys else None
    nm_prev = ys[-2].net_margin if len(ys) >= 2 else None
    rg = data.financials.years[-1].revenue_growth if data.financials.years else None
    checks = [
        _c("Profit higher than at the start of the period", None if not last else last.net_income > first.net_income,
           f"FY{last.fiscal_year} {rcur} {num(last.net_income / 1e6, 0)} mn vs FY{first.fiscal_year} "
           f"{rcur} {num(first.net_income / 1e6, 0)} mn" if last else "Fewer than 4 years of results"),
        _c("Latest profit growth above its average", None if yoy is None or cagr is None else yoy > cagr,
           f"Latest year {pct(yoy, 1, signed=True)} vs {data.financials.cagr_years}-year CAGR {pct(cagr)}"
           if yoy is not None and cagr is not None else "Not enough history"),
        _c("Revenue growth beats peers", None if rg is None or not med or med.revenue_growth is None
           else rg > med.revenue_growth,
           f"Latest year {pct(rg, 1, signed=True)} vs peer median {pct(med.revenue_growth)}"
           if rg is not None and med and med.revenue_growth is not None else "Peer growth unavailable"),
        _c("High ROE (> 20%)", None if not r or r.roe is None else r.roe > 0.20,
           f"ROE FY{r.fiscal_year} {pct(r.roe)}" if r and r.roe is not None else "ROE unavailable"),
        _c("Profit backed by cash (CFO ≥ 80% of profit)",
           None if not eq or eq.cfo_to_net_income is None else eq.cfo_to_net_income >= 0.8,
           f"Operating cash flow ÷ net profit = {mult(eq.cfo_to_net_income, 2)}" if eq and eq.cfo_to_net_income
           is not None else "Cash flow unavailable"),
        _c("Net margin up on last year", None if nm_now is None or nm_prev is None else nm_now > nm_prev,
           f"{pct(nm_now)} vs {pct(nm_prev)}" if nm_now is not None and nm_prev is not None else "Not enough history"),
    ]
    return _area("past", "Past performance", checks)


def _health(data: TearSheetData, fin: bool) -> ScoreArea:
    if fin:
        return _area("health", "Financial health", [], note="Not scored for banks and insurers: their balance "
                     "sheets are mostly borrowed funds, so these checks do not apply.")
    ys = data.financials.years
    y = ys[-1] if ys else None
    rcur = ccy(data.financials.currency)

    def mn(v):
        return f"{rcur} {num(v / 1e6, 0)} mn" if v is not None else "–"
    ca, cl = (y.current_assets, y.current_liabilities) if y else (None, None)
    ltl = (y.total_liabilities - y.current_liabilities) if y and y.total_liabilities is not None \
        and y.current_liabilities is not None else None
    # debt and equity at the latest balance sheet (interim) when the source has it; the fiscal year otherwise
    lt = data.financials.latest
    debt = lt.total_debt if lt is not None and lt.total_debt is not None else (y.total_debt if y else None)
    equity = lt.total_equity if lt is not None and lt.total_equity else (y.total_equity if y else None)
    net_debt = lt.net_debt if lt is not None and lt.net_debt is not None else (y.net_debt if y else None)
    when = f" ({lt.period_end:%d %b %Y})" if lt is not None and lt.total_debt is not None else ""
    de = (debt / equity) if debt is not None and equity else None
    first = next((z for z in ys if z.total_debt is not None and z.total_equity), None)
    de0 = (first.total_debt / first.total_equity) if first and first is not y else None
    ocf_cov = (y.operating_cash_flow / debt) if y and y.operating_cash_flow is not None and debt else None
    icov = (y.operating_income / y.interest_expense) if y and y.operating_income is not None and y.interest_expense \
        else None
    checks = [
        _c("Short-term assets cover short-term liabilities", None if ca is None or cl is None else ca > cl,
           f"{mn(ca)} vs {mn(cl)}"),
        _c("Short-term assets cover long-term liabilities", None if ca is None or ltl is None else ca > ltl,
           f"{mn(ca)} vs {mn(ltl)}"),
        _c("Low debt (debt/equity < 40% or net cash)",
           None if de is None else (de < 0.40 or (net_debt is not None and net_debt < 0)),
           f"Debt/equity {pct(de)}; net debt {mn(net_debt)}{when}" if de is not None else "Debt unavailable"),
        _c("Debt/equity lower than at the start", None if de is None or de0 is None else de <= de0,
           f"{pct(de)} vs {pct(de0)} in FY{first.fiscal_year}" if de is not None and de0 is not None
           else "Not enough history"),
        _c("Debt covered by operating cash flow (> 20%)",
           None if y is None or debt is None else (debt == 0 or (ocf_cov or 0) > 0.20),
           "No debt" if debt == 0 else f"FY operating cash flow = {pct(ocf_cov, 0)} of debt{when}"
           if ocf_cov is not None else "Not enough data"),
        _c("Interest covered by profit (EBIT ≥ 5×)",
           None if y is None else (True if not y.interest_expense else (icov or 0) >= 5) if y.operating_income
           is not None else None,
           "No interest expense reported" if y and not y.interest_expense else f"EBIT ÷ interest = {mult(icov)}"
           if icov is not None else "Not enough data"),
    ]
    return _area("health", "Financial health", checks)


def _dividend(data: TearSheetData) -> ScoreArea:
    q = data.quote
    notable, high = YIELD_CUTS.get(data.profile.market.value, (0.015, 0.04))
    dy = q.dividend_yield or 0.0
    hist = sorted(data.dividends, key=lambda d: d.year)
    full = [d for d in hist if d.year < q.as_of.year]  # complete calendar years only
    stable = growing = None
    if len(full) >= 5:
        stable = all(b.dps >= 0.9 * a.dps for a, b in zip(full, full[1:]))
        growing = full[-1].dps > full[-5].dps
    r = data.ratios[-1] if data.ratios else None
    y = data.financials.years[-1] if data.financials.years else None
    cash_pay = (y.dividends_paid / y.free_cash_flow) if y and y.dividends_paid and y.free_cash_flow \
        and y.free_cash_flow > 0 else None
    pays = dy > 0
    checks = [
        _c(f"Notable yield (≥ {pct(notable)})", dy >= notable, f"Yield {pct(dy)}" if pays else "No dividend"),
        _c(f"High yield (≥ {pct(high)})", dy >= high, f"Yield {pct(dy)}" if pays else "No dividend"),
        _c("Stable: no cut over 10% in 5+ years", stable if pays else False,
           ("Dividend per share " + ", ".join(f"{d.year} {num(d.dps, 2)}" for d in full[-5:])) if stable is not None
           else ("No dividend" if not pays else "Fewer than 5 full years of history")),
        _c("Growing: higher than 5 years ago", growing if pays else False,
           f"{full[-1].year} {num(full[-1].dps, 2)} vs {full[-5].year} {num(full[-5].dps, 2)}" if growing is not None
           else ("No dividend" if not pays else "Fewer than 5 full years of history")),
        _c("Covered by profit (payout < 90%)",
           None if not pays or not r or r.payout_ratio is None else r.payout_ratio < 0.9,
           f"Payout ratio {pct(r.payout_ratio)}" if r and r.payout_ratio is not None else
           ("No dividend" if not pays else "Payout unavailable")),
        _c("Covered by free cash flow (< 90%)", None if not pays or cash_pay is None else cash_pay < 0.9,
           f"Dividends ÷ free cash flow = {pct(cash_pay)}" if cash_pay is not None else
           ("No dividend" if not pays else "Free cash flow unavailable")),
    ]
    if not pays:
        for c in checks:
            c.passed = False
    return _area("dividend", "Dividend", checks)


def piotroski(data: TearSheetData) -> Optional[ScoreArea]:
    """Piotroski F-score: nine yes/no tests of profitability, funding and efficiency (latest vs prior year)."""
    ys, rs = data.financials.years, {r.fiscal_year: r for r in data.ratios}
    if len(ys) < 2:
        return None
    t, p = ys[-1], ys[-2]
    rt, rp = rs.get(t.fiscal_year), rs.get(p.fiscal_year)

    def cmp(a, b, better="up"):
        if a is None or b is None:
            return None
        return a > b if better == "up" else a < b

    def ratio(a, b):
        return a / b if a is not None and b else None
    sh_t, sh_p = ratio(t.net_income, t.diluted_eps), ratio(p.net_income, p.diluted_eps)
    lev_t, lev_p = ratio(t.total_debt, t.total_assets), ratio(p.total_debt, p.total_assets)
    cr_t, cr_p = ratio(t.current_assets, t.current_liabilities), ratio(p.current_assets, p.current_liabilities)
    roa_t, roa_p = (rt.roa if rt else None), (rp.roa if rp else None)
    at_t, at_p = (rt.asset_turnover if rt else None), (rp.asset_turnover if rp else None)
    fy = f"FY{t.fiscal_year} vs FY{p.fiscal_year}"
    checks = [
        _c("Positive return on assets", None if roa_t is None else roa_t > 0, f"ROA {pct(roa_t)}"),
        _c("Positive operating cash flow", None if t.operating_cash_flow is None else t.operating_cash_flow > 0,
           f"{ccy(data.financials.currency)} {num((t.operating_cash_flow or 0) / 1e6, 0)} mn"),
        _c("Return on assets improved", cmp(roa_t, roa_p), f"{pct(roa_t)} vs {pct(roa_p)} ({fy})"),
        _c("Cash flow above profit", cmp(t.operating_cash_flow, t.net_income),
           f"Operating cash flow ÷ profit = {mult(ratio(t.operating_cash_flow, t.net_income), 2)}"),
        _c("Leverage fell (debt ÷ assets)", (True if (t.total_debt == 0) else cmp(lev_t, lev_p, "down")),
           f"{pct(lev_t)} vs {pct(lev_p)}"),
        _c("Liquidity improved (current ratio)", cmp(cr_t, cr_p), f"{mult(cr_t, 2)} vs {mult(cr_p, 2)}"),
        _c("No new shares issued (> 2%)", None if not (sh_t and sh_p) else sh_t <= sh_p * 1.02,
           f"Implied share count {pct(sh_t / sh_p - 1, 1, signed=True)}" if sh_t and sh_p else "Share count unavailable"),
        _c("Gross margin improved", cmp(t.gross_margin, p.gross_margin), f"{pct(t.gross_margin)} vs {pct(p.gross_margin)}"),
        _c("Asset turnover improved", cmp(at_t, at_p), f"{mult(at_t, 2)} vs {mult(at_p, 2)}"),
    ]
    return _area("past", "Piotroski F-score", checks,
                 note="8–9 strong, 0–2 weak (Piotroski 2000). Shares are implied from profit ÷ EPS.")


def build(data: TearSheetData) -> Optional[Scorecard]:
    if not data.financials.years:
        return None
    from .valuation import is_financial
    fin = is_financial(data)
    g_eps, g_rev, src, path = _fwd_growth(data)
    areas = [_value(data, g_eps, fin), _future(data, g_eps, g_rev, src, path), _past(data), _health(data, fin),
             _dividend(data)]
    return Scorecard(areas=areas, piotroski=None if fin else piotroski(data))
