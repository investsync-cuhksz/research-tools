"""US cash and debt from SEC XBRL: cash + current debt securities (equity stakes are not cash), long-term debt."""
from datetime import date

from investsync.data import sec_balance as sb

FACTS = {  # NVIDIA, 10-Q for the quarter to 26 Jul 2026 and 10-K to 25 Jan 2026 (USD)
    "CashAndCashEquivalentsAtCarryingValue": {"2026-07-26": 22_443e6, "2026-01-25": 10_605e6},
    "DebtSecuritiesCurrent": {"2026-07-26": 34_143e6, "2026-01-25": 39_065e6},
    "EquitySecuritiesFvNi": {"2026-07-26": 42_783e6, "2026-01-25": 12_886e6},
    "LongTermDebt": {"2026-07-26": 33_366e6, "2026-01-25": 8_468e6},
}


def test_cash_is_cash_plus_debt_securities_and_excludes_equity_stakes():
    b = sb.balance(FACTS, date(2026, 7, 26))
    assert b["cash"] == 56_586e6 and b["debt"] == 33_366e6 and b["listed_equity"] == 42_783e6
    a = sb.balance(FACTS, date(2026, 1, 25))
    assert a["cash"] - a["debt"] == 41_202e6  # net cash on the same basis at both dates


def test_period_end_within_a_week_and_debt_from_parts():
    f = {"CashAndCashEquivalentsAtCarryingValue": {"2025-12-31": 5e9},
         "LongTermDebtNoncurrent": {"2025-12-31": 3e9}, "LongTermDebtCurrent": {"2025-12-31": 1e9}}
    b = sb.balance(f, date(2025, 12, 28))
    assert b == {"cash": 5e9, "debt": 4e9, "listed_equity": None, "unlisted_equity": None}
    assert sb.balance(f, date(2025, 11, 30)) is None



def test_stakes_enter_the_dcf_bridge_after_the_haircut():
    from investsync.quant import valuation
    from investsync.schema import TearSheetData
    from pathlib import Path
    d = TearSheetData.model_validate_json(
        (Path(__file__).resolve().parent.parent / "fixtures" / "0700_HK_full.json").read_text(encoding="utf-8"))
    assert valuation.stakes(d) == 0.0  # no SEC stakes: unchanged
    fy, lt = d.financials.years[-1], d.financials.latest
    src = lt if (lt is not None and lt.net_debt is not None and lt.period_end > fy.period_end) else fy
    src.equity_investments = 100e9
    assert abs(valuation.stakes(d) - 70e9) < 1

