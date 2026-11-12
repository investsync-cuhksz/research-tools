"""Commentary pipeline end to end with a scripted LM (no network, no API key)."""
import json
from pathlib import Path

import dspy
import pytest
from dspy.utils.dummies import DummyLM

from investsync.narrative import commentary
from investsync.render.render import render_pdf
from investsync.schema import TearSheetData

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "0700_HK.json"


@pytest.fixture()
def data() -> TearSheetData:
    return TearSheetData.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


SECTIONS = {
    "tagline": "A cash-rich platform leader whose valuation trails its profitability.",
    "thesis": "Profitability keeps improving while the shares trade below the peer median, so the rule-based rating is driven by the DCF and peer multiples agreeing.",
    "company_overview": "Tencent runs messaging, games, advertising, fintech and cloud services in China. Value-added services remain the largest segment.",
    "financial_analysis": "Margins expanded as higher-margin services grew, and cash conversion stayed above one.",
    "valuation_overview": "The DCF, peer multiples and the stock's own P/E history point the same way.",
    "competitive_analysis": "Tencent combines scale with margins that most peers do not match.",
    "news_summary": "Recent news focused on AI investment and capital returns.",
    "report_summary": "Management highlighted AI products and steady growth in the latest interim report.",
    "rating_rationale": "The rating follows from the blended fair value of the methods shown, which agree closely.",
    "key_takeaways": json.dumps(["Margins keep rising.", "Earnings are backed by cash.", "Shares lag the index.",
                                 "Valuation sits below peers."]),
    "events_to_monitor": json.dumps([{"title": "Quarterly results", "text": "The next results update the growth picture."},
                                     {"title": "Dividend payment", "text": "The payout signals capital-return policy."}]),
}


def draft(dupont: str, n_catalysts: int = 3, **over) -> dict:
    return {**_draft(dupont, n_catalysts), **SECTIONS, **over}


def _draft(dupont: str, n_catalysts: int = 3) -> dict:
    cats = [{"title": "Video Accounts monetisation", "text": "Ad load on Video Accounts is still low, leaving room for marketing services growth."},
            {"title": "AI lifts games and ads", "text": "Morningstar names Tencent a top long-term AI pick, with AI supporting advertising and games."},
            {"title": "Margin mix keeps improving", "text": "Gross margin rose from 43.9% in FY2021 to 56.2% in FY2025 as high-margin services grew."}]
    return {
        "reasoning": "Notable changes, then ratios, then synthesis.",
        "dupont_commentary": dupont,
        "comps_commentary": "Tencent trades at 14.8x P/E versus a 19.1x peer median, a -22.6% discount despite stronger profitability.",
        "catalysts": json.dumps(cats[:n_catalysts]),
        "risks": json.dumps([
            {"title": "Regulatory scrutiny", "text": "Gaming approvals and platform rules can change quickly in China."},
            {"title": "Share price momentum", "text": "The stock fell -30.8% over 1Y against -4.4% for the Hang Seng Index."}]),
    }


CLEAN = "ROE of 21.1% is driven by a 29.9% net margin and 1.80x leverage; cash conversion of 1.35x signals high earnings quality."
DIRTY = "ROE of 23.4% is driven by a 31.7% net margin; cash conversion of 1.35x signals high earnings quality."


def test_clean_draft_passes_first_time(data):
    n = commentary.generate(data, lm=DummyLM([draft(CLEAN)]), news_step=False)
    assert n.status == "generated"
    assert n.guardrail.passed and n.guardrail.attempts == 1
    assert len(n.catalysts) == 3 and len(n.risks) == 2


def test_invented_numbers_are_fed_back_then_fixed(data):
    lm = DummyLM([draft(DIRTY), draft(CLEAN)])
    n = commentary.generate(data, lm=lm, news_step=False)
    assert n.status == "generated" and n.guardrail.attempts == 2
    second_prompt = str(lm.history[-1]["messages"])
    assert "23.4%" in second_prompt and "31.7%" in second_prompt  # the model was told exactly what failed


def test_persistent_hallucination_is_flagged(data):
    n = commentary.generate(data, lm=DummyLM([draft(DIRTY)] * 3), news_step=False)
    assert n.status == "flagged"
    assert set(n.guardrail.unmatched_numbers) == {"23.4%", "31.7%"}


def test_wrong_number_of_catalysts_is_retried(data):
    n = commentary.generate(data, lm=DummyLM([draft(CLEAN, n_catalysts=2), draft(CLEAN)]), news_step=False)
    assert n.status == "generated" and n.guardrail.attempts == 2


def _pages(pdf: bytes) -> int:
    import re
    return len(re.findall(rb"/Type\s*/Page(?!s)\b", pdf))


def test_full_page_still_fits_one_page(data):
    data.narrative = commentary.generate(data, lm=DummyLM([draft(CLEAN)]), news_step=False)
    pdf = render_pdf(data, layout="tearsheet")
    assert pdf.startswith(b"%PDF")
    assert _pages(pdf) == 1


def test_page_one_prints_our_headline_and_thesis(data):
    # 9 Nov 2026: the tagline and thesis were written but printed only on page 2 of the full report
    data.narrative = commentary.generate(data, lm=DummyLM([draft(CLEAN)]), news_step=False)
    from investsync.render.viewmodel import build
    vm = build(data)
    assert vm["narrative"]["tagline"] == data.narrative.tagline and vm["narrative"]["thesis"] == data.narrative.thesis
    from pypdf import PdfReader
    import io
    text = PdfReader(io.BytesIO(render_pdf(data, layout="tearsheet"))).pages[0].extract_text()
    assert data.narrative.tagline.split()[0] in text and "KEY CATALYSTS" in text


def test_placeholder_page_renders(data):
    data.narrative = commentary.placeholder()
    assert _pages(render_pdf(data, layout="tearsheet")) == 1


def test_us_stock_with_english_news():
    us = TearSheetData.model_validate_json((FIXTURE.parent / "NVDA.json").read_text(encoding="utf-8"))
    ans = {
        "reasoning": "Notable changes, then ratios, then synthesis.",
        "dupont_commentary": "ROE is driven mainly by a very high net margin rather than leverage.",
        "comps_commentary": "The shares trade below the peer median P/E despite stronger growth.",
        "catalysts": json.dumps([{"title": "Upcoming quarterly results", "text": "Results are scheduled, a near-term test of data-centre demand."},
                                 {"title": "AI infrastructure demand", "text": "Hyperscaler spending remains the main driver of orders."},
                                 {"title": "New product cycle", "text": "Next-generation GPUs extend the product lead."}]),
        "risks": json.dumps([{"title": "China export restrictions", "text": "Chips are piling up in Hong Kong as import approval is withheld."},
                             {"title": "Valuation sensitivity", "text": "Any slowdown in AI spending could compress the multiple."}]),
        **SECTIONS,
    }
    lm = DummyLM([ans])
    n = commentary.generate(us, lm=lm, news_step=False)
    assert n.status == "generated" and len(n.catalysts) == 3 and len(n.risks) == 2
    prompt = str(lm.history[-1]["messages"])
    assert "Next scheduled results" in prompt           # earnings date reaches the model
    assert "Nvidia" in prompt or "NVIDIA" in prompt     # English news reaches the model


class _DownLM(DummyLM):
    """A model whose provider is down."""

    def __init__(self):
        super().__init__([{}])
        self.model = "primary-down"

    def __call__(self, *a, **k):
        raise ConnectionError("provider unavailable")

    forward = __call__


def test_backup_model_used_when_primary_fails(data):
    backup = DummyLM([draft(CLEAN)])
    backup.model = "glm-backup"
    n = commentary.generate(data, lm=[_DownLM(), backup], news_step=False)
    assert n.status == "generated" and n.model == "glm-backup"


def test_all_models_down_raises(data):
    with pytest.raises(RuntimeError, match="all models failed"):
        commentary.generate(data, lm=[_DownLM()], news_step=False)


def test_two_step_concept_then_thesis(data):
    concept = {"reasoning": "r", "dupont_commentary": CLEAN,
               "comps_commentary": "Tencent trades at 14.8x P/E versus a 19.1x peer median.",
               "key_findings": json.dumps(["Gross margin keeps rising.", "Shares lagged the index over 1Y."])}
    d = draft(CLEAN)
    thesis = {"reasoning": "r", "catalysts": d["catalysts"], "risks": d["risks"], **SECTIONS}
    lm = DummyLM([concept, thesis])
    n = commentary.generate(data, lm=lm, mode="two_step", news_step=False)
    assert n.status == "generated" and n.mode == "two_step"
    assert len(n.catalysts) == 3 and len(n.risks) == 2
    assert "Gross margin keeps rising." in str(lm.history[-1]["messages"])  # thesis sees the findings


# ---------------------------------------------------------------- full-report AI step
def test_every_report_section_is_filled(data):
    n = commentary.generate(data, lm=DummyLM([draft(CLEAN)]), news_step=False)
    assert n.status == "generated"
    assert n.thesis and n.company_overview and n.valuation_overview and n.rating_rationale
    assert len(n.key_takeaways) == 4 and len(n.events_to_monitor) == 2


def test_contradicting_the_rule_based_rating_is_sent_back(data):
    from investsync.schema import Rating
    data.rating = Rating(rating="Hold", currency="HKD", buy_threshold=0.15, sell_threshold=-0.10)
    wrong = draft(CLEAN, rating_rationale="We rate the shares BUY because the upside is large.")
    lm = DummyLM([wrong, draft(CLEAN)])
    n = commentary.generate(data, lm=lm, news_step=False)
    assert n.status == "generated" and n.guardrail.attempts == 2
    assert "The AI rating is Hold" in str(lm.history[-1]["messages"])


def test_over_long_section_is_sent_back(data):
    long = draft(CLEAN, tagline=" ".join(["growth"] * 40))
    lm = DummyLM([long, draft(CLEAN)])
    n = commentary.generate(data, lm=lm, news_step=False)
    assert n.guardrail.attempts == 2 and "Shorten `tagline`" in str(lm.history[-1]["messages"])


def test_news_step_tags_news_and_drops_invented_figures(data):
    ranked = commentary._rank_news(data)
    assert len(ranked) >= 2
    tags = [{"index": 1, "relevant": True, "category": "earnings", "sentiment": "positive",
             "headline_en": "Tencent shares draw strong buying interest"},
            {"index": 2, "relevant": False, "category": "market", "sentiment": "neutral",
             "headline_en": "Index rises 987.6 points"}]          # 987.6 is not in that item
    lm = DummyLM([{"tags": json.dumps(tags)}, draft(CLEAN)])
    n = commentary.generate(data, lm=lm)
    assert n.status == "generated"
    first, second = ranked[0], ranked[1]
    assert first.category == "earnings" and first.sentiment == "positive"
    assert first.headline_en == "Tencent shares draw strong buying interest"
    assert second.relevant is False and second.headline_en is None   # invented figure -> original title kept
    assert "(earnings, positive)" in str(lm.history[-1]["messages"])  # the writer sees the tags


def test_news_step_failure_does_not_block_the_writer(data):
    bad = {"tags": "not json"}
    lm = DummyLM([bad, bad, draft(CLEAN)])  # DSPy retries a parse failure once with its JSON adapter
    n = commentary.generate(data, lm=lm)
    assert n.status == "generated"


def test_json_fallback_uses_plain_json_mode():
    # DeepSeek rejects DSPy's default strict-schema request ("This response_format type is unavailable now")
    lm = dspy.LM("deepseek/deepseek-flash", api_key="test")
    kw: dict = {}
    commentary.ADAPTER._make_json_adapter_fallback()._prepare_response_format(lm, kw, commentary.ResearchWriter)
    assert kw["response_format"] == {"type": "json_object"}


def test_a_draft_missing_fields_is_retried_not_dropped(data):
    short = {k: v for k, v in draft(CLEAN).items() if k not in ("tagline", "thesis")}
    lm = DummyLM([short, short, draft(CLEAN)])   # the model stops early; DSPy's JSON retry fails too
    n = commentary.generate(data, lm=lm, news_step=False)
    assert n.status == "generated" and n.guardrail.attempts == 2 and n.thesis
    assert "left out these output fields: tagline, thesis" in str(lm.history[-1]["messages"])
