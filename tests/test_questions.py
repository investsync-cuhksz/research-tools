"""The analyst question bank (12 Nov 2026): bank, sector matching, figures computed in code, the AI's choice and the
deep answers checked in code, and where each report type prints them. Offline: DSPy DummyLM, no network, no paid
model."""
import io
import json
import re
from pathlib import Path

import pytest
from dspy.utils.dummies import DummyLM

from investsync.narrative import commentary, guardrail
from investsync.narrative import questions as Q
from investsync.render import dataonly, learner_vm, report_vm
from investsync.render.render import render_pdf
from investsync.schema import (AnalystQuestion, AnalystQuestions, Bullet, DebateArgument, DeepAnalysis, Narrative,
                               ResearchBrief, ResearchFact, TearSheetData)

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def with_research(d: TearSheetData) -> TearSheetData:
    """Research notes with ids, as the research desk writes them (R1 a board investigation, R2 customer financing)."""
    def fact(i, topic, text):
        return ResearchFact(id=i, topic=topic, text=text, quote=text, source="Reuters", title="t", kind="news")
    d.research = ResearchBrief(facts=[
        fact("R1", "events", "The board opened an independent investigation into allegations concerning CEO Jensen "
                             "Huang, with outside counsel leading the review."),
        fact("R2", "capital", "The company guarantees credit support for customers' data-centre buildouts."),
        fact("R3", "guidance", "Management expects revenue of $108.0 billion next quarter.")])
    return d


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return " ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages).split())


# ---------------------------------------------------------------- the bank
def test_bank_file_is_valid_and_has_no_digits():
    assert Q.check_bank() == []
    bank = Q.load_bank()
    keys = [s["key"] for s in bank["sectors"]]
    for k in ("semiconductors", "hardware", "internet_platforms", "consumer_staples", "banks", "batteries_ev",
              "agriculture", "energy", "utilities", "healthcare", "autos", "real_estate"):
        assert k in keys
    texts = [q["text"] for q in bank["general"]] + [q["text"] for s in bank["sectors"] for q in s["questions"]]
    assert not [t for t in texts if re.search(r"\d", t)]
    assert next(s for s in bank["sectors"] if s["key"] == "banks").get("financial") is True
    # the checker catches the team's likely slips
    bad = json.loads(json.dumps(bank))
    bad["general"][0]["text"] = "Is the margin above 40%?"
    bad["general"][1]["id"] = bad["general"][2]["id"]
    bad["general"][3]["data"] = "no_such_figure"
    probs = " ".join(Q.check_bank(bad))
    assert "digits" in probs and "duplicate" in probs and "unknown data key" in probs


@pytest.mark.parametrize("sector,financial,want", [
    ("Semiconductors", False, "semiconductors"), ("半导体", False, "semiconductors"),
    ("Semiconductor Equipment & Materials", False, "semiconductors"),
    ("Farm Products", False, "agriculture"), ("Agricultural Inputs", False, "agriculture"),
    ("农牧饲渔", False, "agriculture"),
    ("Banks - Diversified", True, "banks"), ("Insurance—Life", True, "banks"),
    ("Utilities—Regulated Electric", False, "utilities"),       # not batteries_ev, although it says "electric"
    ("Electrical Equipment & Parts", False, "batteries_ev"), ("电力设备", False, "batteries_ev"),
    ("Consumer Electronics", False, "hardware"), ("Internet Content & Information", False, "internet_platforms"),
    ("Auto Manufacturers", False, "autos"), ("Biotechnology", False, "healthcare"), ("Oil & Gas E&P", False, "energy"),
    ("REIT—Office", False, "real_estate"), ("Packaged Foods", False, "consumer_staples"),
    ("Widgets", False, None), (None, False, None)])
def test_sector_matching(sector, financial, want):
    got = Q.match_sector(sector, financial)
    assert (got or {}).get("key") == want


def test_bank_questions_that_do_not_suit_banks_are_left_out():
    sec, qs = Q.matched(load("0005_HK.json"))
    ids = {q.id for q in qs}
    assert sec["key"] == "banks" and "bank_roe" in ids
    assert not ids & {"cash_conversion", "receivables", "pricing_power", "returns_on_capital"}
    sec, qs = Q.matched(load("NVDA_deep.json"))
    assert sec["key"] == "semiconductors" and {"cash_conversion", "chip_cycle"} <= {q.id for q in qs}


# ---------------------------------------------------------------- figures computed in code
def test_computed_figures_match_the_data():
    d = load("NVDA_deep.json")
    lt = d.financials.latest
    cc = Q.computed(d, "cash_conversion")
    assert f"{lt.label} {lt.operating_cash_flow / lt.net_income:.2f}x" in cc
    last = sorted(d.ratios, key=lambda r: r.fiscal_year)[-1]
    assert f"FY{last.fiscal_year} {last.cash_conversion:.2f}x" in cc
    ys = sorted(d.financials.years, key=lambda y: y.fiscal_year)
    rec = ys[-1].receivables / ys[-2].receivables - 1
    assert f"receivables {rec * 100:+.1f}%" in Q.computed(d, "receivables_vs_revenue")
    sc = Q.computed(d, "share_count")  # US: stock-based pay and buybacks as filed, then the diluted share count
    sbc = next(f for f in d.filing_facts if f.key == "sbc_ytd")
    assert "Stock-based pay" in sc and f"{sbc.value / 1e9:,.1f}bn" in sc and "diluted shares" in sc
    w = d.valuation.wacc.wacc
    assert f"vs WACC {w * 100:.1f}%" in Q.computed(d, "roic_vs_wacc")
    rv = d.valuation.reverse
    assert f"{rv.implied_growth * 100:.1f}% a year" in Q.computed(d, "reverse_dcf")
    assert "Net cash" in Q.computed(d, "net_cash")
    assert "customer shares not in our data" in Q.computed(d, "revenue_mix")
    assert Q.computed(d, "") == ""
    for key in Q.COMPUTE:  # every figure builds on real data without raising
        assert isinstance(Q.computed(d, key), str)


def test_missing_data_says_so():
    d = load("NVDA_deep.json")
    d.ratios, d.segments, d.filing_facts, d.financials.latest = [], [], [], None
    for y in d.financials.years:
        y.receivables = y.buybacks = None
    assert Q.computed(d, "cash_conversion") == Q.NOT_IN_DATA
    assert Q.computed(d, "receivables_vs_revenue") == Q.NOT_IN_DATA
    assert Q.computed(d, "revenue_mix") == Q.NOT_IN_DATA
    assert Q.computed(load("0005_HK.json"), "cash_conversion") == Q.NOT_IN_DATA  # a bank: not meaningful


def test_code_choice():
    d = load("NVDA_deep.json")
    qs = Q.code_select(d)
    ids = [q.id for q in qs.questions]
    assert qs.method == "code" and qs.sector == "semiconductors" and len(ids) <= Q.CODE_CAP
    core = [q["id"] for q in Q.load_bank()["general"] if q.get("core")]
    assert set(core) <= set(ids)
    assert 1 <= sum(q.source == "sector" for q in qs.questions) <= Q.CODE_SECTOR
    keys = [q.data_key for q in qs.questions if q.data_key]
    assert len(keys) == len(set(keys))  # never the same figure twice
    assert all(q.source != "new" and not q.answer for q in qs.questions)
    assert all(q.computed for q in qs.questions if q.data_key)


# ---------------------------------------------------------------- the AI's choice, checked in code
PICK = {
    "picked": json.dumps([
        {"id": "cash_conversion", "why_now": "Profit includes large gains on stakes [R3]."},
        {"id": "chip_customers", "why_now": "Customers get credit support for buildouts [R2]."},
        {"id": "priced_in", "why_now": "Guidance is 55.5% above consensus [R3]."},           # invented figure
        {"id": "moat_source", "why_now": "See the note [R99]."},                               # unknown id
        {"id": "made_up_question", "why_now": ""},                                             # not in the bank
        {"id": "dilution", "why_now": ""},
        {"id": "cyclicality", "why_now": ""}]),
    "new_questions": json.dumps([
        {"theme": "management", "question": "Does the board's investigation into CEO Jensen Huang put strategy at risk?",
         "why_now": "The board opened an independent investigation with outside counsel [R1].", "evidence": ["R1"]},
        {"theme": "events", "question": "Did the CEO commit fraud?", "why_now": "The board is investigating [R1].",
         "evidence": ["R1"]},                                                                  # accuses
        {"theme": "events", "question": "Will CFO Mary Smith resign?", "why_now": "The board is investigating [R1].",
         "evidence": ["R1"]},                                                                  # invented name
        {"theme": "events", "question": "Is the guarantee exposure large?", "why_now": "It is large.",
         "evidence": []},                                                                      # no evidence id
        {"theme": "quality", "question": "Is a write-down of 7.5bn coming?", "why_now": "Guidance [R3].",
         "evidence": ["R3"]},                                                                  # invented figure
        {"theme": "quality", "question": "How large is the exposure from the customer credit guarantees?",
         "why_now": "The company guarantees credit support for customers' buildouts [R2].", "evidence": ["R2"]}]),
}


def test_selection_keeps_only_what_the_checks_allow():
    d = with_research(load("NVDA_deep.json"))
    qs = Q.select(d, DummyLM([PICK]), commentary.ADAPTER)
    ids = [q.id for q in qs.questions]
    assert qs.method == "ai" and qs.sector == "semiconductors"
    new = [q for q in qs.questions if q.source == "new"]
    assert [q.text for q in new] == ["Does the board's investigation into CEO Jensen Huang put strategy at risk?",
                                     "How large is the exposure from the customer credit guarantees?"]
    assert new[0].evidence == ["R1"] and new[0].theme == "management" and new[0].look == "filings"
    assert "made_up_question" not in ids and {"cash_conversion", "chip_customers", "priced_in", "moat_source"} <= set(ids)
    by = {q.id: q for q in qs.questions}
    assert by["chip_customers"].why_now and by["chip_customers"].evidence == ["R2"]
    assert by["priced_in"].why_now == "" and by["moat_source"].why_now == ""   # bad lines dropped, question kept
    assert by["cash_conversion"].computed.startswith("Operating cash flow")
    log = " ".join(qs.log)
    for why in ("unknown bank id 'made_up_question'", "accusing wording", "CFO Mary Smith): Will CFO Mary Smith resign?",
                "cites no evidence id", "figures not in the evidence (7.5bn)", "figures not in the evidence (55.5%)",
                "evidence ids that do not exist (R99)"):
        assert why in log, why


def test_selection_failure_falls_back_to_the_code_choice():
    class Down(DummyLM):
        def __call__(self, *a, **k):
            raise RuntimeError("provider down")
    d = load("NVDA_deep.json")
    qs = Q.select(d, Down([]), commentary.ADAPTER)
    assert qs.method == "code" and qs.questions and "failed" in qs.log[0]


def test_accusing_words_need_the_evidence():
    assert Q.accusing("Did the CEO commit fraud?", "The board is investigating.") == ["fraud"]
    assert Q.accusing("Will the fraud allegations hurt sales?", "Prosecutors allege fraud at the unit.") == []
    assert Q.normalise_ids("as reported (R1, N2) and (see R3)") == "as reported [R1, N2] and (see R3)"


# ---------------------------------------------------------------- deep answers, checked in code
class _A:
    def __init__(self, id, answer, evidence=()):
        self.id, self.answer, self.evidence = id, answer, list(evidence)


def _answered(monkeypatch=None, notes=()):
    d = with_research(load("NVDA_deep.json"))
    qs = Q.code_select(d)
    qs.questions.insert(0, AnalystQuestion(id="new_1", theme="management", source="new", text="Is the probe a risk?",
                                           why_now="The board opened an investigation [R1].", evidence=["R1"]))
    d.analyst_questions = qs
    raw = [
        _A("new_1", "Open: the sources do not say what the investigation found. Outside counsel leads the review [R1]."),
        _A("cash_conversion", "Weak: cash conversion fell [R3]. Tim Cook said it will recover [R3]. Margins are "
                              "77.7% now [R3]."),                       # invented name, then invented figure
        _A("dilution", "Buybacks far exceed stock-based pay [R44]."),     # an id that does not exist
        _A("moat_source", "Scale and switching costs protect the business."),  # cites nothing, no figure
        _A("priced_in", "Demanding: guidance of $108.0 billion supports it [R3]. The market ignores the probe [R1]."),
    ]
    allowed = guardrail.build_allowed(Q.question_lines(d, qs), Q.evidence(d)[0])
    return d, qs, raw, allowed


def test_answers_are_checked_and_failing_sentences_struck(monkeypatch):
    from investsync.narrative import claimcheck
    from investsync.schema import ReviewNote
    d, qs, raw, allowed = _answered()
    seen = {}

    def fake_check(parts, sources, company, lm, adapter, limit=None):
        seen.update(parts)
        return [ReviewNote(section="analyst question priced_in", quote="The market ignores the probe [R1].",
                           problem="unsupported (check 2): no source says so", fix="")], {}
    monkeypatch.setattr(claimcheck, "check", fake_check)
    lines = Q.apply_answers(d, qs, raw, allowed, Q.evidence(d)[0], check_lm=object(), adapter=None)
    by = {q.id: q for q in qs.questions}
    assert by["new_1"].answer_status == "open" and by["new_1"].answer.startswith("Open:")
    assert by["cash_conversion"].answer == "Weak: cash conversion fell [R3]."
    assert by["dilution"].answer == "" and by["dilution"].answer_status == "open"
    assert by["moat_source"].answer == "" and by["moat_source"].answer_status == "open"
    assert by["priced_in"].answer == "Demanding: guidance of $108.0 billion supports it [R3]."
    assert all(q.answer_status for q in qs.questions) and qs.answered
    log = " ".join(lines)
    assert "names not in the evidence (Tim Cook)" in log and "figures not in the evidence (77.7%)" in log
    assert "evidence ids that do not exist (R44)" in log and "cites no evidence" in log
    assert "claim check: unsupported" in log
    assert "analyst question cash_conversion" in seen  # the claim check saw the answers that passed the code checks
    assert lines == qs.log[-len(lines):]


def test_answers_are_capped_at_sixty_words():
    long = " ".join(f"Sentence {w} says the company grows [R3]." for w in ("one", "two", "three", "four", "five",
                                                                            "six", "seven", "eight", "nine", "ten"))
    assert len(Q._cap_words(long).split()) <= Q.ANSWER_WORDS


# ---------------------------------------------------------------- through commentary.generate
def test_generate_selects_once_and_deep_answers(monkeypatch):
    from tests.test_commentary import CLEAN, draft
    from tests.test_deep import BEAR, BULL, FINDINGS, JUDGE, REBUT, REVIEW, WRITER
    d = with_research(load("0700_HK.json"))
    pick = {"picked": json.dumps([{"id": "cash_conversion", "why_now": ""}, {"id": "moat_source", "why_now": ""},
                                  {"id": "variant", "why_now": ""}, {"id": "priced_in", "why_now": ""}]),
            "new_questions": json.dumps([{"theme": "management", "question": "Does the board's investigation put "
                                          "strategy at risk?", "why_now": "The board opened an investigation [R1].",
                                          "evidence": ["R1"]}])}
    answers = {"answers": json.dumps([
        {"id": "new_1", "answer": "Open: the sources do not say what the investigation found [R1].", "evidence": ["R1"]},
        {"id": "cash_conversion", "answer": "Strong: operating cash flow covers net profit (S2, BULL-1).",
         "evidence": ["S2"]},
        {"id": "priced_in", "answer": "Undemanding: the price implies 99.9% growth [R3].", "evidence": ["R3"]}])}
    lm = DummyLM({
        "[[ ## question_bank ## ]]": pick, "[[ ## analyst_questions ## ]]": answers,
        "[[ ## draft ## ]]": REVIEW, "[[ ## previous_draft ## ]]": WRITER, "[[ ## context ## ]]": JUDGE,
        "[[ ## opponent ## ]]": REBUT, "[[ ## side ## ]]\nbull": {"arguments": json.dumps(BULL)},
        "[[ ## side ## ]]\nbear": {"arguments": json.dumps(BEAR)},
        "[[ ## evidence ## ]]": {"findings": json.dumps(FINDINGS), "key_questions": json.dumps(["A?", "B?", "C?"]),
                                 "priced_in": "The price assumes little of the growth the base case expects."}})
    n = commentary.generate(d, lm=lm, mode="deep", news_step=False, questions=True)
    qs = d.analyst_questions
    assert n.mode == "deep" and qs is not None and qs.method == "ai" and qs.answered
    assert sum("[[ ## question_bank ## ]]" in str(h["messages"][-1]["content"]) for h in lm.history) == 1
    by = {q.id: q for q in qs.questions}
    assert by["new_1"].answer_status == "open"
    assert by["cash_conversion"].answer.startswith("Strong") and by["cash_conversion"].answer_status == "answered"
    assert by["priced_in"].answer == "" and by["moat_source"].answer_status == "open"   # 99.9% struck; no answer
    assert any(t.startswith("[struck] analyst question (priced_in)") for t in n.guardrail.text_issues)
    assert n.deep.key_questions == ["A?", "B?", "C?"]   # deep mode's own three questions are kept

    # the standard report on the deep run's data (generate.py --data-from) reuses the list: no new selection call
    lm2 = DummyLM([draft(CLEAN)])
    commentary.generate(d, lm=lm2, news_step=False, questions=True)
    assert d.analyst_questions is qs and len(lm2.history) == 1


def test_generate_with_a_test_model_skips_the_questions_by_default():
    from tests.test_commentary import CLEAN, draft
    d = load("0700_HK.json")
    commentary.generate(d, lm=DummyLM([draft(CLEAN)]), news_step=False)
    assert d.analyst_questions is None


# ---------------------------------------------------------------- where each report prints them
def _deep_data() -> TearSheetData:
    d, qs, raw, allowed = _answered()
    Q.apply_answers(d, qs, raw, allowed, Q.evidence(d)[0])
    arg = DebateArgument(id="BULL-1", claim="Demand keeps growing", reasoning="Revenue doubled.", evidence=["S1"],
                         assumption="Spend holds", breaks_if="Orders fall")
    d.narrative = Narrative(status="generated", mode="deep", model="test-model", dupont_commentary="Margins drive it.",
                            comps_commentary="Cheap on forward earnings.",
                            catalysts=[Bullet(title="Results", text="Results are due.")],
                            risks=[Bullet(title="Demand", text="Spending could slow.")],
                            deep=DeepAnalysis(bull=[arg], verdict="The bull case is stronger.", stronger_side="bull"))
    return d


ANSWER = "Weak: cash conversion fell"


def test_only_the_deep_report_prints_answers():
    d = _deep_data()
    deep_vm = report_vm.build_report(d)["questions"]
    assert deep_vm["answers"] and any(r["answer"].startswith(ANSWER) for r in deep_vm["rows"])
    assert any(r["open"] for r in deep_vm["rows"])
    std = d.model_copy(deep=True)
    std.narrative.deep = None                       # the standard report built from the deep run's data
    std_vm = report_vm.build_report(std)["questions"]
    assert not std_vm["answers"] and all(r["answer"] == "" for r in std_vm["rows"])
    assert std_vm["rows"][0]["new"] and "R1" in std_vm["rows"][0]["why"]
    learner = learner_vm.build(std)["questions"]
    assert learner and all("answer" not in x for x in learner) and "[R1" not in learner[0]["why"]
    text_std = _text(render_pdf(std, layout="report"))
    text_learner = _text(render_pdf(std, layout="learner"))
    text_deep = _text(render_pdf(d, layout="report"))
    assert "QUESTIONS AN ANALYST WOULD ASK" in text_std.upper() and ANSWER not in text_std
    assert "QUESTIONS AN ANALYST WOULD ASK" in text_learner.upper() and ANSWER not in text_learner
    assert ANSWER in text_deep and "ANSWERED" in text_deep.upper()


def test_data_only_edition_shows_the_code_choice_and_makes_no_ai_call(monkeypatch):
    d = _deep_data()
    monkeypatch.setattr(Q, "_sigs", lambda: (_ for _ in ()).throw(AssertionError("an AI step was built")))
    s = dataonly.strip(d)
    qs = s.analyst_questions
    assert qs.method == "code" and not any(q.source == "new" or q.answer or q.why_now for q in qs.questions)
    vm = report_vm.build_report(s, data_only=True)["questions"]
    assert vm["lines"] >= 1 and "AI" not in vm["note"] and all(r["answer"] == "" and r["why"] == "" for r in vm["rows"])
    text = _text(render_pdf(d, layout="data"))
    assert "QUESTIONS AN ANALYST WOULD ASK" in text.upper() and ANSWER not in text and "Is the probe a risk?" not in text
    assert "Our data:" in text


def test_old_reports_without_questions_get_the_code_choice():
    d = load("NVDA_deep.json")
    assert d.analyst_questions is None
    vm = report_vm.build_report(d)["questions"]
    assert vm and "chosen in code" in vm["note"] and len(vm["rows"]) == len(Q.code_select(d).questions)
    assert "where" in vm["rows"][0] and any(r["where"].startswith("ch. ") for r in vm["rows"])
