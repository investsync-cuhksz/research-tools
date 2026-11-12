"""Rule-based "AI rating" (Buy / Hold / Sell) and blended fair value, in the style of FinRobot V2:
the code decides the rating from the valuation numbers, the AI only explains it. FinRobot's own
notes say an AI that chooses the rating itself "drifts run-to-run"; a rule does not.

1. Collect the per-share value from each method that exists for this company:
   DCF (or DDM for banks / insurers) and the peer P/E, EV/EBITDA and P/B mid-points from the
   football field. Analyst targets and the 52-week range never enter the rating.
2. Drop outliers: a method more than ``outlier_band`` away from the median of the methods.
3. Fair value = weighted average of the remaining methods (weights in config/rating.json,
   renormalised over what is available). Fewer than ``min_methods`` left -> "Not rated".
4. Rating from the upside to fair value: >= buy threshold -> Buy, <= sell threshold -> Sell,
   otherwise Hold. Confidence from how closely the included methods agree.

RATING_BASIS=analyst (``from_scenarios``): the fair value is our probability-weighted bear/base/bull value (the AI's
evidence-cited assumptions, values computed in code with the model's DCF); the peer multiples and the mechanical DCF
are computed and shown as cross-checks, outside the rating. The same thresholds apply. Approved by the user on
9 Nov 2026 after four blind reviewers called a Buy resting on peer multiples, against our own scenarios' Hold,
"a rating made by code, not judgement".
"""
from __future__ import annotations

import json
from pathlib import Path
from math import sqrt
from statistics import mean, median, pstdev
from typing import Optional

from ..schema import Rating, RatingMethod, TearSheetData

CONFIG_FILE = Path(__file__).resolve().parents[2] / "config" / "rating.json"
LABELS = {"dcf": "DCF (base case)", "dcf_scenarios": "DCF (analyst scenarios, probability-weighted)", "ddm": "Dividend discount model", "peer_pe": "Peer P/E (median)",
          "peer_ev_ebitda": "Peer EV/EBITDA (median)", "peer_pb": "Peer P/B (median)"}
_FF_KEYS = {"Peer P/E (TTM)": "peer_pe", "Peer P/E (forward)": "peer_pe", "Peer EV/EBITDA": "peer_ev_ebitda", "Peer P/B": "peer_pb"}


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _method_values(data: TearSheetData) -> dict[str, float]:
    out: dict[str, float] = {}
    v = data.valuation
    if v and v.dcf and v.dcf.value_per_share and v.dcf.value_per_share > 0:
        out["dcf"] = v.dcf.value_per_share
    if v and v.ddm and v.ddm.value_per_share and v.ddm.value_per_share > 0:
        out["ddm"] = v.ddm.value_per_share
    if data.football_field:
        for b in data.football_field.bars:
            key = _FF_KEYS.get(b.label)
            if key and b.mid is not None and b.mid > 0:
                out[key] = b.mid
    return out


def compute(data: TearSheetData, cfg: Optional[dict] = None, financial: Optional[bool] = None,
            dcf_override: Optional[float] = None) -> Optional[Rating]:
    """``dcf_override`` (RATING_BASIS=scenarios): the probability-weighted value of the analyst scenarios
    (AI assumptions citing evidence, values computed in code with the model's DCF) takes the DCF's place and
    weight in the blend. Everything else (peers, weights, thresholds, outlier rule) is unchanged."""
    q = data.quote
    if not q.price:
        return None
    cfg = cfg or load_config()
    if financial is None:
        from .valuation import is_financial
        financial = is_financial(data)
    weights = cfg["weights"]["financial" if financial else "default"]
    th = cfg["thresholds"]
    values = {k: val for k, val in _method_values(data).items() if weights.get(k, 0) > 0}
    scen = dcf_override is not None and dcf_override > 0 and "dcf" in values
    if scen:
        values["dcf"] = dcf_override
    rating = Rating(rating="Not rated", currency=q.currency, buy_threshold=th["buy"], sell_threshold=th["sell"])
    if not values:
        rating.reason = "No valuation method is available for this company."
        return rating

    mid = median(values.values())
    band = cfg.get("outlier_band", 0.5)
    for key, val in values.items():
        off = val / mid - 1
        inside = abs(off) <= band
        rating.methods.append(RatingMethod(
            key=key, label=LABELS["dcf_scenarios" if scen and key == "dcf" else key], value=val, weight=weights[key],
            included=inside,
            note=None if inside else f"outlier: {off:+.0%} vs the median of methods"))
    used = [m for m in rating.methods if m.included]
    need = cfg.get("min_methods", 2)
    if len(values) < need:
        rating.reason = (f"Only {len(values)} valuation method available "
                         f"({', '.join(LABELS[k] for k in values)}); a rating needs at least {need}.")
        return rating
    if len(used) < need:
        rating.reason = (f"The valuation methods disagree: only {len(used)} of {len(values)} lie within "
                         f"±{band:.0%} of their median; a rating needs at least {need}.")
        return rating

    total = sum(m.weight for m in used)
    for m in used:
        m.weight = m.weight / total
    rating.fair_value = sum(m.value * m.weight for m in used)
    rating.upside = rating.fair_value / q.price - 1
    rating.rating = "Buy" if rating.upside >= th["buy"] else "Sell" if rating.upside <= th["sell"] else "Hold"
    # The same rule as price levels: Buy at or below fair value / (1 + buy), Sell at or above fair value / (1 + sell)
    rating.buy_below = rating.fair_value / (1 + th["buy"])
    rating.sell_above = rating.fair_value / (1 + th["sell"])
    vals = [m.value for m in used]
    cv = pstdev(vals) / mean(vals)
    c = cfg.get("confidence", {})
    if cv <= c.get("high_cv", 0.15) and len(used) >= 3:
        rating.confidence = "high"
    elif cv <= c.get("medium_cv", 0.30):
        rating.confidence = "medium"
    else:
        rating.confidence = "low"
    rating.reason = f"{len(used)} methods, spread {cv:.0%} (coefficient of variation)."
    return rating


def from_scenarios(data: TearSheetData, cfg: Optional[dict] = None) -> Optional[Rating]:
    """RATING_BASIS=analyst: rating and fair value from our scenarios; the other methods are cross-checks."""
    q, v = data.quote, data.valuation
    sc = v.scenarios if v else None
    if not (q.price and sc and sc.weighted_value and sc.weighted_value > 0 and sc.scenarios):
        return None
    cfg = cfg or load_config()
    th = cfg["thresholds"]
    fv = sc.weighted_value
    rating = Rating(rating="Hold", currency=q.currency, buy_threshold=th["buy"], sell_threshold=th["sell"],
                    basis="scenarios", fair_value=fv, upside=fv / q.price - 1)
    rating.methods.append(RatingMethod(key="dcf", label=LABELS["dcf_scenarios"], value=fv, weight=1.0, included=True))
    checks = _method_values(data)
    # the house outlier rule applies to the cross-checks too: a method more than outlier_band from the median of all
    # values (ours included) is shown but not used as a check (NVIDIA 9 Nov 2026: the TTM EV/EBITDA of fast-growing
    # peers gave USD 460 against our ~USD 205, a "+122%" cross-check a reviewer had already called misleading)
    band = cfg.get("outlier_band", 0.5)
    mid = median([fv, *checks.values()]) if checks else fv
    outliers = {k for k, val in checks.items() if k != "dcf" and abs(val / mid - 1) > band}
    for key, val in checks.items():
        rating.methods.append(RatingMethod(
            key=key, label=("DCF (model, mechanical)" if key == "dcf" else LABELS[key]), value=val, weight=0.0,
            included=False, note=(f"not used even as a cross-check: {val / mid - 1:+.0%} vs the median of the methods "
                                  f"(outlier rule)" if key in outliers else f"cross-check: {val / fv - 1:+.0%} vs our value")))
    checks = {k: val for k, val in checks.items() if k not in outliers}
    rating.rating = "Buy" if rating.upside >= th["buy"] else "Sell" if rating.upside <= th["sell"] else "Hold"
    rating.buy_below = fv / (1 + th["buy"])
    rating.sell_above = fv / (1 + th["sell"])
    # confidence: how far apart our own scenarios are (probability-weighted spread), and whether the
    # cross-checks land near our value
    tot = sum(s.probability for s in sc.scenarios) or 1.0
    sd = sqrt(sum(s.probability / tot * (s.value_per_share - fv) ** 2 for s in sc.scenarios))
    cv = sd / fv
    xs = [val for k, val in checks.items() if k != "dcf"]
    off = (median(xs) / fv - 1) if xs else None
    c = cfg.get("confidence", {})
    near = off is None or abs(off) <= 0.25
    if cv <= c.get("medium_cv", 0.30) and near:
        rating.confidence = "high" if cv <= c.get("high_cv", 0.15) else "medium"
    elif cv <= 2 * c.get("medium_cv", 0.30):
        rating.confidence = "medium" if near else "low"
    else:
        rating.confidence = "low"
    by = {s.name: s for s in sc.scenarios}
    cur = q.currency
    parts = [f"{n} {cur} {by[n].value_per_share:,.2f} ({by[n].probability:.0%})" for n in ("bear", "base", "bull") if n in by]
    rating.reason = (f"Our scenarios: {'; '.join(parts)}; probability-weighted spread {cv:.0%} of the value"
                     + (f"; peer multiples (median) {off:+.0%} vs our value, outside the rating" if off is not None else "")
                     + ".")
    return rating


def how(rt: Optional[Rating]) -> str:
    """How the rating is set, in one phrase (page notes, facts, learner)."""
    if rt is not None and rt.basis == "scenarios":
        return ("set from our bear / base / bull scenarios: the AI sets each scenario's assumptions from cited "
                "evidence, code computes the values and applies fixed Buy / Hold / Sell thresholds")
    return "set by a fixed house rule from the valuation methods"


def method_note(rt: Optional[Rating], th_buy: float = 0.15, th_sell: float = -0.10) -> str:
    """The methodology paragraph for the rating."""
    if rt is not None and rt.basis == "scenarios":
        return ("AI rating: the fair value is the probability-weighted value of our bear, base and bull scenarios. The "
                "AI sets each scenario's revenue growth, margin and probability from the research notes, citing "
                "evidence; code bounds the inputs, computes each value with the model's DCF (same WACC and terminal "
                "assumptions) and applies the thresholds: Buy if the fair value is at least "
                f"{th_buy:.0%} above the price, Sell if at least {-th_sell:.0%} below, else Hold. The peer multiples and "
                "the model's mechanical DCF (consensus revenue, then a fade) are computed and shown as cross-checks; they "
                "do not enter the rating. Confidence comes from the spread of the scenarios and from how far the peer "
                "multiples sit from our value.")
    return ("AI rating: set by a fixed house rule from the valuation; the writer cannot choose it. Fair value = weighted "
            "blend of DCF (or DDM for banks) and the peer-multiple mid-points; methods more than 50% from the median of "
            "methods are dropped; at least two methods are required. Buy if fair value is ≥ 15% above the price, Sell "
            "if ≥ 10% below, else Hold. The AI only writes the explanation, and is checked for stating any other "
            "rating.")
