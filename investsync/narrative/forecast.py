"""House forecast: the AI sets the drivers for the next three fiscal years, code builds the P&L and compares it with
consensus.

Why: every round-3 blind reviewer marked the DeepSeek reports down for "no forecasts of its own"; the Opus reports
wrote FY+1..FY+3 estimates and argued them against consensus. As with the scenarios, the AI chooses only the drivers
(revenue growth, gross and operating margin, tax rate, share-count change), each tied to the evidence; code computes
revenue, operating and net profit and EPS, the gap to consensus, and what the full-year forecast implies for the rest
of the current fiscal year given what is already reported. The base-case scenario then uses the same revenue path.
Never sets the rating by itself.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import dspy
from pydantic import BaseModel, Field

from ..schema import HouseForecast, HouseForecastYear, TearSheetData

log = logging.getLogger(__name__)
YEARS = 3
GROWTH, GM, OPM, TAX, SHARES, OTHER = (-0.50, 2.00), (-0.20, 0.95), (-0.50, 0.80), (0.0, 0.45), (-0.08, 0.08), (-0.10, 0.30)


class YearDrivers(BaseModel):
    period: str = Field(description='e.g. "FY2027E"')
    revenue_growth: float = Field(description="Year-on-year, as a decimal (0.20 = +20%)")
    gross_margin: Optional[float] = Field(None, description="As a decimal; null if the company reports no gross profit")
    operating_margin: float = Field(description="Operating profit / revenue, as a decimal")
    other_income: Optional[float] = Field(None, description="Income between operating and pre-tax profit (net "
                                                            "interest, share of associates) as a share of revenue; "
                                                            "leave out one-off gains")
    tax_rate: float = Field(description="Effective tax rate, as a decimal")
    share_change: float = Field(0.0, description="Change in the diluted share count vs the year before "
                                                 "(-0.02 = 2% fewer shares after buybacks)")


class SetForecast(dspy.Signature):
    """You are the lead analyst writing the house forecast for the next three fiscal years. You choose only the
    drivers for each year; code builds revenue, operating profit, net profit and EPS from them and compares the
    result with consensus.

    - The first year is already partly reported: start from the year to date, the latest quarter and management
      guidance in the research notes. Code shows what your full-year figure implies for the rest of the year.
    - Where the research notes give management's outlook for a year (next quarter, the full year, or a
      preliminary view of the next fiscal year), start that year from it. Differ only on cited evidence.
    - Then use the evidence: orders, capacity, prices, policy and tax changes, competition, broker forecasts.
      Do not copy consensus. Where you differ, say why in `vs_consensus`; where you agree, say what that rests on.
    - A revenue forecast more than 5% away from consensus in any year must cite at least one research note id
      ([R12]) in `vs_consensus` that supports the difference; code checks this and otherwise pulls the year back
      to within 5% of consensus. Never say what consensus or the brokers assume or extrapolate unless a research
      note says so.
    - Margins follow named drivers (mix, input costs, price cuts, a new tax, scale, depreciation from capex) and
      start from the latest reported margins unless the evidence says otherwise. Where management guided margins
      (the next quarter, a trough, the next year), the year's margin follows that guidance; a margin above or below
      the guided range needs a cited note.
    - other_income: what sits between operating and pre-tax profit (net interest, associates), as a share of
      revenue. The history shows past years; leave out one-off items such as gains on equity investments or
      disposals, which do not recur. tax_rate: the effective rate given in the history unless a known tax change
      applies. share_change: buybacks lower the count; share-based pay and issuance raise it.
    - Driver texts: one or two sentences each, citing evidence ids (R12, E40, S3). No figures other than your
      assumptions and figures copied from the inputs."""
    company: str = dspy.InputField()
    history: str = dspy.InputField(desc="Reported fiscal years, this fiscal year to date, consensus, model base case")
    evidence: str = dspy.InputField(desc="Research notes (guidance, results, policy, street), numbered")
    feedback: str = dspy.InputField(desc="Problems with your previous attempt; 'None' at first")
    years: list[YearDrivers] = dspy.OutputField(desc="Exactly three, in order")
    revenue_drivers: str = dspy.OutputField(desc="What drives revenue over the three years, citing evidence ids")
    margin_drivers: str = dspy.OutputField(desc="What drives the margins, citing evidence ids")
    vs_consensus: str = dspy.OutputField(desc="Where and why the forecast differs from (or agrees with) consensus")
    key_risk: str = dspy.OutputField(desc="The assumption most likely to be wrong, and what would show it early")


def _clip(x, lo_hi):
    return min(max(float(x), lo_hi[0]), lo_hi[1])


def _mn(x: float) -> str:
    return f"{x / 1e6:,.0f}mn"


def _base(data: TearSheetData) -> Optional[dict]:
    fin = data.financials
    if not fin or not fin.years:
        return None
    fy = fin.years[-1]
    if not fy.revenue or fy.operating_income is None or fy.net_income is None:
        return None
    shares = fy.net_income / fy.diluted_eps if fy.diluted_eps else None
    if not shares or shares <= 0:
        from ..quant import valuation
        shares = valuation._shares(data)
    if not shares:
        return None
    pt, tax = fy.pretax_income, fy.income_tax
    other = (pt - fy.operating_income) / fy.revenue if pt is not None else 0.0
    tax_rate = tax / pt if pt and tax is not None and pt > 0 else 0.20
    keep = fy.net_income / (pt - tax) if pt and tax is not None and pt - tax > 0 else 1.0
    return {"fy": fy, "shares": shares, "other": other, "tax": min(max(tax_rate, 0.0), 0.45),
            "keep": min(max(keep, 0.5), 1.1), "gm_ok": fy.gross_profit is not None,
            "opm_le_gm": fy.gross_profit is None or fy.operating_income <= fy.gross_profit}


def _consensus(data: TearSheetData) -> tuple[dict, Optional[str]]:
    """Consensus rows by period (same currency as the reports only) and a note if its EPS is on an adjusted basis."""
    c, fin = data.consensus, data.financials
    if not c or not c.estimates or (c.estimate_currency and c.estimate_currency != fin.currency):
        return {}, None
    rows = {e.period: e for e in c.estimates}
    fy = fin.years[-1]
    first = rows.get(f"FY{fy.fiscal_year + 1}E")
    note = None
    if first and first.eps_avg and first.eps_growth is not None and fy.diluted_eps:
        implied = first.eps_avg / (1 + first.eps_growth)
        if abs(implied / fy.diluted_eps - 1) > 0.05:
            note = (f"Consensus EPS looks like an adjusted (non-GAAP / non-IFRS) figure: its growth implies FY"
                    f"{fy.fiscal_year} EPS of {implied:,.2f} vs reported diluted EPS of {fy.diluted_eps:,.2f}. Compare "
                    f"EPS growth with consensus, not the EPS level.")
    return rows, note


def _remainder(data: TearSheetData, rev1: float) -> Optional[tuple[str, float, float, Optional[float]]]:
    """What the first forecast year implies for the unreported rest of it: (label, revenue, growth, ytd growth)."""
    lt, fy = data.financials.latest, data.financials.years[-1]
    if lt is None or not lt.revenue or not lt.prior_revenue or not fy.revenue or lt.months >= 12:
        return None
    prior_rest = fy.revenue - lt.prior_revenue
    if prior_rest <= 0:
        return None
    rest = rev1 - lt.revenue
    ytd = lt.revenue / lt.prior_revenue - 1
    label = {3: "the last 9 months", 6: "the second half", 9: "the fourth quarter"}.get(lt.months, "the rest of the year")
    return label, rest, rest / prior_rest - 1, ytd


def history_text(data: TearSheetData) -> Optional[str]:
    b = _base(data)
    if not b:
        return None
    fin, ccy = data.financials, data.financials.currency
    lines = [f"Reporting currency {ccy}; amounts in millions."]
    for y in fin.years[-3:]:
        if not y.revenue:
            continue
        bits = [f"FY{y.fiscal_year}: revenue {_mn(y.revenue)}"]
        if y.revenue_growth is not None:
            bits.append(f"growth {y.revenue_growth:+.1%}")
        if y.gross_profit is not None:
            bits.append(f"gross margin {y.gross_profit / y.revenue:.1%}")
        if y.operating_income is not None:
            bits.append(f"operating margin {y.operating_income / y.revenue:.1%}")
        if y.net_income is not None:
            bits.append(f"net margin {y.net_income / y.revenue:.1%}")
        if y.pretax_income is not None and y.operating_income is not None:
            bits.append(f"below the operating line {(y.pretax_income - y.operating_income) / y.revenue:+.1%} of revenue")
        if y.pretax_income and y.income_tax is not None and y.pretax_income > 0:
            bits.append(f"effective tax rate {y.income_tax / y.pretax_income:.1%}")
        if y.diluted_eps:
            bits.append(f"diluted EPS {y.diluted_eps:,.2f}")
        lines.append(", ".join(bits))
    lines.append(f"Below the operating line (pre-tax profit minus operating profit) was {b['other']:+.1%} of revenue "
                 f"in FY{b['fy'].fiscal_year}; it may include one-off gains. Diluted shares {b['shares'] / 1e6:,.0f}mn.")
    lt = fin.latest
    if lt is not None and lt.revenue:
        bits = [f"This fiscal year so far ({lt.label}): revenue {_mn(lt.revenue)}"]
        if lt.prior_revenue:
            bits.append(f"{lt.revenue / lt.prior_revenue - 1:+.1%} year on year")
        if lt.gross_profit is not None:
            gm = f"gross margin {lt.gross_profit / lt.revenue:.1%}"
            if lt.prior_gross_profit is not None and lt.prior_revenue:
                gm += f" (a year earlier {lt.prior_gross_profit / lt.prior_revenue:.1%})"
            bits.append(gm)
        if lt.operating_income is not None:
            bits.append(f"operating margin {lt.operating_income / lt.revenue:.1%}")
        if lt.quarter_label and lt.quarter_revenue and lt.quarter_revenue_prior:
            bits.append(f"latest quarter {lt.quarter_label} revenue {_mn(lt.quarter_revenue)} "
                        f"({lt.quarter_revenue / lt.quarter_revenue_prior - 1:+.1%})")
        lines.append(", ".join(bits) + ".")
        if lt.prior_revenue and b["fy"].revenue > lt.prior_revenue:
            lines.append(f"The same months a year earlier were {_mn(lt.prior_revenue)} of FY{b['fy'].fiscal_year}'s "
                         f"{_mn(b['fy'].revenue)}, so the rest of that year was {_mn(b['fy'].revenue - lt.prior_revenue)}.")
    rows, note = _consensus(data)
    for p in sorted(rows):
        e = rows[p]
        bits = [f"Consensus {p}"]
        if e.revenue_avg:
            bits.append(f"revenue {_mn(e.revenue_avg)}" + (f" ({e.revenue_growth:+.1%})" if e.revenue_growth is not None else ""))
        if e.eps_avg:
            bits.append(f"EPS {e.eps_avg:,.2f}" + (f" ({e.eps_growth:+.1%})" if e.eps_growth is not None else ""))
        if e.analysts:
            bits.append(f"{e.analysts} analysts")
        lines.append(", ".join(bits) + " (third-party).")
    if note:
        lines.append(note)
    from .scenarios import model_base_text
    mb = model_base_text(data, with_forecast=False)
    if mb:
        lines.append(mb)
    return "\n".join(lines)


def compute(data: TearSheetData, picks: list[YearDrivers]) -> Optional[HouseForecast]:
    b = _base(data)
    if not b or len(picks) < YEARS:
        return None
    fy, rows = b["fy"], _consensus(data)[0]
    out, rev, shares, eps_prev = [], fy.revenue, b["shares"], fy.diluted_eps
    for i, p in enumerate(picks[:YEARS]):
        year = fy.fiscal_year + i + 1
        g = _clip(p.revenue_growth, GROWTH)
        gm = _clip(p.gross_margin, GM) if (p.gross_margin is not None and b["gm_ok"]) else None
        opm = _clip(p.operating_margin, OPM)
        if gm is not None and b["opm_le_gm"]:
            opm = min(opm, gm)
        tax = _clip(p.tax_rate, TAX)
        other = _clip(p.other_income, OTHER) if p.other_income is not None else b["other"]
        rev *= 1 + g
        op = rev * opm
        ni = (op + other * rev) * (1 - tax) * b["keep"]
        if i == 0:
            ni0 = ni
            ni = _reported_basis(data, rev, opm, other, tax, b["keep"], ni)
            mixed = _mixed_basis(data) if ni != ni0 else None
        shares *= 1 + _clip(p.share_change, SHARES)
        eps = ni / shares
        e = rows.get(f"FY{year}E")
        out.append(HouseForecastYear(
            period=f"FY{year}E", revenue=rev, revenue_growth=g, gross_margin=gm, operating_margin=opm,
            operating_income=op, other_income_share=other, net_income=ni, eps=eps,
            eps_growth=eps / eps_prev - 1 if eps_prev and eps_prev > 0 else None,
            consensus_revenue=e.revenue_avg if e else None, consensus_eps=e.eps_avg if e else None,
            consensus_eps_growth=e.eps_growth if e else None,
            revenue_vs_consensus=rev / e.revenue_avg - 1 if e and e.revenue_avg else None,
            eps_vs_consensus=eps / e.eps_avg - 1 if e and e.eps_avg else None))
        eps_prev = eps
    note = ("Drivers set by the AI from the research notes and reported figures; revenue, profit "
            f"and EPS computed in code (minority share held at its FY{fy.fiscal_year} level).")
    if mixed and out:  # run 4 (round 12): GAAP-with-gains EPS was set against adjusted consensus (+10.2%, ~+2% like for like)
        out[0].eps_vs_consensus = None
        if len(out) > 1:
            out[1].eps_growth = None
        note += (f" {out[0].period} net profit keeps the reported year to date, which includes {mixed} of "
                 f"non-operating income (investment gains and other items below operating profit) that consensus EPS "
                 f"normally excludes, so {out[0].period} EPS is not compared with consensus"
                 + (f" and {out[1].period} EPS growth is not shown." if len(out) > 1 else "."))
    return HouseForecast(currency=data.financials.currency, years=out, consensus_note=_consensus(data)[1],
                         remainder=_remainder_text(data, out[0].revenue), note=note)


def _mixed_basis(data: TearSheetData) -> Optional[str]:
    """Run 4: the reported year to date carries non-operating income above 5% of its net profit (filed data:
    nonoperating_ytd, else investment_gains_ytd): returns that amount as printed ("USD 24.1bn"), else None."""
    lt = data.financials.latest
    if lt is None or not lt.net_income:
        return None
    v = next((f.value for k in ("nonoperating_ytd", "investment_gains_ytd") for f in (data.filing_facts or [])
              if f.key == k and f.value is not None), None)
    if v is None or abs(v) <= 0.05 * abs(lt.net_income):  # both in full units
        return None
    return f"{data.financials.currency} {v / 1e9:,.1f}bn"


def _reported_basis(data: TearSheetData, rev: float, opm: float, other: float, tax: float, keep: float,
                    ni: float) -> float:
    """Run 2 review: FY2027E net profit was forecast for the whole year at a 0.5% "below the line" share, although
    the first half had already booked 24.1bn of investment gains, so the year was effectively ex-gains while its
    growth was measured against a reported (GAAP) prior year. For the partly reported current year, the reported
    year-to-date net profit is kept and only the remaining months are forecast. Falls back to ``ni``."""
    fy, lt = (data.financials.years[-1] if data.financials.years else None), data.financials.latest
    if fy is None or lt is None or lt.period_end <= fy.period_end or not (0 < (lt.months or 0) < 12):
        return ni
    if lt.revenue is None or lt.net_income is None or rev <= lt.revenue:
        return ni
    rest = rev - lt.revenue
    return lt.net_income + (rest * opm + other * rest) * (1 - tax) * keep


def _remainder_text(data: TearSheetData, rev1: float) -> Optional[str]:
    r = _remainder(data, rev1)
    if not r:
        return None
    label, rest, g, ytd = r
    out = (f"The FY{data.financials.years[-1].fiscal_year + 1}E revenue forecast implies revenue of {_mn(rest)} "
           f"for {label} ({g:+.1%} year on year), against {ytd:+.1%} reported so far this year.")
    # against consensus for the same quarters (results preview: is our year above or below the Street's quarters?)
    lt = data.financials.latest
    qs = (data.consensus.quarters if data.consensus else [])[: max(0, (12 - lt.months) // 3)] if lt else []
    if qs and len(qs) == (12 - lt.months) // 3 and all(q.revenue_avg for q in qs) and \
            (data.consensus.estimate_currency or data.financials.currency) == data.financials.currency:
        street = sum(q.revenue_avg for q in qs)
        out += (f" Consensus for those quarters ({' + '.join(q.period for q in qs)}) is {_mn(street)}, so our "
                f"forecast is {rest / street - 1:+.1%} versus the Street for {label}.")
    return out


def _problems(data: TearSheetData, picks: list[YearDrivers]) -> list[str]:
    if len(picks) < YEARS:
        return [f"Give exactly {YEARS} years, in order."]
    f = compute(data, picks)
    if not f:
        return []
    r = _remainder(data, f.years[0].revenue)
    if r and r[1] <= 0:
        return [f"Your first-year revenue is below what is already reported this year to date. Raise it."]
    if r and r[3] is not None and abs(r[2] - r[3]) > 0.25:
        return [f"{f.remainder} That is far from the trend so far. Keep it only if guidance or other evidence "
                f"supports it (say which in revenue_drivers); otherwise adjust the first year's growth."]
    return []


DEV_FREE = 0.05  # a revenue forecast within 5% of consensus needs no cited evidence
_RID = re.compile(r"\bR(\d{1,3})\b")


def _note_ids(data: TearSheetData) -> set[str]:
    return {f.id for f in (data.research.facts if data.research else [])}


def _outlook_ids(data: TearSheetData, year: int) -> list[str]:
    """Research notes with management's outlook for a given fiscal year (guidance topic, the year named; for the next
    fiscal year also "next year" / "next fiscal year" / 明年, as said on the call)."""
    pat = re.compile(rf"\b(fiscal(?: year)? {year}|FY ?{year}|FY ?{year % 100}\b|{year}\b|{year}年)", re.I)
    ys = data.financials.years if getattr(data, "financials", None) else []
    nxt = re.compile(r"\bnext (?:fiscal )?year\b|明年|下一财年", re.I) if ys and year == ys[-1].fiscal_year + 2 else None
    return [f.id for f in (data.research.facts if data.research else [])
            if f.topic == "guidance" and (pat.search(f"{f.text} {f.quote}")
                                          or (nxt is not None and nxt.search(f"{f.text} {f.quote}")))]


def evidence_problems(data: TearSheetData, f: HouseForecast) -> list[str]:
    """Round-6 review (both reviewers, material): FY2028 revenue 12% below consensus and contrary to management's
    preliminary outlook, with no cited source and an invented reason. A departure of more than DEV_FREE needs a cited
    research note; where a note gives management's outlook for that year it must be cited."""
    cited = set(_RID.findall(f"{f.vs_consensus} {f.revenue_drivers}"))
    cited = {f"R{n}" for n in cited} & _note_ids(data)
    out = []
    for y in f.years:
        dev = y.revenue_vs_consensus
        if dev is None or abs(dev) <= DEV_FREE:
            continue
        year = int(y.period[2:6])
        guide = _outlook_ids(data, year)
        if guide and not cited & set(guide):
            out.append(f"{y.period} revenue is {dev:+.1%} vs consensus, and research note(s) {', '.join(guide)} give "
                       f"management's outlook for that year: start from it, or cite in vs_consensus the evidence "
                       f"for differing.")
        elif not cited:
            out.append(f"{y.period} revenue is {dev:+.1%} vs consensus. A difference of more than {DEV_FREE:.0%} "
                       f"needs evidence: cite the research note ids ([R12]) that support it in vs_consensus, or move "
                       f"within {DEV_FREE:.0%} of consensus.")
    return out


_MARGIN_GUIDE = re.compile(r"gross margin|tax rate|毛利率|税率", re.I)


def margin_problems(data: TearSheetData, f: HouseForecast) -> list[str]:
    """Round-7 review (both reviewers): the forecast kept a 74-75% gross margin and a 15.5% tax rate against management's
    guided Q4 trough of 71-72% and 16-18% tax, which produced an "EPS above consensus" claim. Every research note with
    management's gross-margin or tax guidance must be cited in margin_drivers."""
    notes = [x for x in (data.research.facts if data.research else [])
             if x.topic == "guidance" and _MARGIN_GUIDE.search(f"{x.text} {x.quote}")]
    cited = {f"R{n}" for n in _RID.findall(f.margin_drivers or "")}
    missing = [x.id for x in notes if x.id not in cited]
    if not missing:
        return []
    return [f"Research note(s) {', '.join(missing)} give management's gross-margin or tax guidance: set each year's "
            f"margins and tax rate from them (a margin outside the guided range needs a cited reason) and cite them in "
            f"margin_drivers."]


def clamp_to_consensus(data: TearSheetData, picks: list[YearDrivers], f: HouseForecast) -> HouseForecast:
    """Last resort when the evidence rule still fails: years more than DEV_FREE from consensus are pulled to the
    edge of the band (the AI's growth is kept for years without consensus)."""
    rows, fy = _consensus(data)[0], data.financials.years[-1]
    rev, new, moved = fy.revenue, [], []
    for i, p in enumerate(picks[:YEARS]):
        year = fy.fiscal_year + i + 1
        g = _clip(p.revenue_growth, GROWTH)
        e = rows.get(f"FY{year}E")
        if e and e.revenue_avg:
            lo, hi = e.revenue_avg * (1 - DEV_FREE), e.revenue_avg * (1 + DEV_FREE)
            r = rev * (1 + g)
            if not lo <= r <= hi:
                g = min(max(r, lo), hi) / rev - 1
                moved.append(f"FY{year}E")
        new.append(p.model_copy(update={"revenue_growth": g}))
        rev *= 1 + g
    out = compute(data, new)
    if out is None or not moved:
        return f
    out.revenue_drivers, out.margin_drivers, out.key_risk = f.revenue_drivers, f.margin_drivers, f.key_risk
    out.vs_consensus = (f"{', '.join(moved)} revenue was pulled to within {DEV_FREE:.0%} of consensus by code: the "
                        f"analyst's larger difference was not supported by a cited research note.")
    out.note = (out.note or "") + f" {out.vs_consensus}"
    return out


def run(data: TearSheetData, evidence_text: str, lm: dspy.LM, adapter) -> Optional[HouseForecast]:
    hist = history_text(data)
    if not hist:
        return None
    company = f"{data.profile.name} ({data.profile.ticker})"
    feedback, best, best_picks = "None", None, []
    try:
        with dspy.context(lm=lm, adapter=adapter):
            for _ in range(2):  # one retry, only when code finds a problem
                out = dspy.Predict(SetForecast)(company=company, history=hist, evidence=evidence_text,
                                                feedback=feedback)
                picks = list(out.years or [])
                f = compute(data, picks)
                if f:
                    f.revenue_drivers, f.margin_drivers = (out.revenue_drivers or "").strip(), (out.margin_drivers or "").strip()
                    f.vs_consensus, f.key_risk = (out.vs_consensus or "").strip(), (out.key_risk or "").strip()
                    best, best_picks = f, picks
                problems = _problems(data, picks) + ((evidence_problems(data, f) + margin_problems(data, f)) if f else [])
                if not problems:
                    break
                feedback = " ".join(problems)
    except Exception as e:  # the forecast is optional
        log.warning("house forecast failed: %s", e)
    if best is not None and evidence_problems(data, best):
        best = clamp_to_consensus(data, best_picks, best)
    return best


def text(f: Optional[HouseForecast]) -> str:
    """For the writer and the scenarios step: the forecast table as lines (figures as printed)."""
    if not f:
        return ""
    lines = [f"HOUSE FORECAST (drivers set by the AI analyst, figures computed in code; {f.currency} millions "
             f"except per-share figures):"]
    for y in f.years:
        bits = [f"- {y.period}: revenue {_mn(y.revenue)} ({y.revenue_growth:+.1%})"]
        if y.consensus_revenue:
            bits.append(f"consensus {_mn(y.consensus_revenue)}, ours {y.revenue_vs_consensus:+.1%} vs consensus")
        if y.gross_margin is not None:
            bits.append(f"gross margin {y.gross_margin:.1%}")
        bits.append(f"operating margin {y.operating_margin:.1%}")
        if y.other_income_share is not None:
            bits.append(f"below the operating line {y.other_income_share:+.1%} of revenue")
        bits.append(f"net profit {_mn(y.net_income)}")
        eps = f"EPS {y.eps:,.2f}" + (f" ({y.eps_growth:+.1%})" if y.eps_growth is not None else "")
        if y.consensus_eps:
            eps += (f", consensus {y.consensus_eps:,.2f}" + (f" ({y.consensus_eps_growth:+.1%})"
                                                             if y.consensus_eps_growth is not None else ""))
            if not f.consensus_note and y.eps_vs_consensus is not None:
                eps += f", ours {y.eps_vs_consensus:+.1%} vs consensus"
        bits.append(eps)
        lines.append("; ".join(bits))
    for k, v in (("Revenue drivers", f.revenue_drivers), ("Margin drivers", f.margin_drivers),
                 ("Versus consensus", f.vs_consensus), ("Key risk to the forecast", f.key_risk)):
        if v:
            lines.append(f"- {k}: {v}")
    for x in (f.remainder, f.consensus_note):
        if x:
            lines.append(f"- {x}")
    return "\n".join(lines)
