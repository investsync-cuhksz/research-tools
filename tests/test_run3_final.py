"""Run 3 (12 Nov 2026, the final paid run): the top model at chosen judgement steps, cost per phase and per report,
and the research desk's filter counts."""
from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path

import pytest

from investsync.config import settings
from investsync.narrative import commentary as cm
from investsync.research import desk

from dataclasses import dataclass
from datetime import date


@dataclass
class FakeDoc:
    id: str
    kind: str
    title: str
    source: str
    published: date
    url: str
    lang: str
    text: str
    snippet: str = ""


RELEASE = FakeDoc("rel", "results_release", "Acme Announces Financial Results for Second Quarter", "SEC EDGAR",
                  date(2026, 8, 26), "https://www.sec.gov/rel.htm", "en",
                  "Acme Announces Financial Results. Revenue was $9.0 billion for the second quarter. " * 3)


def _news(i, title, day, text="x" * 900, source="Bing News: Reuters"):
    return FakeDoc(f"n{i}", "news", title, source, day, f"https://example.com/{i}", "en", text)


class FakeLM:
    def __init__(self, model="openrouter/acme/model"):
        self.history: list = []
        self.model = model

    def call(self, cost=0.01, pt=100, ct=10):
        self.history.append({"model": self.model, "cost": cost,
                             "usage": {"prompt_tokens": pt, "completion_tokens": ct}})


@pytest.fixture
def lms(monkeypatch):
    monkeypatch.setattr(cm, "_LMS", [])
    monkeypatch.setattr(cm, "_STEP", {})
    monkeypatch.setattr(cm, "_PHASE", {})
    a, b = FakeLM("openrouter/deepseek/flash"), FakeLM("openrouter/anthropic/claude-opus-5.5")
    for lm, step in ((a, "writer"), (b, "top")):
        cm._LMS.append(lm)
        cm._STEP[id(lm)] = step
    return a, b


def test_usage_phase_labels_calls_innermost_wins(lms):
    a, b = lms
    snap = cm.usage_snapshot()
    a.call(0.01)  # outside any phase: keeps its step label
    with cm.usage_phase("debate"):
        a.call(0.02)
        with cm.usage_phase("debate judge"):
            b.call(0.10)
    u = cm.usage_since(snap)
    assert set(u.by_phase) == {"writer", "debate", "debate judge"}
    assert u.by_phase["debate judge"]["models"] == ["anthropic/claude-opus-5.5"]
    assert u.by_phase["debate"]["est_cost_usd"] == pytest.approx(0.02)
    assert sum(p["est_cost_usd"] for p in u.by_phase.values()) == pytest.approx(u.est_cost_usd)


def test_top_model_only_for_listed_steps_and_under_budget(monkeypatch, lms):
    top = object()
    monkeypatch.setattr(cm, "_TOP_LM", top)
    monkeypatch.setattr(cm, "settings", dataclasses.replace(settings, top_steps="scenarios,deep review",
                                                             top_budget_usd=0.5, run_budget_usd=0.0))
    monkeypatch.setattr(cm, "spent_usd", lambda: 0.2)
    assert cm._top_for("scenarios") is top and cm._top_for("learner coach") is None
    monkeypatch.setattr(cm, "spent_usd", lambda: 0.6)
    assert cm._top_for("scenarios") is None  # past TOP_BUDGET_USD: the judgement model takes the step


def test_with_fallback_goes_top_then_judge_then_primary(monkeypatch, lms):
    top, judge, think = "top", "judge", "think"
    monkeypatch.setattr(cm, "_TOP_LM", top)
    monkeypatch.setattr(cm, "settings", dataclasses.replace(settings, top_steps="scenarios", top_budget_usd=0.0,
                                                             run_budget_usd=0.0))
    seen = []

    def fn(m):
        seen.append(m)
        if m == "top":
            raise RuntimeError("provider down")
        return None if m == "judge" else "ok"
    assert cm._with_fallback(fn, judge, think, "scenarios") == "ok"
    assert seen == ["top", "judge", "think"]
    seen.clear()
    assert cm._with_fallback(lambda m: seen.append(m) or m, judge, think, "analyst questions") == "judge"
    assert seen == ["judge"]  # not a top step


def test_research_filter_counts(monkeypatch):
    monkeypatch.setattr(desk, "_low_tier", lambda d: d.source == "Bing News: SomeBlog")
    import investsync.research.sources as rs
    dup = _news(1, "Acme beats", RELEASE.published)
    docs = [RELEASE, dup, _news(1, "Acme beats (again)", RELEASE.published), _news(2, "blog", RELEASE.published,
            source="Bing News: SomeBlog"), _news(3, "empty", RELEASE.published, text="")]
    monkeypatch.setattr(rs, "primary_docs", lambda *a: docs)
    monkeypatch.setattr(rs, "broker_docs", lambda *a: [])
    stats: dict = {}
    out = desk.collect(None, [], RELEASE.published, stats=stats)
    assert stats == {"found": 5, "duplicates": 1, "no_text": 1, "not_on_list": 1, "documents": 2}
    assert len(out) == 2
    picked = desk.select_chunks(out, [("events", "q")], 50, stats=stats)
    assert stats["excerpts_read"] == len(picked) and stats["candidate_excerpts"] >= len(picked)


def _tool():
    spec = importlib.util.spec_from_file_location("cost_split", Path(__file__).parents[1] / "tools/cost_split.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cost_split_by_report():
    tool = _tool()
    ph = lambda c, m="x": {"est_cost_usd": c, "calls": 1, "prompt_tokens": 10, "completion_tokens": 1, "models": [m]}
    deep = {"ai_usage": {"calls": 4, "by_phase": {"research": ph(0.03), "scenarios": ph(0.12), "debate": ph(0.06),
                                                  "deep review": ph(0.1)}}}
    simple = {"ai_usage": {"calls": 2, "by_phase": {"writer": ph(0.04), "learner coach": ph(0.07)}}}
    res = tool.split(deep, simple)
    assert res["reports"] == {"standard": pytest.approx(0.07), "learner": pytest.approx(0.14),
                              "deep": pytest.approx(0.21)}
    assert res["total_usd"] == pytest.approx(0.42)
    with pytest.raises(ValueError):  # run 2's JSON: no by_phase
        tool.split({"ai_usage": {"calls": 3, "by_step": {"judge": {}}}}, simple)
