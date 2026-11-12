"""Overall view for page 1: the InvestSync model and every broker's latest *recent* view, combined.

Code only, no AI. Every view is put on one 1-5 score (Sell 1 · Underperform 2 · Hold 3 ·
Outperform 4 · Buy 5; the model's three levels map to 5 / 3 / 1).

* Brokers: each broker's latest rating, and only if it is recent: notes up to ``full_weight_days``
  old count fully, older ones up to ``fresh_days`` count ``older_weight``, anything older is left out
  (listed as stale). In Hong Kong a news write-up that is newer than etnet's table updates that
  broker's rating and target. The brokers' score is the weighted average.
* The model counts ``model_weight`` (one third by default) and the brokers the rest. With fewer
  than ``min_brokers`` recent brokers their share shrinks in proportion, so one or two notes cannot
  outvote the model. If the model is "Not rated", the brokers alone set the view.
* Yahoo Finance's analyst consensus is shown for reference only (it overlaps with the brokers).

Weights live in config/rating.json ("overall") so the finance team can change them.
"""
from __future__ import annotations

import json
import math
from datetime import date
from statistics import median
from typing import Optional

from ..config import ROOT
from ..render.viewmodel import ccy, num, pct
from ..schema import BrokerNote, BrokerVote, OverallView, TearSheetData, ViewInput

SCALE = ["Sell", "Underperform", "Hold", "Outperform", "Buy"]
SCORE = {r: i + 1 for i, r in enumerate(SCALE)}
MODEL_SCORE = {"Buy": 5.0, "Hold": 3.0, "Sell": 1.0}
DEFAULTS = {"model_weight": 1 / 3, "fresh_days": 90, "full_weight_days": 30, "older_weight": 0.5, "min_brokers": 3}


def config() -> dict:
    try:
        cfg = json.loads((ROOT / "config" / "rating.json").read_text(encoding="utf-8")).get("overall", {})
    except (OSError, ValueError):
        cfg = {}
    return {k: cfg.get(k, v) for k, v in DEFAULTS.items()}


def label(score: float) -> str:
    return SCALE[min(5, max(1, int(math.floor(score + 0.5)))) - 1]


def _latest(data: TearSheetData) -> dict[str, BrokerNote]:
    """Each broker's newest rated view: the notes, updated by newer HK write-ups."""
    st = data.street
    out: dict[str, BrokerNote] = {}
    for n in sorted(st.notes if st else [], key=lambda x: x.on, reverse=True):
        if n.rating and n.broker not in out:
            out[n.broker] = n
    for w in (st.writeups if st else []):
        cur = out.get(w.broker)
        if w.rating and (cur is None or w.on > cur.on):
            out[w.broker] = w.model_copy(update={"target": w.target if w.target is not None
                                                 else (cur.target if cur else None)})
    return out


def build(data: TearSheetData, today: Optional[date] = None, cfg: Optional[dict] = None) -> Optional[OverallView]:
    cfg = cfg or config()
    today = today or data.quote.as_of
    price, cur = data.quote.price, ccy(data.quote.currency)

    votes, stale = [], []
    for b, n in sorted(_latest(data).items(), key=lambda kv: kv[1].on, reverse=True):
        age = (today - n.on).days
        if age > cfg["fresh_days"]:
            stale.append(f"{b} ({n.on.strftime('%-d %b %Y')})")
            continue
        votes.append(BrokerVote(broker=b, on=n.on, rating=n.rating,
                                weight=1.0 if age <= cfg["full_weight_days"] else cfg["older_weight"],
                                target=n.target, source=n.source))
    wsum = sum(v.weight for v in votes)
    brokers = sum(SCORE[v.rating] * v.weight for v in votes) / wsum if wsum else None

    rt = data.rating
    model = MODEL_SCORE.get(rt.rating) if rt else None
    if model is None and brokers is None:
        return None
    if model is not None and brokers is not None:
        broker_share = (1 - cfg["model_weight"]) * min(1.0, len(votes) / cfg["min_brokers"])
    else:
        broker_share = 1.0 if brokers is not None else 0.0
    model_share = 1.0 - broker_share if model is not None else 0.0
    score = (model or 0) * model_share + (brokers or 0) * broker_share

    # recent targets only (same sanity band as the broker chapter)
    tg = [v.target for v in votes if v.target and price and 0.2 <= v.target / price <= 5]
    t_med = median(tg) if tg else None

    inputs = []
    if rt:
        inputs.append(ViewInput(
            source="InvestSync model (AI rating)", rating=rt.rating, score=model, weight=model_share, as_of=today,
            detail=(f"fair value {cur} {num(rt.fair_value, 2)} ({pct(rt.upside, 1, signed=True)} vs the price)"
                    if rt.fair_value and rt.rating != "Not rated" else (rt.reason or "methods disagree; not rated"))))
    if votes:
        mix = {r: sum(1 for v in votes if v.rating == r) for r in reversed(SCALE)}
        inputs.append(ViewInput(
            source="Brokers (latest view each, recent only)", rating=label(brokers), score=round(brokers, 2),
            weight=broker_share, as_of=max(v.on for v in votes),
            detail=(f"{len(votes)} brokers from the last {cfg['fresh_days']} days: "
                    + ", ".join(f"{k} {v}" for k, v in mix.items() if v)
                    + (f"; median target {cur} {num(t_med, 2)} ({pct(t_med / price - 1, 1, signed=True)}, "
                       f"{len(tg)} target{'s' * (len(tg) != 1)})" if t_med and price else ""))))
    c = data.consensus
    if c and c.recommendation_mean:
        yscore = 6 - c.recommendation_mean  # Yahoo: 1 = strong buy ... 5 = strong sell
        inputs.append(ViewInput(
            source="Yahoo Finance consensus (reference only)", rating=label(yscore), score=round(yscore, 2),
            weight=0.0, detail=f"mean {c.recommendation_mean:.2f} on Yahoo's scale (1 = strong buy, 5 = strong sell)"
                               + (f", {c.analysts} analysts" if c.analysts else "")))

    split = model is not None and brokers is not None and abs(model - brokers) >= 2
    split_note = None
    if split:
        split_note = (f"The model ({rt.rating}) and the brokers ({label(brokers)}, {brokers:.1f}/5) are two or more "
                      f"steps apart, so the overall view is a compromise between two different readings; see the "
                      f"broker chapter and the data audit before relying on either.")
    thin = 0 < len(votes) < cfg["min_brokers"]
    parts = []
    if model is not None:
        parts.append(f"model {pct(model_share, 0)}")
    elif rt:
        parts.append("model not rated")
    if votes:
        parts.append(f"{len(votes)} broker{'s' * (len(votes) != 1)} {pct(broker_share, 0)}")
    basis = " + ".join(parts) + (" (few recent brokers)" if thin else "")
    return OverallView(
        rating=label(score), score=round(score, 2), inputs=inputs, votes=votes, stale=stale,
        fresh_days=cfg["fresh_days"], full_weight_days=cfg["full_weight_days"], older_weight=cfg["older_weight"],
        model_share=model_share, broker_share=broker_share, brokers_score=round(brokers, 2) if brokers else None,
        split=split, split_note=split_note, thin=thin, basis=basis,
        target_median=t_med, target_upside=(t_med / price - 1) if t_med and price else None, targets_n=len(tg),
        oldest=min((v.on for v in votes), default=None), newest=max((v.on for v in votes), default=None))
