"""Evidence set for the deep analysis: every bull / bear argument must cite these ids.

* ``E`` ids number each line of the facts the model already reads, in place (no extra tokens).
* ``S`` ids are signals computed in code from the data. Each carries a *stance*, the side its
  sign supports by a fixed rule (cheaper than peers -> bull, margin falling -> bear, ...), so code
  can catch an argument that twists the other side's evidence (FinRobot's bull/bear rule).

Signals also add code-computed changes (e.g. "+12.3pp") so the model never has to subtract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from ..render.viewmodel import ccy, num, pct
from ..schema import TearSheetData

Stance = Literal["bull", "bear", "neutral"]


@dataclass(frozen=True)
class Item:
    id: str
    label: str
    value: str
    stance: Stance = "neutral"
    kind: Literal["fact", "signal"] = "fact"

    def line(self) -> str:
        side = f" (sign supports the {self.stance} case)" if self.stance != "neutral" else ""
        return f"[{self.id}] {self.label}: {self.value}{side}"


@dataclass
class EvidenceSet:
    items: dict[str, Item]
    text: str            # signals block + numbered facts, as the deep steps read it

    def get(self, eid: str) -> Optional[Item]:
        return self.items.get(eid.strip().upper())

    def valid(self, ids) -> list[str]:
        return [i.strip().upper() for i in ids or [] if self.get(i)]


_ID = re.compile(r"\b[ES]\d{1,3}\b")


def number_facts(facts: str) -> tuple[str, dict[str, Item]]:
    """Prefix every fact line that holds a figure with [E1], [E2], ... and index them."""
    out, items, section, n = [], {}, "", 0
    for line in facts.split("\n"):
        s = line.strip()
        if not s or not re.search(r"\d", s):
            if s.endswith(":") and not s.startswith("- "):
                section = s[:-1]
            out.append(line)
            continue
        if s.endswith(":") and not s.startswith("- "):
            section = s[:-1]
            out.append(line)
            continue
        n += 1
        eid = f"E{n}"
        body = s[2:] if s.startswith("- ") else s
        label, sep, value = body.partition(":")
        if not sep or len(label) > 70:
            label, value = (section or body[:50]), body
        elif s.startswith("- ") and section:
            label = f"{section.split(' (')[0]} · {label}"
        items[eid] = Item(eid, label.strip()[:90], value.strip(), "neutral", "fact")
        out.append(f"[{eid}] {s}")
    return "\n".join(out), items


def _side(cond_bull: bool, cond_bear: bool) -> Stance:
    return "bull" if cond_bull else "bear" if cond_bear else "neutral"


def signals(data: TearSheetData) -> list[Item]:
    from ..quant.valuation import is_financial
    out: list[Item] = []

    def add(label: str, value: str, stance: Stance) -> None:
        out.append(Item(f"S{len(out) + 1}", label, value, stance, "signal"))

    fin, q = data.financials, data.quote
    cur = ccy(q.currency)
    bank = is_financial(data)
    r = sorted(data.ratios, key=lambda x: x.fiscal_year)
    last = r[-1] if r else None

    # growth
    if fin.revenue_cagr is not None and fin.cagr_years:
        add(f"Revenue {fin.cagr_years}Y CAGR", pct(fin.revenue_cagr, 1), _side(fin.revenue_cagr > 0, fin.revenue_cagr < 0))
    if last and last.revenue_growth is not None:
        g = last.revenue_growth
        add(f"Revenue growth FY{last.fiscal_year}", pct(g, 1, signed=True), _side(g > 0, g < 0))
    if last and last.eps_growth is not None:
        g = last.eps_growth
        add(f"EPS growth FY{last.fiscal_year}", pct(g, 1, signed=True), _side(g > 0, g < 0))
    est = (data.consensus.estimates if data.consensus else [])[:1]
    for e in est:
        if e.eps_growth is not None:
            add(f"Consensus EPS growth {e.period} (third party)", pct(e.eps_growth, 1, signed=True),
                _side(e.eps_growth > 0.05, e.eps_growth < 0))

    # latest reported period vs a year earlier (more current than the fiscal-year signals above)
    lt = fin.latest
    if lt is not None:
        if lt.revenue_growth is not None:
            g = lt.revenue_growth
            add(f"Revenue growth {lt.label} vs a year earlier", pct(g, 1, signed=True), _side(g > 0, g < 0))
        if lt.quarter_label and lt.quarter_revenue_growth is not None:
            g = lt.quarter_revenue_growth
            add(f"Revenue growth {lt.quarter_label} vs a year earlier", pct(g, 1, signed=True), _side(g > 0, g < 0))
        if lt.net_income_growth is not None:
            g = lt.net_income_growth
            add(f"Net profit growth {lt.label} vs a year earlier", pct(g, 1, signed=True), _side(g > 0, g < 0))
        if not bank and lt.gross_margin is not None and lt.prior_gross_margin is not None:
            ch = lt.gross_margin - lt.prior_gross_margin
            if abs(ch) >= 0.001:
                add(f"Gross margin {lt.label} vs a year earlier",
                    f"{pct(lt.prior_gross_margin, 1)} to {pct(lt.gross_margin, 1)} ({ch * 100:+.1f}pp)", _side(ch > 0, ch < 0))
        if not bank and lt.free_cash_flow is not None and lt.prior_free_cash_flow is not None and lt.prior_free_cash_flow > 0:
            ch = lt.free_cash_flow / lt.prior_free_cash_flow - 1
            add(f"Free cash flow {lt.label} vs a year earlier", pct(ch, 1, signed=True), _side(ch > 0.05, ch < -0.05))
        if not bank and lt.net_debt is not None:
            add(f"Net {'cash' if lt.net_debt < 0 else 'debt'} at {lt.period_end:%d %b %Y} ({ccy(fin.currency)} mn)",
                num(abs(lt.net_debt) / 1e6, 0), _side(lt.net_debt < 0, False))

    # margins and returns: first vs last year, with the change computed here
    for key, name in [("gross_margin", "Gross margin"), ("operating_margin", "Operating margin"),
                      ("net_margin", "Net margin"), ("roe", "ROE")]:
        if bank and key in ("gross_margin", "operating_margin"):
            continue
        pts = [(x.fiscal_year, getattr(x, key)) for x in r if getattr(x, key) is not None]
        if len(pts) >= 2:
            (y0, a), (y1, b) = pts[0], pts[-1]
            ch = b - a
            if abs(ch) >= 0.001:
                add(f"{name} FY{y0} to FY{y1}", f"{pct(a, 1)} to {pct(b, 1)} ({ch * 100:+.1f}pp)",
                    _side(ch > 0, ch < 0))

    # earnings quality and balance sheet
    if last and last.cash_conversion is not None and not bank:
        c = last.cash_conversion
        add(f"Cash conversion (CFO / net profit) FY{last.fiscal_year}", f"{num(c, 2)}x", _side(c >= 1.0, c < 0.8))
    if last and not bank:
        if last.net_debt_to_ebitda is not None:
            x = last.net_debt_to_ebitda
            add(f"Net debt / EBITDA FY{last.fiscal_year}", f"{num(x, 2)}x", _side(x < 1, x > 3))
        if last.interest_coverage is not None:
            x = last.interest_coverage
            add(f"Interest cover FY{last.fiscal_year}", f"{num(x, 1)}x", _side(x > 8, x < 3))

    # valuation vs peers and history
    c = data.comps
    if c:
        for key, name in [("pe_ttm", "P/E (TTM)"), ("pe_fwd", "P/E (forward)"), ("ev_ebitda", "EV/EBITDA"),
                          ("pb", "P/B")]:
            if bank and key == "ev_ebitda":
                continue
            v, t, m = c.premium_discount.get(key), getattr(c.target, key), getattr(c.median, key)
            if v is not None and t is not None and m is not None:
                add(f"{name} vs peer median", f"{num(t, 1)}x vs {num(m, 1)}x ({pct(v, 1, signed=True)})",
                    _side(v < -0.05, v > 0.05))
        v = c.premium_discount.get("dividend_yield")
        if v is not None and c.target.dividend_yield is not None and c.median.dividend_yield is not None:
            add("Dividend yield vs peer median",
                f"{pct(c.target.dividend_yield, 1)} vs {pct(c.median.dividend_yield, 1)}", _side(v > 0.1, v < -0.1))
    band = data.pe_band
    if band:
        add("P/E vs its own 5-year history",
            f"{num(band.current, 1)}x vs median {num(band.median, 1)}x ({pct(band.percentile, 0)} of history below)",
            _side(band.percentile < 0.3, band.percentile > 0.7))

    # intrinsic value (with the load-bearing assumptions)
    va = data.valuation
    if va:
        w = va.wacc.wacc
        if va.dcf and va.dcf.value_per_share is not None and va.dcf.upside is not None:
            assume = (f"WACC {pct(w, 1)}, " if w else "") + f"terminal growth {pct(va.dcf.terminal_growth, 1)}, " \
                     f"FCF margin {pct(va.dcf.fcf_margin, 1)}"
            add("Model DCF (mechanical: consensus, then fade) vs price", f"{cur} {num(va.dcf.value_per_share, 2)} "
                f"({pct(va.dcf.upside, 1, signed=True)}; {assume})", _side(va.dcf.upside > 0, va.dcf.upside < 0))
        if va.ddm and va.ddm.value_per_share is not None and va.ddm.upside is not None:
            add("DDM vs price", f"{cur} {num(va.ddm.value_per_share, 2)} ({pct(va.ddm.upside, 1, signed=True)}; "
                f"cost of equity {pct(va.wacc.cost_of_equity, 1)}, dividend growth {pct(va.ddm.growth, 1)})",
                _side(va.ddm.upside > 0, va.ddm.upside < 0))
        rv = va.reverse
        if rv and rv.implied_growth is not None and rv.model_growth is not None:
            # round 8: one "base" growth number (our base scenario where there is one, else the model DCF), so the
            # report never shows two different base CAGRs
            from .facts import base_scenario_cagr, reverse_window, reverse_years_text
            got = base_scenario_cagr(data)
            base, what = (got[0], "our base scenario") if got else (rv.model_growth, f"the model {rv.model}")
            gap = rv.implied_growth - base
            # run 2: the reverse DCF holds the consensus years and solves for the later ones; say which years
            hold, _ = reverse_window(rv)
            span = reverse_years_text(rv)
            when = (f" after the {hold} consensus years" + (f" ({span})" if span else "")) if hold else ""
            add(f"Growth the price implies{when} vs {what}",
                f"{pct(rv.implied_growth, 1, signed=True)} a year vs {pct(base, 1, signed=True)} "
                f"({gap * 100:+.1f}pp)" if hold else
                f"{pct(rv.implied_growth, 1, signed=True)} vs {pct(base, 1, signed=True)} "
                f"({gap * 100:+.1f}pp)", _side(gap < -0.03, gap > 0.03))
        mc = va.monte_carlo
        if mc:
            add("Monte Carlo draws above today's price", pct(mc.prob_above_price, 0),
                _side(mc.prob_above_price > 0.6, mc.prob_above_price < 0.4))
    rt = data.rating
    if rt and rt.fair_value is not None and rt.upside is not None:
        add("AI rating (rule-based, set in code)",
            f"{rt.rating}, fair value {ccy(rt.currency)} {num(rt.fair_value, 2)} ({pct(rt.upside, 1, signed=True)})",
            _side(rt.upside > 0, rt.upside < 0))

    # third parties
    ov = data.overall
    if ov:
        add("Overall view (model + recent brokers, computed in code)", f"{ov.rating} ({ov.score:.2f} / 5)",
            _side(ov.score >= 3.5, ov.score <= 2.5))
    st = data.street
    if st and st.target_median is not None and st.target_upside is not None:
        add("Broker median target (third party)", f"{ccy(st.currency)} {num(st.target_median, 2)} "
            f"({pct(st.target_upside, 1, signed=True)})", _side(st.target_upside > 0.05, st.target_upside < -0.05))

    # share price
    b1 = next((p for p in (data.benchmark.periods if data.benchmark else []) if p.period == "1Y"), None)
    if b1 and b1.stock_return is not None and b1.benchmark_return is not None:
        add(f"1Y share price return vs {data.benchmark.name}",
            f"{pct(b1.stock_return, 1, signed=True)} vs {pct(b1.benchmark_return, 1, signed=True)}",
            _side(b1.stock_return > b1.benchmark_return, b1.stock_return < b1.benchmark_return))
    tc = data.technicals
    if tc:
        add("Technical picture (rule-based)", tc.overall, _side(tc.overall == "bullish", tc.overall == "bearish"))
        if tc.max_drawdown_1y is not None:
            add("Max drawdown, 1 year", pct(tc.max_drawdown_1y, 1), _side(False, tc.max_drawdown_1y < -0.3))
    return out


# Fact lines carry guidance for the writer ("Call it ..., never ...", "say plainly ..."). Printed evidence must not:
# the round-4 reviewers quoted these as "internal instructions printed in the note" (9 Nov 2026).
_IMPERATIVE = (r"(?:call|say|do not|don't|never|refer|write|explain|mention|use|name|treat|describe|compare|present|"
               r"avoid|quote|cite|state|give|report|note that|keep|prefer|attribute|check)\b")
# an instruction runs to the next ";", ")" or full stop (a "." inside a number such as 4.64 does not end it)
_INSTR_SENT = re.compile(r"(?:^|(?<=[.;:(]))\s*" + _IMPERATIVE + r"(?:[^.;)]|\.(?=\d))*(?:[.;]|(?=\))|$)", re.I)
_INSTR_TAIL = re.compile(r",?\s*(?:so|and|but)\s+(?:never|do not|don't|always)\b[^.;)]*", re.I)


def reader_text(value: str) -> str:
    """A fact line as a reader sees it: the writer's instructions removed, the facts kept."""
    t = _INSTR_TAIL.sub("", value or "")
    t = _INSTR_SENT.sub(lambda m: "\x00" if m.group(0).strip()[-1:] != ":" else m.group(0), t)
    if "\x00" not in t and t == (value or ""):
        return t
    # the sentence after a removed one starts with a capital (only there: "Inc. for" stays as it is)
    t = re.sub(r"([.!?])\s*\x00\s*([a-z])", lambda m: m.group(1) + " " + m.group(2).upper(), t).replace("\x00", "")
    t = re.sub(r":\s*\)", ")", t)                       # "(press report: attribute it …)" -> "(press report)"
    t = re.sub(r"\(\s*([^()]*?)\s*;\s*\)", r"(\1)", t)   # "(…; )" left by a removed clause
    t = re.sub(r"\s*;\s*(?=[).]|$)", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"[;:,]\s*$", "", t)
    if t and t[-1] not in ".)%":
        t += "."
    return t if len(t) >= 8 else (value or "")


def build(data: TearSheetData, facts: str) -> EvidenceSet:
    numbered, items = number_facts(facts)
    sig = signals(data)
    items.update({s.id: s for s in sig})
    head = ("Signals computed in code (the stance is the side the figure's sign supports, by a fixed rule):\n"
            + "\n".join(s.line() for s in sig)) if sig else ""
    return EvidenceSet(items=items, text=(head + "\n\nFacts (numbered):\n" + numbered).strip())


def cited(text: str) -> list[str]:
    """Evidence ids written inline in a text, e.g. "(E12, S3)"."""
    return list(dict.fromkeys(m.group(0) for m in _ID.finditer(text or "")))
