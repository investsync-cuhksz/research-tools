"""Runtime settings, read from the environment (and .env if present)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _key(name: str) -> Optional[str]:
    v = os.getenv(name)
    return None if not v or "your-" in v or v.endswith("-api-key") else v


def _secret_file(name: str) -> Optional[str]:
    """A key kept in secrets/<name> (git-ignored). Accepts plain text or a TextEdit rich-text (RTF) file:
    the key is the longest letters-and-digits token in the file."""
    f = ROOT / "secrets" / name
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8", errors="ignore")
    if text.lstrip().startswith("{\\rtf"):
        text = text.rsplit("\\", 1)[-1]  # RTF: the visible text follows the last control word
    tokens = re.findall(r"[A-Za-z0-9_\-]{16,}", text)
    return max(tokens, key=len) if tokens else None


@dataclass(frozen=True)
class LLMEndpoint:
    name: str           # "primary" / "fallback"
    base_url: str
    model: str
    api_key: Optional[str]

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def _openrouter_key() -> Optional[str]:
    return _key("OPENROUTER_API_KEY") or _secret_file("openrouter.txt")


def _primary() -> LLMEndpoint:
    """DeepSeek direct by default (key: LLM_API_KEY, else secrets/deepseek.txt). A model id starting with
    `openrouter/` (e.g. openrouter/deepseek/deepseek-v4.1-flash-1017) routes every call through OpenRouter with the
    key in OPENROUTER_API_KEY or secrets/openrouter.txt (final run, 10 Nov 2026)."""
    model = os.getenv("LLM_MODEL", "deepseek-flash")
    if model.startswith("openrouter/"):
        return LLMEndpoint("primary", OPENROUTER_BASE, model, _openrouter_key())
    return LLMEndpoint("primary", os.getenv("LLM_BASE_URL", "https://api.deepseek.com"), model,
                       _key("LLM_API_KEY") or _secret_file("deepseek.txt"))


@dataclass(frozen=True)
class Settings:
    llm: LLMEndpoint = field(default_factory=_primary)
    # OpenRouter (final run, 10 Nov 2026; see HANDOFF §0.1): provider routing as JSON for the bulk model and for the
    # judge tier, e.g. {"order":["deepinfra/fp8","deepseek"],"allow_fallbacks":false}. LLM_JUDGE_MODEL: a stronger
    # model for the five judgement checkpoints (scenarios, analyst brief, debate judge, deep reviewer, learner
    # coach via LLM_LEARNER_MODEL), each falling back to the primary model on failure; LLM_JUDGE_EFFORT its
    # reasoning effort. RUN_BUDGET_USD: once billed spend in this process reaches it, the judge tier is skipped.
    openrouter_key: Optional[str] = field(default_factory=_openrouter_key)
    openrouter_provider: str = os.getenv("OPENROUTER_PROVIDER", "")
    openrouter_judge_provider: str = os.getenv("OPENROUTER_JUDGE_PROVIDER", "")
    judge_model: str = os.getenv("LLM_JUDGE_MODEL", "")
    judge_effort: str = os.getenv("LLM_JUDGE_EFFORT", "medium")
    learner_model: str = os.getenv("LLM_LEARNER_MODEL", "")
    # run 3 (12 Nov 2026, the final run): a top model at chosen judgement steps (LLM_TOP_STEPS: step names used in
    # narrative/commentary.py), falling back to the judgement model, then to the primary model. TOP_BUDGET_USD: once
    # billed spend in this process reaches it, those steps use the judgement model instead.
    top_model: str = os.getenv("LLM_TOP_MODEL", "")
    top_steps: str = os.getenv("LLM_TOP_STEPS", "scenarios,analyst brief,debate judge,deep review")
    top_budget_usd: float = float(os.getenv("TOP_BUDGET_USD", "0") or 0)
    run_budget_usd: float = float(os.getenv("RUN_BUDGET_USD", "0") or 0)
    # Backup model, tried automatically when the primary fails (e.g. GLM or Qwen)
    llm_fallback: LLMEndpoint = field(default_factory=lambda: LLMEndpoint(
        "fallback", os.getenv("LLM_FALLBACK_BASE_URL", ""), os.getenv("LLM_FALLBACK_MODEL", ""),
        _key("LLM_FALLBACK_API_KEY")))
    narrative_mode: str = os.getenv("NARRATIVE_MODE", "single")  # single | two_step
    # Peers when config/peers.json has no list: "ai" = the AI picks same-business-model companies from the
    # automatic candidates (reasons shown, code validates each); "auto" = the largest names in the industry
    peer_mode: str = os.getenv("PEER_MODE", "ai")
    # Research desk (investsync/research): read results releases, announcements, broker reports and news before
    # writing. RESEARCH=0 turns it off; RESEARCH_CHUNKS caps the excerpts read (one cheap AI call each).
    # Peer P/E valuation basis: "forward" (next-year consensus, when the target and 3+ peers have it) or "ttm".
    peer_pe_basis: str = os.getenv("PEER_PE_BASIS", "forward")
    # "analyst" (default since 9 Nov 2026): the probability-weighted value of the AI's evidence-cited bear/base/bull
    # scenarios (computed in code with the model's DCF) is the fair value; peer multiples and the mechanical DCF are
    # shown as cross-checks. Falls back to "rule" when there are no scenarios (no AI, banks on a DDM). "rule": the
    # weighted blend of the mechanical DCF and peer multiples. "scenarios": that blend with the scenario value in the
    # DCF's place. Changes ratings.
    rating_basis: str = os.getenv("RATING_BASIS", "analyst")
    research_enabled: bool = os.getenv("RESEARCH", "1") == "1"
    # Run 3 (12 Nov 2026): keep news only from the outlets in config/news_sources.json (report, writers and research
    # desk). NEWS_ALLOWLIST=0 falls back to the old block list of content farms (research/desk.py LOW_TIER).
    news_allowlist: bool = os.getenv("NEWS_ALLOWLIST", "1") == "1"
    # The page-1 "overall view" blends the AI rating with broker ratings (model 1/3, brokers 2/3). Off by default
    # since 9 Nov 2026 (user decision after four blind reviewers said a house note must not blend other firms'
    # ratings into its view): page 1 shows the Street's view separately. OVERALL_VIEW=1 brings it back.
    overall_view: bool = os.getenv("OVERALL_VIEW", "0") == "1"
    # House forecast (narrative/forecast.py): the AI sets three years of drivers, code builds revenue / profit / EPS
    # and compares them with consensus; the base scenario uses the same revenue path. FORECAST=0 turns it off.
    forecast_enabled: bool = os.getenv("FORECAST", "1") == "1"
    # Analyst brief (narrative/brief.py): one thinking call decides the central question, our answer, pillars,
    # quality, governance and the gap to the brokers before the simple report is written. BRIEF=0 turns it off.
    brief_enabled: bool = os.getenv("BRIEF", "1") == "1"
    # run 4 (12 Nov 2026): print the thesis memo's own thesis paragraph and tagline (the judgement model's text,
    # figures re-checked) instead of the writer's version; the deep report debates first and sets the scenario
    # weights after reading the verdict; a "what decides the third forecast year" step; Anthropic prompt caching
    brief_thesis: bool = os.getenv("BRIEF_THESIS", "0") == "1"
    debate_first: bool = os.getenv("DEBATE_FIRST", "0") == "1"
    deciding_year: bool = os.getenv("DECIDING_YEAR", "0") == "1"
    prompt_cache: bool = os.getenv("PROMPT_CACHE", "0") == "1"
    # 60 since 9 Nov 2026 (round 7: policy news and the cause of the biggest move were missed at 40; ~+CNY 0.1)
    research_chunks: int = int(os.getenv("RESEARCH_CHUNKS", "60"))
    # Claim check (narrative/claimcheck.py): each risky sentence checked against the sources before publishing.
    claim_check: bool = os.getenv("CLAIM_CHECK", "1") == "1"
    # DeepSeek V4 models think by default (extra paid output tokens). Our DSPy programs already ask for
    # step-by-step reasoning, so thinking is off unless LLM_THINKING=enabled.
    llm_thinking: str = os.getenv("LLM_THINKING", "disabled")
    # Deep mode (mode=deep): the analyst, bull, bear, judge and reviewer steps think (effort low/high/max);
    # LLM_DEEP_MODEL switches those runs to another model on the same API (e.g. deepseek-v4-pro)
    deep_effort: str = os.getenv("LLM_DEEP_EFFORT", "high")
    deep_model: str = os.getenv("LLM_DEEP_MODEL", "")
    # 9 Nov 2026: split by step so the larger model goes where judgement and writing matter. LLM_WRITER_MODEL: the
    # writer of the simple report and the learner notes (deep mode's writer uses LLM_DEEP_MODEL); LLM_WRITER_EFFORT:
    # the writers' thinking effort (low / high / max; empty = LLM_DEEP_EFFORT); LLM_CHECK_MODEL: the claim check
    # (empty = LLM_DEEP_MODEL, else the primary model). Research always uses the primary model (cheap extraction).
    writer_model: str = os.getenv("LLM_WRITER_MODEL", "")
    writer_effort: str = os.getenv("LLM_WRITER_EFFORT") or os.getenv("LLM_DEEP_EFFORT", "high")
    check_model: str = os.getenv("LLM_CHECK_MODEL", "")
    # LLM_WRITER_THINKING=enabled: the writer (every report section) and the learner coach think first, at
    # LLM_DEEP_EFFORT (otherwise only the deep analysis, debate, judge, reviewer and checks think).
    writer_thinking: bool = os.getenv("LLM_WRITER_THINKING", "disabled") == "enabled"
    # Cost settings (9 Nov 2026 cost experiment, see HANDOFF): LLM_CHECK_EFFORT is the claim check's thinking
    # effort (default: LLM_DEEP_EFFORT); CLAIM_CHECK_LIMIT caps the sentences checked per pass;
    # CLAIM_CHECK_LEARNER / _DEBATE / _FINAL = 0 skip the check of the learner notes, of the deep debate
    # (arguments and judge), and the second pass over sentences the writer rewrote.
    check_effort: str = os.getenv("LLM_CHECK_EFFORT") or os.getenv("LLM_DEEP_EFFORT", "high")
    claim_check_limit: int = int(os.getenv("CLAIM_CHECK_LIMIT", "48"))
    claim_check_learner: bool = os.getenv("CLAIM_CHECK_LEARNER", "1") == "1"
    claim_check_debate: bool = os.getenv("CLAIM_CHECK_DEBATE", "1") == "1"
    claim_check_final: bool = os.getenv("CLAIM_CHECK_FINAL", "1") == "1"
    cache_db_path: Path = ROOT / os.getenv("CACHE_DB_PATH", "data/cache.sqlite3")
    no_cache: bool = os.getenv("INVESTSYNC_NO_CACHE") == "1"
    guardrail_attempts: int = int(os.getenv("GUARDRAIL_ATTEMPTS", "3"))
    # SEC EDGAR asks automated clients to identify themselves with a contact address
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "InvestSync Research Tools investsyncofficial@gmail.com")
    filings_enabled: bool = os.getenv("FILINGS_ENABLED", "1") == "1"
    filings_timeout: int = int(os.getenv("FILINGS_TIMEOUT_SECONDS", "300"))
    # Finnhub (free key): US company news going back weeks. Env var first, else secrets/finnhub.txt
    finnhub_api_key: Optional[str] = field(default_factory=lambda: _key("FINNHUB_API_KEY") or _secret_file("finnhub.txt"))

    # ---- backwards-compatible shortcuts
    @property
    def llm_enabled(self) -> bool:
        return self.llm.enabled or self.llm_fallback.enabled

    @property
    def llm_model(self) -> str:
        return self.llm.model

    @property
    def llm_base_url(self) -> str:
        return self.llm.base_url

    @property
    def llm_api_key(self) -> Optional[str]:
        return self.llm.api_key

    def endpoints(self) -> list[LLMEndpoint]:
        return [e for e in (self.llm, self.llm_fallback) if e.enabled]


settings = Settings()
