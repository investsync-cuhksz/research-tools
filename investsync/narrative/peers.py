"""AI-assisted peer selection (used only when config/peers.json has no list for the ticker).

The automatic peer lists are "largest names in the same industry", which mixes business models: NVIDIA got
memory makers at peak earnings, CATL got its own materials suppliers. Here the AI picks 4-6 listed companies
with the same business model from the candidates (and may add well-known competitors), giving one reason
each. Code then validates every pick (it must parse as an HK / A-share / US ticker, not be the target, and
have a market cap and a positive P/E) and fetches all multiples itself; the AI never supplies a number.
Fewer than three valid picks -> the automatic list stays. Club-curated lists always win.
"""
from __future__ import annotations

import logging
from typing import Optional

import dspy
from pydantic import BaseModel

from ..config import settings
from ..data import adapters
from ..data import sources as src
from ..schema import CompRow, Market
from ..tickers import Ticker, parse

log = logging.getLogger(__name__)
MAX_PEERS, MIN_PEERS = 6, 3


class PeerPick(BaseModel):
    ticker: str
    name: str
    reason: str


class PeerSelect(dspy.Signature):
    """You are an equity analyst choosing comparable companies (peers) for a relative valuation of the target.

    Pick 4 to 6 listed companies that a sell-side analyst covering the target would put in its comparison table.
    - Start with direct competitors: the same products sold to the same customers (platforms with platforms, banks
      with banks of a similar funding model, battery cell makers with cell makers).
    - Then companies whose revenue rides on the same end-market demand and that investors routinely value side by
      side with the target, even one step along the value chain (for example the main contract manufacturer of an
      AI-chip designer's products, or the largest rival platform in an adjacent service). At most two such picks.
    - Leave out companies whose current earnings sit at a cyclical extreme (commodity makers at peak or trough
      prices, turnaround companies with depressed profits): their multiples say nothing about the target.
    - Prefer large, profitable, liquid companies of a meaningful size next to the target; avoid small niche
      suppliers. Never pick the target itself or another share class of it.
    - Use only tickers listed in Hong Kong (format 1211.HK), mainland China (format 002594.SZ or 600519.SH) or
      the US (format AMD; ADRs such as TSM are fine). Prefer the candidates given; you may add up to three
      well-known direct competitors that are not in the list, in the same ticker formats.
    - reason: one short sentence on why the business is comparable. Do not write any figures."""
    target: str = dspy.InputField()
    business: str = dspy.InputField(desc="what the target does")
    candidates: str = dspy.InputField(desc="ticker | name | market cap | P/E TTM, one per line")
    peers: list[PeerPick] = dspy.OutputField()


def _candidates(t: Ticker, md: "adapters.MarketData") -> list[str]:
    rows: list[str] = []
    try:
        if t.market == Market.US:
            info = src.yf_info(adapters._yf_symbol(t))
            top = src.yf_industry_top(info.get("industryKey")) if info.get("industryKey") else None
            if top is not None and len(top):
                for sym, r in top.head(20).iterrows():
                    rows.append(f"{sym} | {r.get('name', '')} | market weight {r.get('market weight', '')}")
        elif t.market == Market.HK:
            df = src.hk_industry_scale(t.code)
            if df is not None and len(df):
                for _, r in df.sort_values("HKTOTAL_MARKET_CAP", ascending=False).head(20).iterrows():
                    rows.append(f"{str(r['CORRE_SECUCODE'])[-7:].lstrip('0')} | {r['CORRE_SECURITY_NAME']} | "
                                f"HKD {float(r.get('HKTOTAL_MARKET_CAP') or 0) / 1e9:,.0f}bn")
        else:
            df = src.cn_peer_comparison(t.em_prefixed)
            if df is not None and len(df):
                for _, r in df.head(20).iterrows():
                    c = str(r["代码"])
                    if c.isdigit() and len(c) == 6:
                        rows.append(f"{c}.{'SH' if c[0] in '69' else 'SZ'} | {r['简称']} | P/E {r.get('市盈率-TTM', '')}")
    except Exception as e:
        log.warning("peer candidates failed for %s: %s", t.canonical, e)
    rows += [f"{p.ticker} | {p.name} | P/E {p.pe_ttm or 'n/a'}" for p in md.peers]
    return list(dict.fromkeys(rows))


def _valid(raw: str, target: Ticker) -> Optional[CompRow]:
    try:
        pt = parse(raw.strip())
    except Exception:
        return None
    if pt.canonical == target.canonical:
        return None
    try:
        row = adapters.comp_row(pt)
    except Exception as e:
        log.warning("peer %s failed: %s", raw, e)
        return None
    if not row.market_cap or not row.pe_ttm or row.pe_ttm <= 0:
        return None  # unknown listing or loss-maker
    return row


def select(t: Ticker, md: "adapters.MarketData") -> Optional[tuple[list[CompRow], str]]:
    """AI-picked peers with reasons, validated in code; None to keep the automatic list."""
    if settings.peer_mode != "ai" or not settings.llm.enabled:
        return None
    from .commentary import ADAPTER, make_lm
    cands = _candidates(t, md)
    business = (md.profile.description or "") + (f" Sector: {md.profile.sector}." if md.profile.sector else "")
    try:
        with dspy.context(lm=make_lm(settings.llm, max_tokens=2000, thinking="disabled", step="peers"), adapter=ADAPTER):
            out = dspy.Predict(PeerSelect)(target=f"{md.profile.name} ({t.canonical})", business=business[:1200],
                                           candidates="\n".join(cands) or "(none)")
        picks = list(out.peers or [])[:MAX_PEERS + 2]
    except Exception as e:
        log.warning("AI peer selection failed for %s: %s", t.canonical, e)
        return None
    rows, reasons = [], []
    for p in picks:
        row = _valid(p.ticker, t)
        if row is None or any(r.ticker == row.ticker for r in rows):
            continue
        rows.append(row)
        reasons.append(f"{row.ticker} ({adapters._short_name(row.name)}): {p.reason.strip().rstrip('.')}")
        if len(rows) == MAX_PEERS:
            break
    rows, reasons, dropped = screen(rows, reasons, _target_cap(md, t))
    if len(rows) < MIN_PEERS:
        log.info("AI peers for %s: only %d valid, keeping automatic peers", t.canonical, len(rows))
        return None
    method = ("Peers with the same business model (selected with AI assistance from the industry and named "
              "competitors, each checked to be listed and profitable; multiples from EastMoney and Yahoo Finance). "
              "Why each: " + "; ".join(reasons) + "." + (f" Left out by the code's screens: {'; '.join(dropped)}."
                                                         if dropped else ""))
    return rows, method


MIN_SIZE, LOW_PE = 0.01, 1 / 3


def _target_cap(md: "adapters.MarketData", t: Ticker) -> Optional[tuple[float, str]]:
    q = getattr(md, "quote", None)
    if q is not None and getattr(q, "market_cap", None):
        return q.market_cap, q.currency
    try:
        r = adapters.comp_row(t)
        return (r.market_cap, r.currency) if r.market_cap and r.currency else None
    except Exception:
        return None


def screen(rows: list[CompRow], reasons: list[str], target: Optional[tuple[float, str]],
           fx=None) -> tuple[list[CompRow], list[str], list[str]]:
    """Code screens on the AI's picks, the same for every company (round-5 review: a USD 33bn niche supplier among
    NVIDIA's peers; Opus left out Micron at 3.7x P/E, "peak memory pricing"):
    - size: a peer worth less than 1% of the target is dropped;
    - earnings at a cyclical extreme: a P/E (forward if known, else TTM) below a third of the median of the other
      picks is dropped.
    Never drops below MIN_PEERS (the largest are kept)."""
    if fx is None:
        fx = src.fx
    keep = list(zip(rows, reasons))
    dropped: list[str] = []

    def usd(r: CompRow) -> Optional[float]:
        if not r.market_cap or not r.currency:
            return None
        rate = fx(r.currency, "USD")
        return r.market_cap * rate if rate else None

    if target and target[0]:
        rate = fx(target[1], "USD")
        t_usd = target[0] * rate if rate else None
        if t_usd:
            small = [(r, why) for r, why in keep if (u := usd(r)) is not None and u < MIN_SIZE * t_usd]
            if small and len(keep) - len(small) >= MIN_PEERS:
                keep = [x for x in keep if x not in small]
                dropped += [f"{r.ticker} (under 1% of the target's market value)" for r, _ in small]

    def pe(r: CompRow) -> Optional[float]:
        return r.pe_fwd if r.pe_fwd and r.pe_fwd > 0 else r.pe_ttm

    from statistics import median
    low = []
    for r, why in keep:
        others = [pe(o) for o, _ in keep if o is not r and pe(o)]
        if pe(r) and len(others) >= 2 and pe(r) < LOW_PE * median(others):
            low.append((r, why))
    if low and len(keep) - len(low) >= MIN_PEERS:
        keep = [x for x in keep if x not in low]
        dropped += [f"{r.ticker} (P/E {pe(r):.1f}x, under a third of the others' median: earnings at a cyclical "
                    f"extreme)" for r, _ in low]
    return [r for r, _ in keep], [w for _, w in keep], dropped
