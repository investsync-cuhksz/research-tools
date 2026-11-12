"""Valuation stress tests for the full report: wider grids, reverse DCF and a Monte Carlo.

All three reuse the base DCF / DDM exactly (same revenue path, FCF margin, net debt, FX and
share count) and only move the inputs named below, so every result can be traced back to the
base case on page 1.

* Grids          5x5: discount rate x terminal growth; FCF margin x revenue-growth shift.
* Reverse DCF    the constant revenue growth (or FCF margin) that makes the DCF equal today's
                 price; for banks, the perpetual dividend growth the price implies (closed form).
                 Run 2 (12 Nov 2026): the leading consensus years are held at the model's path and the
                 constant growth is solved for the later years only (with a 10-year forecast, one rate over
                 all ten read "the price implies 21.0% a year against the model's 21.4%" while the value was
                 30% above the price: the model reaches the same year-10 revenue sooner).
* Monte Carlo    5,000 seeded draws: revenue-growth shift ~ N(0, sd of historical growth),
                 FCF margin ~ N(base, sd of historical margins), WACC ~ N(base, 0.75pp),
                 terminal growth ~ U(base +/- 0.5pp). Draws that break the min-spread rule are
                 discarded, exactly as the base case would be.
"""
from __future__ import annotations

import random
import zlib
from statistics import pstdev, quantiles
from typing import Callable, Optional

from ..schema import MonteCarlo, ReverseDCF, Sensitivity, TearSheetData, Valuation, ValueGrid

N_DRAWS = 5000
WACC_SD = 0.0075
G_HALF_RANGE = 0.005
HIST_BINS = 24


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


class _DCFModel:
    """The base DCF, re-runnable with shifted inputs."""

    def __init__(self, val: Valuation, data: TearSheetData, min_spread: float):
        d = val.dcf
        assert d is not None and d.bridge is not None
        self.base_revenue = d.forecast[0].revenue / (1 + d.forecast[0].growth)
        self.growth = [f.growth for f in d.forecast]
        self.margin, self.g, self.wacc = d.fcf_margin, d.terminal_growth, val.wacc.wacc
        self.path = d.margin_path or [d.fcf_margin] * len(d.forecast)
        self.basis = [f.basis for f in d.forecast]
        self.years = [f.fiscal_year for f in d.forecast]
        self.stub, self.roll = d.stub_years or 1.0, d.bridge.roll_forward_years or 0.0
        self.cash_share = d.stub_cash_share
        self.net_debt = (d.bridge.net_debt + (d.bridge.minority_interest or 0.0)  # all claims ahead of equity,
                         - (d.bridge.investments or 0.0))                   # less the stakes added (haircut)
        self.fx, self.shares = d.bridge.fx_to_reporting, d.bridge.shares
        self.min_spread = min_spread
        self.price = data.quote.price

    def revenues(self, shift: float = 0.0, constant: Optional[float] = None, hold: int = 0) -> list[float]:
        """Revenue path: the model's growth (+ ``shift``), or ``constant`` growth after the first ``hold`` years
        (which keep the model's growth)."""
        out, r = [], self.base_revenue
        for i, gr in enumerate(self.growth):
            r *= 1 + (constant if constant is not None and i >= hold else gr + shift)
            out.append(r)
        return out

    def value(self, revs: list[float], margin: float, wacc: float, g: float,
              enforce_spread: bool = True) -> Optional[float]:
        if wacc < g + (self.min_spread if enforce_spread else 0.005) - 1e-9:
            return None
        from .valuation import dcf_ev
        scale = margin / self.margin if self.margin else 1.0  # shifts move the whole margin path
        ev, _, _ = dcf_ev(revs, [p * scale for p in self.path], wacc, g, self.stub, self.roll, self.cash_share)
        return (ev - self.net_debt) / self.fx / self.shares


def _grid(row_label: str, col_label: str, rows: list[float], cols: list[float],
          fn: Callable[[float, float], Optional[float]]) -> ValueGrid:
    return ValueGrid(row_label=row_label, col_label=col_label, rows=rows, cols=cols,
                     values=[[fn(r, c) for c in cols] for r in rows])


def _bisect(fn: Callable[[float], Optional[float]], target: float, lo: float, hi: float) -> Optional[float]:
    """Root of fn(x) = target for an increasing fn, or None if outside [lo, hi]."""
    flo, fhi = fn(lo), fn(hi)
    if flo is None or fhi is None or not (flo <= target <= fhi):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        fm = fn(mid)
        if fm is None:
            return None
        if fm < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _summarise(values: list[float], price: float, model: str, n: int, seed: int,
               assumptions: dict[str, float]) -> Optional[MonteCarlo]:
    if len(values) < n * 0.2:
        return None
    values.sort()
    qs = quantiles(values, n=100, method="inclusive")  # qs[k-1] = k-th percentile
    pct = {f"p{k}": qs[k - 1] for k in (5, 10, 25, 50, 75, 90, 95)}
    lo, hi = qs[0], qs[98]
    width = (hi - lo) / HIST_BINS or 1.0
    counts = [0] * HIST_BINS
    for v in values:
        counts[int(_clamp((v - lo) / width, 0, HIST_BINS - 1))] += 1  # tails fold into the end bins
    return MonteCarlo(model=model, n_draws=n, n_valid=len(values), seed=seed, percentiles=pct,
                      mean=sum(values) / len(values),
                      prob_above_price=sum(v > price for v in values) / len(values),
                      bins=[lo + i * width for i in range(HIST_BINS + 1)], counts=counts,
                      assumptions=assumptions)


def _seed(ticker: str) -> int:
    return zlib.crc32(ticker.encode()) & 0x7FFFFFFF


MIN_SOLVED_YEARS = 3


def reverse_hold(basis: list[str]) -> int:
    """How many leading forecast years the reverse DCF holds at the model's path: those whose basis is analyst
    consensus, or 0 when there are none or fewer than ``MIN_SOLVED_YEARS`` years would be left to solve for."""
    hold = 0
    for b in basis:
        if b != "consensus":
            break
        hold += 1
    return hold if hold and len(basis) - hold >= MIN_SOLVED_YEARS else 0


def _dcf_extras(val: Valuation, data: TearSheetData, min_spread: float) -> None:
    m = _DCFModel(val, data, min_spread)
    base_revs = m.revenues()
    steps = (-0.01, -0.005, 0.0, 0.005, 0.01)
    rows = [m.wacc + s for s in steps]   # exact, so the centre cell equals the base case
    cols = [m.g + s for s in steps]
    margins = [m.margin * k for k in (0.8, 0.9, 1.0, 1.1, 1.2)]
    shifts = [-0.04, -0.02, 0.0, 0.02, 0.04]
    val.sensitivity = Sensitivity(
        discount_growth=_grid("WACC", "Terminal growth", rows, cols,
                              lambda w, g: m.value(base_revs, m.margin, w, g)),
        margin_growth=_grid("FCF margin", "Revenue growth vs base (each year)", margins, shifts,
                            lambda mg, sh: m.value(m.revenues(sh), mg, m.wacc, m.g)))

    # Reverse DCF: hold the leading consensus years, solve one constant growth for the rest
    n = len(m.growth)
    hold = reverse_hold(m.basis)
    start = base_revs[hold - 1] if hold else m.base_revenue
    model_growth = (base_revs[-1] / start) ** (1 / (n - hold)) - 1
    implied = _bisect(lambda r: m.value(m.revenues(constant=r, hold=hold), m.margin, m.wacc, m.g), m.price, -0.5, 1.0)
    base_value = m.value(base_revs, m.margin, m.wacc, m.g)
    implied_margin = None
    note = None
    if base_value is not None:
        k = (base_value * m.fx * m.shares + m.net_debt) / m.margin  # EV per unit of FCF margin
        implied_margin = (m.price * m.fx * m.shares + m.net_debt) / k if k > 0 else None
    after = f" after the {hold} consensus years" if hold else ""
    if implied is None:
        lo_v = m.value(m.revenues(constant=-0.5, hold=hold), m.margin, m.wacc, m.g)
        note = (f"Even a 50% annual revenue decline{after} would leave the DCF above the price."
                if lo_v is not None and lo_v > m.price else
                f"The price implies more than 100% annual revenue growth{after} at the base FCF margin.")
    val.reverse = ReverseDCF(model="DCF", horizon_years=n - hold, implied_growth=implied, model_growth=model_growth,
                             implied_fcf_margin=implied_margin, model_fcf_margin=m.margin, note=note,
                             hold_years=hold, from_year=m.years[hold] if m.years else None,
                             to_year=m.years[-1] if m.years else None)

    # Monte Carlo
    hist = data.financials.years
    growths = [y.revenue_growth for y in hist if y.revenue_growth is not None]
    fcf_m = [y.free_cash_flow / y.revenue for y in hist if y.free_cash_flow is not None and y.revenue]
    g_sd = _clamp(pstdev(growths), 0.02, 0.10) if len(growths) >= 2 else 0.05
    m_sd = _clamp(pstdev(fcf_m), 0.01, 0.06) if len(fcf_m) >= 2 else 0.03
    m_sd = min(m_sd, max(m.margin * 0.5, 0.01))
    seed = _seed(data.profile.ticker)
    rng = random.Random(seed)
    out = []
    for _ in range(N_DRAWS):
        shift = rng.gauss(0, g_sd)
        margin = max(rng.gauss(m.margin, m_sd), 0.0)
        w = rng.gauss(m.wacc, WACC_SD)
        g = rng.uniform(m.g - G_HALF_RANGE, m.g + G_HALF_RANGE)
        v = m.value(m.revenues(shift), margin, w, g)
        if v is not None:
            out.append(v)
    val.monte_carlo = _summarise(out, m.price, "DCF", N_DRAWS, seed,
                                 {"revenue_growth_sd": g_sd, "fcf_margin_sd": m_sd, "wacc_sd": WACC_SD,
                                  "terminal_growth_half_range": G_HALF_RANGE})


def _ddm_extras(val: Valuation, data: TearSheetData, min_spread: float) -> None:
    d = val.ddm
    ke, g, dps, price = val.wacc.cost_of_equity, d.growth, d.dividend_per_share, data.quote.price

    def value(k: float, gg: float) -> Optional[float]:
        return dps * (1 + gg) / (k - gg) if k >= gg + min_spread - 1e-9 else None
    steps = (-0.01, -0.005, 0.0, 0.005, 0.01)
    val.sensitivity = Sensitivity(discount_growth=_grid(
        "Cost of equity", "Dividend growth", [ke + s for s in steps], [g + s for s in steps], value))
    implied = (price * ke - dps) / (price + dps)
    val.reverse = ReverseDCF(model="DDM", horizon_years=0, implied_growth=implied, model_growth=g)
    seed = _seed(data.profile.ticker)
    rng = random.Random(seed)
    out = [v for _ in range(N_DRAWS)
           if (v := value(rng.gauss(ke, WACC_SD), rng.uniform(g - G_HALF_RANGE, g + G_HALF_RANGE))) is not None]
    val.monte_carlo = _summarise(out, price, "DDM", N_DRAWS, seed,
                                 {"cost_of_equity_sd": WACC_SD, "growth_half_range": G_HALF_RANGE})


def extend(val: Valuation, data: TearSheetData, min_spread: float) -> None:
    """Add grids, reverse DCF and Monte Carlo to ``val`` in place (no-op if no model is shown)."""
    if not data.quote.price:
        return
    if val.dcf is not None and val.dcf.bridge is not None and val.wacc.wacc is not None:
        _dcf_extras(val, data, min_spread)
    elif val.ddm is not None and val.ddm.value_per_share is not None:
        _ddm_extras(val, data, min_spread)
