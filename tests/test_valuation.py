"""WACC / DCF / DDM: maths checked against closed forms, on fixture data."""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from investsync.quant import valuation as v
from investsync.schema import TearSheetData

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def nvda() -> TearSheetData:
    d = TearSheetData.model_validate_json((FIX / "NVDA.json").read_text(encoding="utf-8"))
    for y in d.financials.years:  # fixture predates capex; give a steady 40% FCF margin
        y.operating_cash_flow = 0.5 * y.revenue
        y.capex = 0.1 * y.revenue
    return d


def test_beta_recovers_known_sensitivity():
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(800)]
    bench, stock = {}, {}
    b = s = 100.0
    for i, d in enumerate(days):
        r = 0.01 * ((i * 7919) % 13 - 6) / 6  # deterministic pseudo-random market returns
        b *= 1 + r
        s *= 1 + 1.5 * r
        bench[d], stock[d] = b, s
    beta = v.beta(stock, bench)
    assert beta == pytest.approx(0.67 * 1.5 + 0.33, abs=0.05)


def test_dcf_value_matches_closed_form():
    # flat revenue 100, 10% margin, WACC 10%, g 0 -> EV = 10 / 0.10 = 100
    ev, equity, per_share = v._dcf_value([100.0] * 5, [0.10] * 5, 0.10, 0.0, claims=20.0, fx=1.0, shares=4.0)
    assert ev == pytest.approx(100.0)
    assert equity == pytest.approx(80.0) and per_share == pytest.approx(20.0)
    assert v._dcf_value([100.0] * 5, [0.10] * 5, 0.03, 0.03, 0, 1, 1) is None  # WACC must exceed g


def test_dcf_stub_and_roll_forward():
    # perpetuity of 10 at 10%: valued at a balance-sheet date with half a year to go, then rolled forward.
    # EV at the balance sheet = 5 / 1.1**0.5 + sum_{k>=1} 10 / 1.1**(0.5 + k) = (5 + 100) / 1.1**0.5
    ev, _, _ = v.dcf_ev([100.0] * 5, [0.10] * 5, 0.10, 0.0, stub=0.5)
    assert ev == pytest.approx(105.0 / 1.1 ** 0.5)
    rolled, _, _ = v.dcf_ev([100.0] * 5, [0.10] * 5, 0.10, 0.0, stub=0.5, roll=0.5)
    assert rolled == pytest.approx(105.0)


def test_consensus_aligns_to_the_year_after_latest():
    est = pd.DataFrame({"avg": [110.0, 125.0], "yearAgoRevenue": [100.0, 110.0], "currency": ["USD", "USD"]},
                       index=["0y", "+1y"])
    assert v.consensus_revenue(est, 100.0, "USD") == [110.0, 125.0]
    assert v.consensus_revenue(est, 140.0, "USD") == []   # stale: estimates are for years already reported
    assert v.consensus_revenue(est, 100.0, "CNY") == []   # wrong currency


def test_dcf_uses_consensus_then_fades_and_grid_is_monotonic():
    d = nvda()
    rev0 = d.financials.years[-1].revenue
    est = pd.DataFrame({"avg": [rev0 * 1.5, rev0 * 1.5 * 1.3], "yearAgoRevenue": [rev0, rev0 * 1.5],
                        "currency": ["USD", "USD"]}, index=["0y", "+1y"])
    dcf, notes = v.compute_dcf(d, wacc=0.11, g=0.025, years=5, estimates=est)
    assert [f.basis for f in dcf.forecast] == ["consensus", "consensus", "fade", "fade", "fade"]
    gs = [f.growth for f in dcf.forecast]
    assert gs[0] == pytest.approx(0.5) and gs[1] == pytest.approx(0.3)
    assert gs[2] > gs[3] > gs[4] > 0.025                    # fades towards terminal growth
    # the growth above terminal halves each year, the same fade as the analyst scenarios
    assert gs[2] == pytest.approx(0.025 + (0.3 - 0.025) / 2)
    assert gs[4] == pytest.approx(0.025 + (0.3 - 0.025) / 8)
    assert v.fade_step(0.3, 0.025) == pytest.approx(gs[2])
    assert dcf.fcf_margin == pytest.approx(0.4)
    vals = dcf.grid.values
    assert vals[0][1] > vals[1][1] > vals[2][1]             # higher WACC -> lower value
    assert vals[1][0] < vals[1][1] < vals[1][2]             # higher growth -> higher value
    assert vals[1][1] == pytest.approx(dcf.value_per_share)
    assert any("not a price target" in n for n in notes)


def test_dcf_skipped_without_cash_flow():
    d = nvda()
    for y in d.financials.years:
        y.capex = None
    dcf, notes = v.compute_dcf(d, 0.1, 0.02, 5, pd.DataFrame())
    assert dcf is None and "unavailable" in notes[0]


def test_ddm_closed_form_and_bank_detection():
    d = nvda()
    d.profile.sector = "Banks - Diversified"
    d.quote.price, d.quote.dividend_yield = 100.0, 0.05
    assert v.is_financial(d)
    ddm, _ = v.compute_ddm(d, ke=0.09, g=0.02)
    assert ddm.value_per_share == pytest.approx(5.0 * 1.02 / 0.07)
    assert ddm.grid.values[1][1] == pytest.approx(ddm.value_per_share)


def test_build_uses_config_and_yields():
    d = nvda()
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(800)]
    prices = {x: 100 + i * 0.1 + (i % 5) for i, x in enumerate(days)}
    bench = {x: 100 + i * 0.05 + (i % 3) for i, x in enumerate(days)}
    val = v.build(d, prices, bench, {"US 10Y": 0.045, "China 10Y": 0.016}, pd.DataFrame())
    assert val.wacc.risk_free == 0.045 and val.wacc.equity_risk_premium == pytest.approx(0.0446)
    assert val.dcf is not None and val.ddm is None


def test_dcf_withheld_when_discount_rate_too_close_to_growth():
    d = nvda()
    dcf, notes = v.compute_dcf(d, wacc=0.037, g=0.02, years=5, estimates=pd.DataFrame(), min_spread=0.03)
    assert dcf is None and "less than 3% above terminal growth" in notes[0]


def test_stub_cash_share_uses_revenue_still_to_come():
    from types import SimpleNamespace
    from datetime import date
    from investsync.quant.valuation import stub_cash_share
    data = SimpleNamespace(financials=SimpleNamespace(
        years=[SimpleNamespace(period_end=date(2026, 1, 25))],
        latest=SimpleNamespace(revenue=177.8, period_end=date(2026, 7, 26))))
    assert abs(stub_cash_share(data, 411.7, 0.5) - (411.7 - 177.8) / 411.7) < 1e-9   # back-loaded year: 57%
    assert stub_cash_share(data, 150.0, 0.5) == 0.5                                 # forecast below YTD: time share
    assert stub_cash_share(data, 2000.0, 0.5) == 0.75                               # bounded at 1.5x the time share
    assert stub_cash_share(data, 411.7, 1.0) == 1.0                                 # no stub year
