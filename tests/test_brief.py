"""Analyst brief: one thinking call decides the view before the simple report is written."""
import json

from dspy.utils import DummyLM

from pathlib import Path

from investsync.narrative import brief
from investsync.narrative.commentary import ADAPTER
from investsync.schema import TearSheetData


def tencent() -> TearSheetData:
    f = Path(__file__).resolve().parent.parent / "fixtures" / "0700_HK_full.json"
    return TearSheetData.model_validate_json(f.read_text(encoding="utf-8"))

GOOD = {"central_question": "Does AI capex pay back before buyers balk?",
        "our_answer": "Yes for now: revenue grew strongly while margins held.",
        "priced_in": "The price implies slower growth than our forecast.",
        "pillars": json.dumps([{"claim": "Core engine compounding", "evidence": "Revenue up in every segment",
                                "breaks_if": "Ad revenue stalls"},
                               {"claim": "AI bill modelled in full", "evidence": "Capex in our forecast",
                                "breaks_if": "Capex rises again"}]),
        "beyond_forecast": "Margins must hold after the forecast years.", "quality": "No concerns in the data",
        "governance": "None", "street_gap": "We assume a heavier bear case than the brokers.",
        "watch": "Results date: margins and capex guidance.",
        "tagline": "The market fears the AI bill; the evidence says the core engine pays for it",
        "thesis": "The stock turns on whether AI spending pays back before buyers balk. We think it does."}


def test_brief_is_written_from_the_facts_and_shown_to_the_writer():
    d = tencent()
    b = brief.run(d, "Tencent", "facts", "None", "None", DummyLM([GOOD]), ADAPTER)
    t = brief.text(b)
    assert "Central question: Does AI capex pay back" in t and "Pillar 2: AI bill modelled in full" in t
    assert brief.example_for(d).startswith("Example of a strong page 1 (CATL")  # never the company itself


def test_a_brief_with_one_pillar_is_sent_back_once():
    one = dict(GOOD, pillars=json.dumps([json.loads(GOOD["pillars"])[0]]))
    b = brief.run(tencent(), "Tencent", "facts", "None", "None", DummyLM([one, GOOD]), ADAPTER)
    assert len(b.pillars) == 2


def test_the_writer_gets_the_brief_and_the_example_but_the_sources_do_not(monkeypatch):
    """Integration: with BRIEF on, the simple writer's facts carry the brief and the example."""
    from types import SimpleNamespace
    from investsync.config import settings
    from investsync.narrative import commentary
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_commentary as tc
    seen = {}
    object.__setattr__(settings, "brief_enabled", True)
    fake = SimpleNamespace(central_question="Q?", our_answer="A.", priced_in="P.", pillars=[], beyond_forecast="B.",
                           quality="No concerns in the data", governance="None", street_gap="S.", watch="W.")
    monkeypatch.setattr(brief, "run", lambda *a, **k: fake)
    orig = commentary._run

    def spy(program, lm, inputs, ctx, **kw):
        seen["facts"] = inputs["facts"]
        return orig(program, lm, inputs, ctx, **kw)
    monkeypatch.setattr(commentary, "_run", spy)
    try:
        d = TearSheetData.model_validate_json(tc.FIXTURE.read_text(encoding="utf-8"))
        commentary.generate(d, lm=DummyLM([tc.draft(tc.CLEAN)]), news_step=False)
    finally:
        object.__setattr__(settings, "brief_enabled", False)
    assert "ANALYST BRIEF" in seen["facts"] and "Central question: Q?" in seen["facts"]
    assert "EXAMPLE of the depth and argument wanted" in seen["facts"]
