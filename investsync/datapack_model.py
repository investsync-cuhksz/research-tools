"""The "Model (editable)" sheet of the source data pack: the report's valuation rebuilt with live Excel formulas.

A student changes a yellow input and every other number on the sheet recalculates: the DCF (for banks and insurers,
the dividend discount model), the value per share and upside, a discount rate x growth grid, the bear / base / bull
scenarios and the rating rule. The formulas repeat the report's own method step by step (quant.valuation:
compute_wacc, dcf_ev, stub_cash_share, stakes, compute_ddm; narrative.scenarios.compute; quant.rating), so with the
report's inputs the sheet gives the report's value per share. That is checked here with the report's own functions;
when an older payload cannot be rebuilt exactly, the sheet says so instead of hiding the gap.

Formulas are built only from cell references, numbers and a few fixed words ("n/a", "Buy", ...). Payload text
(sources, notes, scenario drivers, method labels) is always written as text, never as a formula.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .datapack import DOWN, HEAD, HEAD_FILL, MN, MODEL_SHEET, NOTE, NUM4, PCT, PCT2, PS, SPCT, UP, _Sheet, _src
from .quant import valuation as V
from .render.viewmodel import ccy
from .schema import TearSheetData

INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")    # light yellow: change me
INPUT_FONT = Font(color="1F4E9A")
RESULT_FILL = PatternFill("solid", fgColor="DDEBF7")
RESULT_FONT = Font(bold=True)
FIXED_FONT = Font(italic=True, color="5B6475")         # the report's figure, for comparison only
RATE, BETA, YEARS, SHARES = PCT2, "0.00", "0.00", "#,##0.0"
TOLERANCE = 0.005                                       # rebuilt value within 0.5% of the report's
TOO_CLOSE = "Too close: the terminal value explodes (the report would show no value)"
WORDS = ("n/a", "OK", "Buy", "Hold", "Sell", TOO_CLOSE)  # the only text that appears inside formulas


def _show(v: Any, fmt: Optional[str]) -> str:
    if fmt and "%" in fmt:
        return f"{v:.2%}"
    if fmt == MN:
        return f"{v:,.0f}"
    if fmt == NUM4:
        return f"{v:.4f}"
    return f"{v:,.2f}" if fmt in (PS, BETA, YEARS) else f"{v:,.1f}" if fmt == SHARES else f"{v}"


class _Model:
    """Cells by name. Formula templates use {name} for other cells and are filled in once every name is placed,
    so a formula may refer to a cell further down the sheet (the result box at the top does)."""

    def __init__(self, s: _Sheet):
        self.s, self.ws = s, s.ws
        self.ref: dict[str, str] = {}
        self.todo: list[tuple[Any, str]] = []

    def _name(self, name: Optional[str], r: int, c: int) -> None:
        if name:
            assert name not in self.ref, name
            self.ref[name] = f"${get_column_letter(c)}${r}"

    def input(self, r: int, c: int, value: Optional[float], fmt: Optional[str], name: Optional[str] = None):
        cell = self.s.put(r, c, value, fmt, INPUT_FONT, INPUT_FILL)
        was = "a blank (none in the report)" if value is None else _show(value, fmt)
        cell.comment = Comment(f"Change me. The report used {was}.", "InvestSync", height=60, width=240)
        self._name(name, r, c)
        return cell

    def calc(self, r: int, c: int, template: str, fmt: Optional[str] = None, name: Optional[str] = None,
             font: Optional[Font] = None, fill: Optional[PatternFill] = None):
        assert template.startswith("=")
        cell = self.ws.cell(row=r, column=c)
        if fmt:
            cell.number_format = fmt
        if font:
            cell.font = font
        if fill:
            cell.fill = fill
        self.todo.append((cell, template))
        self._name(name, r, c)
        return cell

    def fixed(self, r: int, c: int, value: Any, fmt: Optional[str] = None, name: Optional[str] = None):
        cell = self.s.put(r, c, value, fmt, FIXED_FONT)
        self._name(name, r, c)
        return cell

    def finish(self) -> None:
        for cell, template in self.todo:
            cell.value = template.format(**self.ref)

    # one labelled row: label in A, the cell in B, a plain-English note in C
    def _row(self, label: str, note: str, put) -> None:
        r = self.s.r
        self.s.put(r, 1, label)
        put(r)
        if note:
            self.s.put(r, 3, note, font=NOTE)
        self.s.r += 1

    def row_input(self, label: str, value: Optional[float], fmt: str, name: str, note: str = "") -> None:
        self._row(label, note, lambda r: self.input(r, 2, value, fmt, name))

    def row_calc(self, label: str, template: str, fmt: Optional[str], name: Optional[str] = None, note: str = "",
                 result: bool = False) -> None:
        self._row(label, note, lambda r: self.calc(r, 2, template, fmt, name, RESULT_FONT if result else None,
                                                    RESULT_FILL if result else None))

    def row_fixed(self, label: str, value: Any, fmt: Optional[str], name: Optional[str] = None, note: str = "") -> None:
        self._row(label, note, lambda r: self.fixed(r, 2, value, fmt, name))


def _wrap_header(s: _Sheet) -> None:
    """Let the header row just written wrap onto two lines (long column titles over narrow number columns)."""
    for c in s.ws[s.r - 1]:
        if c.value is not None:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    s.ws.row_dimensions[s.r - 1].height = 30


def _close(a: Optional[float], b: Optional[float], tol: float = 1e-9) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


def _min_gap(data: TearSheetData) -> float:
    cfg = V.load_config(data.profile.ticker)
    return float(cfg["_override"].get("min_spread", cfg.get("min_spread", 0.03)))


# ---------------------------------------------------------------- the report's inputs
@dataclass
class _Dcf:
    """The DCF inputs as the sheet holds them (amounts in millions of the reporting currency)."""
    years: list[int]
    basis: list[str]
    growth: list[float]
    margins: list[float]
    base: float
    g: float
    stub: float
    roll: float
    cs_mode: str                 # interim: (forecast - reported) / forecast, bounded; time: = stub; fixed: as reported
    cs: float
    reported: Optional[float]    # revenue already reported in the first forecast year
    net_debt: float
    minorities: float
    stake_book: Optional[float]
    haircut: Optional[float]
    stakes: float
    shares: float
    fx: float
    bs_date: Any


def _dcf_inputs(data: TearSheetData) -> _Dcf:
    v = data.valuation
    d, b = v.dcf, v.dcf.bridge
    fys = data.financials.years
    fy = fys[-1] if fys else None
    f0 = d.forecast[0]
    base = fy.revenue if fy and fy.revenue and fy.fiscal_year + 1 == f0.fiscal_year else f0.revenue / (1 + f0.growth)
    stub, roll = d.stub_years or 1.0, b.roll_forward_years or 0.0
    lt = data.financials.latest
    rev1 = base * (1 + f0.growth)
    want = d.stub_cash_share if d.stub_cash_share is not None else stub
    interim = bool(stub < 1.0 and lt and fy and lt.revenue and lt.period_end > fy.period_end)
    if interim and _close(V.stub_cash_share(data, rev1, stub), want):
        mode = "interim"
    elif _close(want, stub):
        mode = "time"
    else:
        mode = "fixed"
    src = lt if (lt is not None and fy and lt.net_debt is not None and lt.period_end > fy.period_end) else fy
    book = getattr(src, "equity_investments", None)
    after = b.investments or 0.0
    split = bool(after and book and _close(book * (1 - V.STAKE_HAIRCUT), after))
    return _Dcf(
        years=[x.fiscal_year for x in d.forecast], basis=[x.basis for x in d.forecast],
        growth=[x.growth for x in d.forecast],
        margins=list(d.margin_path) if d.margin_path and len(d.margin_path) == len(d.forecast)
        else [d.fcf_margin] * len(d.forecast),
        base=base / 1e6, g=d.terminal_growth, stub=stub, roll=roll, cs_mode=mode, cs=want,
        reported=lt.revenue / 1e6 if mode == "interim" else None, net_debt=b.net_debt / 1e6,
        minorities=(b.minority_interest or 0.0) / 1e6, stake_book=book / 1e6 if split else None,
        haircut=V.STAKE_HAIRCUT if split else None, stakes=after / 1e6, shares=b.shares / 1e6,
        fx=b.fx_to_reporting or 1.0, bs_date=b.balance_sheet_date or (fy.period_end if fy else None))


def _wacc_built(w) -> float:
    ke = w.risk_free + (w.beta if w.beta is not None else 1.0) * w.equity_risk_premium
    return (1 - w.debt_weight) * ke + w.debt_weight * (w.pre_tax_cost_of_debt or 0.0) * (1 - w.tax_rate)


def _cash_share(x: _Dcf, rev1: float) -> float:
    """The sheet's rule for the share of the first year's cash flow still to come (valuation.stub_cash_share)."""
    if x.cs_mode == "fixed":
        return x.cs
    if x.cs_mode == "time" or x.stub >= 1.0 or rev1 <= x.reported:
        return x.stub
    return min(max((rev1 - x.reported) / rev1, 0.5 * x.stub), min(1.0, 1.5 * x.stub))


def _value(x: _Dcf, wacc: float, growth: list[float], margins: list[float]) -> float:
    """Value per share for the sheet's inputs, with the report's own DCF function."""
    revs, r = [], x.base
    for gr in growth:
        r *= 1 + gr
        revs.append(r)
    ev, _, _ = V.dcf_ev(revs, margins, wacc, x.g, x.stub, x.roll, _cash_share(x, revs[0]))
    return (ev - x.net_debt - x.minorities + x.stakes) / x.fx / x.shares


def _scenario_paths(x: _Dcf, sn) -> tuple[list[float], list[float]]:
    """narrative.scenarios.compute: three years of the scenario's growth, then the growth above terminal growth
    halves each year; the FCF margin moves in equal steps from the model's first-year margin to the scenario's by
    year three, then holds."""
    n = len(x.growth)
    growth, prev = list(sn.revenue_growth[:3]), sn.revenue_growth[2]
    while len(growth) < n:
        prev = V.fade_step(prev, x.g)
        growth.append(prev)
    m0 = x.margins[0]
    return growth[:n], [m0 + (sn.fcf_margin - m0) * min(t, 3) / 3 for t in range(1, n + 1)]


def _scenarios_live(x: _Dcf, sc, wacc: float) -> bool:
    if len(x.growth) < 3 or any(len(sn.revenue_growth) != 3 for sn in sc.scenarios):
        return False
    return all(abs(_value(x, wacc, *_scenario_paths(x, sn)) / sn.value_per_share - 1) <= TOLERANCE
               for sn in sc.scenarios if sn.value_per_share)


# ---------------------------------------------------------------- blocks
def _summary(m: _Model, data: TearSheetData, model: str, report_value: float, ok_note: str, scen: bool,
             rated: bool) -> None:
    s, q, rt = m.s, data.quote, data.rating
    cur = ccy(q.currency)
    s.section("Result (recalculates as soon as you change a yellow cell below)")
    m.row_calc(f"Value per share, your {model} ({cur})", "={vps}", PS, note="Your model's value of one share.",
               result=True)
    m.row_calc(f"Share price used ({cur})", "={price}", PS,
               note=f"Price on {q.as_of.isoformat()} (an input further down).")
    m.row_calc("Upside (+) / downside (-) vs the share price", "={upside}", SPCT, note="Value per share / price - 1.",
               result=True)
    m.row_fixed(f"The report's {model} value per share ({cur})", report_value, PS, "report_vps",
                "Fixed: what the report shows.")
    m.row_calc("Your value vs the report's", "={vps}/{report_vps}-1", SPCT, note=ok_note)
    if scen:
        m.row_calc(f"Probability-weighted scenario value ({cur})", "={sc_wv}", PS,
                   note="Bear, base and bull at your probabilities (Scenarios, below).")
    if rated:
        r = s.r
        s.put(r, 1, f"Fair value ({cur}) and rating by the report's rule, with your inputs")
        m.calc(r, 2, "={rt_fv}", PS, font=RESULT_FONT, fill=RESULT_FILL)
        m.calc(r, 3, "={rt_live}", font=RESULT_FONT)
        s.put(r, 4, f"The report: {rt.rating}, fair value {ccy(rt.currency)} {rt.fair_value:,.2f}.", font=NOTE)
        s.r += 1
    s.r += 1
    s.ws.freeze_panes = f"A{s.r}"   # the result stays in view while you scroll to the inputs


def _discount(m: _Model, w, full: bool) -> None:
    """WACC build-up (compute_wacc), or the cost of equity alone for banks and insurers."""
    s = m.s
    s.section("Discount rate: " + ("WACC, the return all the company's investors need" if full else
                                   "cost of equity, the return shareholders need"))
    s.header(["Input or step", "Value", "What it means"])
    m.row_input("Risk-free rate", w.risk_free, RATE, "rf",
                f"What a (nearly) riskless government bond pays: {w.risk_free_source}.")
    m.row_input("Beta", w.beta if w.beta is not None else 1.0, BETA, "beta",
                "How much the share swings with the market: 1 = in line, above 1 = more. "
                + (f"Measured: {w.beta_method}." if w.beta is not None else "None measured; the report assumed 1."))
    m.row_input("Equity risk premium", w.equity_risk_premium, RATE, "erp",
                f"The extra return investors want for owning shares instead of government bonds ({w.erp_source}).")
    m.row_calc("= Cost of equity", "={rf}+{beta}*{erp}", RATE, "ke",
               "Risk-free rate + beta x equity risk premium (the CAPM).", result=not full)
    if not full:
        return
    m.row_input("Pre-tax cost of debt", w.pre_tax_cost_of_debt, RATE, "kd",
                "Interest paid on borrowings (interest expense / average debt)."
                + (" Blank: no borrowings." if w.pre_tax_cost_of_debt is None else ""))
    m.row_input("Tax rate", w.tax_rate, RATE, "tax", "Interest is tax-deductible, so debt costs less after tax.")
    m.row_calc("= After-tax cost of debt", "={kd}*(1-{tax})", RATE, "kd_at", "Pre-tax cost of debt x (1 - tax rate).")
    m.row_input("Debt weight", w.debt_weight, PCT2, "wd",
                "Share of the funding that comes from debt: debt / (market value of the shares + debt).")
    m.row_calc("= Equity weight", "=1-{wd}", PCT2, "we", "The rest of the funding comes from shareholders.")
    m.row_calc("= WACC", "={we}*{ke}+{wd}*{kd_at}", RATE, "wacc",
               "Weighted average cost of capital: future cash is discounted at this rate, so a higher WACC means a "
               "lower value. You may also type a WACC over this formula.", result=True)


def _gap_check(m: _Model, data: TearSheetData, rate: str, growth: str) -> None:
    m.row_calc(f"= {rate} minus {growth}", "={%s}-{g}" % ("wacc" if rate == "WACC" else "ke"), RATE, "gap",
               "The value divides by this gap: the smaller it is, the bigger (and shakier) the value.")
    m.row_fixed("Smallest gap the report accepts", _min_gap(data), RATE, "min_gap",
                "House rule (config/valuation.json).")
    m.row_calc("= Check", '=IF({gap}<{min_gap},"%s","OK")' % TOO_CLOSE, None)


def _cs_template(rev: str) -> str:
    """valuation.stub_cash_share as a formula: (forecast revenue - revenue already reported) / forecast revenue,
    kept between half and one and a half times the time share."""
    return ("=IF({stub}>=1,{stub},IF({REV}<={rep},{stub},MIN(MAX(({REV}-{rep})/{REV},0.5*{stub}),MIN(1,1.5*{stub}))))"
            .replace("REV", rev))


def _dcf_model(m: _Model, data: TearSheetData) -> None:
    s, v, q = m.s, data.valuation, data.quote
    d = v.dcf
    x = _dcf_inputs(data)
    n, cur, rc = len(x.years), ccy(q.currency), ccy(data.financials.currency)
    wacc = _wacc_built(v.wacc)
    mine = _value(x, wacc, x.growth, x.margins) if wacc > x.g else None
    ok = bool(mine and d.value_per_share) and abs(mine / d.value_per_share - 1) <= TOLERANCE
    sc = v.scenarios if v.scenarios and v.scenarios.scenarios else None
    live = bool(sc and ok and _scenarios_live(x, sc, wacc))
    rated = bool(data.rating and data.rating.fair_value)
    gap_note = (f"With the report's inputs this model gives {cur} {mine or 0:,.2f}, not the report's "
                f"{d.value_per_share:,.2f}: "
                "this payload was made with an earlier version of the method. The model still shows how the value "
                "moves with each input." if not ok else "0.0% until you change an input.")
    _summary(m, data, "DCF", d.value_per_share, gap_note, bool(sc), rated)
    _discount(m, v.wacc, full=True)

    y1, last = x.years[0], x.years[-1]
    bs = x.bs_date.isoformat() if x.bs_date else "the latest balance sheet"
    s.section("Growth after the forecast, and timing")
    s.header(["Input or step", "Value", "What it means"])
    m.row_input("Terminal growth (per year, forever)", x.g, RATE, "g",
                "Growth of free cash flow after the last forecast year, forever. Keep it near long-run inflation "
                "plus real growth (2-3%); it can never be above WACC.")
    _gap_check(m, data, "WACC", "terminal growth")
    m.row_input(f"Part of FY{y1} still to come (years)", x.stub, YEARS, "stub",
                f"From the balance-sheet date ({bs}) to the end of FY{y1}: 0.5 = half a year; 1 = a full year.")
    if x.cs_mode == "interim":
        lt = data.financials.latest
        m.row_input(f"Revenue already reported in FY{y1} ({lt.label}, {rc} mn)", x.reported, MN, "rep",
                    "Earned before the balance-sheet date, so its cash is already in the net cash below.")
        m.row_calc(f"= Share of FY{y1}'s cash flow still to come", _cs_template("rev_0"), PCT, "cs",
                   "(FY revenue forecast - revenue already reported) / FY revenue forecast, kept between 0.5x and "
                   "1.5x the time left. Type a number over it to override.")
    elif x.cs_mode == "time":
        m.row_calc(f"= Share of FY{y1}'s cash flow still to come", "={stub}", PCT, "cs",
                   "The time left in the year (no interim revenue to go on).")
    else:
        m.row_input(f"Share of FY{y1}'s cash flow still to come", x.cs, PCT, "cs", "As the report used it.")
    m.row_input("Years from the balance-sheet date to the price date", x.roll, YEARS, "roll",
                "The value is carried forward at WACC over this time; 0 = valued at the last fiscal year end.")

    s.section(f"Forecast ({rc} millions)")
    m.row_input(f"Revenue in FY{y1 - 1}, the last reported year ({rc} mn)", x.base, MN, "base",
                "Reported (Income statement sheet); the forecast grows from here.")
    s.header([f"{rc} mn"] + [f"FY{y}E" for y in x.years] + ["What it means"])
    note_col = n + 2
    rows = [
        ("Revenue growth", lambda r, i: m.input(r, 2 + i, x.growth[i], SPCT, f"gr_{i}"),
         "Growth on the year before. Change any year."),
        ("  How the report set it", lambda r, i: s.put(r, 2 + i, x.basis[i], font=NOTE),
         "consensus = the analysts' average forecast; fade = steps down towards terminal growth."),
        ("Revenue", lambda r, i: m.calc(r, 2 + i, "={base}*(1+{gr_0})" if i == 0 else
                                        "={rev_%d}*(1+{gr_%d})" % (i - 1, i), MN, f"rev_{i}"),
         "Last year's revenue x (1 + growth)."),
        ("FCF margin", lambda r, i: m.input(r, 2 + i, x.margins[i], PCT, f"m_{i}"),
         "Free cash flow (operating cash flow - capex) per 100 of revenue. " + (d.margin_basis or "")),
        ("Free cash flow", lambda r, i: m.calc(r, 2 + i, "={rev_%d}*{m_%d}" % (i, i), MN, f"fcf_{i}"),
         "Revenue x FCF margin: the cash left after running and investing in the business."),
        ("Cash flow counted", lambda r, i: m.calc(r, 2 + i, "={fcf_0}*{cs}" if i == 0 else "={fcf_%d}" % i, MN,
                                                  f"cash_{i}"),
         f"FY{y1}: only the share still to come (above); later years in full."),
        ("Years from the balance-sheet date", lambda r, i: m.calc(r, 2 + i, "={stub}" if i == 0 else
                                                                 "={t_%d}+1" % (i - 1), YEARS, f"t_{i}"),
         "When the cash arrives (counted at each year end)."),
        ("Discount factor", lambda r, i: m.calc(r, 2 + i, "=1/(1+{wacc})^{t_%d}" % i, NUM4, f"df_{i}"),
         "What 1 received then is worth at the balance-sheet date: 1 / (1 + WACC)^years. Later = worth less."),
        ("Present value", lambda r, i: m.calc(r, 2 + i, "={cash_%d}*{df_%d}" % (i, i), MN, f"pv_{i}",
                                              font=RESULT_FONT),
         "Cash flow counted x discount factor."),
    ]
    for label, write, note in rows:
        s.put(s.r, 1, label)
        for i in range(n):
            write(s.r, i)
        s.put(s.r, note_col, note, font=NOTE)
        s.r += 1

    s.section(f"Terminal value: all the years after FY{last}")
    s.header(["Step", "Value", "What it means"])
    m.row_calc(f"Free cash flow in FY{last} ({rc} mn)", "={fcf_%d}" % (n - 1), MN, "fcf_last",
               "The last forecast year, in full.")
    m.row_calc(f"Terminal value at the end of FY{last} ({rc} mn)", "={fcf_last}*(1+{g})/({wacc}-{g})", MN, "tv",
               "Next year's cash flow / (WACC - terminal growth): the value of a cash flow that grows forever.")
    m.row_calc(f"Present value of the terminal value ({rc} mn)", "={tv}*{df_%d}" % (n - 1), MN, "pv_tv",
               f"Discounted with FY{last}'s factor. Usually most of the value, which is why WACC and terminal "
               "growth matter so much.")

    s.section(f"From enterprise value to value per share")
    s.header(["Step", "Value", "What it means"])
    m.row_calc(f"Present value of the {n} forecast years ({rc} mn)", "=SUM({pv_0}:{pv_%d})" % (n - 1), MN, "sum_pv")
    m.row_calc(f"+ Present value of the terminal value ({rc} mn)", "={pv_tv}", MN)
    m.row_calc(f"= Value at the balance-sheet date, {bs} ({rc} mn)", "={sum_pv}+{pv_tv}", MN, "v_bs")
    m.row_calc("x Carried forward to the price date: (1 + WACC)^years", "=(1+{wacc})^{roll}", NUM4, "roll_f",
               "Time has passed since the balance sheet; the value grows at WACC meanwhile.")
    m.row_calc(f"= Enterprise value ({rc} mn)", "={v_bs}*{roll_f}", MN, "ev",
               "The whole business, for lenders and shareholders together.", result=True)
    m.row_calc("  Terminal value share of the enterprise value", "={pv_tv}*{roll_f}/{ev}", PCT,
               note="How much of the value comes from after the forecast years.")
    m.row_input(f"- Net debt ({rc} mn; negative = net cash)", x.net_debt, MN, "nd",
                f"Debt minus cash at {bs}. Net cash (a negative number) adds to what shareholders own.")
    m.row_input(f"- Minority interests ({rc} mn)", x.minorities, MN, "mi",
                "Parts of subsidiaries owned by other shareholders (book value)."
                + ("" if x.minorities else " The report deducted none."))
    if x.stake_book is not None:
        m.row_input(f"Stakes in other companies, book value ({rc} mn)", x.stake_book, MN, "stake_book",
                    "Associates, joint ventures and other equity investments, as reported.")
        m.row_input("Haircut on those stakes", x.haircut, PCT, "haircut",
                    "Cut for illiquidity, tax and changing market prices.")
        m.row_calc(f"+ Stakes after the haircut ({rc} mn)", "={stake_book}*(1-{haircut})", MN, "stakes")
    else:
        m.row_input(f"+ Stakes in other companies, after a haircut ({rc} mn)", x.stakes, MN, "stakes",
                    "Equity investments outside cash." + ("" if x.stakes else " The report added none."))
    m.row_calc(f"= Equity value ({rc} mn)", "={ev}-{nd}-{mi}+{stakes}", MN, "equity",
               "What belongs to the company's shareholders.", result=True)
    m.row_input("/ Shares (millions)", x.shares, SHARES, "shares", "The report's share count: market cap / price.")
    if data.financials.currency != q.currency:
        m.row_input(f"/ FX: {rc} per 1 {cur}", x.fx, NUM4, "fx", f"Turns {rc} into {cur}, the currency the shares "
                                                                 "trade in.")
    else:
        m.row_fixed("/ FX", x.fx, NUM4, "fx", f"Accounts and share price are both in {cur}, so 1.")
    m.row_calc(f"= Value per share ({cur})", "={equity}/{fx}/{shares}", PS, "vps", "Equity value per share.",
               result=True)
    m.row_input(f"Share price ({cur})", q.price, PS, "price",
                f"Price on {q.as_of.isoformat()}. Try another price to see the upside change.")
    m.row_calc("= Upside (+) / downside (-)", "={vps}/{price}-1", SPCT, "upside", "Value per share / price - 1.",
               result=True)

    terms = "+".join("{cash_%d}/(1+{RW})^{t_%d}" % (i, i) for i in range(n))
    tv = "{fcf_last}*(1+{CG})/({RW}-{CG})/(1+{RW})^{t_%d}" % (n - 1)
    _grid(m, data, "WACC", "terminal growth", "wacc",
          '=IF({RW}-{CG}<{min_gap},"n/a",((' + terms + "+" + tv
          + ")*(1+{RW})^{roll}-{nd}-{mi}+{stakes})/{fx}/{shares})")
    if sc:
        _scenarios(m, data, x, live)
    if rated:
        _rating(m, data, {**({"dcf": "vps"} if ok else {}), **({"dcf_scenarios": "sc_wv"} if sc else {})})
    if live:
        _scenario_workings(m, data, x)
    _notes(m, data, [
        f"Method, as in the report: {d.method}. Cash flows are counted at each year end; the first forecast year "
        "counts only the part still to come; the terminal value grows the last year's free cash flow at terminal "
        "growth forever; net debt, minority interests and stakes are taken at the balance-sheet date."],
        ok, gap_note)


def _grid(m: _Model, data: TearSheetData, rate: str, growth: str, centre: str, template: str) -> None:
    """Value per share over rate x growth, each cell a plain formula (no Excel data table, no macro)."""
    s, cur, steps = m.s, ccy(data.quote.currency), (-2, -1, 0, 1, 2)
    s.section(f"Sensitivity: value per share ({cur}) for other {rate} and {growth} rates")
    m.row_input(f"Step between {rate} rows", 0.005, RATE, "w_step", "Change the steps to widen or narrow the grid.")
    m.row_input(f"Step between {growth} columns", 0.005, RATE, "g_step")

    def shift(name: str, step: str, k: int) -> str:
        return "={%s}" % name + ("" if k == 0 else "%s%s{%s}" % ("+" if k > 0 else "-",
                                                                 "" if abs(k) == 1 else f"{abs(k)}*", step))
    top = s.r
    s.put(top, 1, f"{rate[0].upper() + rate[1:]} (down) / {growth} (across)", font=HEAD, fill=HEAD_FILL)
    for j, k in enumerate(steps):
        m.calc(top, 2 + j, shift("g", "g_step", k), RATE, f"gg_{j}", font=HEAD, fill=HEAD_FILL)
    for i, k in enumerate(steps):
        r = top + 1 + i
        m.calc(r, 1, shift(centre, "w_step", k), RATE, f"gw_{i}", font=RESULT_FONT)
        for j in range(len(steps)):
            m.calc(r, 2 + j, template.replace("{RW}", "{gw_%d}" % i).replace("{CG}", "{gg_%d}" % j), PS,
                   font=RESULT_FONT if (i, j) == (2, 2) else None)
    first, end = f"B{top + 1}", f"{get_column_letter(1 + len(steps))}{top + len(steps)}"
    price = m.ref["price"]
    s.ws.conditional_formatting.add(f"{first}:{end}", FormulaRule(
        formula=[f"AND(ISNUMBER({first}),{first}>={price})"], fill=UP))
    s.ws.conditional_formatting.add(f"{first}:{end}", FormulaRule(
        formula=[f"AND(ISNUMBER({first}),{first}<{price})"], fill=DOWN))
    s.r = top + len(steps) + 1
    s.note(f"Each cell reruns the whole model at that {rate} and {growth}; the centre is your model above. Green = "
           f"at or above the share price; n/a = {rate} less than the smallest accepted gap above {growth} (the "
           f"report shows no value there).")


def _scenarios(m: _Model, data: TearSheetData, x: Optional[_Dcf], live: bool) -> None:
    s, sc, rt = m.s, data.valuation.scenarios, data.rating
    cur = ccy(data.quote.currency)
    k = min(3, min(len(sn.revenue_growth) for sn in sc.scenarios))
    y0 = x.years[0] if x else data.financials.years[-1].fiscal_year + 1
    s.section("Scenarios: bear, base and bull")
    if sc.note:
        s.note(sc.note)
    s.note("Change the probabilities (they need not add up to 100%: the weighted value divides by their total). "
           + ("Each scenario's value is a live DCF with your WACC, terminal growth, timing, net cash and share count "
              "(workings at the bottom); you can change its growth and margin too." if live else
              "The scenario values are the report's (fixed): this payload's scenario method cannot be rebuilt "
              "exactly here."))
    s.header(["Scenario", "Probability"] + [f"Growth FY{y0 + i}E" for i in range(k)]
             + [f"FCF margin by FY{y0 + k - 1}E", f"Value per share ({cur})", "Upside", "What has to happen (the "
                                                                                     "report's words)"])
    _wrap_header(s)
    n = len(sc.scenarios)
    for j, sn in enumerate(sc.scenarios):
        r = s.r
        s.put(r, 1, sn.name.title())
        m.input(r, 2, sn.probability, PCT, f"p_{j}")
        put = m.input if live else m.fixed
        for i in range(k):
            put(r, 3 + i, sn.revenue_growth[i], SPCT, f"s{j}_g{i}")
        put(r, 3 + k, sn.fcf_margin, PCT, f"s{j}_m")
        if live:
            m.calc(r, 4 + k, "={s%d_vps}" % j, PS, f"s{j}_v", font=RESULT_FONT)
        else:
            m.fixed(r, 4 + k, sn.value_per_share, PS, f"s{j}_v")
        m.calc(r, 5 + k, "={s%d_v}/{price}-1" % j, SPCT)
        if sn.drivers:
            s.put(r, 6 + k, sn.drivers, font=NOTE)
        s.r += 1
    probs, vals = "{p_0}:{p_%d}" % (n - 1), "{s0_v}:{s%d_v}" % (n - 1)
    m.row_calc("= Probabilities add up to", "=SUM(%s)" % probs, PCT)
    m.row_calc(f"= Probability-weighted value ({cur})", "=SUMPRODUCT(%s,%s)/SUM(%s)" % (probs, vals, probs), PS,
               "sc_wv", "Each scenario's value x its probability, added up.", result=True)
    m.row_calc("= Upside vs the share price", "={sc_wv}/{price}-1", SPCT)
    basis = ("these scenarios" if rt.basis == "scenarios" else "a blend of methods") if rt and rt.fair_value else ""
    m.row_fixed(f"The AI rating's fair value, as in the report ({cur})",
                rt.fair_value if rt and rt.fair_value else sc.weighted_value, PS, None,
                "Fixed, for comparison." + (f" The report's rating rests on {basis}." if basis else ""))


def _scenario_workings(m: _Model, data: TearSheetData, x: _Dcf) -> None:
    s, sc = m.s, data.valuation.scenarios
    n, cur, rc = len(x.years), ccy(data.quote.currency), ccy(data.financials.currency)
    s.section(f"Scenario workings ({rc} millions): each scenario's DCF")
    s.note("Uses your WACC, terminal growth, timing, net cash, stakes, shares and FX from the model above. Years 1-3 "
           "take the scenario's growth; after that the growth above terminal growth halves each year. The FCF "
           "margin moves in equal steps from your first-year margin to the scenario's margin by year 3, then holds.")
    s.header([""] + [f"FY{y}E" for y in x.years])
    cs = {"interim": None, "time": "={stub}", "fixed": "={cs}"}[x.cs_mode]
    for j, sn in enumerate(sc.scenarios):
        name = sn.name.title()
        p = f"s{j}_"
        rows = [
            (f"{name}: revenue growth", lambda i: "={%sg%d}" % (p, i) if i < 3 else
             "={g}+({%sgr_%d}-{g})*0.5" % (p, i - 1), SPCT, "gr"),
            ("  Revenue", lambda i: "={base}*(1+{%sgr_0})" % p if i == 0 else
             "={%srev_%d}*(1+{%sgr_%d})" % (p, i - 1, p, i), MN, "rev"),
            ("  FCF margin", lambda i: "={m_0}+({%sm}-{m_0})*%d/3" % (p, i + 1) if i < 2 else "={%sm}" % p, PCT, "mg"),
            ("  Cash flow counted", lambda i: "={%srev_0}*{%smg_0}*{%scs}" % (p, p, p) if i == 0 else
             "={%srev_%d}*{%smg_%d}" % (p, i, p, i), MN, "cash"),
            ("  Present value", lambda i: "={%scash_%d}*{df_%d}" % (p, i, i), MN, "pv"),
        ]
        for label, tmpl, fmt, key in rows:
            s.put(s.r, 1, label, font=RESULT_FONT if key == "gr" else None)
            for i in range(n):
                m.calc(s.r, 2 + i, tmpl(i), fmt, f"{p}{key}_{i}")
            s.r += 1
        m.row_calc(f"  Share of FY{x.years[0]}'s cash flow still to come", cs or _cs_template(f"{p}rev_0"), PCT,
                   f"{p}cs")
        m.row_calc(f"  Present value of the terminal value", "={%srev_%d}*{%smg_%d}*(1+{g})/({wacc}-{g})*{df_%d}"
                   % (p, n - 1, p, n - 1, n - 1), MN, f"{p}pvtv")
        m.row_calc(f"  {name} value per share ({cur})", "=((SUM({%spv_0}:{%spv_%d})+{%spvtv})*{roll_f}-{nd}-{mi}"
                   "+{stakes})/{fx}/{shares}" % (p, p, n - 1, p), PS, f"{p}vps", result=True)
        s.r += 1


def _rating(m: _Model, data: TearSheetData, links: dict[str, str]) -> None:
    """quant.rating: fair value = weighted average of the included methods; Buy / Hold / Sell from its upside."""
    from .quant.rating import LABELS
    s, rt = m.s, data.rating
    cur = ccy(rt.currency)
    s.section("The AI rating: fair value and the Buy / Hold / Sell rule")
    s.note(f"The rule: Buy if the fair value is at least {rt.buy_threshold:.0%} above the share price, Sell if it is "
           f"{-rt.sell_threshold:.0%} or more below, otherwise Hold. The fair value is the weighted average of the "
           f"methods below: change a weight, or set it to 0 to leave a method out.")
    s.header(["Method", f"Value per share ({cur})", "Weight", "The report's note"])
    _wrap_header(s)
    n = len(rt.methods)
    for i, meth in enumerate(rt.methods):
        r = s.r
        s.put(r, 1, meth.label)
        key = "dcf_scenarios" if meth.key == "dcf" and meth.label == LABELS["dcf_scenarios"] else meth.key
        if key in links:
            m.calc(r, 2, "={%s}" % links[key], PS, f"rm_{i}")
        else:
            m.fixed(r, 2, meth.value, PS, f"rm_{i}")
        m.input(r, 3, meth.weight if meth.included else 0.0, PCT, f"rw_{i}")
        if meth.note:
            s.put(r, 4, meth.note, font=NOTE)
        s.r += 1
    vals, wts = "{rm_0}:{rm_%d}" % (n - 1), "{rw_0}:{rw_%d}" % (n - 1)
    m.row_calc(f"= Fair value with your inputs ({cur})", "=SUMPRODUCT(%s,%s)/SUM(%s)" % (vals, wts, wts), PS,
               "rt_fv", "Each method's value x its weight, divided by the total weight.", result=True)
    m.row_fixed(f"The report's fair value ({cur})", rt.fair_value, PS, None, "Fixed, for comparison.")
    m.row_calc("= Upside vs the share price", "={rt_fv}/{price}-1", SPCT, "rt_up")
    m.row_fixed("Buy at or above this upside", rt.buy_threshold, SPCT, "buy", "House rule (config/rating.json).")
    m.row_fixed("Sell at or below this upside", rt.sell_threshold, SPCT, "sell")
    m.row_calc("= Rating by the rule, with your inputs", '=IF({rt_up}>={buy},"Buy",IF({rt_up}<={sell},"Sell","Hold"))',
               None, "rt_live", result=True)
    m.row_fixed("The report's rating", rt.rating, None, None,
                f"Confidence: {rt.confidence}." if rt.confidence else "")
    s.note("Not repeated here: the report leaves out a method far from the median of the methods (outlier rule) and "
           "needs a minimum number of methods for a blended rating.")


def _notes(m: _Model, data: TearSheetData, method: list[str], ok: bool, gap_note: str) -> None:
    s = m.s
    s.section("Notes")
    for t in method:
        s.note(t)
    if not ok:
        s.note(gap_note)
    s.note("Yellow = an input (its comment shows the report's figure); white = a formula; grey italics = the "
           "report's figure, fixed, for comparison. Formulas only: no macros, no data tables.")
    for t in (data.valuation.notes if data.valuation else []):
        s.note(f"From the report: {t}")


def _ddm_model(m: _Model, data: TearSheetData) -> None:
    s, v, q = m.s, data.valuation, data.quote
    dd, w = v.ddm, v.wacc
    cur = ccy(q.currency)
    ke = w.risk_free + (w.beta if w.beta is not None else 1.0) * w.equity_risk_premium
    mine = dd.dividend_per_share * (1 + dd.growth) / (ke - dd.growth) if ke > dd.growth else None
    ok = bool(mine and dd.value_per_share) and abs(mine / dd.value_per_share - 1) <= TOLERANCE
    rated = bool(data.rating and data.rating.fair_value)
    gap_note = ("0.0% until you change an input." if ok else
                f"With the report's inputs this model gives {cur} {mine or 0:,.2f}, not the report's "
                f"{dd.value_per_share or 0:,.2f}: this payload was made with an earlier version of the method.")
    _summary(m, data, "dividend discount model", dd.value_per_share, gap_note, False, rated)
    _discount(m, w, full=False)
    s.section("Dividend discount model (Gordon growth)")
    s.header(["Input or step", "Value", "What it means"])
    m.row_input(f"Dividend per share, last 12 months ({cur})", dd.dividend_per_share, PS, "dps",
                "Dividends paid per share over the past year (dividend yield x share price).")
    m.row_input("Dividend growth per year, forever", dd.growth, RATE, "g",
                "Keep it near long-run inflation plus real growth (2-3%); it can never be above the cost of equity.")
    _gap_check(m, data, "Cost of equity", "dividend growth")
    m.row_calc(f"= Next year's dividend ({cur})", "={dps}*(1+{g})", PS, "d1", "This year's dividend x (1 + growth).")
    m.row_calc(f"= Value per share ({cur})", "={d1}/{gap}", PS, "vps",
               "Next year's dividend / (cost of equity - growth): what all future dividends are worth today.",
               result=True)
    m.row_input(f"Share price ({cur})", q.price, PS, "price", f"Price on {q.as_of.isoformat()}.")
    m.row_calc("= Upside (+) / downside (-)", "={vps}/{price}-1", SPCT, "upside", "Value per share / price - 1.",
               result=True)
    _grid(m, data, "cost of equity", "dividend growth", "ke",
          '=IF({RW}-{CG}<{min_gap},"n/a",{dps}*(1+{CG})/({RW}-{CG}))')
    if rated:
        _rating(m, data, {"ddm": "vps"} if ok else {})
    _notes(m, data, [
        f"Method, as in the report: {dd.method}. Banks and insurers are valued on the dividends shareholders receive: "
        "their borrowing is raw material for lending, not funding, so free cash flow and WACC do not describe their "
        "value."], ok, gap_note)


def _no_model(m: _Model, data: TearSheetData, financial: bool) -> None:
    s, v = m.s, data.valuation
    if not v:
        s.note("No DCF / DDM valuation in this payload, so there is no model to rebuild here.")
        return
    s.note(f"The report shows no {'dividend discount model' if financial else 'DCF'} for this company, so there is "
           "no value per share to rebuild. The discount rate below is still live.")
    _discount(m, v.wacc, full=not financial and v.wacc.wacc is not None)
    _notes(m, data, [], True, "")


def model_sheet(wb: Workbook, data: TearSheetData) -> None:
    """The "Model (editable)" sheet."""
    v, q = data.valuation, data.quote
    rc, cur = ccy(data.financials.currency), ccy(q.currency)
    s = _Sheet(wb, MODEL_SHEET, f"Editable valuation model: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("statements", "market", "prices", "fx", "rates", "consensus", "assumptions"),
                    "Inputs are the report's own (data.json); the formulas repeat the report's method step by step."),
               "Yellow cells are inputs: change one and every other number recalculates (Excel formulas, no macros). "
               "Each yellow cell's comment gives the report's figure, to change it back. "
               f"Amounts in {rc} millions; per-share values in {cur}. If the numbers show as 0, click Enable Editing.")
    m = _Model(s)
    financial = V.is_financial(data)
    dcf_ok = bool(v and v.dcf and v.dcf.forecast and v.dcf.bridge and v.dcf.value_per_share and v.wacc.wacc)
    ddm_ok = bool(v and v.ddm and v.ddm.value_per_share)
    if ddm_ok and (financial or not dcf_ok):
        _ddm_model(m, data)
    elif dcf_ok:
        _dcf_model(m, data)
    else:
        _no_model(m, data, financial)
    m.finish()
    labels = [len(str(c.value)) for c in s.ws["A"][4:] if c.value is not None and (c.row, 1) not in s.spill
              and not str(c.value).startswith("=")]
    s.ws.column_dimensions["A"].width = min(max(labels, default=40) + 2, 72)
    for c in range(2, 10):
        s.ws.column_dimensions[get_column_letter(c)].width = 15
