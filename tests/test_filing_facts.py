"""Key items as filed (schema 1.10): the right period is picked, and a missing item says NOT REPORTED."""
from datetime import date

from investsync.data import filing_facts as ff
from investsync.schema import FilingFact

PTS = [
    {"start": "2026-01-26", "end": "2026-04-26", "val": 15_936e6, "form": "10-Q"},
    {"start": "2026-01-26", "end": "2026-07-26", "val": 23_707e6, "form": "10-Q"},
    {"start": "2026-04-27", "end": "2026-07-26", "val": 7_771e6, "form": "10-Q"},
    {"start": "2025-01-27", "end": "2026-01-25", "val": 9_000e6, "form": "10-K"},
]


def test_year_to_date_quarter_and_instant_values():
    end, fy_start = date(2026, 7, 26), date(2026, 1, 26)
    assert ff.pick(PTS, "ytd", end, fy_start)[0] == 23_707e6        # the half year, not the quarter
    assert ff.pick(PTS, "quarter", end, fy_start)[0] == 7_771e6
    inst = [{"start": None, "end": "2026-04-26", "val": 119e9}, {"start": None, "end": "2026-07-26", "val": 99.3e9}]
    assert ff.pick(inst, "instant", end, None)[0] == 99.3e9
    # an older quarter-end is never returned as the current figure
    assert ff.pick(inst[:1], "instant", end, None) is None
    assert ff._period("ytd", end, fy_start) == "6 months to 26 Jul 2026"


def test_missing_items_are_not_reported_not_guessed():
    facts = [FilingFact(key="investment_gains_ytd", label="Gains on investments", value=23_707e6, currency="USD",
                        period="6 months to 26 Jul 2026", source="SEC XBRL"),
             FilingFact(key="purchase_obligations", label="Purchase obligations", value=None, currency="USD",
                        period="at 26 Jul 2026", source="SEC XBRL", note="not reported in the filing's XBRL data")]
    txt = ff.text(facts)
    assert "USD 23.7bn" in txt and "Purchase obligations (at 26 Jul 2026): NOT IN THE TAGGED DATA" in txt
    assert "never" not in txt.lower() or "do not give a figure" in txt
