"""Final run (10 Nov 2026): OpenRouter routing, billed cost, the judgement tier's fallback and the budget guard.
No network: models are built but not called, and histories are filled by hand."""
from dataclasses import replace

import pytest

from investsync.config import LLMEndpoint
from investsync.narrative import commentary as c


@pytest.fixture
def orset(monkeypatch):
    s = replace(c.settings, openrouter_key="test-key",
                openrouter_provider='{"order":["deepinfra/fp8","deepseek"],"allow_fallbacks":false}',
                openrouter_judge_provider='{"order":["anthropic"],"allow_fallbacks":false}',
                judge_model="openrouter/anthropic/claude-sonnet-5.5", judge_effort="medium", run_budget_usd=0.0)
    monkeypatch.setattr(c, "settings", s)
    monkeypatch.setattr(c, "_LMS", [])
    return s


EP = LLMEndpoint("primary", "https://openrouter.ai/api/v1", "openrouter/deepseek/deepseek-v4.1-flash-1017", "k")


def test_openrouter_lm_settings(orset):
    off = c.make_lm(EP, max_tokens=3000, thinking="disabled", step="research")
    assert off.kwargs["extra_body"]["reasoning"] == {"effort": "none"}
    assert off.kwargs["extra_body"]["provider"]["order"][0] == "deepinfra/fp8"
    assert off.kwargs["max_tokens"] == 3000
    hi = c.make_lm(EP, max_tokens=6000, thinking="enabled", effort="high", step="think")
    assert hi.kwargs["extra_body"]["reasoning"] == {"effort": "high"} and hi.kwargs["max_tokens"] == 65536
    j = c.make_lm(EP, max_tokens=10000, thinking="enabled", model=orset.judge_model, effort="medium", step="judge")
    assert j.kwargs["extra_body"]["reasoning"] == {"effort": "medium"}
    assert j.kwargs["extra_body"]["provider"]["order"] == ["anthropic"]
    assert j.kwargs.get("temperature") is None and j.kwargs["max_tokens"] == 10000  # no 65k bump for the judge


def test_usage_prefers_billed_cost(orset):
    lm = c.make_lm(EP, max_tokens=3000, thinking="disabled", step="research")
    snap = c.usage_snapshot()
    lm.history.append({"model": "openrouter/deepseek/deepseek-v4.1-flash-1017", "cost": 0.0123,
                       "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})
    lm.history.append({"model": "openrouter/deepseek/deepseek-v4.1-flash-1017", "cost": 0.0,
                       "usage": {}})  # a DSPy cache replay: nothing billed
    u = c.usage_since(snap)
    assert u.calls == 1 and u.est_cost_usd == pytest.approx(0.0123)
    assert u.price_note.startswith("Cost as billed by OpenRouter")
    assert u.models == ["deepseek/deepseek-v4.1-flash-1017"]
    assert c.spent_usd() == pytest.approx(0.0123)


def test_judgement_tier_falls_back_and_respects_the_budget(orset, monkeypatch):
    judge, think = object(), object()

    def boom(m):
        if m is judge:
            raise RuntimeError("403 from the judgement provider")
        return "ok on think"
    assert c._with_fallback(boom, judge, think, "x") == "ok on think"
    assert c._with_fallback(lambda m: None if m is judge else "think", judge, think, "x") == "think"
    assert c._with_fallback(lambda m: "judge" if m is judge else "think", judge, think, "x") == "judge"
    monkeypatch.setattr(c, "settings", replace(c.settings, run_budget_usd=0.5))
    monkeypatch.setattr(c, "spent_usd", lambda: 0.6)
    assert c._tier(judge, think) is think  # over budget: the judgement steps use the primary model
    monkeypatch.setattr(c, "spent_usd", lambda: 0.1)
    assert c._tier(judge, think) is judge
