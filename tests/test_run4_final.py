"""Run 4 (12 Nov 2026): the round-12 accuracy fixes and the design changes (deciding year, the thesis memo printed as
written, prompt caching)."""
from __future__ import annotations

import dataclasses
import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

import pytest

from investsync.config import settings
from investsync.narrative import commentary as cm
from investsync.narrative import factcheck
from investsync.research import desk


# ---------------------------------------------------------------- event dates
def test_event_date_from_quote_only_for_news():
    pub = date(2026, 9, 29)
    assert desk.event_date("On Sept. 28, NVIDIA authorized an additional $150 billion", pub) == date(2026, 9, 28)
    assert desk.event_date("NVIDIA added $150 billion to its authorization", date(2026, 10, 1)) is None
    assert desk.event_date("On Sept. 28 ...", pub, kind="results_release") is None  # dated by its filing
    assert desk.event_date("On Sept. 28 and Oct. 1 ...", date(2026, 10, 2)) is None  # two dates: ambiguous


def _fact(i, text, pub, kind="news", topic="capital", quote=None):
    from investsync.schema import ResearchFact
    return ResearchFact(id=i, topic=topic, text=text, quote=quote or text, source="Bing News: X", title=text[:40],
                        published=pub, kind=kind)


def test_event_date_shared_by_notes_on_one_event():
    a = _fact("R7", "NVIDIA added $150 billion to its share repurchase authorization.", date(2026, 10, 1))
    b = _fact("R65", "On Sept. 28, NVIDIA authorized an additional $150 billion for stock buybacks.",
              date(2026, 9, 29), topic="events")
    b.event_date = desk.event_date(b.quote, b.published)
    desk.share_event_dates([a, b])
    assert a.event_date == date(2026, 9, 28)


def _data(facts, pe=22.0):
    research = NS(facts=facts)
    return NS(research=research, quote=NS(as_of=date(2026, 11, 11), pe_ttm=pe))


def test_sentence_dated_by_publication_day_is_flagged():
    ban = _fact("R52", "Washington bans the export of Nvidia's top-end Blackwell and Rubin GPUs to China.",
                date(2026, 11, 10), topic="policy")
    ctx = factcheck.context(_data([ban]))
    bad = "Washington banned exports of Blackwell and Rubin GPUs to China on 10 Nov 2026."
    ok = "The Straits Times reported on 10 Nov 2026 that exports of Blackwell and Rubin GPUs to China are barred."
    close = "News since the 10 November close is dominated by export rules for Blackwell and Rubin GPUs."
    assert [i.check for i in factcheck._event_dates([bad], ctx)] == ["event_date"]
    assert factcheck._event_dates([ok, close], ctx) == []


def test_non_disclosure_and_trailing_pe_label():
    ctx = factcheck.context(_data([]))
    assert factcheck._non_disclosure(["Purchase obligations are not disclosed in the latest filing."], ctx)
    assert not factcheck._non_disclosure(["It bought the firm for an undisclosed sum."], ctx)
    assert factcheck._pe_label(["The shares trade at 22.0x last year's profit."], ctx)
    assert not factcheck._pe_label(["Trailing P/E 22.0x; 35.5x last year's EPS."], ctx)


# ---------------------------------------------------------------- consensus on a like-for-like basis
def test_mixed_basis_detected_from_filed_nonoperating_income():
    from investsync.narrative import forecast
    from investsync.schema import FilingFact
    d = NS(financials=NS(latest=NS(net_income=118_010e6), currency="USD"),
           filing_facts=[FilingFact(key="nonoperating_ytd", label="Total non-operating income", value=24_140e6,
                                    currency="USD")])
    assert forecast._mixed_basis(d) == "USD 24.1bn"
    d.filing_facts[0].value = 2e9
    assert forecast._mixed_basis(d) is None


# ---------------------------------------------------------------- the thesis memo printed as written
def test_brief_thesis_replaces_writer_thesis_only_when_figures_check(monkeypatch):
    monkeypatch.setattr(cm, "settings", dataclasses.replace(settings, brief_thesis=True))
    brief = ("- Tagline (by the lead analyst; use it as the report's tagline as written): Demand holds; the price "
             "does not\n- Thesis paragraph (by the lead analyst; use it ...): " + "Revenue rose 95.8% and " * 8 + "x.")
    n = NS(thesis="writer's version", tagline="writer's tagline", status="generated")
    from investsync.narrative import guardrail
    allowed = guardrail.build_allowed("Revenue rose 95.8% in the first half.")
    cm._brief_thesis(n, brief, allowed)
    assert n.thesis.startswith("Revenue rose 95.8%") and n.tagline.startswith("Demand holds")
    n2 = NS(thesis="writer's version", tagline="t", status="generated")
    cm._brief_thesis(n2, brief.replace("95.8%", "97.1%"), allowed)
    assert n2.thesis == "writer's version"  # a figure not in the data: the writer's thesis stays


# ---------------------------------------------------------------- prompt caching
def test_cache_split_before_the_first_volatile_field():
    body = "[[ ## company ## ]]\nAcme\n\n[[ ## facts ## ]]\n" + "x" * 6000 + "\n\n[[ ## feedback ## ]]\nNone\n"
    cut = cm.cache_split(body)
    assert body[cut:].startswith("[[ ## feedback ## ]]")
    assert cm.cache_split("[[ ## facts ## ]]\nshort\n") is None


class _Fake(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.seen.append(body)
        reply = {"id": "x", "object": "chat.completion", "created": 0, "model": body.get("model"),
                 "choices": [{"index": 0, "finish_reason": "stop", "message": {
                     "role": "assistant", "content": "[[ ## answer ## ]]\nok\n\n[[ ## completed ## ]]"}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
        out = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_claude_request_carries_one_cache_breakpoint(monkeypatch):
    import dspy
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("OPENROUTER_API_BASE", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr(cm, "settings", dataclasses.replace(settings, prompt_cache=True, openrouter_key="test"))

    class Sig(dspy.Signature):
        """Answer."""
        facts: str = dspy.InputField()
        feedback: str = dspy.InputField()
        answer: str = dspy.OutputField()
    try:
        for model in ("openrouter/anthropic/claude-sonnet-5.5", "openrouter/deepseek/deepseek-v4.1-flash-1017"):
            lm = cm._openrouter_lm(model, 200, None, None)
            lm.cache = False
            with dspy.context(lm=lm, adapter=cm.ADAPTER):
                dspy.Predict(Sig)(facts="figures " * 900 + model, feedback="None")
    finally:
        srv.shutdown()
    claude, flash = _Fake.seen[-2], _Fake.seen[-1]
    parts = claude["messages"][-1]["content"]
    assert isinstance(parts, list) and parts[0].get("cache_control") == {"type": "ephemeral"}
    assert "[[ ## feedback ## ]]" in parts[1]["text"]
    assert isinstance(flash["messages"][-1]["content"], str)  # the cheap model's prompt is unchanged
