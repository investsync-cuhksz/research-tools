"""Value ranges per share from several methods ("football field") and the stock's own
historical P/E band. All per-share figures are in the trading currency.

Football field bars (each shown only when its inputs exist):
* 52-week trading range
* Analyst price targets (third-party consensus, low - high, mean marked)
* Peer P/E, EV/EBITDA and P/B: the peers' 25th-75th percentile multiple (min-max with 3 peers)
  applied to the company's own TTM EPS (price / P/E), latest EBITDA and book value
  (price / P/B); the peer median is marked
* DCF / DDM: the full sensitivity grid range, base case marked
* Monte Carlo: 10th-90th percentile, median marked

P/E band: daily close / latest annual diluted EPS that had been published (assumed 90 days
after the fiscal year end), converted to the trading currency at today's FX rate.
"""
from __future__ import annotations

from datetime import timedelta
from statistics import mean, median, pstdev, quantiles
from typing import Optional

import pandas as pd

from ..schema import (Consensus, FootballField, MultipleBand, RangeBar, SeriesPoint, TearSheetData)
from ..config import settings

REPORT_LAG_DAYS = 90


def _spread(values: list[float]) -> Optional[tuple[float, float, float]]:
    vals = sorted(v for v in values if v is not None)
    if len(vals) < 3:
        return None
    if len(vals) >= 4:
        q1, q2, q3 = quantiles(vals, n=4, method="inclusive")
        return q1, q2, q3
    return vals[0], median(vals), vals[-1]


def football_field(data: TearSheetData, consensus: Optional[Consensus]) -> Optional[FootballField]:
    q = data.quote
    if not q.price:
        return None
    bars: list[RangeBar] = []
    if q.week52_low is not None and q.week52_high is not None:
        bars.append(RangeBar(label="52-week trading range", low=q.week52_low, high=q.week52_high,
                             basis="Lowest and highest price over the last 12 months"))
    c = consensus
    if c and c.target_low is not None and c.target_high is not None and (c.currency in (None, q.currency)):
        bars.append(RangeBar(label="Analyst price targets", low=c.target_low, high=c.target_high,
                             mid=c.target_mean,
                             basis=f"{c.analysts or 'n/a'} analysts via {c.source} (third-party, mean marked)"))

    comps = data.comps
    latest = data.financials.years[-1] if data.financials.years else None
    shares = q.market_cap / q.price if q.market_cap else None
    fx = q.fx_to_reporting or None
    if comps:
        peers = comps.peers
        fwd = [p.pe_fwd for p in peers if p.pe_fwd]
        tf = comps.target.pe_fwd
        if settings.peer_pe_basis == "forward" and tf and tf > 0 and len(fwd) >= 3:
            # like for like: peers' forward P/E applied to the target's forward (consensus) EPS
            pe, eps = _spread(fwd), q.price / tf
            bars.append(RangeBar(label="Peer P/E (forward)", low=pe[0] * eps, high=pe[2] * eps, mid=pe[1] * eps,
                                 basis="Peer forward P/E interquartile range x consensus next-year EPS "
                                       "(Yahoo Finance; median marked)"))
        else:
            pe = _spread([p.pe_ttm for p in peers])
            if pe and q.pe_ttm and q.pe_ttm > 0:
                eps = q.price / q.pe_ttm
                bars.append(RangeBar(label="Peer P/E (TTM)", low=pe[0] * eps, high=pe[2] * eps, mid=pe[1] * eps,
                                     basis="Peer P/E interquartile range x TTM EPS (median marked)"))
        ev = _spread([p.ev_ebitda for p in peers])
        lt = data.financials.latest
        nd = (lt.net_debt if lt is not None and lt.net_debt is not None
              else (latest.net_debt or 0.0) if latest else 0.0)
        t_ebitda, basis = None, ""
        if (comps.target.ebitda_ttm and comps.target.ebitda_ttm > 0
                and comps.target.ebitda_currency == data.financials.currency):
            # peers' multiples are trailing twelve months (Yahoo), so use the target's TTM EBITDA too
            t_ebitda, basis = comps.target.ebitda_ttm, "TTM EBITDA (Yahoo Finance)"
        elif latest and latest.ebitda and latest.ebitda > 0:
            t_ebitda, basis = latest.ebitda, f"FY{latest.fiscal_year} EBITDA"
        if ev and t_ebitda and shares and fx:
            from .valuation import stakes as _stakes
            st_ = _stakes(data)  # equity stakes outside cash, after the haircut (same as the DCF bridge)

            def per_share(mult: float) -> float:
                return (mult * t_ebitda - nd + st_) / fx / shares
            bars.append(RangeBar(label="Peer EV/EBITDA", low=per_share(ev[0]), high=per_share(ev[2]),
                                 mid=per_share(ev[1]),
                                 basis=f"Peer EV/EBITDA (TTM) interquartile range x {basis}, less net debt"
                                       + (", plus equity stakes (30% haircut)" if st_ else "")))
        pb = _spread([p.pb for p in peers])
        if pb and q.pb and q.pb > 0:
            bvps = q.price / q.pb
            bars.append(RangeBar(label="Peer P/B", low=pb[0] * bvps, high=pb[2] * bvps, mid=pb[1] * bvps,
                                 basis="Peer P/B interquartile range x book value per share"))

    v = data.valuation
    if v:
        model = v.dcf or v.ddm
        grid = v.sensitivity.discount_growth if v.sensitivity and v.sensitivity.discount_growth else (
            model.grid if model else None)
        if model and grid:
            flat = [x for row in grid.values for x in row if x is not None]
            if flat:
                kind = "DCF" if v.dcf else "DDM"
                axis = "WACC" if v.dcf else "cost of equity"
                bars.append(RangeBar(label=f"{kind} (sensitivity range)", low=min(flat), high=max(flat),
                                     mid=model.value_per_share,
                                     basis=f"{axis} and terminal growth +/-1pp (base case marked)"))
        mc = v.monte_carlo
        if mc:
            bars.append(RangeBar(label="Monte Carlo (P10-P90)", low=mc.percentiles["p10"],
                                 high=mc.percentiles["p90"], mid=mc.percentiles["p50"],
                                 basis=f"{mc.n_valid:,} simulated {mc.model} values (median marked)"))
    bars = [b for b in bars if b.high >= b.low and b.high > 0]
    return FootballField(currency=q.currency, price=q.price, bars=bars) if bars else None


def pe_band(prices: pd.DataFrame, data: TearSheetData, years_back: int = 5,
            max_points: int = 160) -> Optional[MultipleBand]:
    fx = data.quote.fx_to_reporting
    years = [y for y in data.financials.years if y.diluted_eps is not None]
    if prices is None or prices.empty or not fx or not years:
        return None
    published = sorted((y.period_end + timedelta(days=REPORT_LAG_DAYS), y.diluted_eps / fx) for y in years)
    df = prices.sort_values("date")
    end = df["date"].iloc[-1]
    start = end - timedelta(days=round(365.25 * years_back))
    pts: list[tuple] = []
    for d, close in zip(df["date"], df["close"]):
        if d < start:
            continue
        eps = None
        for when, e in published:
            if when <= d:
                eps = e
        if eps is None or eps <= 0:
            continue
        pts.append((d, float(close) / eps))
    if len(pts) < 200:
        return None
    vals = [p[1] for p in pts]
    cur = vals[-1]
    step = max(len(pts) / max_points, 1)
    sample = [pts[int(i * step)] for i in range(min(max_points, len(pts)))]
    if sample[-1] != pts[-1]:
        sample[-1] = pts[-1]
    same_ccy = data.financials.currency == data.quote.currency
    return MultipleBand(
        metric="P/E (trailing annual EPS)",
        series=[SeriesPoint(d=d, v=round(x, 2)) for d, x in sample],
        current=cur, median=median(vals), low=min(vals), high=max(vals), mean=mean(vals), std=pstdev(vals),
        percentile=sum(x < cur for x in vals) / len(vals),
        note=None if same_ccy else
        f"EPS reported in {data.financials.currency}, converted at today's rate; history is approximate.")


def rerating(data: TearSheetData) -> Optional[str]:
    """Why the shares moved over 90 days: consensus EPS revisions vs the change in the multiple (round-5 review:
    "why a stock with rising estimates fell 22%: de-rating versus estimates"). Code only."""
    c, q = data.consensus, data.quote
    if not c or not c.price_90d_ago or not q.price or (c.estimate_currency or q.currency) != q.currency:
        return None
    row = next((e for e in reversed(c.estimates) if e.eps_avg and e.eps_90d_ago and e.eps_90d_ago > 0), None)
    if row is None:
        return None
    de, dp = row.eps_avg / row.eps_90d_ago - 1, q.price / c.price_90d_ago - 1
    pe_now, pe_then = q.price / row.eps_avg, c.price_90d_ago / row.eps_90d_ago
    move = ("the multiple fell: a de-rating, not lower estimates" if dp < de and pe_now < pe_then else
            "the multiple rose: a re-rating ahead of estimates" if dp > de and pe_now > pe_then else
            "the price followed estimates")
    return (f"Over 90 days, consensus {row.period} EPS went from {row.eps_90d_ago:.2f} to {row.eps_avg:.2f} "
            f"({de:+.1%}) while the share price went from {c.price_90d_ago:,.2f} to {q.price:,.2f} ({dp:+.1%}): the P/E "
            f"on {row.period} EPS moved from {pe_then:.1f}x to {pe_now:.1f}x, so {move} (Yahoo Finance consensus).")
