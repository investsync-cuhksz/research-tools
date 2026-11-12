"""Claim check: risky sentences picked in code; the checker's objections and 'ok' causes verified in code."""
import json

from dspy.utils import DummyLM

from investsync.narrative import claimcheck as cc
from investsync.narrative.commentary import ADAPTER

SOURCES = cc.sources_text(
    "Latest reported period: 3Q 2026 gross margin 20.7% vs 25.8% a year earlier.\n"
    "Total debt rose to RMB 452,963mn from RMB 387,733mn; net cash fell to RMB 58,665mn.",
    "[1] 2026-10-21 | Brokers blame product mix and the new consumption tax for the margin drop.", "None")


def test_candidates_pick_risky_sentences_page_one_first():
    parts = {"company_overview": "CATL makes batteries for electric cars and storage systems worldwide.",
             "thesis": "Margins fell as lithium prices rose. The company is internally funded rather than debt-dependent.",
             "news_summary": "The shares fell after results because of margin pressure."}
    got = cc.candidates(parts)
    assert [s for _, s in got] == ["Margins fell as lithium prices rose.",
                                   "The company is internally funded rather than debt-dependent.",
                                   "The shares fell after results because of margin pressure."]


def test_objections_need_real_evidence_and_ok_causes_need_real_support():
    parts = {"thesis": "Margins fell as lithium prices rose. The company is internally funded rather than "
                       "debt-dependent. The shares fell after results because of margin pressure from the new "
                       "consumption tax and product mix."}
    verdicts = [
        {"n": 1, "verdict": "ok", "check": 0, "problem": "", "evidence": "", "fix": "",
         "support": "lithium prices rose sharply"},                                      # support invented -> flagged
        {"n": 2, "verdict": "wrong", "check": 6, "problem": "Debt rose and net cash fell.",
         "evidence": "Total debt rose to RMB 452,963mn from RMB 387,733mn", "fix": "Say debt rose."},  # kept
        {"n": 3, "verdict": "ok", "check": 0, "problem": "", "evidence": "", "fix": "",
         "support": "Brokers blame product mix and the new consumption tax for the margin drop"},     # backed -> ok
    ]
    lm = DummyLM([{"verdicts": json.dumps(verdicts)}])
    notes, stats = cc.check(parts, SOURCES, "CATL", lm, ADAPTER)
    assert [n.quote for n in notes] == ["Margins fell as lithium prices rose.",
                                        "The company is internally funded rather than debt-dependent."]
    assert notes[0].problem.startswith("unsupported (check 2)") and stats["cause_unbacked"] == 1
    assert notes[1].problem.startswith("wrong (check 6)") and "452,963" in notes[1].problem


def test_objection_with_invented_evidence_is_dropped():
    parts = {"thesis": "Gross margin expanded strongly in the latest quarter."}
    verdicts = [{"n": 1, "verdict": "wrong", "check": 1, "problem": "It fell.",
                 "evidence": "gross margin fell to 12.0% in the quarter", "fix": "Say it fell."}]
    notes, stats = cc.check(parts, SOURCES, "CATL", DummyLM([{"verdicts": json.dumps(verdicts)}]), ADAPTER)
    assert notes == [] and stats["no_evidence"] == 1


def test_final_check_only_sees_new_sentences_and_strips_flagged(monkeypatch):
    from types import SimpleNamespace
    from investsync.narrative import commentary as c
    seen = {}

    def fake_check(parts, sources, company, lm, adapter, limit=cc.MAX_CLAIMS):
        seen.update(parts)
        q = "Confidence is low because terminal value is 85% of EV."
        return [cc.ReviewNote(section="rating_rationale", quote=q, problem="unsupported (check 3): wrong cause",
                              fix="Say the methods disagree.")], {}
    monkeypatch.setattr(c.claimcheck, "check", fake_check)
    d = SimpleNamespace(TEXT=("rating_rationale", "thesis"), LISTS=(),
                        rating_rationale="The rule-based Buy blends three methods. Confidence is low because terminal "
                                         "value is 85% of EV.", thesis="Revenue rose 56.2% in 9M 2026.")
    monkeypatch.setattr(c, "draft_parts", lambda x: {"rating_rationale": x.rating_rationale, "thesis": x.thesis})
    first = "## rating_rationale\nThe rule-based Buy blends three methods.\n\n## thesis\nRevenue rose 56.2% in 9M 2026."
    notes = c._new_sentence_check("sources", "CATL", object())(d, first)
    assert seen == {"rating_rationale": "Confidence is low because terminal value is 85% of EV."}
    c._strip_flagged(d, notes)
    assert d.rating_rationale == "The rule-based Buy blends three methods."


def test_first_batch_runs_alone_so_the_sources_prefix_is_cached(monkeypatch):
    """The provider caches a prompt prefix only after a call: batch 1 must finish before the rest start."""
    import threading
    order, lock = [], threading.Lock()

    def fake_predict(sig):
        def run(sources, company, claims):
            n = int(claims.split("]")[0][1:])
            with lock:
                order.append(("start", n))
            with lock:
                order.append(("end", n))
            return SimpleNamespace(verdicts=[])
        return run
    from types import SimpleNamespace
    monkeypatch.setattr(cc.dspy, "Predict", fake_predict)
    parts = {"thesis": " ".join(f"Margins fell in year {i} because costs rose sharply." for i in range(12))}
    notes, stats = cc.check(parts, SOURCES, "CATL", object(), ADAPTER, limit=12)
    assert stats["calls"] == 3 and notes == []
    assert order[:2] == [("start", 1), ("end", 1)]


def test_flagged_list_items_are_cut_or_dropped_but_reviewer_flags_are_not():
    from types import SimpleNamespace
    from investsync.narrative import commentary as c
    P = c.Point
    d = SimpleNamespace(TEXT=("thesis",), LISTS=("risks",), thesis="Revenue rose 56.2% in 9M 2026 on storage demand.",
                        risks=[P(title="Margin squeeze", text="Gross margin fell to 20.7%. Lithium prices caused all of it."),
                               P(title="Invented risk", text="A probe was opened by regulators into the company."),
                               P(title="Tax", text="A 4% consumption tax starts in September 2027.")])
    notes = [cc.ReviewNote(section="risks", quote="Lithium prices caused all of it.", problem="unsupported (check 2): x", fix="f"),
             cc.ReviewNote(section="risks", quote="A probe was opened by regulators into the company.", problem="wrong (check 1): x", fix="f"),
             # the deep reviewer only sees the evidence list: its "unsupported claim" may be real news, so it stays
             cc.ReviewNote(section="thesis", quote="on storage demand", problem="unsupported claim", fix="f")]
    c._strip_flagged(d, notes)
    assert [r.title for r in d.risks] == ["Margin squeeze", "Tax"]
    assert d.risks[0].text == "Gross margin fell to 20.7%."
    assert d.thesis.endswith("storage demand.") and "(Removed in code" in notes[0].fix


def test_failed_batch_is_retried_once_with_a_fresh_call(monkeypatch):
    """A batch that fails (e.g. cut off at max_tokens) is retried with a new rollout_id; if it fails twice it is
    counted, so unchecked sentences are visible in the stats."""
    from types import SimpleNamespace
    seen = []

    def fake_predict(sig):
        def run(sources, company, claims, **kw):
            seen.append(kw.get("config", {}).get("rollout_id"))
            if len(seen) == 1:
                raise ValueError("The LM returned an empty or null response.")
            return SimpleNamespace(verdicts=[])
        return run
    monkeypatch.setattr(cc.dspy, "Predict", fake_predict)
    parts = {"thesis": "Margins fell because costs rose sharply."}
    notes, stats = cc.check(parts, SOURCES, "CATL", object(), ADAPTER, limit=4)
    assert seen == [None, 1] and stats["failed_batches"] == 0

    def always_fail(sig):
        def run(sources, company, claims, **kw):
            raise ValueError("empty")
        return run
    monkeypatch.setattr(cc.dspy, "Predict", always_fail)
    notes, stats = cc.check(parts, SOURCES, "CATL", object(), ADAPTER, limit=4)
    assert notes == [] and stats["failed_batches"] == 1


def test_printed_evidence_drops_the_writers_instructions():
    from investsync.narrative.evidence import reader_text
    assert reader_text("Mechanical DCF USD 270.21: a cross-check. Call it 'the mechanical DCF', never 'our base "
                       "case'; the reverse DCF uses it too.") == ("Mechanical DCF USD 270.21: a cross-check. The "
                                                                 "reverse DCF uses it too.")
    assert reader_text("Overall view (from the AI rating; refer to it as \"the overall view\", never as a rating): "
                       "Buy, 4.64 on a 1-5 scale.") == "Overall view (from the AI rating): Buy, 4.64 on a 1-5 scale."
    assert reader_text("Reuters (press report: attribute it): NVIDIA signed a deal with Acme Inc. for chips.") == \
        "Reuters (press report): NVIDIA signed a deal with Acme Inc. for chips."
    plain = "On 2 Sep NVIDIA agreed to acquire Hugging Face, Inc. for about $11.9 billion."
    assert reader_text(plain) == plain
