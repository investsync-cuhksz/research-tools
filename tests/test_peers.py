"""AI peer selection: validation in code, fallback to the automatic list (offline, DummyLM)."""
import json
from types import SimpleNamespace

from dspy.utils import DummyLM

from investsync.narrative import peers
from investsync.schema import CompRow
from investsync.tickers import parse


def _md():
    prof = SimpleNamespace(name="NVIDIA Corporation", description="Designs GPUs.", sector="Semiconductors")
    return SimpleNamespace(profile=prof, peers=[CompRow(ticker="MU", name="Micron", pe_ttm=9.0, market_cap=1e11)])


def _run(monkeypatch, picks, rows):
    monkeypatch.setattr(peers, "settings", SimpleNamespace(peer_mode="ai", llm=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(peers, "_candidates", lambda t, md: ["AMD | Advanced Micro Devices | 1%"])
    monkeypatch.setattr(peers.adapters, "comp_row", lambda t: rows[t.canonical])
    import investsync.narrative.commentary as c
    lm = DummyLM([{"peers": json.dumps(picks)}])
    monkeypatch.setattr(c, "make_lm", lambda *a, **k: lm)
    return peers.select(parse("NVDA"), _md())


def test_ai_peers_are_validated(monkeypatch):
    picks = [{"ticker": t, "name": t, "reason": "GPU and accelerator designer"} for t in ("AMD", "AVGO", "NVDA", "XYZQ", "INTC", "MRVL")]
    rows = {"AMD": CompRow(ticker="AMD", name="AMD", pe_ttm=40.0, market_cap=3e11),
            "AVGO": CompRow(ticker="AVGO", name="Broadcom", pe_ttm=60.0, market_cap=1e12),
            "XYZQ": CompRow(ticker="XYZQ", name="", pe_ttm=None, market_cap=None),     # unknown listing
            "INTC": CompRow(ticker="INTC", name="Intel", pe_ttm=-5.0, market_cap=1e11),  # loss-maker
            "MRVL": CompRow(ticker="MRVL", name="Marvell", pe_ttm=30.0, market_cap=1e11)}
    rows_out, method = _run(monkeypatch, picks, rows)
    assert [r.ticker for r in rows_out] == ["AMD", "AVGO", "MRVL"]   # target, unknown and loss-maker dropped
    assert "AI assistance" in method and "GPU and accelerator designer" in method


def test_too_few_valid_peers_keeps_automatic_list(monkeypatch):
    picks = [{"ticker": "AMD", "name": "AMD", "reason": "x"}, {"ticker": "XYZQ", "name": "?", "reason": "y"}]
    rows = {"AMD": CompRow(ticker="AMD", name="AMD", pe_ttm=40.0, market_cap=3e11),
            "XYZQ": CompRow(ticker="XYZQ", name="", pe_ttm=None, market_cap=None)}
    assert _run(monkeypatch, picks, rows) is None


def test_usage_tracking_counts_only_new_billed_calls():
    from types import SimpleNamespace
    from investsync.narrative import commentary as c
    lm = SimpleNamespace(history=[{"usage": {"prompt_tokens": 999}, "model": "deepseek/deepseek-flash"}])
    c._LMS.append(lm)
    try:
        snap = c.usage_snapshot()                       # the old call above is not counted
        lm.history.append({"usage": {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 400_000,
                                     "completion_tokens": 100_000,
                                     "completion_tokens_details": {"reasoning_tokens": 60_000}},
                           "model": "deepseek/deepseek-flash"})
        lm.history.append({"usage": {}, "model": "deepseek/deepseek-flash"})   # DSPy cache hit: not billed
        u = c.usage_since(snap)
        assert (u.calls, u.prompt_tokens, u.cache_hit_tokens, u.completion_tokens, u.reasoning_tokens) == \
            (1, 1_000_000, 400_000, 100_000, 60_000)
        # 0.6M x 0.30 + 0.4M x 0.006 + 0.1M x 1.20 = 0.18 + 0.0024 + 0.12
        assert u.est_cost_usd == round(0.3024, 5) and u.models == ["deepseek-flash"]
    finally:
        c._LMS.remove(lm)
