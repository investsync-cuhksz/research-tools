"""Broker research (street view), scorecard, buy-below / sell-above and run history. Offline."""
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from dspy.utils.dummies import DummyLM

from investsync.data import brokers
from investsync.quant import rating, scorecard, street
from investsync.render.render import render_pdf
from investsync.schema import BrokerNote, Market, TearSheetData
from investsync.tickers import parse

FIX = Path(__file__).resolve().parent.parent / "fixtures"
TODAY = date(2026, 11, 6)


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)\b", pdf))


def _text(pdf: bytes) -> str:
    import io
    from pypdf import PdfReader
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


# ---------------------------------------------------------------- normalisation
@pytest.mark.parametrize("raw,std", [
    ("买入", "Buy"), ("增持", "Outperform"), ("优于大市", "Outperform"), ("高度确信优于大市", "Outperform"),
    ("中性", "Hold"), ("持有", "Hold"), ("减持", "Underperform"), ("卖出", "Sell"), ("强烈推荐", "Buy"),
    ("Strong Buy", "Buy"), ("Overweight", "Outperform"), ("Market Perform", "Hold"), ("Equal-Weight", "Hold"),
    ("Underperform", "Underperform"), ("Underweight", "Underperform"), ("Sell", "Sell"), ("--", None)])
def test_ratings_map_onto_one_scale(raw, std):
    assert brokers.std_rating(raw) == std


def test_wording_keeps_the_brokers_english_and_translates_chinese():
    assert brokers.wording_en("买入（Buy）") == "Buy"
    assert brokers.wording_en("区间操作(Trading Buy)") == "Trading Buy"
    assert brokers.wording_en("优于大市") == "Outperform"
    assert brokers.broker_en("国信证券") == "Guosen Securities" and brokers.broker_en("美银") == "BofA Securities"


def test_eastmoney_this_year_is_the_first_unreported_year():
    # observed: Jan-Apr reports without a third year still forecast last year; later ones the current year
    assert brokers._this_fy(date(2026, 1, 5), has_third_year=False) == 2025
    assert brokers._this_fy(date(2026, 4, 19), has_third_year=True) == 2026
    assert brokers._this_fy(date(2026, 11, 4), has_third_year=True) == 2026


def test_a_share_reports_become_notes_with_years_actions_and_pdf(monkeypatch):
    rows = [{"publishDate": "2026-11-04 00:00:00.000", "infoCode": "AP1", "title": "Q3 点评", "orgSName": "国信证券",
             "emRatingName": "增持", "sRatingName": "优于大市", "lastEmRatingName": "买入", "ratingChange": 1,
             "predictThisYearEps": "64.62", "predictNextYearEps": "70.01", "predictNextTwoYearEps": "73.98",
             "indvAimPriceT": "", "indvAimPriceL": "", "researcher": "张三"},
            {"publishDate": "2026-01-05 00:00:00.000", "infoCode": "AP2", "title": "年度展望", "orgSName": "开源证券",
             "emRatingName": "买入", "sRatingName": "买入", "lastEmRatingName": "", "ratingChange": 2,
             "predictThisYearEps": "72.04", "predictNextYearEps": "73.07", "predictNextTwoYearEps": "",
             "indvAimPriceT": "1610", "indvAimPriceL": "1610", "researcher": "李四"}]
    monkeypatch.setattr(brokers.src, "em_research_reports", lambda code, b, e: rows)
    monkeypatch.setattr(brokers.src, "em_report_abstract",
                        lambda code: {"abstract": "收入同比增长3%。" * 200, "pdf": f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf"})
    notes = brokers.load(parse("600519.SH"), "600519.SS", "CNY", today=TODAY)
    a, b = notes
    assert a.broker == "Guosen Securities" and a.rating == "Outperform" and a.rating_original == "Outperform"
    assert a.action == "downgrade" and a.previous_rating == "Buy"
    assert a.eps == {"FY2026": 64.62, "FY2027": 70.01, "FY2028": 73.98}
    assert b.eps == {"FY2025": 72.04, "FY2026": 73.07} and b.action == "initiate" and b.target == 1610
    assert a.url.endswith("H3_AP1_1.pdf") and len(a.abstract) <= brokers.ABSTRACT_CHARS + 3


def test_hk_forecasts_use_the_rated_row_and_convert_cents(monkeypatch):
    df = pd.DataFrame([
        {"财政年度": 2026.0, "每股盈利": 2912.0, "证券商": "美银", "评级": "买入", "目标价": 780.0, "更新日期": "08/10/2026", "eps_ccy": "CNY"},
        {"财政年度": 2027.0, "每股盈利": 3100.0, "证券商": "美银", "评级": "--", "目标价": None, "更新日期": "08/10/2026", "eps_ccy": "CNY"},
        {"财政年度": 2026.0, "每股盈利": 2300.0, "证券商": "旧券商", "评级": "持有", "目标价": 400.0, "更新日期": "01/01/2024", "eps_ccy": "CNY"}])
    monkeypatch.setattr(brokers.src, "etnet_hk_forecasts", lambda code: df)
    notes = brokers.load(parse("0700.HK"), "0700.HK", "CNY", today=TODAY)
    assert len(notes) == 1                                   # notes older than a year are dropped
    n = notes[0]
    assert n.broker == "BofA Securities" and n.rating == "Buy" and n.target == 780.0
    assert n.eps == {"FY2026": 29.12, "FY2027": 31.0} and n.on == date(2026, 10, 8)
    df["eps_ccy"] = "USD"                                    # forecasts in another currency are not used
    monkeypatch.setattr(brokers.src, "etnet_hk_forecasts", lambda code: df)
    assert brokers.load(parse("0700.HK"), "0700.HK", "CNY", today=TODAY)[0].eps == {}


def test_us_actions_keep_targets_and_direction(monkeypatch):
    df = pd.DataFrame([
        {"GradeDate": pd.Timestamp("2026-11-02"), "Firm": "Melius Research", "ToGrade": "Buy", "FromGrade": "Buy",
         "Action": "main", "currentPriceTarget": 315.0, "priorPriceTarget": 420.0},
        {"GradeDate": pd.Timestamp("2026-09-10"), "Firm": "Piper Sandler", "ToGrade": "Overweight", "FromGrade": "",
         "Action": "init", "currentPriceTarget": 300.0, "priorPriceTarget": 0.0},
        {"GradeDate": pd.Timestamp("2025-01-01"), "Firm": "Old", "ToGrade": "Sell", "FromGrade": "Hold",
         "Action": "down", "currentPriceTarget": 10.0, "priorPriceTarget": 20.0}])
    monkeypatch.setattr(brokers.src, "yf_analyst_actions", lambda sym: df)
    notes = brokers.load(parse("NVDA"), "NVDA", "USD", today=TODAY)
    assert [n.broker for n in notes] == ["Melius Research", "Piper Sandler"]   # outside the window dropped
    assert notes[0].previous_target == 420.0 and notes[1].action == "initiate" and notes[1].previous_target is None


# ---------------------------------------------------------------- street view
def _note(broker, days_ago, rating=None, target=None, eps=None):
    return BrokerNote(on=TODAY - timedelta(days=days_ago), broker=broker, rating=rating, target=target,
                      eps=eps or {}, source="test")


def tencent() -> TearSheetData:
    d = load("0700_HK_full.json")
    d.quote.as_of = TODAY
    return d


def test_street_compares_brokers_with_each_other_and_the_model():
    d = tencent()
    p = d.quote.price
    last = [y for y in d.financials.years if y.diluted_eps][-1]
    fy1 = f"FY{last.fiscal_year + 1}"
    d.rating = rating.compute(d) or d.rating
    from investsync.schema import Rating
    d.rating = Rating(rating="Buy", fair_value=1.2 * p, upside=0.2, currency=d.quote.currency,
                      buy_threshold=0.15, sell_threshold=-0.10)
    notes = [_note("A", 5, "Buy", 1.5 * p, {fy1: last.diluted_eps * 1.10}),
             _note("B", 10, "Outperform", 1.4 * p, {fy1: last.diluted_eps * 1.00}),
             _note("C", 100, "Hold", 1.1 * p, {fy1: last.diluted_eps * 0.95}),
             _note("A", 60, "Hold", 1.3 * p),                           # older note from A is superseded
             _note("D", 3, "Buy", 50 * p, {fy1: last.diluted_eps * 8})]   # absurd target / per-ADS EPS ignored
    sv = street.build(d, notes, today=TODAY)
    assert sv.brokers == 4 and sv.rating_counts == {"Buy": 2, "Outperform": 1, "Hold": 1}
    assert sv.targets_n == 3 and sv.target_median == pytest.approx(1.4 * p)
    assert sv.stale_targets == 1 and sv.targets_above_model == 2
    e = sv.eps[0]
    assert e.period == fy1 and e.n == 3 and e.excluded == 1 and e.median == pytest.approx(last.diluted_eps)
    assert e.vs_last_actual == pytest.approx(0, abs=1e-9)
    text = " ".join(sv.findings)
    assert "inside the brokers' range (2 of 3 targets are higher)" in text
    assert "Most bullish target: A" in text and "most cautious: C" in text


def test_estimate_trend_uses_recent_vs_earlier_notes():
    d = tencent()
    d.profile.market = Market.CN
    last = [y for y in d.financials.years if y.diluted_eps][-1]
    fy1, e0 = f"FY{last.fiscal_year + 1}", last.diluted_eps
    notes = [_note("A", 5, "Buy", eps={fy1: e0 * 0.98}), _note("B", 12, "Buy", eps={fy1: e0 * 0.96}),
             _note("A", 60, "Buy", eps={fy1: e0 * 1.02}), _note("B", 70, "Buy", eps={fy1: e0 * 1.00})]
    sv = street.build(d, notes, today=TODAY)
    assert sv.revision is not None and sv.revision.change == pytest.approx(0.97 / 1.01 - 1)
    assert any(f.startswith("Estimate trend:") and "lower than" in f for f in sv.findings)


def test_agreement_reflects_direction_first():
    d = tencent()
    p = d.quote.price
    same = [_note(x, 5, "Buy", p * t) for x, t in zip("ABCD", (1.1, 1.5, 2.0, 2.4))]
    assert street.build(d, same, today=TODAY).agreement == "medium"    # all positive, very different targets
    tight = [_note(x, 5, "Buy", p * t) for x, t in zip("ABCD", (1.2, 1.25, 1.3, 1.3))]
    assert street.build(d, tight, today=TODAY).agreement == "high"
    split = [_note(x, 5, r) for x, r in zip("ABCD", ("Buy", "Sell", "Hold", "Buy"))]
    assert street.build(d, split, today=TODAY).agreement == "low"


# ---------------------------------------------------------------- scorecard, buy-below, history
def test_scorecard_states_the_figures_behind_each_check():
    d = tencent()
    sc = scorecard.build(d)
    assert [a.key for a in sc.areas] == ["value", "future", "past", "health", "dividend"]
    for a in sc.areas:
        assert 0 <= a.score <= a.available <= len(a.checks) and all(c.detail for c in a.checks)
    assert sc.piotroski is not None and len(sc.piotroski.checks) == 9


def test_banks_are_not_scored_on_health():
    sc = scorecard.build(load("0005_HK.json"))
    health = next(a for a in sc.areas if a.key == "health")
    assert health.available == 0 and "banks" in health.note and sc.piotroski is None


def test_buy_below_and_sell_above_are_the_rule_as_prices():
    from tests.test_report import CFG, _ff, nvda_with_dcf
    d = nvda_with_dcf()
    p = d.quote.price
    d.valuation.dcf.value_per_share = 1.30 * p
    _ff(d, peer_pe=1.20 * p, peer_ev_ebitda=1.25 * p)
    r = rating.compute(d, CFG)
    assert r.buy_below == pytest.approx(r.fair_value / 1.15) and r.sell_above == pytest.approx(r.fair_value / 0.90)
    d.quote.price = r.buy_below * 0.999                     # just below buy-below -> the rule says Buy
    assert rating.compute(d, CFG).rating == "Buy"


def test_history_reports_changes_and_rating_since(tmp_path, monkeypatch):
    from investsync import history
    from investsync.schema import Rating
    monkeypatch.setenv("INVESTSYNC_HISTORY", "1")
    monkeypatch.setenv("INVESTSYNC_HISTORY_DIR", str(tmp_path))
    d = tencent()
    p = d.quote.price
    for days, rt in ((20, "Hold"), (10, "Buy"), (3, "Buy")):
        d.quote.as_of = TODAY - timedelta(days=days)
        d.rating = Rating(rating=rt, fair_value=p * 1.2, upside=0.2, currency="HKD", buy_threshold=0.15,
                          sell_threshold=-0.1)
        history.save(d)
    d.quote.as_of, d.quote.price = TODAY, p * 1.1
    s = history.compare(d)
    assert s.previous_date == TODAY - timedelta(days=3)
    assert s.rating_since == TODAY - timedelta(days=10)
    assert any("Model rating unchanged (Buy)" in c for c in s.changes)
    assert any(c.startswith("Share price") and "+10.0%" in c for c in s.changes)


def test_history_is_off_in_tests_by_default(tmp_path, monkeypatch):
    from investsync import history
    monkeypatch.setenv("INVESTSYNC_HISTORY_DIR", str(tmp_path))
    assert history.save(tencent()) is None and not any(tmp_path.iterdir())


# ---------------------------------------------------------------- AI broker step + layout
def _with_street(d: TearSheetData) -> TearSheetData:
    p = d.quote.price
    d.street = street.build(d, [
        BrokerNote(on=TODAY - timedelta(days=i), broker=f"Broker {i}", rating="Buy", target=p * (1.3 + i / 50),
                   title="Q3 收入同比增长3%", abstract="2026Q3实现营业收入402.67亿元，同比增长3.08%。直销占比提升。",
                   source="test") for i in range(1, 6)], today=TODAY)
    return d


def test_broker_step_keeps_checked_summaries_and_drops_invented_figures():
    from investsync.narrative import commentary
    d = _with_street(tencent())
    out = {"summaries": json.dumps([
        {"index": 1, "summary_en": "Q3 revenue rose 3.08% to RMB 40.27bn as direct sales grew."},
        {"index": 2, "summary_en": "Revenue jumped 45% on a new product cycle."}]),            # 45% is invented
        "street_view": "All five brokers rate the shares positively, but their targets differ."}
    assert commentary.digest_brokers(d, DummyLM([out])) is True
    n1, n2 = d.street.notes[0], d.street.notes[1]
    assert n1.summary_en.startswith("Q3 revenue rose 3.08%") and n2.summary_en is None
    assert d.street.synthesis.startswith("All five brokers")


def test_page_one_still_fits_with_brokers_and_max_length_text():
    from investsync.narrative.commentary import SECTIONS
    from investsync.schema import Bullet, Narrative
    d = _with_street(tencent())
    d.scorecard = scorecard.build(d)
    w = ("The business keeps compounding as services with higher margins grow faster than the group while "
         "capital returns continue").split()

    def words(n):
        return " ".join((w * (n // len(w) + 1))[:n]) + "."
    d.narrative = Narrative(status="generated", model="test", dupont_commentary=words(55), comps_commentary=words(60),
                            catalysts=[Bullet(title="Catalyst", text=words(35))] * 3,
                            risks=[Bullet(title="Risk", text=words(35))] * 2,
                            **{k: words(lim) for k, (_, lim) in SECTIONS.items()})
    for n in d.street.notes:
        n.summary_en = words(28)
    d.street.synthesis = words(90)
    assert _pages(render_pdf(d, layout="tearsheet")) == 1
    text = _text(render_pdf(d))
    assert "Broker research" in text and "Scorecard" not in text and "WHAT THE LATEST REPORTS ARGUE" in text.upper()


def test_guardrail_reads_figures_inside_chinese_text():
    from investsync.narrative import guardrail as g
    a = g.build_allowed("2026Q3实现营业收入402.67亿元，同比增长3.08%；毛利率89.64%，同比下降1.64pcts。")
    assert g.unmatched("Q3 revenue rose 3.08% to RMB 40.27bn; gross margin fell 1.64pp to 89.64%.", a) == []
    assert g.unmatched("Revenue jumped 45%.", a) == ["45%"]



def test_guardrail_chinese_percentage_points_and_ranges():
    from investsync.narrative import guardrail as g
    a = g.build_allowed("2026年1-5月全球动力电池市占率40.2%，同比提升2.2个百分点；拟回购200-400亿元")
    assert g.unmatched("global share of 40.2%, up 2.2pp", a) == []
    assert g.unmatched("a RMB 20-40bn buyback", a) == []
    assert g.unmatched("a RMB 200-400bn buyback", a) == ["200bn", "400bn"]


def test_chinese_amounts_are_converted_in_code():
    from investsync.narrative.guardrail import annotate_cn_amounts as a
    assert a("已回购53.6亿元") == "已回购53.6亿元 (RMB 5.36bn)"
    assert a("拟回购200-400亿元") == "拟回购200-400亿元 (RMB 20bn-40bn)"
    assert a("累计回购1960.59万股") == "累计回购1960.59万股 (19.61mn shares)"
    assert a(a("已回购53.6亿元")) == a("已回购53.6亿元")   # idempotent


def test_history_does_not_compare_across_a_method_change(tmp_path, monkeypatch):
    """A report from before method tracking (or with another rating basis) is a different measurement: no
    "Sell → Buy, +164%" line and no rating change for the writer to explain (round-4 review, 9 Nov 2026)."""
    import json as _json
    from investsync import history
    from investsync.schema import Rating
    monkeypatch.setenv("INVESTSYNC_HISTORY", "1")
    monkeypatch.setenv("INVESTSYNC_HISTORY_DIR", str(tmp_path))
    d = tencent()
    p = d.quote.price
    d.quote.as_of = TODAY - timedelta(days=4)
    d.rating = Rating(rating="Sell", fair_value=p * 0.6, upside=-0.4, currency="HKD", buy_threshold=0.15,
                      sell_threshold=-0.1)
    f = history.save(d)
    snap = _json.loads(f.read_text())
    snap.pop("methods"); snap.pop("basis")  # an old-format record
    f.write_text(_json.dumps(snap))
    d.quote.as_of = TODAY
    d.rating = Rating(rating="Buy", fair_value=p * 1.5, upside=0.5, currency="HKD", buy_threshold=0.15,
                      sell_threshold=-0.1)
    s = history.compare(d)
    assert s.previous_rating is None and s.previous_fair_value is None
    assert any(c.startswith("Not comparable") for c in s.changes)
    assert not any("Model rating changed" in c or "Model fair value" in c for c in s.changes)


def test_analyst_basis_rating_follows_our_scenarios_and_lists_cross_checks():
    """RATING_BASIS=analyst: fair value = probability-weighted scenarios; peers and the mechanical DCF are shown as
    cross-checks outside the rating (user decision, 9 Nov 2026)."""
    from investsync.schema import Scenario, ScenarioSet
    d = tencent()
    p = d.quote.price
    d.valuation.scenarios = ScenarioSet(currency=d.quote.currency, weighted_value=p * 1.05, scenarios=[
        Scenario(name="bear", probability=0.25, revenue_growth=[0.0] * 3, fcf_margin=0.2, value_per_share=p * 0.6),
        Scenario(name="base", probability=0.5, revenue_growth=[0.1] * 3, fcf_margin=0.25, value_per_share=p * 1.1),
        Scenario(name="bull", probability=0.25, revenue_growth=[0.2] * 3, fcf_margin=0.3, value_per_share=p * 1.4)])
    r = rating.from_scenarios(d)
    assert r.basis == "scenarios" and r.rating == "Hold" and abs(r.fair_value - p * 1.05) < 1e-6
    used = [m for m in r.methods if m.included]
    assert len(used) == 1 and used[0].weight == 1.0
    assert all(m.note.startswith(("cross-check", "not used even as a cross-check")) for m in r.methods
               if not m.included) and len(r.methods) > 1
    assert "bear" in r.reason and r.confidence in ("high", "medium", "low")
    assert "scenarios" in rating.how(r) and "scenarios" in rating.method_note(r)


def test_page_one_shows_the_street_beside_our_view_without_blending():
    from investsync.render.viewmodel import street_line
    from investsync.schema import Rating
    d = _with_street(tencent())
    d.overall = None
    d.rating = Rating(rating="Hold", fair_value=d.quote.price * 1.05, upside=0.05, currency="HKD",
                      buy_threshold=0.15, sell_threshold=-0.1)
    sl = street_line(d)
    assert sl["lean"] == "Buy" and sl["n"] == 5 and "median target" in sl["target"]
    assert "the brokers' median target" in sl["ours"]


def test_disclosures_name_the_producer_and_show_the_rating_history_with_its_basis(tmp_path, monkeypatch):
    from investsync import history
    from investsync.render.report_vm import _disclosures
    from investsync.schema import Rating, RatingMethod
    monkeypatch.setenv("INVESTSYNC_HISTORY", "1")
    monkeypatch.setenv("INVESTSYNC_HISTORY_DIR", str(tmp_path))
    d = tencent()
    p = d.quote.price
    d.quote.as_of = TODAY - timedelta(days=2)
    d.rating = Rating(rating="Hold", fair_value=p * 1.05, upside=0.05, currency="HKD", buy_threshold=0.15,
                      sell_threshold=-0.1, basis="scenarios", methods=[RatingMethod(
                          key="dcf", label="DCF (analyst scenarios, probability-weighted)", value=p * 1.05, weight=1.0,
                          included=True)])
    history.save(d)
    dz = _disclosures(d)
    assert "no analyst certification" in dz["producer"] and "holds no positions" in dz["producer"]
    assert dz["history"] and dz["history"][-1][1] == "Hold" and dz["history"][-1][4] == "our scenarios"
    d.narrative = None
    assert "AI model" not in _disclosures(d)["producer"]  # blind renders blank the model: no name, no gap


def test_results_preview_box_shows_the_next_quarters_when_results_are_near():
    from investsync.render.report_vm import _preview
    from investsync.schema import Consensus, EstimateRow
    d = tencent()
    d.quote.next_earnings_date = TODAY + timedelta(days=12)
    d.consensus = Consensus(currency="HKD", estimate_currency="RMB", quarters=[
        EstimateRow(period="3Q26E", revenue_avg=210.4e9, revenue_growth=0.08, eps_avg=7.22, analysts=30)])
    pv = _preview(d)
    assert pv["rows"][0][0].startswith("3Q26E (results") and pv["rows"][0][1] == "210,400"
    assert "RMB mn" in pv["rev_head"]
    d.quote.next_earnings_date = TODAY + timedelta(days=80)  # too far away: no box
    assert _preview(d) is None


def test_options_implied_move_and_risks_to_fair_value(monkeypatch):
    from investsync.data import extras
    from investsync.data import sources as src
    from investsync.render.report_vm import _rating
    from investsync.schema import Scenario, ScenarioSet
    from investsync.tickers import parse as tparse
    d = tencent()
    d.quote.price, d.quote.next_earnings_date = 100.0, TODAY + timedelta(days=11)
    monkeypatch.setattr(src, "yf_option_straddle", lambda sym, after, spot: {"expiry": "2026-11-18", "strike": 100.0,
                                                                            "call": 5.0, "put": 6.0})
    extras.implied_move(tparse("NVDA"), d)
    assert abs(d.quote.implied_move - 0.11) < 1e-9 and d.quote.implied_move_expiry.isoformat() == "2026-11-18"
    p = d.quote.price
    d.valuation.scenarios = ScenarioSet(currency="HKD", weighted_value=p * 1.05, scenarios=[
        Scenario(name="bear", probability=0.3, revenue_growth=[0.0] * 3, fcf_margin=0.2, value_per_share=p * 0.5,
                 drivers="Capex cuts stall growth."),
        Scenario(name="base", probability=0.5, revenue_growth=[0.1] * 3, fcf_margin=0.25, value_per_share=p * 1.2),
        Scenario(name="bull", probability=0.2, revenue_growth=[0.2] * 3, fcf_margin=0.3, value_per_share=p * 1.4)])
    d.rating = rating.from_scenarios(d)
    r = _rating(d)
    assert "Downside: the bear case" in r["risks_fv"] and "Capex cuts stall growth." in r["risks_fv"]
    assert "Sell at or above" in r["risks_fv"]


def test_rerating_splits_the_price_move_into_estimates_and_multiple():
    from investsync.quant.ranges import rerating
    from investsync.schema import Consensus, EstimateRow
    d = tencent()
    d.quote.price = 186.64
    d.consensus = Consensus(currency=d.quote.currency, estimate_currency=d.quote.currency, price_90d_ago=223.71,
                            estimates=[EstimateRow(period="FY2028E", eps_avg=15.91, eps_90d_ago=12.81)])
    t = rerating(d)
    assert "+24.2%" in t and "-16.6%" in t and "17.5x to 11.7x" in t and "de-rating" in t
    d.consensus.estimate_currency = "RMB" if d.quote.currency != "RMB" else "USD"  # EPS in another currency: no
    assert rerating(d) is None


def test_a_share_with_an_h_listing_gets_the_h_price_and_premium(monkeypatch):
    import pandas as pd
    from datetime import datetime, timezone
    from investsync.data import extras
    from investsync.data import sources as src
    from investsync.schema import Market, Profile, Quote, Financials
    from investsync.tickers import parse as tparse
    d = TearSheetData(profile=Profile(ticker="300750.SZ", name="CATL", name_local="宁德时代", market=Market.CN,
                                      exchange="SZSE", trading_currency="CNY", reporting_currency="CNY"),
                      quote=Quote(as_of=TODAY, price=254.22, currency="CNY"), financials=Financials(currency="CNY", years=[]),
                      generated_at=datetime.now(timezone.utc))
    monkeypatch.setattr(src, "ah_names", lambda: {"宁德时代": "03750"})
    monkeypatch.setattr(src, "price_history", lambda m, c: pd.DataFrame({"date": [TODAY], "close": [380.0]}))
    monkeypatch.setattr(src, "fx", lambda a, b, on=None: 0.8532)
    extras.ah_premium(tparse("300750.SZ"), d)
    assert d.quote.h_share == "3750.HK" and d.quote.h_share_price == 380.0
    assert abs(d.quote.h_premium - (380.0 * 0.8532 / 254.22 - 1)) < 1e-9

