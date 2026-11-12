"""9 Nov 2026 data fixes (from the round-3 to 5 blind reviews): warranty reclassification note, FX at the price
date, traded 52-week range, HK / A-share equity stakes. No network: sources are stubbed."""
from datetime import date

import pandas as pd

from investsync.data import adapters
from investsync.data import sources as src
from investsync.quant import metrics
from investsync.schema import FiscalYear, Financials, Market


def _fy(y, rev, sga):
    return FiscalYear(fiscal_year=y, period_end=date(y, 12, 31), revenue=rev, sga_expense=sga)


def test_warranty_reclassification_is_flagged_for_a_shares_only():
    fin = Financials(currency="CNY", years=[_fy(2021, 100, 5.9), _fy(2022, 100, 5.5), _fy(2023, 100, 2.9),
                                            _fy(2024, 100, 3.7)])
    note = metrics.warranty_break(fin, Market.CN)
    assert "FY2022 and earlier" in note and "5.5% to 2.9%" in note and "operating margin is unaffected" in note
    assert metrics.warranty_break(fin, Market.HK) is None
    steady = Financials(currency="CNY", years=[_fy(2022, 100, 5.5), _fy(2023, 100, 5.2), _fy(2024, 100, 5.0)])
    assert metrics.warranty_break(steady, Market.CN) is None


def test_fx_uses_the_price_dates_close_then_spot(monkeypatch):
    monkeypatch.setattr(src, "_yf_fx_on", lambda pair, on: 0.8532 if on == "2026-11-06" else None)
    monkeypatch.setattr(src, "_yf_fx", lambda pair: 0.8499)
    assert src.fx("HKD", "CNY", on=date(2026, 11, 6)) == 0.8532
    assert src.fx("HKD", "CNY", on=date(2026, 11, 7)) == 0.8499  # no close that day: spot
    assert src.fx("HKD", "CNY") == 0.8499 and src.fx("CNY", "CNY", on=date(2026, 11, 6)) == 1.0


def test_traded_52_week_range_comes_from_unadjusted_prices(monkeypatch):
    days = pd.date_range(end=pd.Timestamp.today().normalize(), periods=300, freq="D")
    raw = pd.DataFrame({"date": days, "high": [400.0] * 299 + [468.75], "low": [216.51] + [300.0] * 299})

    class _AK:
        def stock_zh_a_daily(self, symbol, adjust):
            assert adjust == ""  # unadjusted
            return raw.copy()
    monkeypatch.setattr(src, "_ak", lambda: _AK())
    hi, lo = src.traded_range_1y.__wrapped__("CN", "sz300750")
    assert hi == 468.75 and lo == 216.51


def test_hk_and_a_share_stakes_lists_exclude_what_cash_already_counts():
    assert not set(adapters.HK_STAKES) & set(adapters.HK_CASH)
    assert not set(adapters.CN_STAKES) & set(adapters.CN_CASH)
    b = {"联营公司权益": 342.4e9, "合营公司权益": 6.3e9, "指定以公允价值记账之金融资产": 563.8e9,
         "指定以公允价值记账之金融资产(流动)": 44.7e9}
    assert abs(adapters._sum(b, adapters.HK_STAKES) - 912.5e9) < 1e6  # Tencent FY2025, current FV assets excluded
