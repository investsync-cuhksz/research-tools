"""House forecast: the AI sets drivers; code builds revenue, profit and EPS, compares with consensus, and checks
what the first year implies for the months not yet reported."""
import json
from datetime import date
from pathlib import Path

import pytest
from dspy.utils import DummyLM

from investsync.narrative import forecast as fc
from investsync.narrative import scenarios as sc
from investsync.narrative.commentary import ADAPTER
from investsync.schema import EstimateRow, InterimPeriod, TearSheetData

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "0700_HK_full.json"


@pytest.fixture
def data():
    d = TearSheetData.model_validate(json.loads(FIX.read_text(encoding="utf-8")))
    fy = d.financials.years[-1]
    if not (fy.revenue and fy.operating_income is not None and fy.net_income is not None and fy.diluted_eps):
        pytest.skip("fixture lacks a full income statement")
    return d


def _notes(*rows):
    from investsync.schema import ResearchBrief, ResearchFact
    return ResearchBrief(questions=[], facts=[ResearchFact(id=i, topic=t, text=txt, quote=txt, source="s", title="t")
                                              for i, t, txt in rows], gaps=[], docs_read=1, chunks_read=1,
                         facts_dropped=0, method="m")


def _y(g, gm=0.55, opm=0.33, tax=0.18, sc_=0.0, period="FY"):
    return fc.YearDrivers(period=period, revenue_growth=g, gross_margin=gm, operating_margin=opm, tax_rate=tax,
                          share_change=sc_)


def test_pnl_is_built_in_code_and_bounded(data):
    fy = data.financials.years[-1]
    f = fc.compute(data, [_y(0.10), _y(0.08, opm=0.90), _y(9.0, sc_=-0.5)])
    y1, y2, y3 = f.years
    assert y1.period == f"FY{fy.fiscal_year + 1}E" and y1.revenue == pytest.approx(fy.revenue * 1.10)
    assert y1.operating_income == pytest.approx(y1.revenue * 0.33)
    assert y2.operating_margin <= 0.55 + 1e-9  # operating margin cannot exceed the gross margin
    assert y3.revenue_growth == fc.GROWTH[1]  # growth bounded
    shares0 = fy.net_income / fy.diluted_eps
    assert y3.eps == pytest.approx(y3.net_income / (shares0 * (1 + fc.SHARES[0])))
    assert y1.eps_growth == pytest.approx(y1.eps / fy.diluted_eps - 1)


def test_consensus_gap_and_adjusted_eps_note(data):
    fy = data.financials.years[-1]
    data.consensus.estimate_currency = data.financials.currency
    # consensus EPS growth implies a base 20% above reported EPS: an adjusted (non-IFRS) figure
    data.consensus.estimates = [EstimateRow(period=f"FY{fy.fiscal_year + 1}E", revenue_avg=fy.revenue * 1.10,
                                            eps_avg=fy.diluted_eps * 1.2 * 1.05, eps_growth=0.05)]
    f = fc.compute(data, [_y(0.12), _y(0.08), _y(0.07)])
    assert f.years[0].revenue_vs_consensus == pytest.approx(1.12 / 1.10 - 1)
    assert f.consensus_note and "adjusted" in f.consensus_note
    t = fc.text(f)
    assert "ours +1.8% vs consensus" in t and "EPS growth" in t and "vs consensus\n" not in t


def test_remainder_of_the_year_is_checked(data):
    fy = data.financials.years[-1]
    data.financials.latest = InterimPeriod(label=f"9M {fy.fiscal_year + 1}", months=9, period_end=date(fy.fiscal_year + 1, 9, 30), revenue=fy.revenue * 0.9,
                                           prior_revenue=fy.revenue * 0.7)
    low = [_y(0.05), _y(0.08), _y(0.07)]  # FY +5% while 9M is already +28.6%: Q4 would have to collapse
    probs = fc._problems(data, low)
    assert probs and "far from the trend" in probs[0]
    below = [_y(-0.2), _y(0.08), _y(0.07)]  # below what is already reported
    assert "below what is already reported" in fc._problems(data, below)[0]
    ok = [_y(0.286), _y(0.08), _y(0.07)]
    assert fc._problems(data, ok) == []
    assert "fourth quarter" in fc.compute(data, ok).remainder


def test_run_retries_once_with_the_code_feedback(data):
    fy = data.financials.years[-1]
    data.financials.latest = InterimPeriod(label="9M", months=9, period_end=date(fy.fiscal_year + 1, 9, 30), revenue=fy.revenue * 0.9, prior_revenue=fy.revenue * 0.7)
    out = lambda g: {"years": json.dumps([_y(g).model_dump(), _y(0.08).model_dump(), _y(0.07).model_dump()]),
                     "revenue_drivers": "Games (R1).", "margin_drivers": "Mix (R2).",
                     "vs_consensus": "In line (R3).", "key_risk": "Ads (R4)."}
    data.research = _notes(("R1", "results", "x"), ("R2", "results", "x"), ("R3", "results", "x"),
                           ("R4", "street", "x"))
    lm = DummyLM([out(-0.2), out(0.29)])
    f = fc.run(data, "R1 ...", lm, ADAPTER)
    assert f.years[0].revenue_growth == pytest.approx(0.29) and f.vs_consensus == "In line (R3)."
    assert "below what is already reported" in lm.history[-1]["messages"][-1]["content"]


def test_base_scenario_uses_the_house_revenue_path(data, monkeypatch):
    if not (data.valuation and data.valuation.dcf and data.valuation.wacc and data.valuation.wacc.wacc):
        pytest.skip("fixture has no DCF")
    data.forecast = fc.compute(data, [_y(0.11), _y(0.09), _y(0.07)])
    pick = lambda n, g: sc.ScenarioPick(name=n, probability=1 / 3, revenue_growth=g, fcf_margin=0.2, drivers=n)
    s = sc.compute(data, [pick("bear", [0.0] * 3), pick("base", [0.5] * 3), pick("bull", [0.2] * 3)])
    base = [x for x in s.scenarios if x.revenue_growth == pytest.approx([0.11, 0.09, 0.07])]
    assert base, [x.revenue_growth for x in s.scenarios]
    assert "house forecast" in sc.model_base_text(data)


def test_rest_of_year_is_compared_with_consensus_for_the_same_quarters():
    """Results preview: the forecast's implied second half vs the Street's next two quarters (same currency)."""
    from datetime import date
    from investsync.schema import Consensus, EstimateRow, FiscalYear, Financials, InterimPeriod, TearSheetData
    from investsync.narrative import forecast as fc
    from pathlib import Path
    d = TearSheetData.model_validate_json(
        (Path(__file__).resolve().parent.parent / "fixtures" / "0700_HK_full.json").read_text(encoding="utf-8"))
    fy = d.financials.years[-1].model_copy(update={"revenue": 200e9})
    d.financials = d.financials.model_copy(update={"years": d.financials.years[:-1] + [fy], "latest": InterimPeriod(
        period_end=date(2026, 7, 26), months=6, label="1H FY2027", revenue=180e9, prior_revenue=90e9,
        quarter_label="Q2 FY2027")})
    d.consensus = Consensus(currency=d.financials.currency, estimate_currency=d.financials.currency, quarters=[
        EstimateRow(period="Q3 FY2027E", revenue_avg=110e9), EstimateRow(period="Q4 FY2027E", revenue_avg=120e9)])
    t = fc._remainder_text(d, 412e9)
    assert "232,000mn for the second half" in t and "Q3 FY2027E + Q4 FY2027E" in t and "230,000mn" in t
    assert "+0.9% versus the Street" in t
    d.consensus.quarters = d.consensus.quarters[:1]  # one quarter cannot stand for a half year
    assert "versus the Street" not in fc._remainder_text(d, 412e9)


def _with_consensus(data, growth=0.10):
    fy = data.financials.years[-1]
    rows = [EstimateRow(period=f"FY{fy.fiscal_year + i}E", revenue_avg=fy.revenue * (1 + growth) ** i,
                        revenue_growth=growth) for i in (1, 2)]
    data.consensus.estimates = rows
    data.consensus.estimate_currency = data.financials.currency
    data.financials.latest = None
    return fy


def test_a_departure_from_consensus_needs_a_cited_note_else_it_is_pulled_back(data):
    """Round-6 review (material): FY2028 revenue 12% below consensus with no cited source and an invented reason."""
    if data.consensus is None:
        pytest.skip("fixture has no consensus block")
    fy = _with_consensus(data)
    data.research = _notes(("R1", "results", "Orders fell."))
    out = {"years": json.dumps([_y(0.10).model_dump(), _y(-0.05).model_dump(), _y(0.05).model_dump()]),
           "revenue_drivers": "Demand slows.", "margin_drivers": "Mix.", "vs_consensus": "Consensus extrapolates.",
           "key_risk": "Ads."}
    lm = DummyLM([out, out])
    f = fc.run(data, "[R1] Orders fell.", lm, ADAPTER)
    assert "needs evidence" in lm.history[-1]["messages"][-1]["content"]          # retried with the rule
    y2 = f.years[1]
    assert y2.revenue_vs_consensus == pytest.approx(-fc.DEV_FREE)                   # then pulled to the band edge
    assert "pulled to within 5% of consensus" in f.vs_consensus
    # with a cited note the analyst may differ
    cited = dict(out, vs_consensus="Below consensus because orders fell [R1].")
    f2 = fc.run(data, "[R1] Orders fell.", DummyLM([cited]), ADAPTER)
    assert f2.years[1].revenue_vs_consensus < -0.10 and "R1" in f2.vs_consensus


def test_management_outlook_for_the_year_must_be_cited(data):
    if data.consensus is None:
        pytest.skip("fixture has no consensus block")
    fy = _with_consensus(data)
    y2 = fy.fiscal_year + 2
    data.research = _notes(("R1", "competition", "A rival launched."),
                           ("R2", "guidance", f"Management expects fiscal {y2} revenue growth of about 10%."))
    f = fc.compute(data, [_y(0.10), _y(-0.05), _y(0.05)])
    f.vs_consensus = "A rival launched [R1]."
    probs = fc.evidence_problems(data, f)
    assert probs and "R2" in probs[0] and "start from it" in probs[0]
    f.vs_consensus = "Below management's outlook [R2] because a rival launched [R1]."
    assert fc.evidence_problems(data, f) == []


def test_large_below_the_line_income_is_flagged(data):
    from investsync.narrative.facts import below_the_line_note
    fy = data.financials.years[-1]
    data.financials.latest = InterimPeriod(label="1H", months=6, period_end=date(fy.fiscal_year + 1, 6, 30),
                                           revenue=100.0, operating_income=50.0, net_income=52.0,
                                           prior_operating_income=25.0, prior_net_income=20.0)
    note = below_the_line_note(data)
    assert "104% of operating profit" in note and "operating profit grew +100.0%" in note
    data.financials.latest.net_income = 40.0
    assert below_the_line_note(data) == ""          # a normal tax gap: nothing to flag


def test_margin_and_tax_guidance_notes_must_be_cited(data):
    """Round-7 review: margins and tax set against management's guidance (Q4 trough 71-72%, tax 16-18%)."""
    data.research = _notes(("R1", "guidance", "Management expects gross margins to bottom in Q4 at 71% to 72%."),
                           ("R2", "guidance", "The tax rate is expected to be 16% to 18%."),
                           ("R3", "guidance", "Revenue is expected to be $108.0 billion."))
    f = fc.compute(data, [_y(0.10), _y(0.08), _y(0.07)])
    f.margin_drivers = "Gross margin holds at 75% [R3]."
    probs = fc.margin_problems(data, f)
    assert probs and "R1, R2" in probs[0]
    f.margin_drivers = "Gross margin dips to the guided Q4 trough [R1]; tax at the guided range [R2]."
    assert fc.margin_problems(data, f) == []


def test_cash_conversion_uses_the_latest_period(data):
    from investsync.narrative.facts import latest_cash_conversion
    fy = data.financials.years[-1]
    data.financials.latest = InterimPeriod(label="1H", months=6, period_end=date(fy.fiscal_year + 1, 6, 30),
                                           revenue=100.0, net_income=50.0, operating_cash_flow=30.0,
                                           prior_net_income=40.0, prior_operating_cash_flow=38.0)
    txt = latest_cash_conversion(data)
    assert txt.startswith("1H operating cash flow / net profit 0.60x") and "0.95x" in txt


def test_a_small_gap_between_implied_and_base_growth_is_no_variant_view():
    """Round 8: a 1pp gap between the price's implied growth and our base case was headlined as the variant view."""
    from types import SimpleNamespace as NS
    from investsync.narrative import facts as F
    rv = NS(model="DCF", implied_growth=0.402, horizon_years=5)
    base = NS(name="base", revenue_growth=[0.45, 0.40, 0.38])
    data = NS(valuation=NS(reverse=rv, scenarios=NS(scenarios=[base]), dcf=NS(terminal_growth=0.03)))
    ours, _ = F.base_scenario_cagr(data)
    rv.implied_growth = ours + 0.01
    txt = F.implied_vs_base(data)
    assert "NOT a variant view" in txt and "gap" in txt
    rv.implied_growth = ours - 0.08
    assert "LESS growth than our base case" in F.implied_vs_base(data)
