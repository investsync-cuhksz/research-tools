"""Final check (11 Nov 2026): no unfinished trading day as the price, one thesis memo shared by the reports of one
day, and the lead analyst's tagline and thesis passed to the writer. No network."""
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from investsync.data.sources import completed_sessions
from investsync.narrative import brief


def _prices():
    df = pd.DataFrame({"date": [date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)],
                       "close": [178.67, 168.89, 170.0]})
    df.attrs["source"] = "yahoo"
    return df


def test_unfinished_day_is_dropped_while_the_session_is_open():
    ny = ZoneInfo("America/New_York")
    open_ = completed_sessions(_prices(), "US", datetime(2026, 11, 11, 11, 0, tzinfo=ny))
    assert open_["date"].iloc[-1] == date(2026, 11, 10) and open_.attrs["source"] == "yahoo"
    closed = completed_sessions(_prices(), "US", datetime(2026, 11, 11, 17, 0, tzinfo=ny))
    assert closed["date"].iloc[-1] == date(2026, 11, 11)
    # Beijing evening = New York morning of the same date: still open
    bj = datetime(2026, 11, 11, 23, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert completed_sessions(_prices(), "US", bj)["date"].iloc[-1] == date(2026, 11, 10)
    # Hong Kong: a 15:00 bar is intraday, 17:00 is final
    hk = ZoneInfo("Asia/Hong_Kong")
    assert completed_sessions(_prices(), "HK", datetime(2026, 11, 11, 15, 0, tzinfo=hk))["date"].iloc[-1] == \
        date(2026, 11, 10)
    assert completed_sessions(_prices(), "HK", datetime(2026, 11, 11, 17, 0, tzinfo=hk))["date"].iloc[-1] == \
        date(2026, 11, 11)


def _brief(**kw):
    base = dict(central_question="Q?", our_answer="A.", priced_in="P.", beyond_forecast="B.", quality="Q.",
                governance="None", street_gap="S.", watch="W.", pillars=[], tagline="", thesis="")
    return SimpleNamespace(**{**base, **kw})


def test_brief_passes_the_tagline_and_thesis_to_the_writer():
    t = brief.text(_brief(tagline="The market prices a slowdown; the evidence says otherwise",
                          thesis="Our thesis paragraph."))
    assert "Tagline (by the lead analyst" in t and "Thesis paragraph (by the lead analyst" in t
    assert "Tagline" not in brief.text(_brief())  # an older brief without them still works


def test_brief_requires_the_tagline_and_thesis():
    issues = brief._problems(_brief(pillars=[1, 2]), None)
    assert any("`tagline` is empty" in i for i in issues) and any("`thesis` is empty" in i for i in issues)


def test_data_from_reuses_the_saved_brief(monkeypatch):
    from investsync import pipeline
    from investsync.narrative import commentary
    from investsync.schema import TearSheetData
    seen = {}

    def fake_generate(data, mode=None, learner=False, brief=None):
        seen["brief"], seen["narrative"] = brief, data.narrative
        return commentary.placeholder()
    monkeypatch.setattr(commentary, "generate", fake_generate)
    monkeypatch.setattr(pipeline.history, "save", lambda d: None)
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "dev_v7_NVDA_deep.json"
    if not p.exists():
        import pytest
        pytest.skip("round 9 data not present")
    base = TearSheetData.model_validate(json.loads(p.read_text()))
    base.narrative.brief = "ANALYST BRIEF: saved"
    pipeline.build_tearsheet("NVDA", mode="single", base=base)
    assert seen["brief"] == "ANALYST BRIEF: saved" and seen["narrative"] is None
