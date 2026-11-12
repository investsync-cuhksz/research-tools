"""Backups for failed data sources (11 Nov 2026): the stale-copy rule in cache.cached and the risk-free rate chain.
Offline: a temporary cache, a fake clock and fake sources."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from investsync import cache as cache_mod
from investsync import pipeline, provenance
from investsync.data import adapters
from investsync.data import sources as src
from investsync.quant import valuation

T0 = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def clock(monkeypatch, tmp_path):
    """A fresh cache file and a clock the test moves by hand."""
    now = [T0]
    monkeypatch.setattr(cache_mod, "time", SimpleNamespace(time=lambda: now[0]))
    monkeypatch.setattr(cache_mod, "settings", SimpleNamespace(no_cache=False))
    monkeypatch.setattr(cache_mod, "_cache", cache_mod.Cache(tmp_path / "cache.sqlite3"))
    return now


def fake_source(behaviour: dict):
    """A @cached("prices") source whose next answer is set by the test (a value, or an exception to raise)."""
    @cache_mod.cached("prices")
    def price_history(market, code):
        behaviour["calls"] = behaviour.get("calls", 0) + 1
        out = behaviour["next"]
        if isinstance(out, Exception):
            raise out
        return out
    return price_history


def prices(last: date) -> pd.DataFrame:
    return pd.DataFrame({"date": [last - timedelta(days=1), last], "close": [10.0, 11.0]})


def test_stale_copy_is_used_when_the_live_call_raises(clock):
    b = {"next": prices(date(2026, 11, 2))}
    fn = fake_source(b)
    fn("US", "AAPL")
    clock[0] += cache_mod.TTL["prices"] + 3600          # the copy has expired
    b["next"] = ConnectionError("Sina down")
    rec = provenance.start()
    out = fn("US", "AAPL")
    assert out["date"].iloc[-1] == date(2026, 11, 2)     # the series keeps its own date: honest when stale
    assert rec[-1].stale and rec[-1].fetched_at.timestamp() == T0  # cited at the original fetch time


def test_stale_copy_is_used_when_the_live_call_returns_nothing(clock):
    b = {"next": prices(date(2026, 11, 2))}
    fn = fake_source(b)
    fn("HK", "00700")
    clock[0] += cache_mod.TTL["prices"] + 60
    for empty in (pd.DataFrame(), None, {}, []):
        clock[0] += cache_mod.RETRY_AFTER + 1           # past the retry pause, so the live source is asked
        b["next"] = empty
        assert len(fn("HK", "00700")) == 2


def test_an_empty_result_never_overwrites_a_good_copy(clock):
    b = {"next": {"marketCap": 1e12}}
    fn = fake_source(b)
    fn("US", "MSFT")
    clock[0] += cache_mod.TTL["prices"] + 1
    b["next"] = {}
    fn("US", "MSFT")
    key = cache_mod._key(fn.__wrapped__, "prices", ("US", "MSFT"), {})
    value, _, fetched = cache_mod.get_cache().entry(key)
    assert value == {"marketCap": 1e12} and fetched == T0
    clock[0] += cache_mod.RETRY_AFTER + 1               # source back: the new value replaces the copy
    b["next"] = {"marketCap": 2e12}
    assert fn("US", "MSFT") == {"marketCap": 2e12}


def test_a_failed_source_is_not_asked_again_during_the_retry_pause(clock):
    b = {"next": [1, 2]}
    fn = fake_source(b)
    fn("CN", "sh600519")
    clock[0] += cache_mod.TTL["prices"] + 1
    b["next"] = TimeoutError()
    rec = provenance.start()
    fn("CN", "sh600519")
    calls = b["calls"]
    clock[0] += 60
    assert fn("CN", "sh600519") == [1, 2] and b["calls"] == calls  # served from the pause, no live call
    assert all(r.stale and r.fetched_at.timestamp() == T0 for r in rec)


def test_an_empty_result_without_a_copy_is_kept_only_briefly(clock):
    b = {"next": pd.DataFrame()}
    fn = fake_source(b)
    rec = provenance.start()
    fn("US", "ZZZZ")
    assert rec == []                                    # a source that gave nothing is not cited
    fn("US", "ZZZZ")
    assert b["calls"] == 1                              # kept for a few minutes ...
    clock[0] += cache_mod.EMPTY_TTL + 1
    fn("US", "ZZZZ")
    assert b["calls"] == 2                              # ... then the source is asked again


def test_no_copy_means_the_error_still_reaches_the_caller(clock):
    fn = fake_source({"next": ConnectionError("down")})
    with pytest.raises(ConnectionError):
        fn("US", "AAPL")


def test_fresh_skips_the_stale_copy_and_last_copy_returns_it(clock):
    b = {"next": {"US 10Y": 0.045}}
    fn = fake_source(b)
    fn("x", "y")
    clock[0] += cache_mod.TTL["prices"] + 1
    b["next"] = ConnectionError()
    with pytest.raises(ConnectionError):
        fn.fresh("x", "y")
    rec = provenance.start()
    assert fn.last_copy("x", "y") == {"US 10Y": 0.045} and rec[-1].stale


def test_a_fresh_hit_is_not_stale_and_keeps_its_fetch_time(clock):
    fn = fake_source({"next": [1]})
    fn("a", "b")
    clock[0] += 60
    rec = provenance.start()
    fn("a", "b")
    assert rec[-1].from_cache and not rec[-1].stale and rec[-1].fetched_at.timestamp() == T0


def test_an_old_cache_file_gets_the_fetch_time_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE cache (key TEXT PRIMARY KEY, expires REAL, value BLOB)")
        c.execute("INSERT INTO cache VALUES ('k', 100.0, ?)", (__import__("pickle").dumps([1]),))
    old = cache_mod.Cache(path).entry("k")
    assert old == ([1], 100.0, None)
    assert cache_mod._fetched(old, 40) == 60.0        # old rows: expiry minus TTL, as before


def test_stale_use_becomes_a_data_note_with_the_fetch_date():
    rec = [provenance.Record("yf_info", ("AAPL",), datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc), True, True),
           provenance.Record("yf_info", ("MSFT",), datetime(2026, 11, 5, tzinfo=timezone.utc), True, True),
           provenance.Record("bond_yields", (), datetime(2026, 11, 11, tzinfo=timezone.utc), False)]
    assert provenance.stale_notes(rec) == [            # one line per fetch day; the oldest copy's time
        "Live data unavailable: Quote, multiples, profile, management, ownership split, analyst targets. "
        "Used the copy fetched on 3 Nov 2026 08:00 UTC."]
    assert provenance.stale_notes(rec[2:]) == []        # healthy sources: no note
    day = datetime(2026, 11, 8, 14, tzinfo=timezone.utc)
    many = [provenance.Record(fn, (), day, True, True) for fn in ("_sec_cik_map", "bond_yields")]
    assert provenance.stale_notes(many) == [
        "Live data unavailable: SEC company index; 10-year government bond yields (China, US). "
        "Used the copies fetched on 8 Nov 2026 (times in the citations)."]


# ---------------------------------------------------------------- risk-free rate
def rates(monkeypatch, live, yahoo, copy):
    """Fake EastMoney (live: a dict, or an exception), Yahoo ^TNX and the saved EastMoney copy."""
    asked = []

    def fresh():
        asked.append("eastmoney")
        if isinstance(live, Exception):
            raise live
        return live

    def tnx():
        asked.append("yahoo")
        return yahoo

    def last_copy():
        asked.append("copy")
        return copy
    monkeypatch.setattr(src, "bond_yields", SimpleNamespace(fresh=fresh, last_copy=last_copy))
    monkeypatch.setattr(src, "us10y_yahoo", tnx)
    return asked


def test_live_eastmoney_yields_need_no_backup(monkeypatch):
    asked = rates(monkeypatch, {"US 10Y": 0.045, "China 10Y": 0.018}, 0.05, None)
    assert src.risk_free_yields("US 10Y") == ({"US 10Y": 0.045, "China 10Y": 0.018}, [])
    assert asked == ["eastmoney"]


def test_us_yield_falls_back_to_yahoo_before_the_saved_copy(monkeypatch):
    asked = rates(monkeypatch, ConnectionError(), 0.0499, {"US 10Y": 0.041, "China 10Y": 0.018})
    yields, notes = src.risk_free_yields("US 10Y")
    assert yields == {"US 10Y": 0.0499} and asked == ["eastmoney", "yahoo"]
    assert "^TNX" in notes[0]


def test_saved_copy_is_the_last_backup(monkeypatch):
    asked = rates(monkeypatch, ConnectionError(), None, {"US 10Y": 0.041, "China 10Y": 0.018})
    assert src.risk_free_yields("US 10Y") == ({"US 10Y": 0.041}, [])
    assert asked == ["eastmoney", "yahoo", "copy"]
    asked = rates(monkeypatch, ConnectionError(), 0.0499, {"US 10Y": 0.041, "China 10Y": 0.018})
    assert src.risk_free_yields("China 10Y") == ({"China 10Y": 0.018}, [])
    assert asked == ["eastmoney", "copy"]                  # Yahoo has no China yield: not asked


def test_every_rate_source_failing_leaves_the_label_out(monkeypatch):
    rates(monkeypatch, ConnectionError(), None, None)
    assert src.risk_free_yields("US 10Y") == ({}, [])


def test_yahoo_tnx_scale(monkeypatch):
    import yfinance as yf
    for close, want in ((4.998, 0.04998), (49.98, 0.04998), (0.0, None), (250.0, None)):
        monkeypatch.setattr(yf, "Ticker", lambda s, c=close: SimpleNamespace(
            history=lambda period: pd.DataFrame({"Close": [4.9, c]})))
        got = src.us10y_yahoo.__wrapped__()
        assert got == pytest.approx(want) if want else got is None


def test_a_partial_bond_table_is_a_failure(monkeypatch):
    table = pd.DataFrame({"中国国债收益率10年": [None, None], "美国国债收益率10年": [4.1, 4.2]})
    monkeypatch.setattr(src, "_ak", lambda: SimpleNamespace(bond_zh_us_rate=lambda start_date: table))
    with pytest.raises(LookupError, match="China 10Y"):
        src.bond_yields.__wrapped__()


def nvda():
    from tests.test_valuation import nvda as fixture
    return fixture()


def test_valuation_builds_on_the_backup_rate_alone(monkeypatch):
    rates(monkeypatch, ConnectionError(), 0.0499, None)
    d = nvda()
    yields, label = pipeline._risk_free(d)
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(800)]
    stock = {x: 100 + i * 0.1 + (i % 5) for i, x in enumerate(days)}
    bench = {x: 100 + i * 0.05 + (i % 3) for i, x in enumerate(days)}
    v = valuation.build(d, stock, bench, yields, pd.DataFrame())
    assert v is not None and v.wacc.risk_free == 0.0499 and v.dcf is not None
    assert "Yahoo" in label and any("^TNX" in w for w in d.warnings)


def test_no_rate_at_all_is_said_in_the_report(monkeypatch):
    rates(monkeypatch, ConnectionError(), None, None)
    d = nvda()
    yields, _ = pipeline._risk_free(d)
    assert valuation.build(d, {}, {}, yields, pd.DataFrame()) is None
    assert any(w.startswith("Valuation not shown: the risk-free rate (US 10Y") for w in d.warnings)


def test_a_past_results_date_from_a_stale_copy_is_dropped():
    assert adapters._upcoming(src.today() - timedelta(days=3)) is None
    assert adapters._upcoming(src.today()) == src.today()
    assert adapters._upcoming(None) is None


# ---------------------------------------------------------------- US statements from SEC XBRL
def fy(start, end, val, filed="2026-01-30"):
    return {"start": start, "end": end, "val": val, "filed": filed}


def at(end, val, filed="2026-01-30"):
    return {"start": None, "end": end, "val": val, "filed": filed}


FACTS = {
    "NetIncomeLoss": [fy("2024-01-01", "2024-12-31", 90, "2025-02-01"), fy("2024-01-01", "2024-12-31", 95),
                      fy("2025-01-01", "2025-12-31", 120)],              # the later 10-K's restatement wins
    "Revenues": [fy("2024-01-01", "2024-12-31", 1000), fy("2025-01-01", "2025-12-31", 1200),
                 fy("2025-10-01", "2025-12-31", 330)],                   # a fourth quarter is not a year
    "CostOfRevenue": [fy("2025-01-01", "2025-12-31", 700)],              # no GrossProfit tag: revenue - cost
    "PaymentsToAcquirePropertyPlantAndEquipment": [fy("2025-01-01", "2025-12-31", -50)],
    "EarningsPerShareDiluted": [fy("2025-01-01", "2025-12-31", 1.25)],
    "Assets": [at("2025-12-31", 5000)],
    "StockholdersEquity": [at("2025-12-30", 2000)],                      # a day off the year end still counts
    "LiabilitiesAndStockholdersEquity": [at("2025-12-31", 5000)],
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [at("2025-12-31", 2100)],
    "CashAndCashEquivalentsAtCarryingValue": [at("2025-12-31", 300)],
    "MarketableSecuritiesCurrent": [at("2025-12-31", 200)],
}


def test_sec_facts_become_fiscal_years():
    from investsync.data import sec_statements
    y24, y25 = sec_statements.years_from_facts(FACTS)
    assert (y24.fiscal_year, y24.net_income, y24.revenue) == (2024, 95, 1000)
    assert y25.revenue == 1200 and y25.gross_profit == 500 and y25.capex == 50 and y25.diluted_eps == 1.25
    assert y25.total_equity == 2000 and y25.total_liabilities == 2900 and y25.cash_and_equivalents == 500
    assert y24.total_assets is None                                      # not filed: unknown, not zero


def test_us_statements_come_from_the_sec_first(monkeypatch):
    """12 Nov 2026 (Karel): the company's own SEC filings first, EastMoney only as the backup."""
    from investsync.data import sec_statements
    from investsync.tickers import parse

    def down(code):
        raise ConnectionError("EastMoney down")
    monkeypatch.setattr(src, "us_indicators", down)
    monkeypatch.setattr(sec_statements, "facts_for", lambda t: FACTS)
    monkeypatch.setattr(adapters, "_us_debt", lambda s, d: 10.0)
    monkeypatch.setattr(adapters, "_us_latest", lambda c, s, y: None)
    monkeypatch.setattr(adapters, "_load_us_rest", lambda *a: a)
    _, _, got, _, reporting, name_local, warnings, source = adapters.load_us(parse("AAPL"))
    assert got == sec_statements.years_from_facts(FACTS) or [y.revenue for y in got] == [1000, 1200]
    assert all(y.total_debt == 10.0 for y in got) and reporting == "USD" and warnings == []
    assert source == "SEC EDGAR XBRL (the company's 10-K and 10-Q filings)"
    monkeypatch.setattr(sec_statements, "facts_for", lambda t: None)
    with pytest.raises(LookupError, match="No financial statements found for ZZZZ"):
        adapters.load_us(parse("ZZZZ"))                                  # neither source: same message as before


def test_eastmoney_fills_gaps_and_stands_in_for_the_sec(monkeypatch):
    from investsync.data import sec_statements
    from investsync.tickers import parse
    sec = sec_statements.years_from_facts(FACTS)
    em = [y.model_copy(update={"total_assets": 9000.0, "revenue": 1.0}) for y in sec]   # SEC wins where it has a figure
    monkeypatch.setattr(src, "us_indicators", lambda code: pd.DataFrame([{"CURRENCY_ABBR": "USD",
                                                                         "SECURITY_NAME_ABBR": "苹果"}]))
    monkeypatch.setattr(src, "us_statement", lambda code, k: None)
    monkeypatch.setattr(adapters, "_us_years_east_money", lambda *a: em)
    monkeypatch.setattr(adapters, "_us_debt", lambda s, d: 10.0)
    monkeypatch.setattr(adapters, "_us_latest", lambda c, s, y: None)
    monkeypatch.setattr(adapters, "_load_us_rest", lambda *a: a)
    monkeypatch.setattr(sec_statements, "facts_for", lambda t: FACTS)
    _, _, got, _, _, name_local, warnings, source = adapters.load_us(parse("AAPL"))
    assert [y.revenue for y in got] == [y.revenue for y in sec] and got[0].total_assets == 9000.0   # gap filled
    assert source.endswith("; EastMoney for total assets") and name_local == "苹果"
    monkeypatch.setattr(sec_statements, "facts_for", lambda t: None)                             # SEC unreachable
    _, _, got, _, _, _, warnings, source = adapters.load_us(parse("AAPL"))
    assert got == em and source == "EastMoney (statements)" and "SEC XBRL" in warnings[0]


def test_latest_period_from_the_10q_facts():
    """The latest 10-Q period (year to date, a year earlier, the quarter alone) from the company's own XBRL facts."""
    from types import SimpleNamespace as N
    from investsync.data import sec_statements
    q = lambda s, e, v, form="10-Q", filed="2026-08-26": {"start": s, "end": e, "val": v, "filed": filed, "form": form}  # noqa: E731
    facts = {
        "Revenues": [q("2026-01-26", "2026-07-26", 177_837), q("2025-01-27", "2025-07-27", 90_805),
                     q("2026-04-27", "2026-07-26", 96_221), q("2025-04-28", "2025-07-27", 46_743),
                     q("2025-01-27", "2026-01-25", 215_938, form="10-K", filed="2026-02-25")],
        "NetIncomeLoss": [q("2026-01-26", "2026-07-26", 118_010), q("2025-01-27", "2025-07-27", 45_317),
                          q("2026-04-27", "2026-07-26", 59_688), q("2025-04-28", "2025-07-27", 26_422)],
        "CostOfRevenue": [q("2026-01-26", "2026-07-26", 44_000)],
        "NetCashProvidedByUsedInOperatingActivities": [q("2026-01-26", "2026-07-26", 74_421)],
        "PaymentsToAcquirePropertyPlantAndEquipment": [q("2026-01-26", "2026-07-26", -3_000)],
        "StockholdersEquity": [{"end": "2026-07-26", "val": 150_000, "filed": "2026-08-26", "form": "10-Q"}],
    }
    years = [N(period_end=date(2025, 1, 26)), N(period_end=date(2026, 1, 25))]
    v = sec_statements.latest_from_facts(facts, years)
    assert v["period_end"] == date(2026, 7, 26) and v["months"] == 6
    assert v["ytd"]["revenue"] == 177_837 and v["prior"]["revenue"] == 90_805 and v["ytd"]["net_income"] == 118_010
    assert v["ytd"]["gross_profit"] == 177_837 - 44_000 and v["ytd"]["capex"] == 3_000     # derived; capex positive
    assert v["quarter"]["revenue"] == 96_221 and v["quarter_prior"]["net_income"] == 26_422
    assert v["total_equity"] == 150_000
    assert sec_statements.latest_from_facts({"Revenues": facts["Revenues"][-1:]}, years) is None   # no 10-Q yet
