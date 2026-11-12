"""Round 13 (run 4, reviewed 13 Nov 2026): errors the reviewers verified, fixed with general rules."""
from pathlib import Path

from investsync.quant import street
from investsync.schema import TearSheetData

RUN4 = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "run4_NVDA_deep.json"


def test_street_view_drops_a_superseded_model_value():
    """The broker digest was written before the debate set the scenarios (DEBATE_FIRST) and printed "the USD 281.76
    InvestSync fair value" next to a USD 196.26 rating; refreshing the model value must drop that sentence."""
    d = TearSheetData.model_validate_json(RUN4.read_text(encoding="utf-8"))
    st = d.street
    assert "281.76" in st.synthesis and round(d.rating.fair_value, 2) == 196.26
    st.model_fair_value = 281.76                     # the value the digest was written against
    street.refresh_model(d)
    assert "281.76" not in (st.synthesis or "") and st.synthesis   # the other sentences stay
    assert any("196.26" in f for f in st.findings) and not any("281.76" in f for f in st.findings)


def test_street_view_unchanged_when_the_value_did_not_move():
    d = TearSheetData.model_validate_json(RUN4.read_text(encoding="utf-8"))
    before = d.street.synthesis
    street.refresh_model(d)                          # model value already 196.26: nothing to drop
    assert d.street.synthesis == before


def test_52_week_range_stays_on_the_price_date():
    """Round 13: the live quote's 52-week low (148.80, a 12 Nov intraday print) was printed in a report priced at the
    11 Nov close; the daily history up to the price date says 164.27."""
    from types import SimpleNamespace
    from investsync import pipeline
    d = SimpleNamespace(quote=SimpleNamespace(week52_low=148.80, week52_high=243.37),
                        technicals=SimpleNamespace(low_52w=164.27, high_52w=243.30))
    pipeline._range_to_price_date(d)
    assert d.quote.week52_low == 164.27 and d.quote.week52_high == 243.37   # high within 2%: the traded figure stays
    d = SimpleNamespace(quote=SimpleNamespace(week52_low=163.77, week52_high=250.0),
                        technicals=SimpleNamespace(low_52w=164.27, high_52w=243.30))
    pipeline._range_to_price_date(d)
    assert d.quote.week52_low == 163.77 and d.quote.week52_high == 243.30   # dividend-adjustment gap kept; high fixed


def test_after_debate_line_states_the_new_rating():
    """Round 13: the deep reviewer read the pre-debate rating (Buy, USD 281.76) in the numbered evidence."""
    from investsync.narrative import commentary
    d = TearSheetData.model_validate_json(RUN4.read_text(encoding="utf-8"))
    line = commentary._after_debate_line(d)
    assert line.startswith("UPDATED AFTER THE DEBATE") and "Hold" in line and "196.26" in line and "+13.0%" in line
    assert "supersedes" in line and "281.76" not in line
