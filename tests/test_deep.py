"""Deep mode: analyst -> bull / bear -> rebuttals -> judge -> writer -> reviewer -> revision. Offline."""
import json

from dspy.utils.dummies import DummyLM

from investsync.narrative import commentary, deep, evidence, textcheck
from investsync.narrative.guardrail import build_allowed
from investsync.render.render import render_pdf

from tests.test_commentary import CLEAN, data, draft  # noqa: F401  (fixture)
from tests.test_street import _pages, _text

FINDINGS = [
    {"area": "valuation", "finding": "The shares trade below the peer median on P/E despite better margins.",
     "stance": "positive", "evidence": ["S2"]},
    {"area": "share price", "finding": "The stock has lagged the Hang Seng Index badly over a year.",
     "stance": "negative", "evidence": ["S6"]},
    {"area": "growth", "finding": "Revenue has compounded steadily over four years.", "stance": "positive",
     "evidence": ["S1"]},
    {"area": "valuation", "finding": "Book value multiples are well above peers.", "stance": "negative",
     "evidence": ["S4", "E99999"]},
    {"area": "profitability", "finding": "A finding with no evidence at all.", "stance": "positive", "evidence": []},
]
BULL = [
    {"claim": "Cheaper than peers despite better margins", "reasoning": "The P/E discount to peers (S2) ignores "
     "superior profitability.", "evidence": ["S2"], "assumption": "Peer multiples are a fair yardstick",
     "breaks_if": "Peers re-rate down"},
    {"claim": "Steady compounding", "reasoning": "Revenue keeps compounding.", "evidence": ["S1"],
     "assumption": "Growth persists", "breaks_if": "Growth stalls"},
    {"claim": "The weak share price is a bargain", "reasoning": "Underperformance means it must rebound.",
     "evidence": ["S6"], "assumption": "Mean reversion", "breaks_if": "It keeps falling"},       # twisted bear evidence
    {"claim": "Made-up evidence", "reasoning": "Trust me.", "evidence": ["Z9"], "assumption": "x", "breaks_if": "y"},
]
BEAR = [
    {"claim": "The market has lost faith", "reasoning": "A year of underperformance (S6) shows investors doubt the "
     "AI spending.", "evidence": ["S6"], "assumption": "Momentum persists", "breaks_if": "Results beat"},
    {"claim": "Rich on book value", "reasoning": "P/B is far above peers.", "evidence": ["S4"],
     "assumption": "Book value matters for this business", "breaks_if": "Returns stay high"},
]
REBUT = {"rebuttals": json.dumps([{"target": "BEAR-1", "response": "Momentum says little about value (S2).",
                                   "evidence": ["S2"]},
                                  {"target": "BEAR-9", "response": "Answering an argument that does not exist.",
                                   "evidence": []}]),
         "concessions": json.dumps(["The share price trend is genuinely weak."])}
JUDGE = {"stronger_side": "bull", "conviction": "medium",
         "verdict": "The valuation evidence outweighs the momentum argument, which rests on sentiment.",
         "swing_factor": "Whether peer multiples suit a company with superior margins.",
         "change_my_mind": "Evidence that AI spending is eroding returns.",
         "divergences": json.dumps(["Bull reads S6 as an opportunity, bear as lost confidence."])}
REVIEW = {"issues": json.dumps([
    {"section": "thesis", "quote": "Profitability keeps improving while the shares trade below the peer median",
     "problem": "missing caveat", "fix": "Mention the weak share price and the bear case."},
    {"section": "thesis", "quote": "This sentence is not in the draft at all", "problem": "other", "fix": "x"}]),
    "overall": "Sound but one-sided."}
WRITER = draft(CLEAN, thesis="The debate favours the bull case: profitability keeps improving while the shares "
                             "trade below the peer median, though the bear case on momentum is real.",
               variant_view="The analysis agrees with the brokers on direction but leans on peers.",
               pre_mortem="If the case fails, the likely reason is that AI spending erodes returns.")


def routed_lm() -> DummyLM:
    # keys are matched against the step's inputs, most specific first
    return DummyLM({
        "[[ ## draft ## ]]": REVIEW,
        "[[ ## previous_draft ## ]]": WRITER,
        "[[ ## context ## ]]": JUDGE,
        "[[ ## opponent ## ]]": REBUT,
        "[[ ## side ## ]]\nbull": {"arguments": json.dumps(BULL)},
        "[[ ## side ## ]]\nbear": {"arguments": json.dumps(BEAR)},
        "[[ ## evidence ## ]]": {"findings": json.dumps(FINDINGS), "key_questions": json.dumps(
            ["Do AI investments earn their cost?", "Are peers the right yardstick?", "Will momentum turn?"]),
            "priced_in": "The price assumes little of the growth the base case expects."},
    })


def test_deep_chain_runs_and_checks_every_step(data):  # noqa: F811
    n = commentary.generate(data, lm=routed_lm(), mode="deep", news_step=False)
    assert n.status == "generated" and n.mode == "deep"
    da = n.deep
    # analyst: findings without real evidence are dropped; unknown ids are stripped
    assert len(da.findings) == 4 and da.findings[3].evidence == ["S4"]
    assert len(da.key_questions) == 3 and da.priced_in
    # bull: the twisted argument (only bear-side evidence) and the made-up id are rejected in code
    assert [a.claim for a in da.bull] == ["Cheaper than peers despite better margins", "Steady compounding"]
    assert any("supports the bear case" in d for d in da.dropped) and any("no evidence id" in d for d in da.dropped)
    assert [a.id for a in da.bear] == ["BEAR-1", "BEAR-2"]
    # rebuttals must answer a real argument
    assert [r.target for r in da.rebuttals if r.side == "bull"] == ["BEAR-1"]
    assert da.concessions_bull == ["The share price trend is genuinely weak."]
    # judge never sets the rating; alignment is computed in code
    assert da.stronger_side == "bull" and da.conviction == "medium" and da.swing_factor
    assert da.rating_alignment == "not rated"
    # reviewer: only quotes that are really in the draft survive
    assert len(da.review) == 1 and da.review[0].problem == "missing caveat"
    assert da.variant_view and da.pre_mortem
    assert {e.id for e in da.evidence} >= {"S1", "S2", "S4", "S6"}
    assert da.calls >= 8


def test_reviewer_notes_reach_the_revision(data):  # noqa: F811
    lm = routed_lm()
    commentary.generate(data, lm=lm, mode="deep", news_step=False)
    writer_calls = [h for h in lm.history if "previous_draft" in str(h["messages"][-1]["content"])]
    assert len(writer_calls) >= 2
    second = str(writer_calls[1]["messages"][-1]["content"])
    assert "[reviewer]" in second and "Mention the weak share price" in second
    assert "## thesis" in second  # the writer edits its own previous draft


def test_arguments_that_cite_only_the_other_sides_signals_are_dropped(data):  # noqa: F811
    from investsync.render import viewmodel
    from investsync.render.report_vm import build_report
    from investsync.narrative.facts import facts_text, report_facts_text
    f = facts_text(viewmodel.build(data), data) + "\n\n" + report_facts_text(build_report(data), data)
    ev = evidence.build(data, f)
    allowed = build_allowed(data.model_dump(exclude={"narrative"}), f, ev.text)

    class A:
        def __init__(self, **kw):
            self.__dict__.update(kw)
    args = [A(claim="Momentum is a buy signal", reasoning="It fell a lot.", evidence=["S6"], assumption="",
              breaks_if=""),
            A(claim="Cheap and growing", reasoning="Discount to peers (S2) with a mixed record (S6).",
              evidence=["S2"], assumption="", breaks_if=""),
            A(claim="Invented figure", reasoning="Margins are 99.9% now.", evidence=["S1"], assumption="",
              breaks_if="")]
    kept, dropped = deep.verify_arguments(args, "bull", ev, allowed, "BULL")
    assert [k.claim for k in kept] == ["Cheap and growing"] and kept[0].evidence == ["S2", "S6"]
    assert "supports the bear case" in dropped[0] and "99.9%" in dropped[1]


def test_signals_put_the_sign_on_the_right_side(data):  # noqa: F811
    sig = {s.label: s for s in evidence.signals(data)}
    assert sig["P/E (TTM) vs peer median"].stance == "bull"
    assert sig["P/B vs peer median"].stance == "bear"
    assert evidence.cited("see S2 and E14, not X3") == ["S2", "E14"]


def test_wording_checks():
    from tests.test_street import tencent
    d = tencent()
    msgs = lambda t: [i.check for i in textcheck.run({"financial_analysis": t}, d)]  # noqa: E731
    assert msgs("Gross margin climbed from 43.9% to 56.2% and operating margin from 47.3% to 32.1%.") == ["direction"]
    assert msgs("Gross margin expanded from 36.8% to 39.8%, yet operating margin collapsed to 4.9% from 14.1%.") == []
    assert msgs("Revenue fell +0.9% in the year.") == ["direction"]
    assert msgs("Growth slowed from 13.9% to 8.4%, and losses narrowed from 5% to 2%.") == []
    assert msgs("The October bond issue raised US$1.8 billion.") == []


def test_deep_report_has_the_debate_chapter(data):  # noqa: F811
    data.narrative = commentary.generate(data, lm=routed_lm(), mode="deep", news_step=False)
    assert _pages(render_pdf(data, layout="tearsheet")) == 1
    text = _text(render_pdf(data))
    assert "Investment debate" in text and "BULL-1" in text and "Swing factor" in text
    assert "What would change the view" in text and "AI reviewer checked the draft" in text
    # round-7 review: no reviewer table, no evidence codes in sentences; round 8: no evidence-code appendix, no
    # scorecard appendix (both "machine output" for the reviewers)
    assert "Quoted text" not in text and "evidence index" not in text.lower()
    assert "quality scorecard" not in text.lower() and "Insider and major-holder" not in text


def test_learner_guide_renders_with_exact_worked_examples():
    from investsync.render import learner_vm
    from tests.test_street import tencent
    d = tencent()
    g = learner_vm.build(d)
    assert [s["key"] for s in g["steps"]] == ["business", "growth", "profit", "safety", "cheap", "worth", "others",
                                             "wrong"]
    growth = g["steps"][1]["worked"]["lines"]
    assert growth[0].startswith("CAGR = (Revenue") and growth[-1].endswith(g["exercises"][0]["answer"])
    assert all(e["answer"] and e["working"] for e in g["exercises"])
    pdf = render_pdf(d, layout="learner")
    text = _text(pdf)
    assert "Learner" in text and "How to read the" in text and "Try it yourself" in text and "Answers" in text and "Glossary" in text
    assert "What could go wrong?" in text and _pages(pdf) >= 5


def test_learner_notes_are_checked(data):  # noqa: F811
    from investsync.narrative import learner
    from tests.test_street import tencent
    d = tencent()
    good = {"big_picture": "A profitable platform whose shares trail the index.",
            "notes": json.dumps([{"step": k, "note": f"Plain note for {k}."} for k in learner.STEP_KEYS]),
            "discussion": json.dumps(["Q1?", "Q2?", "Q3?"])}
    bad = dict(good, big_picture="Revenue rose 99.9% and we rate it a Buy rating.")
    lm = DummyLM([bad, good])
    notes = learner.coach(d, lm, "facts", None)
    assert notes and notes.steps["growth"] == "Plain note for growth." and len(notes.discussion) == 3
    assert "99.9%" in str(lm.history[-1]["messages"])  # the second try was told what was wrong


def test_vs_price_check():
    from investsync.narrative import textcheck as t
    d = _data() if "_data" in globals() else None
    if d is None:
        import json
        from pathlib import Path
        from investsync.schema import TearSheetData
        d = TearSheetData.model_validate_json(Path("fixtures/0700_HK_full.json").read_text())
    d.quote.price, d.quote.currency = 419.80, "HKD"
    bad = t._vs_price("x", "the sensitivity range already reaches HKD 457.31, below today's price.", d)
    assert bad and bad[0].severity == "hard"
    assert not t._vs_price("x", "The bear value of HKD 337 sits below the current price.", d)
    assert not t._vs_price("x", "HKD 573.44, with only 24% of draws above the current price", d)
    assert not t._vs_price("x", "USD 500 is below the current price", d)  # other currency: not compared
