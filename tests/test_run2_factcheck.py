"""Run 2, WP1: the fact sweep. Each error class the run-1 reviewers verified is found and struck; run 1's correct
sentences are left alone; a failing check is skipped; the writer loop never flags a report for these checks."""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from dspy.utils.dummies import DummyLM

from investsync.narrative import claimcheck, commentary, factcheck
from investsync.schema import (Bullet, DebateRebuttal, DeepAnalysis, GuardrailReport, Narrative, ResearchFact,
                               ReviewNote, TearSheetData, TechPoint)

ROOT = Path(__file__).resolve().parent.parent
RUN1 = ROOT / "fixtures" / "runs" / "run1_NVDA"   # run 1 (final_v8/NVDA), saved as fixtures
needs_run1 = pytest.mark.skipif(not Path(f"{RUN1}_deep.json").exists(), reason="run 1's saved reports are not here")


def _load(kind: str) -> TearSheetData:
    return TearSheetData.model_validate_json(Path(f"{RUN1}_{kind}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def nvda() -> TearSheetData:
    if not Path(f"{RUN1}_simple.json").exists():
        pytest.skip("run 1's saved reports are not here")
    return _load("simple")


def checks(text, data):
    return {i.check for i in factcheck.find(text, data)}


# ---------------------------------------------------------------- run 1's verified errors are found
SUNDAY = ("Press reports say CEO Jensen Huang admitted an extramarital affair on 8 November 2026 and that the board "
          "opened an independent probe into whether he was targeted by a foreign intelligence operation; the shares "
          "closed down 5.5% that day.")
MEDIAN = ("At 21.4x trailing and 10.6x forward earnings, versus a 34.5x five-year median on the fiscal-year basis "
          "(4th percentile), the de-rating is demanding only relative to peers' 46.6x, not to its own record.")
THIRD = ("New governors pledged moratoriums in three states that account for about one-third of planned capacity "
         "(about 141 GW out of a total of about 156 GW currently planned).")
PRESS = ("The Q4 71-72% figure is a press report, not company guidance; the filed Q3 guide is 74.0% ±50bp.")
WEIGHT = "We weight a 28% bear case at USD 77.97 because funding could tighten."
BASE = "The price implies 37.1% growth a year, against 41.7% in the base case."


def test_each_run1_error_is_found(nvda):
    sunday = factcheck.find(SUNDAY, nvda)
    assert [i.check for i in sunday] == ["move_dates"]
    assert "8 Nov 2026 was a Sunday" in sunday[0].message and "10 Nov -5.5%" in sunday[0].message
    med = factcheck.find(MEDIAN, nvda)
    assert [i.check for i in med] == ["stat_labels"] and "64.0x" in med[0].message
    assert checks(THIRD, nvda) == {"fractions"}
    assert checks(PRESS, nvda) == {"provenance"}
    for s in ("Brokers cite figures that are only in a press report.",
              "Neither figure appears in the filed documents, so we leave it out.",
              "The margin outlook is not in the filed 10-Q."):
        assert checks(s, nvda) == {"provenance"}, s
    w = factcheck.find(WEIGHT, nvda)
    assert [i.check for i in w] == ["scenario_weights"] and "25%" in w[0].message
    b = factcheck.find(BASE, nvda)
    assert [i.check for i in b] == ["stat_labels"] and "mechanical DCF" in b[0].message


def test_a_move_on_a_session_must_match_its_close(nvda):
    assert checks("The shares closed down 9.3% on 10 November, extending the slide.", nvda) == {"move_dates"}
    assert checks("On 10 November the shares fell 9.3% that day after the board probe.", nvda) == {"move_dates"}


def test_run1_correct_sentences_are_left_alone(nvda):
    clean = [
        "The shares closed down 5.5% on 10 November, 29.4% below their record close.",
        "The shares closed down 4.3% on 9 November after the weekend news.",   # 6 Nov is not in the chart: unknown
        "The shares fell 3.0% on 6 November.",                                # a weekday the chart skips: unknown
        "On its own history the P/E of 34.5x sits far below the 64.0x five-year median.",
        "At 10.6x forward earnings against a peer median of 19.0x, the shares are cheap versus the four peers.",
        "The price implies 37.1% growth a year for five years, 4.9pp below our 42.0% base case.",
        "Bear USD 77.97 at 25%, base USD 200.97 at 55%, bull USD 307.60 at 20% give USD 191.54.",
        "We weight a 25% bear case at USD 77.97 because funding could tighten.",
        "The three states hold more than half of planned capacity (141 GW out of 156 GW).",
        "In the first half, 141 of 156 planned sites were approved.",
        "Huang admitted an affair on 8 November and the shares fell 4.3% on 9 November.",
        "Our base-case FCF margin of 41.0% sits against the model's 43.3%.",
        "Management returned $26.0bn in Q2 and has $99.3bn of buyback authorisation left.",  # no later note in run 1
        "Revenue rose 95.8% in the six months to 26 July 2026.",
        "Results are due on 18 November; options price a move of about ±10.3%.",
    ]
    for s in clean:
        assert factcheck.find(s, nvda) == [], s


@needs_run1
def test_sweep_on_run1_strikes_few_sentences_and_empties_nothing():
    for kind in ("deep", "simple"):
        d = _load(kind)
        before = d.narrative.model_dump()
        lines = factcheck.sweep(d.narrative, d)
        assert lines and len(lines) <= 12, (kind, lines)
        assert not [x for x in lines if x.startswith("[open]")], lines
        after = d.narrative.model_dump()
        for k, v in before.items():
            if isinstance(v, str) and v:
                assert after[k], f"{kind}.{k} was emptied"
        assert d.narrative.tagline and d.narrative.thesis
        text = d.narrative.model_dump_json()
        for s in ("versus a 34.5x five-year median", "a press report, not company guidance",
                  "neither figure appears in the filed documents"):
            assert s not in text
        assert factcheck.sweep(d.narrative, d) == []  # idempotent: nothing left to strike


@needs_run1
def test_run1_sunday_sentence_is_struck_and_logged():
    d = _load("simple")
    assert "closed down 5.5% that day" in d.narrative.news_summary
    lines = factcheck.sweep(d.narrative, d)
    assert "closed down 5.5% that day" not in d.narrative.news_summary
    assert d.narrative.news_summary.startswith("News since late October")
    assert any(x.startswith("[struck] move_dates: Press reports say CEO Jensen Huang") for x in lines)


def _narr(**kw) -> Narrative:
    base = dict(status="generated", dupont_commentary="", comps_commentary="", catalysts=[], risks=[],
                guardrail=GuardrailReport(passed=True, attempts=1))
    return Narrative(**{**base, **kw})


def test_sweep_strikes_the_sentence_and_keeps_the_rest(nvda):
    n = _narr(thesis="Growth holds into FY2028 on the Q3 guide and supply commitments. " + PRESS,
              key_takeaways=["Growth holds.", WEIGHT, "Cash conversion is weak.", "Governance is a risk."],
              risks=[Bullet(title="Funding", text="Customer financing could tighten. " + WEIGHT)],
              learner=None)
    lines = factcheck.sweep(n, nvda)
    assert n.thesis == "Growth holds into FY2028 on the Q3 guide and supply commitments."
    assert n.key_takeaways == ["Growth holds.", "Cash conversion is weak.", "Governance is a risk."]  # item dropped
    assert n.risks[0].text == "Customer financing could tighten."
    assert {x.split(":")[0] for x in lines} == {"[struck] provenance", "[struck] scenario_weights"}


def test_fallbacks_tagline_review_note_and_open_field(nvda):
    rv = [ReviewNote(section="thesis", quote="q", problem="unsupported (check 7): attribution.",
                     fix="Also say the Q4 71-72% figure is not company guidance."),
          ReviewNote(section="thesis", quote="q2", problem="wrong (check 1): direction.", fix="Say it fell.")]
    n = _narr(tagline="The Q4 figure is a press report, not company guidance.",
              deep=DeepAnalysis(review=rv, verdict=PRESS,
                                rebuttals=[DebateRebuttal(side="bull", target="BEAR-1", response=PRESS)]))
    lines = factcheck.sweep(n, nvda)
    assert n.tagline == "Hold: fair value USD 191.54 (+13.4% vs the price)"
    assert [r.fix for r in n.deep.review] == ["Say it fell."]                        # emptied fix: note dropped
    assert n.deep.verdict == PRESS                                                    # any other field: left, [open]
    assert n.deep.rebuttals[0].response == PRESS                                      # a one-item list keeps its item
    assert any(x.startswith("[open] provenance") for x in lines)
    assert any("review note dropped" in x for x in lines) and any("code-built line" in x for x in lines)


def test_a_check_that_raises_is_skipped(nvda, monkeypatch):
    def boom(sents, ctx):
        raise RuntimeError("broken check")
    monkeypatch.setitem(factcheck.CHECKS, "provenance", boom)
    assert checks(PRESS + " " + MEDIAN, nvda) == {"stat_labels"}
    assert factcheck.find("anything", None) == [] and factcheck.find("", nvda) == []


def test_stale_remaining_buyback_needs_the_later_authorisation(nvda):
    s_old = "Roughly $99.0bn of share repurchase authorisation remained at the end of the quarter."
    s_new = "About $99.0bn of repurchase authorisation remained at 26 July, before the new $150.0bn programme."
    assert factcheck.find(s_old, nvda) == []                       # no later note: nothing to check
    nvda.research.facts.append(ResearchFact(
        id="R999", topic="capital", text="The board approved an additional $150.0 billion share repurchase "
        "authorization.", quote="additional $150.0 billion", source="Company press release", title="Buyback",
        published=date(2026, 11, 5), kind="announcement"))
    assert checks(s_old, nvda) == {"stale_remaining"}             # regex fallback (no WP2 key)
    assert factcheck.find(s_new, nvda) == []
    nvda.research.facts[-1].key = "update:capital_return"
    assert checks(s_old, nvda) == {"stale_remaining"}


def test_a_holiday_is_found_only_where_the_chart_lists_every_session(nvda):
    as_of = nvda.quote.as_of
    days, d = [], as_of - timedelta(days=200)
    while d <= as_of:
        if d.weekday() < 5 and d != date(2026, 9, 7):  # a Monday market holiday
            days.append(d)
        d += timedelta(days=1)
    nvda.technicals.chart = [TechPoint(d=x, close=100 + i * 0.1) for i, x in enumerate(days)]
    assert checks("The shares fell 2.0% on 7 September.", nvda) == {"move_dates"}
    assert factcheck.find("The shares fell 2.0% on 8 September.", nvda) == []
    assert "Daily closes, last 10 sessions" in factcheck.writer_notes(nvda)


def test_writer_notes_from_the_report_data(nvda):
    w = factcheck.writer_notes(nvda)
    assert "10 Nov 2026 (Tue) 168.89 -5.5%" in w and "5 Nov 2026 (Thu) 181.60 -9.3%" in w
    assert "weekend or holiday announcement moved the price on the next session" in w
    assert ("net cash (cash and investments minus debt) went from 41,202mn (25 Jan 2026) to 23,220mn (26 Jul 2026): "
            "cash and investments changed by +6,916mn, debt by +24,898mn") in w
    assert "today's P/E on last fiscal year's EPS is 34.5x; the 5-year median is 64.0x" in w


def test_brief_lines_are_swept_without_breaking_the_layout(nvda):
    brief = ("ANALYST BRIEF (the lead analyst's view):\n- Our answer: Yes, mostly: Hold at fair value USD 191.54.\n"
             f"- Pillar 1: Guidance holds. Evidence: {PRESS} Breaks if: Q3 misses.\n"
             "- Pillar 2: Cash conversion recovers. Evidence: DSO 60 days. Breaks if: receivables keep rising.")
    new, lines = factcheck.strike_text(brief, nvda)
    assert "not company guidance" not in new and "- Pillar 2: Cash conversion recovers." in new
    assert "- Pillar 1: Guidance holds. Breaks if: Q3 misses." in new and "- Our answer: Yes, mostly" in new
    assert lines == [f"[struck] provenance: Evidence: {PRESS}"]


# ---------------------------------------------------------------- claim check: time words as a balance-sheet cause
def test_time_words_count_as_a_cause_only_with_a_balance_sheet_word():
    s = "Net cash fell from $41.2bn at FY2026 after $39.0bn of buybacks."
    assert claimcheck._CAUSAL.search(s) and claimcheck.candidates({"thesis": s})
    for ok in ("Free cash flow after capex was 69,987mn.", "Revenue grew strongly following the launch.",
               "Cash returns are planned for the following year."):
        assert not claimcheck._CAUSAL.search(ok), ok


# ---------------------------------------------------------------- the writer loop
FIXTURE = ROOT / "fixtures" / "0700_HK.json"


@pytest.fixture()
def tencent() -> TearSheetData:
    return TearSheetData.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _draft(news_summary: str) -> dict:
    from tests.test_commentary import CLEAN, draft
    return draft(CLEAN, news_summary=news_summary)


DIRTY_NEWS = ("Recent news focused on AI investment and capital returns. "
              "The margin outlook is a press report, not company guidance.")


def test_fact_issue_is_sent_back_once_as_soft_feedback(tencent):
    lm = DummyLM([_draft(DIRTY_NEWS), _draft("Recent news focused on AI investment and capital returns.")])
    n = commentary.generate(tencent, lm=lm, news_step=False)
    assert n.status == "generated" and n.guardrail.attempts == 2
    prompt = str(lm.history[-1]["messages"])
    assert "[fact] In `news_summary`" in prompt and "Earnings calls are not filed" in prompt
    assert not [t for t in n.guardrail.text_issues if t.startswith(("[fact]", "[struck]"))]


def test_a_fact_issue_that_survives_is_struck_never_flagged(tencent):
    n = commentary.generate(tencent, lm=DummyLM([_draft(DIRTY_NEWS)] * 2), news_step=False)
    assert n.status == "generated" and n.guardrail.passed
    assert n.news_summary == "Recent news focused on AI investment and capital returns."
    assert "[struck] provenance: The margin outlook is a press report, not company guidance." in n.guardrail.text_issues
    assert not [t for t in n.guardrail.text_issues if t.startswith("[fact]")]


def test_a_learner_coach_failure_keeps_the_paid_narrative(tencent, monkeypatch):
    from investsync.narrative import learner

    def boom(*a, **k):
        raise RuntimeError("coach crashed")
    monkeypatch.setattr(learner, "coach", boom)
    from tests.test_commentary import CLEAN, draft
    n = commentary.generate(tencent, lm=DummyLM([draft(CLEAN)]), news_step=False, learner=True)
    assert n.status == "generated" and n.learner is None and n.thesis


@needs_run1
def test_writer_notes_reach_the_writer():
    d = _load("simple")
    d.narrative = None
    from tests.test_commentary import CLEAN, draft
    lm = DummyLM([draft(CLEAN)] * 4)
    commentary.generate(d, lm=lm, news_step=False)
    prompt = str(lm.history[0]["messages"])
    assert "Net cash bridge (code, USD)" in prompt and "Statistic labels (code)" in prompt
    assert "supersedes the key fact on that item" in prompt
