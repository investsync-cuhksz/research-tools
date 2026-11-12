from datetime import date, timedelta

import pytest

from investsync import tickers
from investsync.narrative import guardrail as g
from investsync.quant import metrics as m
from investsync.schema import CompRow, Financials, FiscalYear, Market


# ---------- tickers ----------
@pytest.mark.parametrize("raw,canonical,market,exchange,code", [
    ("0700.HK", "0700.HK", Market.HK, "HKEX", "00700"),
    ("700.hk", "0700.HK", Market.HK, "HKEX", "00700"),
    ("9988.HK", "9988.HK", Market.HK, "HKEX", "09988"),
    ("600519.SH", "600519.SH", Market.CN, "SSE", "600519"),
    ("600519.SS", "600519.SH", Market.CN, "SSE", "600519"),
    ("000858.SZ", "000858.SZ", Market.CN, "SZSE", "000858"),
    ("sz000858", "000858.SZ", Market.CN, "SZSE", "000858"),
    ("300750", "300750.SZ", Market.CN, "SZSE", "300750"),
    ("NVDA", "NVDA", Market.US, "US", "NVDA"),
    ("brk.b", "BRK.B", Market.US, "US", "BRK.B"),
])
def test_parse(raw, canonical, market, exchange, code):
    t = tickers.parse(raw)
    assert (t.canonical, t.market, t.exchange, t.code) == (canonical, market, exchange, code)


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        tickers.parse("12-34")


# ---------- metrics ----------
def _fin():
    ys = [FiscalYear(fiscal_year=2020 + i, period_end=date(2020 + i, 12, 31),
                     revenue=100.0 * (1.1 ** i), gross_profit=40.0 * (1.1 ** i),
                     net_income=20.0 * (1.1 ** i), total_assets=200.0 + 10 * i,
                     total_equity=100.0 + 5 * i, cash_and_equivalents=30.0, total_debt=50.0,
                     operating_cash_flow=25.0 * (1.1 ** i), operating_income=28.0,
                     depreciation_amortization=5.0)
          for i in range(5)]
    return m.finalize_financials(Financials(currency="CNY", years=list(reversed(ys))))


def test_finalize_sorts_and_derives():
    f = _fin()
    assert [y.fiscal_year for y in f.years] == [2020, 2021, 2022, 2023, 2024]
    assert f.years[1].revenue_growth == pytest.approx(0.10)
    assert f.years[0].revenue_growth is None
    assert f.years[-1].gross_margin == pytest.approx(0.40)
    assert f.years[-1].net_debt == pytest.approx(20.0)
    assert f.years[-1].ebitda == pytest.approx(33.0)
    assert f.revenue_cagr == pytest.approx(0.10)
    assert f.cagr_years == 4


def test_cagr_guards():
    assert m.cagr(None, 10, 3) is None
    assert m.cagr(-5, 10, 3) is None
    assert m.cagr(10, 10, 0) is None


def test_dupont_identity():
    f = _fin()
    d = m.dupont(f)
    cur, prev = f.years[-1], f.years[-2]
    avg_eq = (cur.total_equity + prev.total_equity) / 2
    assert d.roe == pytest.approx(cur.net_income / avg_eq)
    assert d.net_margin * d.asset_turnover * d.equity_multiplier == pytest.approx(d.roe)


def test_earnings_quality():
    q = m.earnings_quality(_fin())
    assert q.cfo_to_net_income == pytest.approx(1.25)
    assert q.accruals_ratio < 0  # cash earnings exceed accounting earnings


def test_comps_median_and_premium():
    target = CompRow(ticker="T", name="Target", pe_ttm=20, ev_ebitda=12, pb=4, dividend_yield=0.02)
    peers = [CompRow(ticker=f"P{i}", name=f"P{i}", pe_ttm=pe, ev_ebitda=10, pb=2, dividend_yield=0.03)
             for i, pe in enumerate([10, 16, -5, 18])]
    c = m.build_comps(target, peers, "test")
    assert c.median.pe_ttm == 16  # negative P/E excluded as not meaningful
    assert c.premium_discount["pe_ttm"] == pytest.approx(0.25)
    assert c.premium_discount["pb"] == pytest.approx(1.0)
    assert c.peers[2].pe_ttm is None


def test_rebase_periods():
    start = date(2020, 1, 1)
    days = [start + timedelta(days=i) for i in range(0, 365 * 6, 1) if (start + timedelta(days=i)).weekday() < 5]
    stock = {d: 10 + i * 0.01 for i, d in enumerate(days)}
    bench = {d: 1000.0 for d in days}
    periods = m.rebase_periods(stock, bench)
    assert [p.period for p in periods] == ["1Y", "3Y", "5Y"]
    for p in periods:
        assert p.stock[0].v == 100 and p.benchmark[0].v == 100
        assert p.benchmark_return == pytest.approx(0)
        assert p.stock_return > 0
        assert len(p.stock) <= 160


# ---------- guardrail ----------
FACTS = {"revenue": 660_257_000_000.0, "net_margin": 0.2938, "pe": 18.43,
         "text": "P/E TTM 18.4x vs peer median 15.1x (premium +22.0%); ROE 21.3%"}


def test_guardrail_accepts_numbers_from_data():
    a = g.build_allowed(FACTS)
    text = ("Revenue reached RMB 660.3bn (660,257mn) with a 29.4% net margin. Shares trade at "
            "18.4x earnings, a +22.0% premium to the 15.1x peer median, backed by 21.3% ROE.")
    assert g.unmatched(text, a) == []


def test_guardrail_rejects_invented_numbers():
    a = g.build_allowed(FACTS)
    text = "Net margin expanded to 31.7% and the stock trades at 25.0x, revenue RMB 700bn."
    assert g.unmatched(text, a) == ["31.7%", "25.0x", "700bn"]


def test_guardrail_ignores_labels_years_and_counts():
    a = g.build_allowed({})
    text = "In FY2024 and 1H25 the company named 3 catalysts over a 5-year view; Q3 was strong in 2023."
    assert g.unmatched(text, a) == []


def test_guardrail_rounding_is_strict():
    a = g.build_allowed({"m": 0.256})
    assert g.unmatched("margin of 25.6%", a) == []
    assert g.unmatched("margin of 26%", a) == []
    assert g.unmatched("margin of 25%", a) == ["25%"]  # truncation is not a correct rounding


# ---------- splits & peer picking ----------
def test_eps_restated_for_split():
    ys = [FiscalYear(fiscal_year=2022, period_end=date(2022, 1, 30), net_income=9.75e9, diluted_eps=3.85),
          FiscalYear(fiscal_year=2025, period_end=date(2025, 1, 26), net_income=72.88e9, diluted_eps=2.94),
          FiscalYear(fiscal_year=2026, period_end=date(2026, 1, 25), net_income=120.07e9, diluted_eps=4.90)]
    notes = m.restate_eps_for_splits(ys)
    assert ys[0].diluted_eps == pytest.approx(0.385)
    assert ys[1].diluted_eps == 2.94 and ys[2].diluted_eps == 4.90
    assert notes == ["FY2022 EPS restated for a 10-for-1 share split."]


def test_eps_not_restated_for_buybacks():
    ys = [FiscalYear(fiscal_year=2023, period_end=date(2023, 12, 31), net_income=100.0, diluted_eps=1.00),
          FiscalYear(fiscal_year=2024, period_end=date(2024, 12, 31), net_income=100.0, diluted_eps=1.08)]
    assert m.restate_eps_for_splits(ys) == [] and ys[0].diluted_eps == 1.00


def test_pick_peers_prefers_profitable():
    from investsync.data.adapters import _pick_peers
    pes = [17.0, None, -3.0, 140.0, 9.0, 11.0, 10.0, 12.0, 8.0]
    assert _pick_peers(pes) == [0, 4, 5, 6, 7]
    assert _pick_peers([None, None, 5.0]) == [0, 1, 2]  # top up when too few profitable names


def test_comps_drop_absurd_values():
    t = CompRow(ticker="T", name="T", dividend_yield=0.01)
    c = m.build_comps(t, [CompRow(ticker="P", name="P", dividend_yield=18.3, pe_ttm=2500)], "x")
    assert c.peers[0].dividend_yield is None and c.peers[0].pe_ttm is None


def test_eps_restated_with_known_bonus_issue():
    # CATL-like: 10-for-8 bonus issue (x1.8) in Apr 2023; source already restated FY2022 but not FY2021
    ys = [FiscalYear(fiscal_year=2021, period_end=date(2021, 12, 31), net_income=15.93e9, diluted_eps=6.8392),
          FiscalYear(fiscal_year=2022, period_end=date(2022, 12, 31), net_income=30.73e9, diluted_eps=7.1553),
          FiscalYear(fiscal_year=2025, period_end=date(2025, 12, 31), net_income=70.0e9, diluted_eps=16.14)]
    notes = m.restate_eps_for_splits(ys, [(date(2023, 4, 26), 1.8)])
    assert ys[0].diluted_eps == pytest.approx(6.8392 / 1.8)
    assert ys[1].diluted_eps == 7.1553
    assert len(notes) == 1


def test_unknown_code_is_not_found_not_a_crash(monkeypatch):
    from investsync import pipeline

    def crash(t):  # what the data libraries do with a code they do not know
        return None["result"]
    monkeypatch.setattr(pipeline.adapters, "load", crash)
    with pytest.raises(LookupError, match="No market data found for ZZZZ"):
        pipeline.build_data("ZZZZ", with_filings=False)
