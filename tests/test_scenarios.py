"""Scenario valuation: AI assumptions are bounded and run through the model's own DCF in code."""
import json
from pathlib import Path

import pytest

from investsync.narrative import scenarios as sc
from investsync.quant import valuation
from investsync.schema import TearSheetData

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "0700_HK_full.json"


@pytest.fixture
def data():
    d = TearSheetData.model_validate(json.loads(FIX.read_text(encoding="utf-8")))
    if not (d.valuation and d.valuation.dcf and d.valuation.wacc and d.valuation.wacc.wacc):
        pytest.skip("fixture has no DCF")
    return d


def _pick(name, p, g, m):
    return sc.ScenarioPick(name=name, probability=p, revenue_growth=g, fcf_margin=m, drivers=f"{name} (R1)")


def test_growth_after_year_three_halves_towards_terminal(data, monkeypatch):
    seen = {}

    def fake_value(revs, margins, w, g, claims, fx, shares, min_spread, stub, roll, cash_share=None):
        seen.setdefault("all", []).append(revs)  # bear, base, bull in that order; the base keeps its path
        return 1.0, 1.0, 100.0
    monkeypatch.setattr(sc.valuation, "_dcf_value", fake_value)
    s = sc.compute(data, [_pick("bear", 0.25, [0.5, 0.5, 0.5], 0.2), _pick("base", 0.5, [0.5, 0.5, 0.5], 0.2),
                          _pick("bull", 0.25, [0.5, 0.5, 0.5], 0.2)])
    revs, g = seen["all"][1], data.valuation.dcf.terminal_growth
    growth = [revs[i] / revs[i - 1] - 1 for i in range(1, len(revs))]
    assert growth[1] == pytest.approx(0.5) and growth[2] == pytest.approx(g + (0.5 - g) * 0.5)
    assert growth[3] == pytest.approx(g + (0.5 - g) * 0.25)
    assert s.weighted_value == pytest.approx(100.0)


def test_scenarios_are_bounded_ordered_and_weighted(data):
    s = sc.compute(data, [_pick("bull", 2.0, [9.0], 0.95),          # absurd inputs are clipped
                          _pick("base", 1.0, [0.08, 0.07, 0.06], 0.2),
                          _pick("bear", 1.0, [-0.1, 0.0, 0.02], 0.1)])
    names = [x.name for x in s.scenarios]
    vals = [x.value_per_share for x in s.scenarios]
    assert names == ["bear", "base", "bull"] and vals == sorted(vals)
    bull = s.scenarios[-1]
    assert bull.revenue_growth == [sc.GROWTH_BOUNDS[1]] * 3 and bull.fcf_margin == sc.MARGIN_BOUNDS[1]
    assert sum(x.probability for x in s.scenarios) == pytest.approx(1.0, abs=0.01)
    assert s.weighted_value == pytest.approx(sum(x.probability * x.value_per_share for x in s.scenarios))
    assert "Probability-weighted value" in sc.text(s)


def test_incomplete_set_is_rejected(data):
    assert sc.compute(data, [_pick("base", 1.0, [0.1], 0.2)]) is None


def test_rating_can_use_the_scenario_value_in_place_of_the_dcf(data):
    from investsync.quant import rating
    base = rating.compute(data)
    if base is None or not any(m.key == "dcf" for m in base.methods):
        pytest.skip("no DCF in the rating")
    new = rating.compute(data, dcf_override=base.fair_value * 0.5)
    m = next(m for m in new.methods if m.key == "dcf")
    assert m.label.startswith("DCF (analyst scenarios") and m.value == pytest.approx(base.fair_value * 0.5)
    assert rating.compute(data, dcf_override=None).fair_value == pytest.approx(base.fair_value)


def test_analyst_rating_leaves_outlier_cross_checks_out(data, monkeypatch):
    # NVIDIA 9 Nov 2026: TTM EV/EBITDA of fast-growing peers gave USD 460 against our ~USD 205; the house outlier rule
    # (> 50% from the median of the methods) now applies to the cross-checks too
    from investsync.quant import rating
    s = sc.compute(data, [_pick("bear", 0.25, [0.0, 0.0, 0.0], 0.2), _pick("base", 0.5, [0.1, 0.1, 0.1], 0.25),
                          _pick("bull", 0.25, [0.2, 0.2, 0.2], 0.3)])
    data.valuation.scenarios = s
    fv = s.weighted_value
    monkeypatch.setattr(rating, "_method_values",
                        lambda d: {"dcf": fv * 1.02, "peer_pe": fv * 1.3, "peer_ev_ebitda": fv * 2.2})
    rt = rating.from_scenarios(data)
    notes = {m.key: m.note for m in rt.methods if not m.included}
    assert notes["peer_ev_ebitda"].startswith("not used even as a cross-check")
    assert notes["peer_pe"].startswith("cross-check: +30%")
    assert notes["dcf"].startswith("cross-check: +2%")
    assert "peer multiples (median) +30% vs our value" in rt.reason   # the outlier is not in the median


def test_peer_screens_drop_tiny_and_cyclical_extreme_picks():
    from investsync.narrative import peers
    from investsync.schema import CompRow
    rows = [CompRow(ticker=t, name=t, market_cap=cap, currency="USD", pe_ttm=pe, pe_fwd=fwd) for t, cap, pe, fwd in [
        ("AMD", 736e9, 95.9, 25.4), ("AVGO", 1.4e12, 37.5, 15.1), ("TSM", 1.95e12, 24.3, 16.1),
        ("QCOM", 177e9, 13.0, 13.5), ("ALAB", 33e9, 120.0, 60.0), ("MU", 300e9, 3.7, 3.5)]]
    kept, why, dropped = peers.screen(rows, [r.ticker for r in rows], (4.5e12, "USD"), fx=lambda a, b: 1.0)
    assert [r.ticker for r in kept] == ["AMD", "AVGO", "TSM", "QCOM"] and why == ["AMD", "AVGO", "TSM", "QCOM"]
    assert any(d.startswith("ALAB") for d in dropped) and any(d.startswith("MU") for d in dropped)
    # never below three peers
    few, _, _ = peers.screen(rows[3:], ["q", "a", "m"], (4.5e12, "USD"), fx=lambda a, b: 1.0)
    assert len(few) == 3


def test_value_bridge_adds_up_and_flip_points(data):
    """Round-6 review: reconcile our fair value with the model DCF; say how far the rating is from changing."""
    s = sc.compute(data, [_pick("bear", 0.2, [0.0, 0.0, 0.0], 0.2), _pick("base", 0.5, [0.05, 0.05, 0.05], 0.25),
                          _pick("bull", 0.3, [0.2, 0.2, 0.2], 0.3)])
    data.valuation.scenarios = s
    b = sc.bridge(data)
    assert b[0][1] == pytest.approx(data.valuation.dcf.value_per_share)
    assert b[-1][1] == pytest.approx(s.weighted_value)
    assert b[0][1] + sum(x for _, x in b[1:-1]) == pytest.approx(b[-1][1])      # the steps add up
    by = {x.name: x for x in s.scenarios}
    up = by["bull"].value_per_share - by["base"].value_per_share
    down = by["base"].value_per_share - by["bear"].value_per_share
    assert "VALUE BRIDGE" in sc.bridge_text(data)
    # round 9: each rating case names the move away from the CURRENT rating; never "from 25% to 25%"
    for price, now, key, target in [(s.weighted_value / 1.25, "Buy", "bear_for_hold", 1.15),
                                    (s.weighted_value, "Hold", "bull_for_buy", 1.15),
                                    (s.weighted_value, "Hold", "bear_for_sell", 0.90),
                                    (s.weighted_value / 0.85, "Sell", "bull_for_hold", 0.90)]:
        data.quote.price = price
        fp = sc.flip_points(data)
        assert fp["now"] == now
        if fp.get(key) is not None:
            name = "bull" if key.startswith("bull") else "bear"
            step = up if name == "bull" else -down
            moved = s.weighted_value + (fp[key] - by[name].probability) * step
            assert moved == pytest.approx(price * target)
            assert fp[key] > by[name].probability
        t = sc.flip_text(data)
        assert t.startswith(f"it is {now} now")
        import re as _re
        assert not _re.search(r"from (\d+%) to \1", t)


def test_bear_and_bull_stay_in_a_band_in_reported_and_guided_years(data):
    """Round 8: a bear case at +10% against management's ~70% outlook set the rating. In the partly reported year
    and in years management has guided, bear and bull growth stay within a band around the base case."""
    from datetime import date as _d
    from investsync.schema import ResearchBrief, ResearchFact
    fy = data.financials.years[-1].fiscal_year
    data.forecast = None
    data.research = ResearchBrief(facts=[ResearchFact(
        id="R1", topic="guidance", text=f"Management expects revenue growth of about 20% in fiscal {fy + 2}.",
        quote="about 20%", source="Company", title="Results", published=_d(2026, 8, 26))])
    s = sc.compute(data, [_pick("bear", 0.2, [0.10, -0.30, 0.05], 0.30), _pick("base", 0.5, [0.15, 0.20, 0.12], 0.32),
                          _pick("bull", 0.3, [0.20, 0.60, 0.15], 0.34)])
    bear = next(x for x in s.scenarios if x.name == "bear")
    bull = next(x for x in s.scenarios if x.name == "bull")
    # year 2 is guided: base 20%, band +/- max(10%, 10pp) -> 10% .. 30%
    assert abs(bear.revenue_growth[1] - 0.10) < 1e-9 and abs(bull.revenue_growth[1] - 0.30) < 1e-9
    # year 3 is neither reported nor guided: only the global bounds
    assert abs(bear.revenue_growth[2] - 0.05) < 1e-9
    assert "limited" in s.note


def test_bear_is_a_real_downside_and_bull_a_real_upside(data):
    """Round 9: a bear case 5 points of growth and 2.6 points of margin below the base (worth -2% vs the price) was
    called "not a downside scenario". Code keeps bear and bull a minimum distance from the base, set from the
    company's own historical swings; the partly reported current year is left alone."""
    sg, sm = sc.spreads(data)
    assert 0.05 <= sg <= 0.40 and 0.02 <= sm <= 0.10
    s = sc.compute(data, [_pick("bear", 0.2, [0.10, 0.10, 0.10], 0.24), _pick("base", 0.55, [0.10, 0.10, 0.10], 0.25),
                          _pick("bull", 0.25, [0.11, 0.11, 0.11], 0.26)])
    by = {x.name: x for x in s.scenarios}
    base = by["base"]
    for i in range(1, 3):  # later years are not guided in the fixture
        assert by["bear"].revenue_growth[i] <= base.revenue_growth[i] - sg + 1e-9
        assert by["bull"].revenue_growth[i] >= base.revenue_growth[i] + sg / 2 - 1e-9
    assert by["bear"].fcf_margin <= base.fcf_margin - sm + 1e-9
    assert by["bull"].fcf_margin >= base.fcf_margin + sm / 2 - 1e-9
    assert "widened" in s.note
    # a bear case already far enough below is left as the analyst set it
    s2 = sc.compute(data, [_pick("bear", 0.2, [-0.5, -0.5, -0.5], 0.05), _pick("base", 0.55, [0.10, 0.10, 0.10], 0.25),
                           _pick("bull", 0.25, [0.6, 0.6, 0.6], 0.5)])
    assert "widened" not in s2.note
