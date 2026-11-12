"""Run 2 (WP3): the 10-year fading DCF, the reverse DCF that holds the consensus years, and the scenario workings
(paths, fragility). Offline: the fixtures' consensus years are fed back as the estimates table."""
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from investsync.narrative import facts, scenarios
from investsync.quant import rating, sensitivity
from investsync.quant import valuation as V
from investsync.schema import ReverseDCF, TearSheetData, Valuation

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def rebuilt(name: str = "NVDA_deep.json", years: int = 0) -> TearSheetData:
    """The fixture's DCF rebuilt with the configured explicit years (or ``years``), from its own consensus years,
    WACC and terminal growth; its scenarios re-run from the stored assumptions and the rating re-set from them."""
    d = load(name)
    old = d.valuation
    cons = [f for f in old.dcf.forecast if f.basis == "consensus"]
    prev, rows = d.financials.years[-1].revenue, {}
    for key, f in zip(("0y", "+1y"), cons):
        rows[key] = {"avg": f.revenue, "yearAgoRevenue": prev, "currency": d.financials.currency}
        prev = f.revenue
    est = pd.DataFrame.from_dict(rows, orient="index") if rows else None
    n = years or int(V.load_config(d.profile.ticker)["explicit_years"])
    dcf, notes = V.compute_dcf(d, old.wacc.wacc, old.dcf.terminal_growth, n, est, 0.03)
    val = Valuation(currency=d.quote.currency, wacc=old.wacc, dcf=dcf, notes=notes)
    sensitivity.extend(val, d, 0.03)
    d.valuation = val
    if old.scenarios:
        picks = [scenarios.ScenarioPick(name=s.name, probability=s.probability, revenue_growth=s.revenue_growth,
                                        fcf_margin=s.fcf_margin, drivers=s.drivers or "x")
                 for s in old.scenarios.scenarios]
        val.scenarios = scenarios.compute(d, picks)
        d.rating = rating.from_scenarios(d) or d.rating
    return d


@pytest.fixture(scope="module")
def nvda() -> TearSheetData:
    return rebuilt()


# ---------------------------------------------------------------- the 10-year fading DCF
def test_config_uses_ten_explicit_years(nvda):
    assert V.load_config()["explicit_years"] == 10
    dcf = nvda.valuation.dcf
    assert len(dcf.forecast) == 10 and dcf.method.startswith("FCFF, 10-year explicit forecast")
    assert [f.basis for f in dcf.forecast[:2]] == ["consensus", "consensus"]
    assert [f.fiscal_year for f in dcf.forecast] == list(range(dcf.forecast[0].fiscal_year,
                                                               dcf.forecast[0].fiscal_year + 10))


@pytest.mark.parametrize("name", ["NVDA_deep.json", "0700_HK_full.json"])
def test_year_ten_growth_is_near_terminal_growth(name):
    dcf = rebuilt(name).valuation.dcf
    assert abs(dcf.forecast[-1].growth - dcf.terminal_growth) <= 0.01
    fade = [f.growth for f in dcf.forecast if f.basis == "fade"]
    assert fade == sorted(fade, reverse=True)           # the fade only steps down


def test_terminal_share_falls_below_sixty_percent(nvda):
    five = rebuilt(years=5).valuation.dcf
    ten = nvda.valuation.dcf
    assert ten.bridge.terminal_share < 0.60 < five.bridge.terminal_share
    assert ten.value_per_share > five.value_per_share     # the same fade, valued year by year instead of in the TV
    for p in scenarios.paths(nvda):                        # every scenario's year 10 is near terminal growth too
        assert abs(p["revenue_growth"][-1] - ten.terminal_growth) <= 0.01 and p["terminal_share"] < 0.60


# ---------------------------------------------------------------- the reverse DCF
def test_reverse_dcf_holds_the_consensus_years_and_reproduces_the_price(nvda):
    rv, dcf = nvda.valuation.reverse, nvda.valuation.dcf
    assert rv.model == "DCF" and rv.hold_years == 2 and rv.horizon_years == 8
    assert (rv.from_year, rv.to_year) == (dcf.forecast[2].fiscal_year, dcf.forecast[-1].fiscal_year)
    m = sensitivity._DCFModel(nvda.valuation, nvda, 0.03)
    revs = m.revenues(constant=rv.implied_growth, hold=rv.hold_years)
    assert revs[:2] == pytest.approx([f.revenue for f in dcf.forecast[:2]], rel=1e-12)   # consensus years kept
    assert [revs[i] / revs[i - 1] - 1 for i in range(2, 10)] == pytest.approx([rv.implied_growth] * 8)
    assert m.value(revs, m.margin, m.wacc, m.g) == pytest.approx(nvda.quote.price, rel=1e-4)
    model = (dcf.forecast[-1].revenue / dcf.forecast[1].revenue) ** (1 / 8) - 1
    assert rv.model_growth == pytest.approx(model, rel=1e-12)
    # the value is above the price, so the price must need less growth than the model: no contradiction
    assert dcf.value_per_share > nvda.quote.price and rv.implied_growth < rv.model_growth


@pytest.mark.parametrize("basis, hold", [(["fade"] * 10, 0), (["consensus"] * 2 + ["fade"] * 8, 2),
                                         (["consensus"] * 2 + ["fade"] * 2, 0),   # only 2 years left to solve
                                         (["consensus"] * 2 + ["fade"] * 3, 2), (["consensus"] * 10, 0),
                                         (["fade", "consensus"] + ["fade"] * 8, 0), ([], 0)])
def test_held_years_are_the_leading_consensus_years(basis, hold):
    assert sensitivity.reverse_hold(basis) == hold


def test_without_consensus_nothing_is_held():
    d = load("NVDA.json")
    for y in d.financials.years:  # fixture predates capex; give a steady 40% FCF margin
        y.operating_cash_flow, y.capex = 0.5 * y.revenue, 0.1 * y.revenue
    d.valuation = V.build(d, {}, {}, {"US 10Y": 0.042}, None)
    rv = d.valuation.reverse
    assert rv.hold_years == 0 and rv.horizon_years == len(d.valuation.dcf.forecast) == 10
    assert rv.from_year == d.valuation.dcf.forecast[0].fiscal_year
    m = sensitivity._DCFModel(d.valuation, d, 0.03)
    assert m.value(m.revenues(constant=rv.implied_growth), m.margin, m.wacc, m.g) == pytest.approx(d.quote.price,
                                                                                                    rel=1e-4)


def test_banks_keep_their_dividend_discount_model():
    d = load("0005_HK.json")
    val = V.build(d, {}, {}, {"US 10Y": 0.042}, None)
    if not (val and val.ddm):
        pytest.skip("DDM not applicable to fixture")
    assert val.dcf is None and val.reverse.model == "DDM"
    assert val.reverse.hold_years == 0 and val.reverse.from_year is None and val.reverse.horizon_years == 0
    d.valuation = val
    assert facts.base_scenario_cagr(d) is None and facts.implied_vs_base(d) == ""


def test_base_scenario_growth_runs_over_the_same_years(nvda):
    rv, base = nvda.valuation.reverse, next(s for s in nvda.valuation.scenarios.scenarios if s.name == "base")
    got, n = facts.base_scenario_cagr(nvda)
    assert n == rv.horizon_years == 8
    want = next(p for p in scenarios.paths(nvda) if p["name"] == "base")
    assert want["revenue_growth"][:3] == pytest.approx(base.revenue_growth)
    assert got == pytest.approx((want["revenue"][-1] / want["revenue"][1]) ** (1 / 8) - 1, rel=1e-12)
    txt = facts.implied_vs_base(nvda)
    assert (f"after the 2 consensus years, the price needs revenue growth of {rv.implied_growth:.1%} a year from "
            f"FY{rv.from_year} to FY{rv.to_year}") in txt
    assert f"our base case grows {got:.1%} a year over those years" in txt


def test_reports_saved_before_run_two_keep_the_old_wording():
    """No hold_years in the JSON (or a test double without it): the whole horizon, as before."""
    rv = NS(model="DCF", implied_growth=0.30, horizon_years=5)
    base = NS(name="base", revenue_growth=[0.45, 0.40, 0.38])
    data = NS(valuation=NS(reverse=rv, scenarios=NS(scenarios=[base]), dcf=NS(terminal_growth=0.03)))
    ours, n = facts.base_scenario_cagr(data)
    assert n == 5 and "for 5 years at the model's margins" in facts.implied_vs_base(data)
    assert ReverseDCF(model="DCF", horizon_years=5).hold_years == 0


def test_evidence_and_datapack_name_the_solved_years(nvda):
    from investsync.narrative import evidence
    rv = nvda.valuation.reverse
    got, _ = facts.base_scenario_cagr(nvda)
    row = next(x for x in evidence.signals(nvda) if x.label.startswith("Growth the price implies"))
    assert row.label == (f"Growth the price implies after the 2 consensus years (from FY{rv.from_year} to "
                         f"FY{rv.to_year}) vs our base scenario")
    assert row.value.startswith(f"+{rv.implied_growth * 100:.1f}% a year vs +{got * 100:.1f}%")
    from investsync.data import company_docs
    from investsync.render import html_pdf
    from tests.test_datapack import unpack
    mp = pytest.MonkeyPatch()
    mp.setattr(company_docs, "shareholder_documents", lambda data: [])
    mp.setattr(html_pdf, "browser", lambda: None)
    try:
        _, wb = unpack(nvda)
    finally:
        mp.undo()
    labels = [r[0] for r in wb["Valuation"].iter_rows(values_only=True) if isinstance(r[0], str)]
    span = f"FY{rv.from_year} to FY{rv.to_year}"
    assert f"Reverse DCF: what today's price implies (after the 2 consensus years, {span})" in labels
    assert f"Implied revenue growth (constant, per year, {span})" in labels
    assert f"Model DCF revenue growth (CAGR, {span})" in labels


# ---------------------------------------------------------------- scenario workings
def test_paths_values_equal_the_scenario_values(nvda):
    sc = nvda.valuation.scenarios
    ps = scenarios.paths(nvda)
    assert [p["name"] for p in ps] == [s.name for s in sc.scenarios] == ["bear", "base", "bull"]
    for p, s in zip(ps, sc.scenarios):
        assert p["value_per_share"] == pytest.approx(s.value_per_share, rel=1e-12)
        assert p["probability"] == s.probability and p["fcf_margin"] == s.fcf_margin
        assert len(p["revenue_growth"]) == len(p["years"]) == len(p["margins"]) == 10
        assert p["pv_explicit"] + p["pv_terminal"] == pytest.approx(p["enterprise_value"])
        assert p["terminal_share"] == pytest.approx(p["pv_terminal"] / p["enterprise_value"])
        b = nvda.valuation.dcf.bridge
        claims = b.net_debt + (b.minority_interest or 0) - (b.investments or 0)
        assert (p["enterprise_value"] - claims) / b.fx_to_reporting / b.shares == pytest.approx(s.value_per_share)


def test_paths_and_fragility_are_empty_without_scenarios():
    d = load("0700_HK_full.json")
    assert scenarios.paths(d) == [] and scenarios.fragility(d) is None


def test_fragility_cell_at_todays_weights_is_the_fair_value(nvda):
    f = scenarios.fragility(nvda)
    sc = nvda.valuation.scenarios
    by = {s.name: s for s in sc.scenarios}
    assert f["bear"] == pytest.approx([0.15, 0.20, 0.25, 0.30, 0.35, 0.40])
    assert f["bull"] == pytest.approx([0.10, 0.15, 0.20, 0.25, 0.30])
    assert len(f["cells"]) == 6 and all(len(r) == 5 for r in f["cells"])
    i, j = f["current"]
    assert (f["bear"][i], f["bull"][j]) == pytest.approx((by["bear"].probability, by["bull"].probability))
    c = f["cells"][i][j]
    assert c["value"] == pytest.approx(sc.weighted_value, rel=1e-9)
    assert c["rating"] == nvda.rating.rating
    for pb, row in zip(f["bear"], f["cells"]):
        for pu, cell in zip(f["bull"], row):
            want = pb * by["bear"].value_per_share + pu * by["bull"].value_per_share \
                + (1 - pb - pu) * by["base"].value_per_share
            assert cell["value"] == pytest.approx(want)
            up = want / nvda.quote.price - 1
            assert cell["rating"] == ("Buy" if up >= 0.15 else "Sell" if up <= -0.10 else "Hold")
    # more weight on the bear case never raises the value
    assert all(f["cells"][k][j]["value"] > f["cells"][k + 1][j]["value"] for k in range(5))


def test_fragility_current_is_none_off_the_grid(nvda):
    d = nvda.model_copy(deep=True)
    for s in d.valuation.scenarios.scenarios:
        s.probability = {"bear": 0.18, "base": 0.57, "bull": 0.25}[s.name]
    assert scenarios.fragility(d)["current"] is None


def test_scenario_prompt_asks_for_a_probability_sentence_and_the_note_names_our_analyst_step(nvda):
    assert "starts 'Probability:'" in scenarios.SetScenarios.__doc__
    assert "'Probability:'" in scenarios.ScenarioPick.model_fields["drivers"].description
    assert nvda.valuation.scenarios.note.startswith("Assumptions set by our analyst step from the research notes")


def test_model_sheet_reproduces_the_ten_year_dcf_and_scenarios(nvda, monkeypatch):
    from investsync.data import company_docs
    from investsync.render import html_pdf
    from tests.test_datapack import MODEL, XL, cell, grid, unpack
    monkeypatch.setattr(company_docs, "shareholder_documents", lambda data: [])
    monkeypatch.setattr(html_pdf, "browser", lambda: None)
    _, wb = unpack(nvda)
    ws = wb[MODEL]
    xl = XL(ws)
    dcf = nvda.valuation.dcf
    assert xl(cell(ws, "= Value per share (USD)").coordinate) == pytest.approx(dcf.value_per_share, rel=1e-9)
    assert grid(ws, xl, "WACC (down)")[2][2] == pytest.approx(dcf.value_per_share, rel=1e-9)
    counted = [xl(cell(ws, "Cash flow counted", 2 + i).coordinate) for i in range(10)]
    assert counted == pytest.approx([f.free_cash_flow / 1e6 for f in dcf.forecast])
    for s in nvda.valuation.scenarios.scenarios:
        assert xl(cell(ws, s.name.title(), 7).coordinate) == pytest.approx(s.value_per_share, rel=1e-9)
    wv = cell(ws, "= Probability-weighted value (USD)").coordinate
    assert xl(wv) == pytest.approx(nvda.valuation.scenarios.weighted_value, rel=1e-9)


def test_report_exhibits_read_paths_and_fragility(nvda):
    """WP4's deep-only exhibits read these two functions; the shapes must match."""
    from investsync.render import report_vm as RV
    model, flips = getattr(RV, "_scenario_model", None), getattr(RV, "_flip_grid", None)
    if model is None or flips is None:
        pytest.skip("report exhibits not present")
    m = model(nvda)
    assert m and len(m["summary"]) == 3 and all(len(r["values"]) == 10 for r in m["growth"])
    assert m["years"][0] == f"FY{nvda.valuation.dcf.forecast[0].fiscal_year}E"
    assert [r[6] for r in m["summary"]] == [f"USD {s.value_per_share:,.2f}" for s in nvda.valuation.scenarios.scenarios]
    f = flips(nvda)
    assert f and sum(c["current"] for r in f["rows"] for c in r["cells"]) == 1
