"""Learner's guide visuals: life-cycle phase rules, region-name mapping, scale levels, and the guide still renders."""
from pathlib import Path

import pytest

from investsync.render import learner_visuals as lv
from investsync.render.render import render_pdf
from investsync.schema import TearSheetData
from tests.test_street import _pages, _text

ROOT = Path(__file__).resolve().parent.parent
NVDA_AI = ROOT / "fixtures" / "runs" / "dev_v7_NVDA_simple.json"


def _load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def _company(revenue, op, ni=None, div=None, bb=None) -> TearSheetData:
    """A hand-made five-year company on the NVDA fixture's skeleton (no interim period, no peers)."""
    d = _load("NVDA.json").model_copy(deep=True)
    d.financials.latest = None
    d.financials.ttm = None
    d.dividends = []
    for i, y in enumerate(d.financials.years):
        y.revenue, y.operating_income = revenue[i], op[i]
        y.net_income = (ni or op)[i]
        y.dividends_paid = div[i] if div else 0.0
        y.buybacks = bb[i] if bb else 0.0
    return d


def _phase(d: TearSheetData, bank: bool = False) -> dict:
    ph = lv.life_cycle(d, bank)
    assert ph is not None
    return ph


# ---------------------------------------------------------------------------------------------- phase rules
def test_phase_1_startup_losses_growing():
    ph = _phase(_company([10, 20, 30, 45, 60], [-5, -8, -12, -18, -25]))
    assert ph["n"] == 1 and ph["alt"] is None
    assert [q["a"] for q in ph["questions"]] == ["yes", "no", "no"]
    assert "P/E is meaningless" in ph["measure"]


def test_phase_2_fast_growth_losses_shrinking():
    ph = _phase(_company([10, 20, 35, 55, 80], [-30, -25, -18, -10, -4]))
    assert ph["n"] == 2 and ph["alt"] is None and "price-to-sales" in ph["measure"]


def test_phase_3_profitable_fast_growth_keeps_most_profit():
    ph = _phase(_company([100, 130, 170, 220, 290], [10, 20, 35, 55, 80], div=[0, 0, 1, 2, 3], bb=[0, 0, 0, 5, 10]))
    assert ph["n"] == 3 and ph["alt"] is None and "P/E becomes useful" in ph["measure"]


def test_phase_3_just_past_breakeven():
    ph = _phase(_company([100, 103, 105, 106, 108], [-10, -5, -1, 2, 6]))
    assert ph["n"] == 3 and any("recently" in n for n in ph["notes"])


def test_phase_4_slow_growth_big_payouts():
    ph = _phase(_company([100, 103, 106, 109, 112], [30, 31, 32, 33, 34], div=[10, 11, 12, 13, 14],
                         bb=[5, 6, 8, 10, 12]))
    assert ph["n"] == 4 and ph["alt"] is None and "dividend" in ph["measure"]
    assert ph["questions"][2]["a"] == "yes" and "of net profit" in ph["questions"][2]["fig"]


def test_phase_5_revenue_shrinking():
    ph = _phase(_company([100, 95, 90, 85, 80], [20, 18, 15, 12, 10], div=[5] * 5))
    assert ph["n"] == 5 and ph["questions"][0]["a"] == "no" and "P/B" in ph["measure"]


def test_phase_borderline_recent_growth_on_the_other_side_of_the_line():
    # multi-year revenue growth ~7% a year but +14% last year, and 60%+ of profit paid out: phase 4, borderline 3
    ph = _phase(_company([100, 101, 108, 115, 131], [30, 30, 32, 34, 40], div=[8, 8, 9, 10, 11],
                         bb=[5, 8, 10, 12, 14]))
    assert ph["n"] == 4 and ph["alt"] == 3
    assert any("different sides" in n for n in ph["notes"])


def test_phase_bank_uses_net_profit_and_says_the_diagram_fits_less_well():
    d = _load("0005_HK.json")
    ph = _phase(d, bank=True)
    assert ph["profit_label"] == "net profit" and ph["n"] == 4
    assert any("fits them less well" in n for n in ph["notes"]) and "P/B" in ph["measure"]


def test_phase_needs_data():
    d = _company([100] * 5, [10] * 5)
    for y in d.financials.years:
        y.revenue = None
    assert lv.life_cycle(d, False) is None


# ---------------------------------------------------------------------------------------------- regions
@pytest.mark.parametrize("name,expected", [
    ("United States", {"USA"}), ("U.S.", {"USA"}), ("Taiwan", {"TWN"}), ("Japan", {"JPN"}),
    ("China (including Hong Kong)", {"CHN", "HKG"}), ("Mainland China & Hong Kong", {"CHN", "HKG"}),
    ("Mainland China", {"CHN"}), ("境内", {"CHN"}), ("香港", {"HKG"}), ("United Kingdom", {"GBR"}),
    ("Republic of Korea", {"KOR"}), ("Singapore", {"SGP"}),
])
def test_region_names_map_to_countries(name, expected):
    codes, broad = lv.region_codes(name)
    assert codes == expected and broad == 0


def test_broad_regions_and_unmappable_names():
    eu, broad = lv.region_codes("Europe")
    assert broad == 1 and {"DEU", "FRA", "GBR", "ITA"} <= eu and "RUS" not in eu and "USA" not in eu
    emea, _ = lv.region_codes("Europe, Middle East and Africa")
    assert {"DEU", "SAU", "ZAF", "EGY"} <= emea
    apac, _ = lv.region_codes("Asia Pacific")
    assert {"JPN", "AUS", "IND", "CHN"} <= apac and "SAU" not in apac
    assert {"USA", "CAN", "MEX"} <= lv.region_codes("North America")[0]
    for name in ("Other", "Rest of world", "Others", "其他", "境外"):
        assert lv.region_codes(name)[0] == set()


def test_map_named_countries_win_over_broad_regions_and_unmapped_stay_in_legend():
    d = _load("NVDA.json").model_copy(deep=True)
    from investsync.schema import Segment, SegmentBreakdown
    d.segments = [SegmentBreakdown(kind="region", period="FY2026", currency="USD", source="test", segments=[
        Segment(name="China", revenue=30.0), Segment(name="Asia Pacific", revenue=20.0),
        Segment(name="Europe", revenue=40.0), Segment(name="Rest of world", revenue=10.0)])]
    m = lv.geo_map(d)
    assert m is not None
    assert [x["name"] for x in m["legend"]] == ["Europe", "China", "Asia Pacific", "Rest of world"]
    assert m["unmapped"] == ["Rest of world"]
    # China (30%) keeps its own shade although Asia Pacific (20%) also covers it
    china = lv._shade(0.3)
    assert f'id="CHN" fill="{china}"' in m["svg"] and f'id="JPN" fill="{lv._shade(0.2)}"' in m["svg"]


def test_map_asset_is_small_and_credits_natural_earth():
    svg = lv.MAP_FILE.read_text(encoding="utf-8")
    assert len(svg) < 1_000_000 and "Natural Earth" in svg and "public domain" in svg
    assert (lv.ASSETS / "README.md").read_text(encoding="utf-8").count("public domain") >= 1


# ---------------------------------------------------------------------------------------------- scales
def test_three_step_levels_compare_not_cut_off():
    assert lv._three(0.10, 0.10) == 1 and lv._three(0.12, 0.10) == 1  # within 3 points
    assert lv._three(0.40, 0.10) == 2 and lv._three(0.02, 0.10) == 0
    assert lv._three(0.60, 0.55) == 1 and lv._three(0.80, 0.55) == 2  # within a fifth of a large median


def test_cheap_scale_follows_own_history_percentile():
    d = _load("0700_HK_full.json").model_copy(deep=True)
    for p, level in [(0.05, 0), (0.3, 1), (0.5, 2), (0.7, 3), (0.95, 4)]:
        d.pe_band.percentile = p
        assert lv.scale_cheap(d)["chosen"] == level
    d.pe_band = None
    assert lv.scale_cheap(d)["chosen"] is None


def test_safety_scale_net_cash_and_banks():
    nv = TearSheetData.model_validate_json(NVDA_AI.read_text(encoding="utf-8"))
    s = lv.scale_safety(nv, False)
    assert s["chosen"] == 2 and "net cash" in s["evidence"]
    hs = lv.scale_safety(_load("0005_HK.json"), True)
    assert hs["chosen"] is None and "Not scored for banks" in hs["evidence"]


def test_growth_and_profit_scales_use_peers_then_own_past():
    t = _load("0700_HK_full.json")
    g = lv.scale_growth(t)
    assert g["basis"] == "vs peers" and g["chosen"] == 2 and "peer median" in g["evidence"]
    t2 = t.model_copy(deep=True)
    t2.comps = None
    g2 = lv.scale_growth(t2)
    assert g2["basis"] == "vs its own past" and g2["levels"] == ["Slowing down", "Steady", "Speeding up"]
    p2 = lv.scale_profit(t2, False)
    assert p2["basis"] == "vs its own past" and p2["chosen"] is not None


# ---------------------------------------------------------------------------------------------- the guide renders
@pytest.mark.parametrize("path,lo,hi", [(NVDA_AI, 10, 16), (ROOT / "fixtures" / "0700_HK_full.json", 10, 16),
                                        (ROOT / "fixtures" / "0005_HK.json", 10, 16)])
def test_guide_renders_with_visuals(path, lo, hi):
    d = TearSheetData.model_validate_json(path.read_text(encoding="utf-8"))
    pdf = render_pdf(d, layout="learner")
    text = _text(pdf)
    assert lo <= _pages(pdf) <= hi
    assert "At a glance" in text and "NOT INVESTMENT ADVICE" in text and "life cycle" in text
    assert "FOUR SCALES" in text and "HOW THE PHASE IS DECIDED" in text
    if d.rating:
        assert d.rating.rating.upper() in text  # the AI rating as the report states it, never another verdict
