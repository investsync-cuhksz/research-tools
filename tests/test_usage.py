"""ai_usage: totals and the per-step split (writer / think / check / research), priced in code."""
from types import SimpleNamespace

from investsync.narrative import commentary as c


def _lm(step, calls):
    lm = SimpleNamespace(history=[])
    c._LMS.append(lm)
    c._STEP[id(lm)] = step
    lm.history += calls
    return lm


def test_usage_is_split_by_step_and_cached_calls_are_free():
    snap = c.usage_snapshot()
    call = {"model": "deepseek/deepseek-flash",
            "usage": {"prompt_tokens": 10_000, "prompt_cache_hit_tokens": 4_000, "completion_tokens": 2_000,
                      "completion_tokens_details": {"reasoning_tokens": 1_500}}}
    _lm("check", [call, call, {"model": "deepseek/deepseek-flash", "usage": {}}])  # last one: DSPy cache hit
    _lm("think", [call])
    u = c.usage_since(snap)
    assert u.calls == 3 and u.by_step["check"]["calls"] == 2 and u.by_step["think"]["calls"] == 1
    one = (6_000 * 0.30 + 4_000 * 0.006 + 2_000 * 1.20) / 1e6
    assert abs(u.by_step["check"]["est_cost_usd"] - 2 * one) < 1e-5
    assert abs(u.est_cost_usd - 3 * one) < 1e-5
    assert u.by_step["think"]["reasoning_tokens"] == 1_500


def test_truncated_calls_are_counted_per_step():
    snap = c.usage_snapshot()
    resp = lambda fr: SimpleNamespace(choices=[SimpleNamespace(finish_reason=fr)])
    call = {"model": "deepseek/deepseek-flash", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
    _lm("check", [dict(call, response=resp("length")), dict(call, response=resp("stop"))])
    u = c.usage_since(snap)
    assert u.by_step["check"]["truncated"] == 1


def test_thinking_calls_get_deepseeks_own_output_limit():
    from investsync.config import LLMEndpoint
    ep = LLMEndpoint("primary", "https://api.deepseek.com", "deepseek-flash", "test-key-not-real")
    assert c.make_lm(ep, max_tokens=32000, thinking="enabled", effort="max").kwargs["max_tokens"] == 131072
    assert c.make_lm(ep, max_tokens=32000, thinking="enabled", effort="high").kwargs["max_tokens"] == 65536
    assert c.make_lm(ep, max_tokens=6000, thinking="disabled").kwargs["max_tokens"] == 6000
