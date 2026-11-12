"""Run 2 (WP5): the learner's guide prints the scenario set's own figures and its exercises ask a "what if" computed
in code instead of repeating the worked example."""
import re
from pathlib import Path

import pytest

from investsync.narrative import facts, learner
from investsync.quant import rating
from investsync.render import learner_vm
from investsync.schema import StreetView, TearSheetData

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def with_scenarios(bear_p: float, bull_p: float = 0.20, values=(77.97, 200.97, 307.60)) -> TearSheetData:
    """NVDA fixture with run 1's scenario values, the given weights and the rating re-set from them."""
    d = load("NVDA_deep.json")
    sc = d.valuation.scenarios
    probs = {"bear": bear_p, "base": round(1 - bear_p - bull_p, 3), "bull": bull_p}
    for s, v in zip(sc.scenarios, values):
        s.value_per_share, s.probability = v, probs[s.name]
    sc.weighted_value = sum(s.probability * s.value_per_share for s in sc.scenarios)
    d.rating = rating.from_scenarios(d)
    return d


def exercise(g: dict, start: str) -> dict:
    return next(e for e in g["exercises"] if e["q"].startswith(start))


def row(g: dict, step: str, start: str) -> dict:
    s = next(s for s in g["steps"] if s["key"] == step)
    return next(r for r in s["rows"] if r["label"].startswith(start))


# ---------------------------------------------------------------- item 1: the bear case's own probability
@pytest.mark.parametrize("bear_p, shown", [(0.25, True), (0.15, False)])
def test_working_prints_the_bear_probability_only_when_it_pulls_most(bear_p, shown):
    d = with_scenarios(bear_p)
    e = exercise(learner_vm.build(d), "What if we were less sure of the base case?")
    text = " ".join(e["working"])
    assert "28%" not in text
    printed = {int(x) for x in re.findall(r"(?<![\d.,])(\d{1,2})%\s+bear\b", text)}
    assert printed == ({round(bear_p * 100)} if shown else set())
    assert ("biggest pull on the value" in text) is shown


# ---------------------------------------------------------------- item 4: the "what if" answers, recomputed
def test_weights_what_if_moves_ten_points_to_the_bear_case_and_reapplies_the_rule():
    d = with_scenarios(0.25)
    g = learner_vm.build(d)
    e = exercise(g, "What if we were less sure of the base case?")
    by = {s.name: s for s in d.valuation.scenarios.scenarios}
    want = 0.35 * by["bear"].value_per_share + 0.45 * by["base"].value_per_share + 0.20 * by["bull"].value_per_share
    up = want / d.quote.price - 1
    rt = d.rating
    new = "Buy" if up >= rt.buy_threshold else ("Sell" if up <= rt.sell_threshold else "Hold")
    assert e["answer"].startswith(f"USD {want:,.2f} ({up * 100:+.1f}% vs the price) → {new}")
    assert ("(no change)" in e["answer"]) is (new == rt.rating)
    assert "bear 35%, base 45%, bull 20%" in e["working"][0]
    # the exercise no longer repeats the worked example (today's weighted value)
    worth = next(s for s in g["steps"] if s["key"] == "worth")
    assert e["answer"] not in " ".join(worth["worked"]["lines"]) and f"{rt.fair_value:,.2f}" not in e["answer"]


def test_weights_what_if_says_when_the_rating_changes():
    d = with_scenarios(0.15, values=(77.20, 211.61, 335.19))   # today Buy; 10 points more bear case -> Hold
    e = exercise(learner_vm.build(d), "What if we were less sure of the base case?")
    assert d.rating.rating == "Buy" and "→ Hold (changes from Buy)" in e["answer"]


def test_weights_what_if_is_omitted_without_enough_base_weight():
    d = with_scenarios(0.45, bull_p=0.50)                      # base case at 5%: nothing to move
    assert not [e for e in learner_vm.build(d)["exercises"] if e["q"].startswith("What if we were less sure")]


def test_pe_what_if_is_the_price_at_the_five_year_median():
    d = load("0700_HK_full.json")
    b, p = d.pe_band, d.quote.price
    e = exercise(learner_vm.build(d), "Today's P/E on the last fiscal year's EPS")
    want = b.median * p / b.current
    assert e["answer"].startswith(f"HKD {want:,.2f} ({(want / p - 1) * 100:+.1f}% vs today's {p:,.2f})")
    assert "cheaper or dearer than its peers" not in " ".join(x["q"] for x in learner_vm.build(d)["exercises"])


def test_margin_what_if_uses_the_median_of_the_three_years_before():
    d = load("NVDA_deep.json")
    g = learner_vm.build(d)
    e = exercise(g, "What if FY")
    r = sorted(d.ratios, key=lambda x: x.fiscal_year)
    pts = [(x.fiscal_year, x.net_margin) for x in r if x.net_margin is not None]
    (fy, m), prior = pts[-1], pts[-4:-1]
    med = round(sorted(x for _, x in prior)[1], 4)
    rev = next(y.revenue for y in d.financials.years if y.fiscal_year == fy)
    du = d.dupont
    want_roe = du.roe * med / du.net_margin
    assert e["answer"] == (f"USD {rev * med / 1e6:,.0f}mn ({(med / m - 1) * 100:+.1f}%); "
                           f"ROE about {want_roe * 100:.1f}%")
    assert f"FY{prior[0][0]}–FY{prior[-1][0]}" in e["q"]
    assert not [x for x in g["exercises"] if x["q"].startswith("Multiply the three DuPont parts")]


def test_what_ifs_are_omitted_when_inputs_are_missing():
    d = load("NVDA_deep.json")
    d.pe_band = None
    d.ratios = d.ratios[-3:]                                      # three years: no "three years before"
    d.valuation.scenarios = None
    d.rating.basis = None
    qs = [e["q"] for e in learner_vm.build(d)["exercises"]]
    assert not [q for q in qs if q.startswith(("What if", "Today's P/E on the last"))]
    assert all(e["answer"] and e["working"] for e in learner_vm.build(d)["exercises"])


# ---------------------------------------------------------------- item 2: the growth the price assumes
def test_reverse_row_compares_with_our_base_case_when_the_rating_follows_scenarios():
    d = with_scenarios(0.25)
    rv = d.valuation.reverse
    got = facts.base_scenario_cagr(d)
    r = row(learner_vm.build(d), "worth", "Growth the price assumes")
    assert r["note"] == f"vs {got[0] * 100:+.1f}% in our base case"
    assert f"{rv.model_growth * 100:+.1f}%" not in r["note"] or abs(rv.model_growth - got[0]) < 0.0005
    # rating not set from the scenarios: the model DCF's own growth, called that
    d.rating.basis = None
    r = row(learner_vm.build(d), "worth", "Growth the price assumes")
    assert r["note"] == f"vs {rv.model_growth * 100:+.1f}% in the model DCF"
    assert row(learner_vm.build(d), "worth", "DCF base case")


def test_reverse_row_names_the_solved_years_when_consensus_years_are_held():
    from tests.test_run2_valuation import rebuilt
    d = rebuilt()
    rv = d.valuation.reverse
    assert rv.hold_years == 2
    r = row(learner_vm.build(d), "worth", "Growth the price assumes")
    got = facts.base_scenario_cagr(d)[0]
    assert r["label"] == "Growth the price assumes after the 2 consensus years (reverse DCF)"
    assert r["value"] == f"{rv.implied_growth * 100:+.1f}% a year, FY{rv.from_year}–FY{rv.to_year}"
    assert r["note"] == f"vs {got * 100:+.1f}% in our base case over the same years"
    assert row(learner_vm.build(d), "worth", "Model DCF (cross-check, not in the rating)")


def test_bank_reverse_row_is_the_dividend_model():
    from investsync.quant import valuation as V
    d = load("0005_HK.json")
    d.valuation = V.build(d, {}, {}, {"US 10Y": 0.042}, None)
    if not (d.valuation and d.valuation.reverse and d.valuation.reverse.model == "DDM"):
        pytest.skip("DDM not applicable to fixture")
    r = row(learner_vm.build(d), "worth", "Dividend growth the price assumes (reverse DDM)")
    assert r["note"].endswith("in the model DDM")


# ---------------------------------------------------------------- item 3: two different counts, two labels
def test_brokers_with_a_dated_view_and_the_consensus_count():
    d = load("NVDA_deep.json")
    d.street = StreetView(source="test", market=d.profile.market, window_days=180, brokers=31,
                          rating_counts={"Buy": 17, "Outperform": 13, "Hold": 1})
    d.consensus.analysts = 57
    g = learner_vm.build(d)
    assert row(g, "others", "Brokers with a dated view (last 180 days)")["value"] == "31"
    assert row(g, "others", "Analysts in Yahoo's consensus")["value"] == "57"
    assert not [r for s in g["steps"] for r in s["rows"] if r["label"] == "Brokers covering"]
    d.street, d.consensus.analysts = None, None
    labels = [r["label"] for s in learner_vm.build(d)["steps"] for r in s["rows"]]
    assert not [x for x in labels if x.startswith(("Brokers with", "Analysts in"))]


# ---------------------------------------------------------------- item 5 and rendering
def test_coach_prompt_asks_for_specifics_a_question_and_neutral_governance():
    doc = " ".join(learner.LearnerCoach.__doc__.split())
    assert "name something specific to this business" in doc and "end with one question" in doc
    assert "Personal matters of executives are not teaching material" in doc


@pytest.mark.parametrize("name", ["0700_HK_full.json", "0005_HK.json"])
def test_guide_without_scenarios_renders(name):
    from investsync.render.render import render_pdf
    d = load(name)
    assert not (d.valuation and d.valuation.scenarios)
    g = learner_vm.build(d)
    assert all(e["answer"] and e["working"] for e in g["exercises"])
    pdf = render_pdf(d, layout="learner")
    assert pdf[:4] == b"%PDF" and len(pdf) > 10_000
