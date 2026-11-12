"""Full report: ratios, technicals, reverse DCF, Monte Carlo, ranges, audit and rendering (offline)."""
import io
import math
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from investsync.quant import audit, ranges, ratios, sensitivity, technical
from investsync.quant import valuation as v
from investsync.render.render import render_pdf
from investsync.schema import Consensus, FiscalYear, TearSheetData

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def nvda_with_dcf() -> TearSheetData:
    d = load("NVDA.json")
    for y in d.financials.years:  # fixture predates capex; give a steady 40% FCF margin
        y.operating_cash_flow = 0.5 * y.revenue
        y.capex = 0.1 * y.revenue
    d.valuation = v.build(d, {}, {}, {"US 10Y": 0.042}, None)
    return d


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)\b", pdf))


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


# ---------------------------------------------------------------- ratios
def test_ratios_use_average_balances_and_skip_missing():
    y0 = FiscalYear(fiscal_year=2024, period_end=date(2024, 12, 31), revenue=100.0, net_income=10.0,
                    total_assets=200.0, total_equity=100.0, current_assets=60.0, current_liabilities=30.0)
    y1 = FiscalYear(fiscal_year=2025, period_end=date(2025, 12, 31), revenue=120.0, net_income=15.0,
                    total_assets=240.0, total_equity=110.0, operating_income=20.0, interest_expense=4.0,
                    dividends_paid=6.0, buybacks=3.0)
    r = ratios.ratio_years([y0, y1])
    assert r[1].roe == pytest.approx(15.0 / 105.0)          # average equity
    assert r[1].asset_turnover == pytest.approx(120.0 / 220.0)
    assert r[1].interest_coverage == pytest.approx(5.0)
    assert r[1].payout_ratio == pytest.approx(0.4) and r[1].total_payout_ratio == pytest.approx(0.6)
    assert r[0].current_ratio == pytest.approx(2.0) and r[1].current_ratio is None  # never 0 for missing
    assert r[0].roe is None and r[0].asset_turnover is None   # no opening balance: blank, not a year-end ratio


# ---------------------------------------------------------------- technicals
def _prices(closes: list[float], start: date = date(2023, 1, 2)) -> pd.DataFrame:
    days = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame({"date": days, "open": closes, "high": closes, "low": closes, "close": closes,
                         "volume": [1e6] * len(closes)})


def test_indicator_formulas():
    assert technical.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert technical.rsi(list(range(1, 30)))[-1] == pytest.approx(100.0)       # only gains
    assert technical.rsi(list(range(30, 1, -1)))[-1] == pytest.approx(0.0)     # only losses
    assert technical.max_drawdown([100, 120, 60, 90]) == pytest.approx(-0.5)
    assert technical.volatility([100.0] * 30) == pytest.approx(0.0)


def test_uptrend_reads_bullish_and_chart_is_downsampled():
    closes = [100 * 1.002 ** i for i in range(800)]
    t = technical.compute(_prices(closes), {})
    assert t.overall == "bullish" and t.sma50 < t.price and t.sma200 < t.sma50
    assert len(t.chart) <= 261 and t.chart[-1].close == pytest.approx(closes[-1], rel=1e-6)
    assert {r.period for r in t.returns} >= {"1M", "1Y"}


# ---------------------------------------------------------------- valuation extras
def test_reverse_dcf_reproduces_the_price():
    d = nvda_with_dcf()
    rev = d.valuation.reverse
    assert d.valuation.dcf and rev and rev.model == "DCF"
    m = sensitivity._DCFModel(d.valuation, d, 0.03)
    if rev.implied_growth is not None:
        value = m.value(m.revenues(constant=rev.implied_growth, hold=rev.hold_years), m.margin, m.wacc, m.g)
        assert value == pytest.approx(d.quote.price, rel=1e-4)
    value = m.value(m.revenues(), rev.implied_fcf_margin, m.wacc, m.g)
    assert value == pytest.approx(d.quote.price, rel=1e-6)


def test_sensitivity_grid_centre_is_the_base_case_and_monotonic():
    d = nvda_with_dcf()
    g = d.valuation.sensitivity.discount_growth
    assert g.values[2][2] == pytest.approx(d.valuation.dcf.value_per_share, rel=1e-9)
    col = [row[2] for row in g.values if row[2] is not None]
    assert col == sorted(col, reverse=True)      # higher WACC -> lower value
    mg = d.valuation.sensitivity.margin_growth
    assert mg.values[2][2] == pytest.approx(d.valuation.dcf.value_per_share, rel=1e-9)


def test_monte_carlo_is_seeded_and_centred_near_base():
    a, b = nvda_with_dcf().valuation.monte_carlo, nvda_with_dcf().valuation.monte_carlo
    assert a.percentiles == b.percentiles                       # reproducible
    assert a.percentiles["p5"] < a.percentiles["p50"] < a.percentiles["p95"]
    assert sum(a.counts) == a.n_valid and len(a.bins) == len(a.counts) + 1
    base = nvda_with_dcf().valuation.dcf.value_per_share
    assert 0.5 * base < a.percentiles["p50"] < 1.5 * base


def test_ddm_reverse_is_closed_form():
    d = load("0005_HK.json") if (FIX / "0005_HK.json").exists() else None
    if d is None:
        pytest.skip("no bank fixture")
    val = v.build(d, {}, {}, {"US 10Y": 0.042}, None)
    if not (val and val.ddm and val.reverse):
        pytest.skip("DDM not applicable to fixture")
    ke, dps, p = val.wacc.cost_of_equity, val.ddm.dividend_per_share, d.quote.price
    g = val.reverse.implied_growth
    assert val.reverse.hold_years == 0 and val.reverse.horizon_years == 0  # no held years for a DDM
    assert dps * (1 + g) / (ke - g) == pytest.approx(p, rel=1e-9)


def test_football_field_bars_are_ordered_and_use_peer_quartiles():
    d = nvda_with_dcf()
    ff = ranges.football_field(d, Consensus(target_low=100.0, target_high=200.0, target_mean=150.0,
                                            currency=d.quote.currency, analysts=10))
    assert ff and all(b.low <= b.high for b in ff.bars)
    labels = [b.label for b in ff.bars]
    assert "Analyst price targets" in labels and "DCF (sensitivity range)" in labels
    pe = next((b for b in ff.bars if b.label == "Peer P/E (TTM)"), None)
    if pe:
        assert pe.low <= pe.mid <= pe.high


def test_pe_band_lags_eps_and_reports_percentile():
    d = load("NVDA.json")
    end = d.quote.as_of
    days = [end - timedelta(days=i) for i in range(5 * 365, -1, -1)]
    prices = pd.DataFrame({"date": days, "close": [100.0] * len(days)})
    band = ranges.pe_band(prices, d)
    assert band is not None and 0.0 <= band.percentile <= 1.0
    assert band.low <= band.median <= band.high


# ---------------------------------------------------------------- audit
def test_audit_flags_stale_statements_and_missing_peers():
    d = load("NVDA.json")
    d.comps = None
    a = audit.run(d, today=d.financials.years[-1].period_end + timedelta(days=600))
    by = {c.name: c.status for c in a.checks}
    assert by["Latest annual statements"] == "caveat" and by["Peer set"] == "caveat"
    assert a.status in ("caveated", "review")


# ---------------------------------------------------------------- rendering
def test_report_renders_from_an_old_1_0_payload_with_placeholders():
    d = load("0700_HK.json")                  # schema 1.0: none of the new sections
    pdf = render_pdf(d)
    assert pdf.startswith(b"%PDF") and _pages(pdf) >= 8
    text = _text(pdf)
    assert "AI SECTION" in text and "Investment summary" in text and "Methodology" in text


def test_tearsheet_layout_is_still_one_page():
    assert _pages(render_pdf(load("0700_HK.json"), layout="tearsheet")) == 1


def test_full_payload_renders_every_chapter():
    path = FIX / "0700_HK_full.json"
    if not path.exists():
        pytest.skip("no 1.1 fixture")
    d = TearSheetData.model_validate_json(path.read_text(encoding="utf-8"))
    text = _text(render_pdf(d))
    for title in ("Investment summary", "Company overview", "Financial analysis", "Financial statements",
                  "Valuation", "Competitive landscape", "technical indicators", "Catalysts, news",
                  "Ownership", "Methodology"):
        assert title in text, title
    assert "MONTE CARLO" in text.upper() and "REVERSE DCF" in text.upper()


# ---------------------------------------------------------------- AI rating (rule-based)
def _ff(data, **mids):
    from investsync.schema import FootballField, RangeBar
    labels = {"peer_pe": "Peer P/E (TTM)", "peer_ev_ebitda": "Peer EV/EBITDA", "peer_pb": "Peer P/B"}
    data.football_field = FootballField(currency=data.quote.currency, price=data.quote.price, bars=[
        RangeBar(label=labels[k], low=val * 0.9, high=val * 1.1, mid=val, basis="test") for k, val in mids.items()])


CFG = {"thresholds": {"buy": 0.15, "sell": -0.10}, "outlier_band": 0.5, "min_methods": 2,
       "weights": {"default": {"dcf": 0.5, "peer_pe": 0.25, "peer_ev_ebitda": 0.25},
                   "financial": {"ddm": 0.5, "peer_pb": 0.3, "peer_pe": 0.2}},
       "confidence": {"high_cv": 0.15, "medium_cv": 0.30}}


def test_rating_blends_methods_and_applies_thresholds():
    from investsync.quant import rating
    d = nvda_with_dcf()
    p = d.quote.price
    d.valuation.dcf.value_per_share = 1.30 * p
    _ff(d, peer_pe=1.20 * p, peer_ev_ebitda=1.25 * p)
    r = rating.compute(d, CFG, financial=False)
    assert r.fair_value == pytest.approx(p * (0.5 * 1.30 + 0.25 * 1.20 + 0.25 * 1.25))
    assert r.rating == "Buy" and r.confidence == "high"
    d.valuation.dcf.value_per_share = 0.85 * p
    _ff(d, peer_pe=0.85 * p, peer_ev_ebitda=0.80 * p)
    assert rating.compute(d, CFG, financial=False).rating == "Sell"


def test_rating_drops_outliers_and_needs_two_methods():
    from investsync.quant import rating
    d = nvda_with_dcf()
    p = d.quote.price
    d.valuation.dcf.value_per_share = 1.0 * p
    _ff(d, peer_pe=1.05 * p, peer_ev_ebitda=4.0 * p)       # EV/EBITDA is an outlier
    r = rating.compute(d, CFG, financial=False)
    assert [m.key for m in r.methods if not m.included] == ["peer_ev_ebitda"]
    assert r.rating == "Hold"
    _ff(d)                                                   # DCF only
    r = rating.compute(d, CFG, financial=False)
    assert r.rating == "Not rated" and "Only 1 valuation method" in r.reason


# ---------------------------------------------------------------- citations
def test_every_cached_source_function_has_a_citation_entry():
    import inspect
    from investsync import provenance
    from investsync.data import filings, sources
    cached_fns = [f for mod in (sources, filings) for _, f in inspect.getmembers(mod, inspect.isfunction)
                  if hasattr(f, "__wrapped__") and f.__module__ == mod.__name__]
    assert cached_fns, "expected @cached source functions"
    missing = [f.__qualname__ for f in cached_fns if f.__qualname__ not in provenance.REGISTRY]
    assert not missing, f"add these to provenance.REGISTRY: {missing}"


def test_citations_group_peers_and_link_the_company_itself():
    from datetime import datetime, timezone
    from investsync import provenance
    d = load("NVDA.json")
    t0 = datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp()
    recs = [provenance.Record("yf_info", ("AMD",), datetime.fromtimestamp(t0, tz=timezone.utc), True),
            provenance.Record("yf_info", ("NVDA",), datetime.fromtimestamp(t0 + 60, tz=timezone.utc), False),
            provenance.Record("us_statement", ("NVDA", "bs"), datetime.fromtimestamp(t0, tz=timezone.utc), True)]
    cites = provenance.citations(recs, d)
    info = next(c for c in cites if c.via == "yfinance Ticker.info")
    assert info.url.endswith("/NVDA") and "1 peer company" in info.what
    assert info.retrieved.timestamp() == t0          # oldest retrieval in the group
    assert [c.n for c in cites] == list(range(1, len(cites) + 1))
    assert cites[0].topic == "statements"            # statements listed first


# ---------------------------------------------------------------- official announcements
def test_announcements_are_labelled_and_routine_filings_left_out(monkeypatch):
    from datetime import date as _date, timedelta as _td
    from investsync import tickers
    from investsync.data import extras, filings
    today = _date.today()
    d = lambda k: (today - _td(days=k)).isoformat()  # noqa: E731
    monkeypatch.setattr(filings, "sec_cik", lambda code: 1045810)
    monkeypatch.setattr(filings, "sec_recent_filings", lambda cik: [
        {"form": "4", "date": d(1), "items": "", "description": "", "url": "u0"},
        {"form": "8-K", "date": d(2), "items": "2.02,9.01", "description": "8-K", "url": "u1"},
        {"form": "10-Q", "date": d(3), "items": "", "description": "", "url": "u2"},
        {"form": "8-K", "date": d(200), "items": "8.01", "description": "", "url": "old"}])
    us, routine = extras.announcements(tickers.parse("NVDA"))
    assert [a.kind for a in us] == ["8-K: Results of operations", "Quarterly report (10-Q)"]
    assert all(a.important for a in us) and routine == 1          # Form 4 left out; 200-day-old 8-K ignored

    monkeypatch.setattr(filings, "cninfo_announcements", lambda code, s, e: [
        {"date": d(1), "title": "贵州茅台2026年半年度报告", "url": "c1"},
        {"date": d(1), "title": "贵州茅台2026年半年度报告摘要", "url": "c2"},
        {"date": d(2), "title": "贵州茅台2026年年度权益分派实施公告", "url": "c3"}])
    cn, routine = extras.announcements(tickers.parse("600519.SH"))
    assert [a.kind for a in cn] == ["Interim report", "Dividend payment"] and routine == 1

    monkeypatch.setattr(filings, "hkex_stock_id", lambda code: 7609)
    monkeypatch.setattr(filings, "hkex_announcements", lambda sid, s, e: [
        {"date": d(1), "title": "NEXT DAY DISCLOSURE RETURN", "category": "Next Day Disclosure Returns", "url": "h0"},
        {"date": d(2), "title": "COMPLETION OF US$1.8 BILLION ISSUE OF NOTES", "category":
         "Announcements and Notices - [Issue of Debt Securities]", "url": "h1"}])
    hk, routine = extras.announcements(tickers.parse("0700.HK"))
    assert hk[0].title == "Completion of US$1.8 Billion Issue of Notes" and hk[0].kind == "Issue of Debt Securities"
    assert hk[0].important and routine == 1


def test_news_is_spread_across_weeks():
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from investsync.narrative.facts import spread_by_week
    from investsync.schema import NewsItem
    now = _dt(2026, 11, 6, tzinfo=_tz.utc)
    busy_day = [NewsItem(published=now - _td(hours=h), title=f"today {h}") for h in range(20)]
    older = [NewsItem(published=now - _td(days=7 * w), title=f"week {w}") for w in range(1, 5)]
    picked = spread_by_week(busy_day + older, 6)
    assert {n.title for n in picked} >= {"week 1", "week 2", "week 3", "week 4"}


def test_facts_label_every_comps_column_correctly():
    """Regression (8 Nov 2026): a new comps column shifted the labels in the facts, so the writer called the
    forward P/E "EV/EBITDA" and the P/B "dividend yield" on page 1 of all three test reports."""
    import json
    from pathlib import Path
    from investsync.narrative.facts import facts_text
    from investsync.render import viewmodel
    from investsync.schema import TearSheetData
    d = TearSheetData.model_validate(json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "0700_HK_full.json")
                                                .read_text(encoding="utf-8")))
    d.comps.target.pe_fwd, d.comps.target.ev_ebitda, d.comps.target.pb = 11.9, 10.4, 3.1
    text = facts_text(viewmodel.build(d), d)
    assert "- P/E forward (next-year consensus): " in text and "11.9x" in text.split("P/E forward")[1].split("\n")[0]
    assert "10.4x" in text.split("- EV/EBITDA (TTM): ")[1].split("\n")[0]
    assert "3.1x" in text.split("- P/B: ")[1].split("\n")[0]


def test_large_amounts_in_ai_text_print_in_bn():
    from investsync.render.render import readable_amounts
    assert readable_amounts("net profit of 118,010mn (+161%)") == "net profit of 118.0bn (+161%)"
    assert readable_amounts("EV USD 4,913,510mn") == "EV USD 4.91tn"
    assert readable_amounts("opex of 9,200mn") == "opex of 9,200mn"       # under 10bn: unchanged


def test_debate_evidence_codes_are_not_printed_in_sentences():
    from investsync.render.render import strip_codes
    assert strip_codes("the $108.0bn Q3 guide (E110) marks a pause") == "the $108.0bn Q3 guide marks a pause"
    assert strip_codes("margins hold (S5, E24).") == "margins hold."
    assert strip_codes("guidance (R6, E24) and [R7]") == "guidance (R6) and [R7]"      # research-note ids stay
    assert strip_codes("Q3 FY2027E guide (+12%)") == "Q3 FY2027E guide (+12%)"
