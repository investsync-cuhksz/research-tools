"""Scenario valuation (deep mode): the AI sets bear / base / bull assumptions, code computes the values.

Why: blind reviewers marked the DeepSeek reports down for a mechanical valuation with "no forecasts of its own",
while the Opus reports argued explicit scenarios tied to identifiable drivers (guidance, a tax change, a capex
surge) and gave a probability-weighted value. Here the AI only chooses a few assumptions per scenario (revenue
growth for the next three years, the FCF margin it reaches by year three, a probability) and must say which
evidence each rests on; code bounds them and runs the same DCF as the model (same WACC, terminal growth, net debt,
share count, stub year). The result is shown next to the debate and given to the writer. It never sets or
changes the rule-based rating.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Literal, Optional

import dspy
from pydantic import BaseModel, Field

from ..quant import valuation
from ..schema import Scenario, ScenarioSet, TearSheetData

log = logging.getLogger(__name__)
GROWTH_BOUNDS, MARGIN_BOUNDS = (-0.40, 1.50), (-0.10, 0.70)


class ScenarioPick(BaseModel):
    name: Literal["bear", "base", "bull"]
    probability: float = Field(description="0 to 1; the three add up to 1")
    revenue_growth: list[float] = Field(description="Revenue growth for each of the next 3 fiscal years, as decimals "
                                                    "(0.20 = +20%)")
    fcf_margin: float = Field(description="Free-cash-flow margin reached by year 3 and held, as a decimal")
    drivers: str = Field(description="For a reader of the report, in plain English. One sentence: what has to "
                                     "happen, naming the specific events, people and products as the evidence "
                                     "names them, citing evidence ids in square brackets (e.g. [R12], [E40], "
                                     "[BULL-2]). Then one sentence that starts 'Probability:' and says what pushes "
                                     "this weight up and what holds it down, each with its evidence id. No figures "
                                     "except your own assumptions and figures copied exactly from the evidence")


class SetScenarios(dspy.Signature):
    """You are the lead analyst setting three valuation scenarios for the company. Code will run the same DCF as
    the model with your assumptions; you choose only revenue growth for the next three fiscal years, the
    free-cash-flow margin reached by year three, and a probability for each scenario.

    - Anchor the base case on the evidence: management guidance and broker forecasts in the research notes, the
      latest reported period, and the model's base case. Explain any departure from consensus in `drivers`.
    - Bear and bull must each follow from named drivers in the evidence or the debate (a policy change, a margin
      guide-down, a capex surge, a demand shift), not from adding or subtracting a fixed amount.
    - Margins: start from the current FCF margin given; a capex surge, a new tax or price cuts lower it, scale
      raises it. Keep the three internally consistent (bear < base < bull for value).
    - Probabilities reflect how likely each is given the evidence, not a default 25/50/25; they add up to 1.
    - Stay consistent with what is already known: the current fiscal year is partly reported, and where management
      has given an outlook for a year, a scenario far from it needs a cited reason why management would be wrong
      (a cancelled order, a policy change). Code limits bear and bull growth in reported or guided years to a band
      around the base case, so an extreme case cannot set the value on its own.
    - The bear case is the case where the thesis is wrong, and it must be a real downside: the risk that most
      threatens the main assumption (for a fast grower usually a slowdown or a reversal in demand once the current
      cycle peaks), not a minor variation on the base case. A risk the guidance already excludes (a market or product
      it already assumes no revenue from) cannot drive it. Code keeps bear and bull at least a minimum distance from
      the base case, set from the company's own historical swings in growth and margin (given in model_base).
    - `drivers` is printed in the report next to the numbers, so write it for a reader, in plain English. First one
      sentence saying what would have to be true for that case. Be specific: name the event, the people (with their
      role), the products and the dates as the evidence names them ("the board's investigation into allegations about
      the chief executive [R12]", not "governance concerns"), and never add a name or detail the evidence does not
      give. Then one sentence that starts 'Probability:' and says what pushes this weight up and what holds it down,
      each with its evidence id ("Probability: 25%, raised by ... [R12] and held down by ... [R3]"). Cite evidence ids
      in square brackets. No figures except your own assumptions and figures copied exactly from the evidence. Code
      checks every figure, name and id, and deletes a sentence that fails."""
    company: str = dspy.InputField()
    model_base: str = dspy.InputField(desc="The model's DCF base case and the current figures it starts from")
    evidence: str = dspy.InputField(desc="Research notes, signals and facts, numbered")
    debate: str = dspy.InputField(desc="Bull and bear arguments and the judge's verdict")
    scenarios: list[ScenarioPick] = dspy.OutputField(desc="Exactly three: bear, base, bull")


def _clip(x: float, lo_hi: tuple[float, float]) -> float:
    return min(max(float(x), lo_hi[0]), lo_hi[1])


def model_base_text(data: TearSheetData, with_forecast: bool = True) -> Optional[str]:
    v = data.valuation
    dcf = v.dcf if v else None
    if not dcf or not dcf.forecast or not v.wacc or not v.wacc.wacc:
        return None
    f = dcf.forecast
    growth = ", ".join(f"FY{x.fiscal_year} {x.growth:+.1%} ({x.basis})" for x in f)
    path = dcf.margin_path or [dcf.fcf_margin] * len(f)
    lines = [f"Model DCF base case: value per share {data.quote.currency} {dcf.value_per_share:,.2f} vs price "
             f"{data.quote.price:,.2f}; WACC {v.wacc.wacc:.1%}; terminal growth {dcf.terminal_growth:.1%}; "
             f"terminal value {dcf.bridge.terminal_share:.0%} of EV." if dcf.bridge else "",
             f"Revenue growth path: {growth}.",
             f"FCF margin path: " + ", ".join(f"{m:.1%}" for m in path) + f" ({dcf.margin_basis or ''}).",
             f"Latest fiscal-year revenue: {data.financials.currency} {data.financials.years[-1].revenue / 1e6:,.0f}mn."]
    lt = data.financials.latest
    if lt is not None and lt.revenue_growth is not None:
        lines.append(f"Latest reported period {lt.label}: revenue growth {lt.revenue_growth:+.1%} year on year.")
    sg, sm = spreads(data)
    lines.append(f"Historical swings (standard deviation over the years we have): annual revenue growth {sg:.0%}, FCF "
                 f"margin {sm:.0%}. Code keeps the bear case at least this far below the base case in years nobody "
                 f"has guided (half as far in guided years) and the bull case half as far above.")
    if with_forecast and data.forecast:
        from .forecast import text as forecast_text
        lines.append(forecast_text(data.forecast))
        lines.append("The base case's revenue growth for the next three years is the house forecast's (set by code); "
                     "choose its FCF margin and probability, and set bear and bull around it.")
    return "\n".join(x for x in lines if x)


def growth_bands(data: TearSheetData, base: list[float]) -> list[Optional[tuple[float, float]]]:
    """Round-8 review: the bear case cut next year's growth to +10% against management's ~70% outlook, with nothing
    cited, and at 18% probability it set the rating. In years that are partly reported (the current fiscal year) or
    that management has guided (an outlook note names the year), bear and bull growth stay within a band around
    the base case (which follows the guidance): half the base growth (at least 10 points) either side, narrowed by
    the share of the current year already reported. Other years keep only the global bounds."""
    out: list[Optional[tuple[float, float]]] = [None] * min(3, len(base))
    years = data.financials.years
    if not years:
        return out
    fy = years[-1].fiscal_year
    lt = data.financials.latest
    reported = (lt.months if lt is not None and lt.period_end > years[-1].period_end and lt.months else 0)
    from .forecast import _outlook_ids
    for i in range(len(out)):
        b = base[i]
        width = max(0.5 * abs(b), 0.10)
        if i == 0 and reported:
            width *= (12 - min(reported, 11)) / 12
        elif not _outlook_ids(data, fy + 1 + i):
            continue
        out[i] = (b - width, b + width)
    return out


def spreads(data: TearSheetData) -> tuple[float, float]:
    """Minimum distance of bear and bull from the base case: (growth, FCF margin), from the company's own history.

    Round 9 (blind review, 10 Nov 2026): the bear case was the base case less 5 points of growth and 2.6 points of
    margin, worth only 2% below the price; both reviewers called it "not a downside scenario" and the reference
    report's bear case (revenue falling once the capex cycle peaks) was worth half the price. The spread is the
    robust standard deviation of the company's annual revenue growth (5 to 40 points) and of its FCF margin (2 to 10
    points, and at most a quarter of the latest margin) over the years we have; with fewer than three observations,
    10 and 3 points."""
    ys = [y for y in data.financials.years if y.revenue]
    g = [b.revenue / a.revenue - 1 for a, b in zip(ys, ys[1:]) if a.revenue and a.revenue > 0]
    m = [(y.operating_cash_flow - (y.capex or 0)) / y.revenue for y in ys
         if y.operating_cash_flow is not None and y.revenue and y.revenue > 0]

    def sd(x: list[float]) -> Optional[float]:
        """Robust standard deviation (1.4826 x the median absolute deviation): one-off years (a tax settlement in
        cash flow, a boom year) do not set the spread on their own."""
        if len(x) < 3:
            return None
        med = sorted(x)[len(x) // 2] if len(x) % 2 else sum(sorted(x)[len(x) // 2 - 1: len(x) // 2 + 1]) / 2
        dev = sorted(abs(v - med) for v in x)
        mad = dev[len(dev) // 2] if len(dev) % 2 else (dev[len(dev) // 2 - 1] + dev[len(dev) // 2]) / 2
        return 1.4826 * mad
    sg, sm = sd(g), sd(m)
    # the margin spread is also capped at a quarter of the latest FCF margin: a bear case cuts margins in proportion,
    # it does not erase them (Coca-Cola's one-off payments in 2024-25 would otherwise set a 10-point cut)
    last = m[-1] if m else None
    cap_m = min(0.10, max(0.02, 0.25 * abs(last))) if last is not None else 0.10
    return (_clip(sg, (0.05, 0.40)) if sg is not None else 0.10,
            _clip(sm, (0.02, cap_m)) if sm is not None else 0.03)


def _path(data: TearSheetData, gr: list[float], m_end: float) -> Optional[dict]:
    """One scenario through the model's DCF (same WACC, terminal growth, stub year, net debt, stakes and share count):
    its three years of revenue growth, then the growth above terminal growth halving each year (a linear fade from a
    hypergrowth year 3 kept NVIDIA growing ~19% in year 10, which reviewers called unsupported); the FCF margin moves
    from the model's first-year margin to ``m_end`` by year 3 and is held. Shared by ``compute`` and ``paths`` so the
    printed workings are the values. None when the model DCF is missing or the discount rate is too close to
    terminal growth."""
    v = data.valuation
    dcf = v.dcf if v else None
    if not dcf or not dcf.forecast or not v.wacc or not v.wacc.wacc or not gr:
        return None
    years = len(dcf.forecast)
    w, g = v.wacc.wacc, dcf.terminal_growth
    stub, roll, net_debt, minorities, _ = valuation._stub(data)
    fx = data.quote.fx_to_reporting or 1.0
    shares = valuation._shares(data)
    start_rev = data.financials.years[-1].revenue
    path0 = dcf.margin_path or [dcf.fcf_margin] * years
    if not shares or not start_rev:
        return None
    growth, prev_g = list(gr), gr[-1]
    for _ in range(len(gr) + 1, years + 1):
        prev_g = valuation.fade_step(prev_g, g)
        growth.append(prev_g)
    growth = growth[:years]
    revs, prev = [], start_rev
    for x in growth:
        prev *= 1 + x
        revs.append(prev)
    m0 = path0[0]
    margins = [m0 + (m_end - m0) * min(t, 3) / 3 for t in range(1, years + 1)]
    claims = net_debt + minorities - valuation.stakes(data)
    cs = valuation.stub_cash_share(data, revs[0], stub)
    res = valuation._dcf_value(revs, margins, w, g, claims, fx, shares, 0.005, stub, roll, cs)
    if res is None:
        return None
    ev, pv_tv, _ = valuation.dcf_ev(revs, margins, w, g, stub, roll, cs)
    return {"years": [dcf.forecast[i].fiscal_year for i in range(years)], "revenue_growth": growth, "revenue": revs,
            "margins": margins, "fcf_margin": m_end, "pv_explicit": ev - pv_tv, "pv_terminal": pv_tv,
            "enterprise_value": ev, "terminal_share": pv_tv / ev if ev else None, "value_per_share": res[2]}


def compute(data: TearSheetData, picks: list[ScenarioPick]) -> Optional[ScenarioSet]:
    """Run the model's DCF with each scenario's assumptions (code only)."""
    v = data.valuation
    dcf = v.dcf if v else None
    if not dcf or not dcf.forecast or not v.wacc or not v.wacc.wacc:
        return None
    w, g = v.wacc.wacc, dcf.terminal_growth
    if not valuation._shares(data) or not data.financials.years[-1].revenue:
        return None
    by = {}
    for p in picks:
        if p.name in by or len(p.revenue_growth or []) < 1:
            continue
        by[p.name] = p
    if set(by) != {"bear", "base", "bull"}:
        return None
    total = sum(max(0.0, by[k].probability) for k in by) or 1.0
    out = []
    house = [y.revenue_growth for y in data.forecast.years][:3] if data.forecast else []
    base_g = house if len(house) == 3 else [_clip(x, GROWTH_BOUNDS) for x in
                                            (list(by["base"].revenue_growth) + [by["base"].revenue_growth[-1]] * 3)[:3]]
    bands = growth_bands(data, base_g)
    limited: list[str] = []
    widened: list[str] = []
    sg, sm = spreads(data)
    base_m = _clip(by["base"].fcf_margin, MARGIN_BOUNDS)
    lt0 = data.financials.latest
    reported_now = bool(lt0 is not None and lt0.months and data.financials.years
                        and lt0.period_end > data.financials.years[-1].period_end)
    fy0 = data.financials.years[-1].fiscal_year
    for k in ("bear", "base", "bull"):
        p = by[k]
        g3 = house if (k == "base" and len(house) == 3) else p.revenue_growth  # base = the house forecast
        gr = [_clip(x, GROWTH_BOUNDS) for x in (list(g3) + [g3[-1]] * 3)[:3]]
        m_end = _clip(p.fcf_margin, MARGIN_BOUNDS)
        if k != "base":
            for i, band in enumerate(bands):
                if band and not (band[0] - 1e-9 <= gr[i] <= band[1] + 1e-9):
                    gr[i] = min(max(gr[i], band[0]), band[1])
                    limited.append(f"{k} FY{fy0 + 1 + i}")
            # a minimum distance from the base case: full in years nobody has guided, half (within the band) in
            # guided years, none in the partly reported current year
            for i in range(len(gr)):
                partly = i == 0 and reported_now
                if partly:
                    continue
                band = bands[i] if i < len(bands) else None
                gap = sg if band is None else min(sg, band[1] - base_g[i]) / 2
                if k == "bull":
                    gap = gap / 2 if band is None else 0.0
                lo_hi = (base_g[i] - gap, base_g[i] + gap)
                if k == "bear" and gr[i] > lo_hi[0] + 1e-9:
                    gr[i] = _clip(lo_hi[0], GROWTH_BOUNDS)
                    widened.append(f"bear FY{fy0 + 1 + i} growth")
                elif k == "bull" and gap and gr[i] < lo_hi[1] - 1e-9:
                    gr[i] = _clip(lo_hi[1], GROWTH_BOUNDS)
                    widened.append(f"bull FY{fy0 + 1 + i} growth")
            if k == "bear" and m_end > base_m - sm + 1e-9:
                m_end, _ = _clip(base_m - sm, MARGIN_BOUNDS), widened.append("bear margin")
            elif k == "bull" and m_end < base_m + sm / 2 - 1e-9:
                m_end, _ = _clip(base_m + sm / 2, MARGIN_BOUNDS), widened.append("bull margin")
        res = _path(data, gr, m_end)
        if res is None:
            return None
        out.append(Scenario(name=k, probability=round(max(0.0, p.probability) / total, 3),
                            revenue_growth=gr, fcf_margin=m_end, value_per_share=res["value_per_share"],
                            upside=res["value_per_share"] / data.quote.price - 1 if data.quote.price else None,
                            drivers=p.drivers.strip()))
    out.sort(key=lambda s: s.value_per_share)  # keep bear < base < bull by value
    for s, name in zip(out, ("bear", "base", "bull")):
        s.name = name
    wv = sum(s.probability * s.value_per_share for s in out)
    return ScenarioSet(scenarios=out, weighted_value=wv,
                       weighted_upside=wv / data.quote.price - 1 if data.quote.price else None,
                       currency=data.quote.currency,
                       note=(f"Assumptions set by our analyst step from the research notes and the debate"
                             + ("; the base case's revenue growth is our forecast's" if len(house) == 3 else "")
                             + f"; values computed in code with the model's DCF (WACC {w:.1%}, terminal growth "
                             f"{g:.1%}, same net debt and share count). After year 3 the growth above terminal growth "
                             f"halves each year."
                             + (f" Growth in partly reported or guided years is kept within a band around the base "
                                f"case; limited: {', '.join(limited)}." if limited else "")
                             + (f" Bear and bull are kept at least a minimum distance from the base case, set from "
                                f"the company's own historical swings (revenue growth {sg:.0%}, FCF margin {sm:.0%} "
                                f"standard deviation); widened: {', '.join(widened)}." if widened else "")))


def run(data: TearSheetData, evidence_text: str, debate_text: str, lm: dspy.LM, adapter) -> Optional[ScenarioSet]:
    base = model_base_text(data)
    if not base:
        return None
    try:
        with dspy.context(lm=lm, adapter=adapter):
            out = dspy.Predict(SetScenarios)(company=f"{data.profile.name} ({data.profile.ticker})",
                                             model_base=base, evidence=evidence_text, debate=debate_text)
        return compute(data, list(out.scenarios or []))
    except Exception as e:  # scenarios are optional
        log.warning("scenarios failed: %s", e)
        return None


def text(s: Optional[ScenarioSet]) -> str:
    """For the writer: the scenario table as lines (figures as printed)."""
    if not s:
        return ""
    from ..render.viewmodel import ccy
    cur = ccy(s.currency)
    lines = ["SCENARIOS (assumptions by the AI, values computed in code; not the rating):"]
    for x in s.scenarios:
        lines.append(f"- {x.name.title()} ({x.probability:.0%}): revenue growth "
                     + ", ".join(f"{g:+.1%}" for g in x.revenue_growth) + f" over 3 years, FCF margin {x.fcf_margin:.1%}"
                     f" -> {cur} {x.value_per_share:,.2f} ({x.upside:+.1%} vs price). {x.drivers}")
    lines.append(f"- Probability-weighted value: {cur} {s.weighted_value:,.2f} ({s.weighted_upside:+.1%} vs price).")
    lines.append("- After year 3 each scenario's growth above terminal growth halves every year.")
    return "\n".join(lines)


# ---------------------------------------------------------------- checking the drivers
# Run 3 (12 Nov 2026): the drivers are AI text printed next to the scenario numbers and read by the writers, but no
# check ran on them (run 2's bear case leaned on a minor site's CEO note). They now get the writer's checks: every
# figure must be in the evidence or be one of the final scenario numbers (code may have moved an assumption after
# the model wrote it), every cited id must exist, every name must be in the evidence, and a claim the sources
# contradict is removed. A sentence that fails is deleted, never printed. A driver is a hypothesis about the future,
# so "unsupported" alone does not remove it; it is only logged.
_SENT = re.compile(r"(?<=[.!?])\s+(?=[\"'“(\[A-Z])")
_IDS = re.compile(r"\b[RES]\d+\b")
CLAIM_SECTION = "scenario drivers ({}): a scenario hypothesis; check its statements of fact and its cited evidence"


def _sentences(t: str) -> list[str]:
    return [x.strip() for x in _SENT.split(t or "") if x.strip()]


def check_drivers(data: TearSheetData, s: Optional[ScenarioSet], evidence_text: str, lm: Optional[dspy.LM] = None,
                  adapter=None) -> list[str]:
    """Check each scenario's drivers in place (failing sentences deleted). ``evidence_text``: everything the
    scenario call read (notes, facts, the debate). ``lm``: the claim checker (None = code checks only). Returns log
    lines for the guardrail's text issues: "[struck] ..." for a deletion, "[scenario] ..." for a kept doubt."""
    if not s or not s.scenarios:
        return []
    from . import guardrail
    nums: list[float] = []
    for x in s.scenarios:
        for v in [x.probability, x.fcf_margin, x.value_per_share, x.upside, *x.revenue_growth]:
            if v is not None:
                nums += [v, abs(v)]
    nums += [v for v in (s.weighted_value, s.weighted_upside) if v is not None]
    allowed = guardrail.build_allowed(evidence_text or "", model_base_text(data) or "", nums)
    known = set(_IDS.findall(evidence_text or ""))
    lines: list[str] = []
    for x in s.scenarios:
        keep = []
        for sent in _sentences(x.drivers):
            bad = guardrail.unmatched(sent, allowed)
            ghost = [i for i in dict.fromkeys(_IDS.findall(sent)) if i not in known]
            names = guardrail.names_missing(sent, f"{data.profile.name} {evidence_text or ''}")
            why = (f"figures not in the data ({', '.join(bad)})" if bad else
                   f"evidence ids that do not exist ({', '.join(ghost)})" if ghost else
                   f"names not in the evidence ({', '.join(names)})" if names else "")
            if why:
                lines.append(f"[struck] scenario drivers ({x.name}), {why}: {sent}")
            else:
                keep.append(sent)
        x.drivers = " ".join(keep)
    if lm is None or not any(x.drivers for x in s.scenarios):
        return lines
    from . import claimcheck
    parts = {CLAIM_SECTION.format(x.name): x.drivers for x in s.scenarios if x.drivers}
    notes, _ = claimcheck.check(parts, evidence_text or "", f"{data.profile.name} ({data.profile.ticker})", lm,
                                adapter)
    for note in notes:
        x = next((y for y in s.scenarios if CLAIM_SECTION.format(y.name) == note.section), None)
        if x is None:
            continue
        verdict = note.problem.split(" ", 1)[0]
        q = (note.quote or "").strip()
        if verdict in ("wrong", "misleading"):
            sents = _sentences(x.drivers)
            kept = [t for t in sents if not (q and (t.startswith(q[:120]) or q.startswith(t[:120])))]
            if len(kept) < len(sents):
                x.drivers = " ".join(kept)
                lines.append(f"[struck] scenario drivers ({x.name}), claim check: {note.problem} | {q}")
        else:
            lines.append(f"[scenario] {x.name} drivers, claim check (kept, a hypothesis): {note.problem} | {q}")
    return lines


def bridge(data: TearSheetData) -> list[tuple[str, float]]:
    """From the model's mechanical DCF to our fair value, in steps that add up exactly (round-6 review, both
    reviewers: "the HOLD sits below every one of its own cross-checks without a convincing reconciliation").
    Steps: our revenue forecast instead of consensus (the model's margins kept), our base case's FCF margin, then the
    bear and bull cases at their probabilities. Only the first intermediate value is computed here; the others are
    the model DCF and the scenario values themselves."""
    v, sc = data.valuation, (data.valuation.scenarios if data.valuation else None)
    dcf = v.dcf if v else None
    if not (dcf and dcf.forecast and dcf.value_per_share and sc and sc.scenarios and v.wacc and v.wacc.wacc):
        return []
    base = next((x for x in sc.scenarios if x.name == "base"), None)
    if base is None:
        return []
    years = len(dcf.forecast)
    w, g = v.wacc.wacc, dcf.terminal_growth
    growth, prev_g = list(base.revenue_growth[:3]), base.revenue_growth[min(2, len(base.revenue_growth) - 1)]
    while len(growth) < years:
        prev_g = valuation.fade_step(prev_g, g)
        growth.append(prev_g)
    revs, r = [], data.financials.years[-1].revenue
    for x in growth[:years]:
        r *= 1 + x
        revs.append(r)
    stub, roll, net_debt, minorities, _ = valuation._stub(data)
    res = valuation._dcf_value(revs, dcf.margin_path or [dcf.fcf_margin] * years, w, g,
                               net_debt + minorities - valuation.stakes(data), data.quote.fx_to_reporting or 1.0,
                               valuation._shares(data), 0.005, stub, roll, valuation.stub_cash_share(data, revs[0], stub))
    if res is None:
        return []
    v0, v1, v2, v3 = dcf.value_per_share, res[2], base.value_per_share, sc.weighted_value
    return [("Model DCF (consensus revenue, model FCF margins)", v0),
            ("Our revenue forecast instead of consensus", v1 - v0),
            ("Our base case's FCF margin", v2 - v1),
            ("Bear and bull cases at their probabilities", v3 - v2),
            ("= Our fair value (probability-weighted)", v3)]


def flip_points(data: TearSheetData, buy: float = 0.15, sell: float = -0.10) -> dict:
    """How far the probabilities must move, from the base case, for the rating to change from where it is now.

    Keys: ``now`` (Buy / Hold / Sell at today's price) and, as relevant, ``bear_for_hold`` (Buy -> Hold),
    ``bull_for_buy`` (Hold -> Buy), ``bear_for_sell`` (Hold -> Sell), ``bull_for_hold`` (Sell -> Hold). Each is the
    probability the bull or bear case would need, the extra weight taken from the base case; None when no shift
    within the base case's probability gets there. Round 9: when the rating was already Buy the old version printed
    "Buy if the bull case's probability rose from 25% to 25%"."""
    sc, price = (data.valuation.scenarios if data.valuation else None), data.quote.price
    if not (sc and sc.scenarios and price):
        return {}
    by = {x.name: x for x in sc.scenarios}
    if not {"bear", "base", "bull"} <= set(by):
        return {}
    fv, base_p = sc.weighted_value, by["base"].probability
    up = by["bull"].value_per_share - by["base"].value_per_share
    down = by["base"].value_per_share - by["bear"].value_per_share
    buy_at, sell_at = price * (1 + buy), price * (1 + sell)

    def shift(gap: float, step: float, start: float) -> Optional[float]:
        return start + gap / step if step > 0 and gap / step <= base_p else None

    now = "Buy" if fv >= buy_at else ("Sell" if fv <= sell_at else "Hold")
    out: dict = {"now": now}
    if now == "Buy":
        out["bear_for_hold"] = shift(fv - buy_at, down, by["bear"].probability)
    elif now == "Sell":
        out["bull_for_hold"] = shift(sell_at - fv, up, by["bull"].probability)
    else:
        out["bull_for_buy"] = shift(buy_at - fv, up, by["bull"].probability)
        out["bear_for_sell"] = shift(fv - sell_at, down, by["bear"].probability)
    return out


def paths(data: TearSheetData) -> list[dict]:
    """The scenario model's workings, one dict per scenario (bear, base, bull): ``name``, ``probability``,
    ``years`` (fiscal years, ints), ``revenue_growth`` (revenue growth each forecast year, the same length for every
    scenario: the scenario's three years, then the halving fade), ``revenue``, ``margins`` (FCF margin each year), ``fcf_margin`` (the margin reached by year 3),
    ``pv_explicit`` and ``pv_terminal`` (present values in the reporting currency, at the price date),
    ``enterprise_value``, ``terminal_share`` and ``value_per_share`` (trading currency; equal to the scenario's
    value). Computed with the same helper as ``compute``; [] without scenarios or when any scenario fails."""
    sc = data.valuation.scenarios if data.valuation else None
    if not (sc and sc.scenarios):
        return []
    out = []
    try:
        for x in sc.scenarios:
            res = _path(data, list(x.revenue_growth), x.fcf_margin)
            if res is None:
                return []
            out.append({"name": x.name, "probability": x.probability, **res})
    except Exception as e:  # an exhibit, never a reason to lose the report
        log.warning("scenario paths failed: %s", e)
        return []
    return out


FRAGILITY_BEAR = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40)
FRAGILITY_BULL = (0.10, 0.15, 0.20, 0.25, 0.30)


def fragility(data: TearSheetData, buy: float = 0.15, sell: float = -0.10) -> Optional[dict]:
    """Where the rating flips: the probability-weighted fair value and the rating it gives (the rating rule's
    thresholds: Buy at ``buy`` or more above the price, Sell at ``sell`` or more below) for bear-case probabilities of
    15% to 40% (rows) by bull-case probabilities of 10% to 30% (columns), the base case taking the rest; the three
    scenario values are held. Returns ``{"bear": [...], "bull": [...], "cells": [[{"value", "upside", "rating"}]],
    "current": [i, j] or None}``; ``current`` is the cell at today's probabilities when they fall on the grid. None
    without the three scenarios or a price."""
    sc, price = (data.valuation.scenarios if data.valuation else None), data.quote.price
    if not (sc and sc.scenarios and price):
        return None
    by = {x.name: x for x in sc.scenarios}
    if not {"bear", "base", "bull"} <= set(by):
        return None
    vb, vm, vu = by["bear"].value_per_share, by["base"].value_per_share, by["bull"].value_per_share
    cells = []
    for pb in FRAGILITY_BEAR:
        row = []
        for pu in FRAGILITY_BULL:
            value = pb * vb + pu * vu + (1 - pb - pu) * vm
            up = value / price - 1
            row.append({"value": value, "upside": up,
                        "rating": "Buy" if up >= buy else ("Sell" if up <= sell else "Hold")})
        cells.append(row)
    near = lambda grid, p: next((i for i, x in enumerate(grid) if abs(x - p) < 0.0005), None)  # noqa: E731
    i, j = near(FRAGILITY_BEAR, by["bear"].probability), near(FRAGILITY_BULL, by["bull"].probability)
    return {"bear": list(FRAGILITY_BEAR), "bull": list(FRAGILITY_BULL), "cells": cells,
            "current": [i, j] if i is not None and j is not None else None}


def flip_text(data: TearSheetData, buy: float = 0.15, sell: float = -0.10) -> str:
    """One plain sentence on what would change the rating, or "" when there are no scenarios."""
    f, sc = flip_points(data, buy, sell), data.valuation.scenarios if data.valuation else None
    if not (f and sc):
        return ""
    by = {x.name: x for x in sc.scenarios}
    p = lambda x: f"{x:.0%}"  # noqa: E731
    # Run 2 review: the flip at 29.5% was printed as "rose ... to 29%", where the rating is still Buy (the grid said
    # 30%). A probability the case must rise to is rounded up, so the sentence is true at the printed figure.
    up = lambda x: f"{math.ceil(x * 100 - 1e-9):.0f}%"  # noqa: E731
    now, bits = f["now"], []
    edge = {"Buy": ("bear_for_hold", "bear", "Hold"), "Sell": ("bull_for_hold", "bull", "Hold")}.get(now)
    if edge and f.get(edge[0]) is not None and up(f[edge[0]]) == p(by[edge[1]].probability):
        return (f"it is {now} now, but only just: any rise in the {edge[1]} case's probability (now "
                f"{p(by[edge[1]].probability)}, taken from the base case) takes it to {edge[2]}")
    if now == "Buy":
        v = f.get("bear_for_hold")
        bits.append(f"it is Buy now and would fall to Hold if the bear case's probability rose from "
                    f"{p(by['bear'].probability)} to {up(v)} (taken from the base case)" if v is not None else
                    "it is Buy now, and no shift of probability from the base to the bear case takes it to Hold")
    elif now == "Sell":
        v = f.get("bull_for_hold")
        bits.append(f"it is Sell now and would rise to Hold if the bull case's probability rose from "
                    f"{p(by['bull'].probability)} to {up(v)} (taken from the base case)" if v is not None else
                    "it is Sell now, and no shift of probability from the base to the bull case takes it to Hold")
    else:
        v = f.get("bull_for_buy")
        if v is not None and up(v) == p(by["bull"].probability):
            bits.append(f"it is Hold now, just short of Buy: any rise in the bull case's probability (now "
                        f"{p(by['bull'].probability)}, taken from the base case) makes it Buy")
        else:
            bits.append(f"it is Hold now; it would be Buy if the bull case's probability rose from "
                        f"{p(by['bull'].probability)} to {up(v)} (taken from the base case)" if v is not None else
                        "it is Hold now; no shift of probability from the base to the bull case makes it Buy")
        v = f.get("bear_for_sell")
        if v is not None and up(v) == p(by["bear"].probability):
            bits.append("any rise in the bear case's probability makes it Sell")
        else:
            bits.append(f"Sell if the bear case's rose from {p(by['bear'].probability)} to {up(v)}" if v is not None
                        else "no shift from the base to the bear case makes it Sell")
    return "; ".join(bits)


def bridge_text(data: TearSheetData) -> str:
    """Lines for the writer and the report: the bridge and the flip points (figures as printed)."""
    from ..render.viewmodel import ccy
    cur, lines = ccy(data.quote.currency), []
    b = bridge(data)
    if b:
        lines.append("VALUE BRIDGE (computed in code; why our fair value differs from the model DCF): " + "; ".join(
            f"{k} {cur} {x:,.2f}" if i in (0, len(b) - 1) else f"{k} {x:+,.2f}" for i, (k, x) in enumerate(b)) + ".")
    ft = flip_text(data)
    if ft:
        lines.append("RATING SENSITIVITY (computed in code; at today's price): " + ft + ".")
    return "\n".join(lines)
