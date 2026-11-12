"""Source data pack: the numbers behind a report, for readers who want to dig further.

``build_datapack(data)`` returns a ZIP with
  <TICKER>_data.xlsx   statements, ratios, valuation workings, peers, prices, broker views, sources
  sources.pdf          how to use the pack, every source and filing link, and the research evidence (clickable)
  data.json            the full TearSheetData payload
  filings/             the original documents (only with include_filing_docs=True; downloaded in parallel): the
                       latest reports, the official documents the research notes cite (results releases,
                       announcements) and, for US listings, the annual report to shareholders and the proxy
                       statement. SEC web-page filings are printed to PDF when a browser is available
                       (render/html_pdf.py). Broker research and news stay links (third-party copyright).

Every figure is copied from the payload. The only arithmetic here is simple and labelled where it is
shown: amounts in millions, margins of the interim / TTM columns, the after-tax cost of debt. The one exception is
the "Model (editable)" sheet (datapack_model.py): the report's DCF / DDM rebuilt with live Excel formulas from the
report's own inputs, for students to change.
"""
from __future__ import annotations

import io
import logging
import math
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Callable, NamedTuple, Optional
from urllib.parse import urlparse

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import settings
from .render.viewmodel import DISCLAIMER, ccy
from .schema import BrokerNote, FilingExcerpt, TearSheetData, ValueGrid

log = logging.getLogger(__name__)

MAX_DOC_BYTES = 200 * 1024 * 1024
MN = '#,##0;(#,##0);0'          # amounts in millions, negatives in brackets
PCT, PCT2, SPCT = "0.0%", "0.00%", "+0.0%;-0.0%;0.0%"
X, X1, PS, NUM4, INT, DATE, DAYS = '0.00"x"', '0.0"x"', "#,##0.00", "0.0000", "#,##0", "yyyy-mm-dd", "0"

NAVY = "1B3A8C"
TITLE = Font(bold=True, size=13, color=NAVY)
NOTE = Font(italic=True, size=9, color="5B6475")
HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
SECTION = Font(bold=True, color=NAVY)
BOLD = Font(bold=True)
LINK = Font(color="0563C1", underline="single")
UP, DOWN = PatternFill("solid", fgColor="E3F3EA"), PatternFill("solid", fgColor="FBE5E3")

MODEL_SHEET = "Model (editable)"
SHEETS = {
    "Income statement": "Revenue to net profit and EPS for 5 fiscal years, plus the latest interim period, the same "
                        "period a year earlier, the latest quarter and TTM when the payload has them.",
    "Balance sheet": "Cash, assets, debt, liabilities, equity and minority interest at each period end.",
    "Cash flow": "Operating cash flow, capex, free cash flow, D&A, dividends and buybacks.",
    "Ratios": "Margins, returns (ROE, ROA, ROIC), DuPont, growth, leverage and liquidity, efficiency, cash and payout.",
    "Valuation": "Market data, WACC build-up, DCF forecast and EV-to-equity bridge, DDM, sensitivity grids, reverse "
                 "DCF, Monte Carlo, football field, P/E band and the AI rating's fair-value methods.",
    MODEL_SHEET: "The report's valuation as a live Excel model you can change: the DCF (the dividend discount model "
                 "for banks and insurers) with its inputs in yellow cells (WACC build-up, terminal growth, each "
                 "year's revenue growth and FCF margin, net cash, shares, price, FX), the value per share and upside, "
                 "a WACC x terminal growth grid, the bear / base / bull scenarios with editable probabilities, and "
                 "the rating rule. Formulas only, no macros.",
    "Peers": "Comparable companies (target, each peer, median) with multiples, operating metrics and the target's "
             "premium / discount to the median.",
    "Prices": "Share price with moving averages, volume and RSI; stock vs benchmark (rebased to 100); trailing P/E "
              "history; returns.",
    "Brokers": "Broker ratings, price targets and EPS forecasts (street view), news write-ups of broker notes, and "
               "the analyst consensus.",
    "Evidence": "The research notes the report cites as [R1], [R2] ...: each fact, the exact words in its source "
                "document, and the link (or the file in this pack's filings/ folder).",
    "Sources": "Numbered citations (publisher, access route, link, retrieval time), the latest reports read and "
               "recent official announcements.",
}

# research notes from these document types are the company's or the exchange's own publications: the pack may copy
# them; broker research and news are third-party (copyright), so they stay links
OFFICIAL_KINDS = ("results_release", "results_commentary", "periodic_report", "announcement", "ir_record")


def research_documents(data: TearSheetData) -> list[FilingExcerpt]:
    """The official documents behind the research notes, one per link, as filing records for the download."""
    out, seen = [], {f.url for f in data.filings}
    for f in (data.research.facts if data.research else []):
        if f.kind in OFFICIAL_KINDS and _is_url(f.url) and f.url not in seen:
            seen.add(f.url)
            out.append(FilingExcerpt(source=f.source.split(":")[0], title=f.title, filed=f.published, url=f.url,
                                     sections={}))
    return out


# Ratios the PDF leaves out for banks and insurers (cash-flow and working-capital measures mislead there)
FIN_DROP = {"fcf_margin", "capex_ratio", "cash_conversion", "accruals_ratio", "current_ratio", "receivable_days",
            "inventory_days", "gross_margin", "interest_coverage", "net_debt_to_ebitda", "ebitda_margin"}


# ---------------------------------------------------------------- cell helpers
def _is_url(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://"))


def _clean(v: Any) -> Any:
    """A value openpyxl can store: finite numbers, naive (UTC) datetimes, legal text."""
    if v is None or isinstance(v, (bool, int, date)) and not isinstance(v, datetime):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v
    return ILLEGAL_CHARACTERS_RE.sub("", str(v))[:32000]


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return a / b if a is not None and b else None


def _mn(v: Optional[float]) -> Optional[float]:
    return v / 1e6 if _num(v) else None


def _text_width(s: str) -> int:
    return max((sum(2 if ord(ch) > 0x2E80 else 1 for ch in line) for line in s.split("\n")), default=0)


def _width(v: Any, fmt: str) -> int:
    if isinstance(v, bool):
        return 5
    if _num(v):
        if "%" in fmt:
            return len(f"{v * 100:+,.1f}%")
        return len(f"{v:,.0f}") + 2 if fmt in (MN, INT, DAYS) else len(f"{v:,.2f}") + 1
    if isinstance(v, (date, datetime)):
        return 11
    return _text_width(str(v))


class _Sheet:
    """One worksheet written top to bottom: title, sources and a note in rows 1-3, then sections and tables."""

    def __init__(self, wb: Workbook, name: str, title: str, source: str, note: str = ""):
        self.ws = wb.create_sheet(name)
        self.spill: set[tuple[int, int]] = set()   # long text allowed to run into the empty cells on its right
        self.heads: set[tuple[int, int]] = set()   # header cells always set their column's width
        self.line(1, title, TITLE)
        self.line(2, source, NOTE)
        if note:
            self.line(3, note, NOTE)
        self.r = 4

    def put(self, r: int, c: int, v: Any, fmt: Optional[str] = None, font: Optional[Font] = None,
            fill: Optional[PatternFill] = None):
        cell = self.ws.cell(row=r, column=c)
        cell.value = _clean(v)
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"  # text, never a formula
        if fmt and not isinstance(cell.value, str):
            cell.number_format = fmt
        if font:
            cell.font = font
        if fill:
            cell.fill = fill
            if fill is HEAD_FILL:
                self.heads.add((r, c))
        if _is_url(cell.value) and len(cell.value) < 2000 and " " not in cell.value:  # Excel's link limits
            cell.hyperlink = cell.value
            cell.font = LINK
        return cell

    def line(self, r: int, text: str, font: Optional[Font] = None) -> None:
        self.put(r, 1, text, font=font)
        self.spill.add((r, 1))

    def section(self, text: str) -> None:
        if self.r > 4:
            self.r += 1
        self.line(self.r, text, SECTION)
        self.r += 1

    def note(self, text: str) -> None:
        self.line(self.r, text, NOTE)
        self.r += 1

    def header(self, labels: list[Any], fmts: Optional[list[Optional[str]]] = None, col: int = 1) -> None:
        for i, lab in enumerate(labels):
            self.put(self.r, col + i, lab, (fmts or [None] * len(labels))[i], HEAD, HEAD_FILL)
        self.r += 1

    def row(self, values: list[Any], fmts: Optional[list[Optional[str]]] = None, font: Optional[Font] = None,
            col: int = 1) -> None:
        for i, v in enumerate(values):
            self.put(self.r, col + i, v, fmts[i] if fmts and i < len(fmts) else None, font)
        self.r += 1

    def kv(self, label: str, value: Any, fmt: Optional[str] = None, note: str = "", font: Optional[Font] = None):
        if value is None or value == "":
            return
        self.row([label, value, note or None], [None, fmt, None], font)

    def fit(self, cap: int = 60, first: int = 4) -> None:
        """Column widths from the content; text with an empty cell on its right runs into it instead."""
        filled = {(c.row, c.column) for row in self.ws.iter_rows(min_row=first) for c in row if c.value is not None}
        widths: dict[int, int] = {}
        for row in self.ws.iter_rows(min_row=first):
            for c in row:
                key = (c.row, c.column)
                if c.value is None or key in self.spill or (isinstance(c.value, str) and key not in self.heads
                                                             and (c.row, c.column + 1) not in filled):
                    continue
                widths[c.column] = max(widths.get(c.column, 0), _width(c.value, c.number_format))
        for col, w in widths.items():
            self.ws.column_dimensions[get_column_letter(col)].width = min(max(w + 2, 9), cap)


# ---------------------------------------------------------------- shared bits
def _safe(data: TearSheetData) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", data.profile.ticker.replace(".", "_").upper())


def _src(data: TearSheetData, topics: tuple[str, ...], extra: str = "") -> str:
    cits = [c for c in data.citations if c.topic in topics]
    if cits:
        text = "Sources: " + "; ".join(f"[{c.n}] {c.publisher} ({c.via})" for c in cits) + \
               ". Links and retrieval times: Sources sheet."
    else:
        text = "Sources: " + ("; ".join(data.sources) or "not recorded in this payload") + "."
    return f"{text} {extra}".strip()


def _prior_label(label: str) -> str:
    """'9M 2026' -> '9M 2025', '1H FY2027' -> '1H FY2026'."""
    years = list(re.finditer(r"(?:19|20)\d{2}", label))
    if not years:
        return f"{label} (a year earlier)"
    y = years[-1]
    return label[:y.start()] + str(int(y.group()) - 1) + label[y.end():]


def _ccy_long(code: str) -> str:
    """'RMB (CNY)', but 'HKD' once."""
    return ccy(code) if ccy(code) == code else f"{ccy(code)} ({code})"


def _is_financial(data: TearSheetData) -> bool:
    from .quant.valuation import is_financial
    return is_financial(data)


class _Col(NamedTuple):
    head: str
    kind: str          # fy | int | prior | q | qprior | ttm
    obj: Any
    end: Optional[date]


def _columns(data: TearSheetData, kinds: set[str]) -> list[_Col]:
    f = data.financials
    cols = [_Col(f"FY{y.fiscal_year}", "fy", y, y.period_end) for y in f.years[-5:]]
    lt = f.latest
    if lt:
        if "int" in kinds:
            cols.append(_Col(lt.label, "int", lt, lt.period_end))
        if "prior" in kinds:
            cols.append(_Col(_prior_label(lt.label), "prior", lt, None))
        if "q" in kinds and lt.quarter_label:
            cols += [_Col(lt.quarter_label, "q", lt, lt.period_end),
                     _Col(_prior_label(lt.quarter_label), "qprior", lt, None)]
    if f.ttm and "ttm" in kinds:
        cols.append(_Col("TTM", "ttm", f.ttm, f.ttm.period_end))
    return cols


Getter = Any  # attribute name or callable(obj) per column kind


def _value(col: _Col, getters: dict[str, Getter]) -> Any:
    g = getters.get(col.kind)
    if g is None:
        return None
    return g(col.obj) if callable(g) else getattr(col.obj, g, None)


def _period_table(s: _Sheet, cols: list[_Col], rows: list[tuple], unit: str) -> None:
    """Rows = line items, columns = periods. A row is (label, fmt, {kind: getter}, bold)."""
    s.header([unit] + [c.head for c in cols])
    s.row(["Period end"] + [c.end for c in cols], [None] + [DATE] * len(cols), NOTE)
    s.ws.freeze_panes = f"B{s.r}"
    for label, fmt, getters, bold in rows:
        vals = [_value(c, getters) for c in cols]
        if all(v is None for v in vals):
            continue
        if fmt == MN:
            vals = [_mn(v) for v in vals]
        s.row([label] + vals, [None] + [fmt] * len(cols), BOLD if bold else None)


def _statement_notes(s: _Sheet, data: TearSheetData, cols: list[_Col], extra: tuple[str, ...] = ()) -> None:
    f, lt = data.financials, data.financials.latest
    s.r += 1
    for x in extra:
        s.note(x)
    if f.accounting_standard:
        s.note(f"Accounting standard: {f.accounting_standard}.")
    if lt and any(c.kind == "int" for c in cols):
        s.note(f"{lt.label}: {lt.months} months to {lt.period_end.isoformat()}, cumulative from the start of the "
               f"fiscal year; {_prior_label(lt.label)} = the same period a year earlier."
               + (f" {lt.quarter_label} = the latest quarter on its own." if lt.quarter_label and
                  any(c.kind == "q" for c in cols) else ""))
        if not lt.capex_complete and s.ws.title == "Cash flow":
            s.note(f"The source lacks some capex lines for {lt.label}: capex and free cash flow are incomplete.")
    if f.ttm and any(c.kind == "ttm" for c in cols):
        s.note(f"TTM = trailing twelve months to {f.ttm.period_end.isoformat()}: {f.ttm.basis}.")
    s.note("An empty cell means the source did not provide the figure (never a zero); rows with no data at all "
           "are left out.")


# ---------------------------------------------------------------- statements
def _income(wb: Workbook, data: TearSheetData) -> None:
    rc = ccy(data.financials.currency)
    s = _Sheet(wb, "Income statement", f"Income statement: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("statements",)),
               f"{rc} millions unless a row says otherwise. Costs are positive amounts, as stored in the payload "
               f"(the PDF shows them in brackets).")
    cols = _columns(data, {"int", "prior", "q", "ttm"})
    if not cols:
        s.note("No fiscal-year data in this payload.")
        return
    _period_table(s, cols, [
        ("Revenue", MN, dict(fy="revenue", int="revenue", prior="prior_revenue", q="quarter_revenue",
                             qprior="quarter_revenue_prior", ttm="revenue"), True),
        ("  Revenue growth (YoY, %)", SPCT, dict(fy="revenue_growth", int="revenue_growth",
                                                 q="quarter_revenue_growth"), False),
        ("Gross profit", MN, dict(fy="gross_profit", int="gross_profit", prior="prior_gross_profit",
                                  q="quarter_gross_profit", qprior="quarter_gross_profit_prior"), False),
        ("  Gross margin (%)", PCT, dict(fy="gross_margin", int="gross_margin", prior="prior_gross_margin",
                                         q="quarter_gross_margin", qprior="quarter_gross_margin_prior"), False),
        ("Selling, general & admin. expense", MN, dict(fy="sga_expense"), False),
        ("Research & development expense", MN, dict(fy="rnd_expense"), False),
        ("Operating profit", MN, dict(fy="operating_income", int="operating_income",
                                      prior="prior_operating_income"), True),
        ("EBITDA", MN, dict(fy="ebitda"), False),
        ("Interest expense", MN, dict(fy="interest_expense"), False),
        ("Pre-tax profit", MN, dict(fy="pretax_income"), False),
        ("Income tax", MN, dict(fy="income_tax"), False),
        ("Net profit to shareholders", MN, dict(fy="net_income", int="net_income", prior="prior_net_income",
                                                q="quarter_net_income", qprior="quarter_net_income_prior",
                                                ttm="net_income"), True),
        ("  Net profit growth (YoY, %)", SPCT, dict(int="net_income_growth", q="quarter_net_income_growth"), False),
        (f"Diluted EPS ({rc} per share, restated for splits)", PS, dict(fy="diluted_eps"), False),
    ], f"{rc} mn")
    _statement_notes(s, data, cols)
    s.fit()


def _balance(wb: Workbook, data: TearSheetData) -> None:
    f = data.financials
    rc = ccy(f.currency)
    s = _Sheet(wb, "Balance sheet", f"Balance sheet: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("statements",)), f"{rc} millions, at each period end.")
    cols = _columns(data, {"int"})
    if not cols:
        s.note("No fiscal-year data in this payload.")
        return
    _period_table(s, cols, [
        ("Cash & short-term investments", MN, dict(fy="cash_and_equivalents", int="cash_and_equivalents"), False),
        ("Receivables", MN, dict(fy="receivables"), False),
        ("Inventory", MN, dict(fy="inventory"), False),
        ("Current assets", MN, dict(fy="current_assets"), False),
        ("Total assets", MN, dict(fy="total_assets"), True),
        ("Current liabilities", MN, dict(fy="current_liabilities"), False),
        ("Total debt (excl. leases)", MN, dict(fy="total_debt", int="total_debt"), False),
        ("Total liabilities", MN, dict(fy="total_liabilities"), False),
        ("Shareholders' equity", MN, dict(fy="total_equity", int="total_equity"), True),
        ("Minority interest (non-controlling)", MN, dict(fy="minority_interest", int="minority_interest"), False),
        ("Net debt / (net cash)", MN, dict(fy="net_debt", int="net_debt"), False),
    ], f"{rc} mn")
    _statement_notes(s, data, cols, ((f"Cash definition: {f.cash_definition}",) if f.cash_definition else ()) + (
        "Total debt = borrowings + bonds / notes, excluding lease liabilities. Net debt = total debt - cash; "
        "negative = net cash.",))
    s.fit()


def _cashflow(wb: Workbook, data: TearSheetData) -> None:
    rc = ccy(data.financials.currency)
    s = _Sheet(wb, "Cash flow", f"Cash flow: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("statements",)),
               f"{rc} millions. Capex, dividends and buybacks are positive amounts (cash out), as stored in the "
               f"payload. Free cash flow = operating cash flow - capex.")
    cols = _columns(data, {"int", "prior", "ttm"})
    if not cols:
        s.note("No fiscal-year data in this payload.")
        return
    _period_table(s, cols, [
        ("Operating cash flow", MN, dict(fy="operating_cash_flow", int="operating_cash_flow",
                                         prior="prior_operating_cash_flow", ttm="operating_cash_flow"), True),
        ("Capital expenditure", MN, dict(fy="capex", int="capex", prior="prior_capex", ttm="capex"), False),
        ("Free cash flow", MN, dict(fy="free_cash_flow", int="free_cash_flow", prior="prior_free_cash_flow",
                                    ttm="free_cash_flow"), True),
        ("Depreciation & amortisation", MN, dict(fy="depreciation_amortization"), False),
        ("Dividends paid", MN, dict(fy="dividends_paid"), False),
        ("Share buybacks", MN, dict(fy="buybacks"), False),
    ], f"{rc} mn")
    _statement_notes(s, data, cols)
    s.fit()


# ---------------------------------------------------------------- ratios
RATIO_GROUPS = [
    ("Profitability", [("Gross margin", "gross_margin", PCT), ("Operating margin", "operating_margin", PCT),
                       ("EBITDA margin", "ebitda_margin", PCT), ("Net margin", "net_margin", PCT),
                       ("FCF margin", "fcf_margin", PCT), ("SG&A / revenue", "sga_ratio", PCT),
                       ("R&D / revenue", "rnd_ratio", PCT)]),
    ("Returns", [("ROE", "roe", PCT), ("ROA", "roa", PCT), ("ROIC", "roic", PCT)]),
    ("DuPont (ROE = net margin x asset turnover x equity multiplier)",
     [("Net margin", "net_margin", PCT), ("Asset turnover", "asset_turnover", X),
      ("Equity multiplier", "equity_multiplier", X), ("ROE", "roe", PCT)]),
    ("Growth", [("Revenue growth", "revenue_growth", SPCT), ("EPS growth", "eps_growth", SPCT),
                ("Net profit growth", "net_income_growth", SPCT)]),
    ("Leverage and liquidity", [("Current ratio", "current_ratio", X), ("Debt / equity", "debt_to_equity", X),
                                ("Liabilities / assets", "liabilities_to_assets", PCT),
                                ("Net debt / EBITDA", "net_debt_to_ebitda", X),
                                ("Interest cover (EBIT / interest)", "interest_coverage", X1)]),
    ("Efficiency", [("Asset turnover", "asset_turnover", X), ("Receivable days", "receivable_days", DAYS),
                    ("Inventory days", "inventory_days", DAYS), ("Capex / revenue", "capex_ratio", PCT)]),
    ("Cash and payout", [("Cash conversion (CFO / net profit)", "cash_conversion", X),
                         ("Accruals ratio", "accruals_ratio", SPCT), ("Effective tax rate", "effective_tax", PCT),
                         ("Dividend payout", "payout_ratio", PCT),
                         ("Total payout (dividends + buybacks)", "total_payout_ratio", PCT)]),
]

INTERIM_RATIOS: dict[str, tuple[dict[str, Getter], str]] = {
    "gross_margin": ({"int": "gross_margin", "prior": "prior_gross_margin"}, ""),
    "operating_margin": ({"int": lambda p: _div(p.operating_income, p.revenue),
                          "prior": lambda p: _div(p.prior_operating_income, p.prior_revenue)},
                         "Interim columns computed here: operating profit / revenue"),
    "net_margin": ({"int": lambda p: _div(p.net_income, p.revenue),
                    "prior": lambda p: _div(p.prior_net_income, p.prior_revenue),
                    "ttm": lambda t: _div(t.net_income, t.revenue)},
                   "Interim / TTM columns computed here: net profit / revenue"),
    "fcf_margin": ({"int": lambda p: _div(p.free_cash_flow, p.revenue),
                    "prior": lambda p: _div(p.prior_free_cash_flow, p.prior_revenue), "ttm": "fcf_margin"},
                   "Interim columns computed here: free cash flow / revenue"),
    "revenue_growth": ({"int": "revenue_growth"}, ""),
    "net_income_growth": ({"int": "net_income_growth"}, ""),
}


def _fy_ratio(data: TearSheetData, attr: str) -> Callable:
    """Fiscal-year value: the report's ratio table, else the older payload fields (FiscalYear, DuPont, quality)."""
    by_year = {r.fiscal_year: r for r in data.ratios}

    def get(y):
        v = getattr(by_year.get(y.fiscal_year), attr, None)
        if v is None and attr in ("gross_margin", "net_margin", "revenue_growth"):
            v = getattr(y, attr)
        dp, eq = data.dupont, data.earnings_quality
        if v is None and dp and dp.fiscal_year == y.fiscal_year:
            v = getattr(dp, attr, None)
        if v is None and eq and eq.fiscal_year == y.fiscal_year:
            v = getattr(eq, {"cash_conversion": "cfo_to_net_income"}.get(attr, attr), None)
        return v
    return get


def _ratios(wb: Workbook, data: TearSheetData) -> None:
    bank = _is_financial(data)
    s = _Sheet(wb, "Ratios", f"Ratios: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("statements",), "Ratios computed by InvestSync from the statements (average opening "
                                           "and closing balances where both exist)."),
               "Ratios in %, multiples with an x. Fiscal-year columns are the report's own figures; any interim / "
               "TTM figure computed here is marked in the Note column."
               + (" Bank / insurer: cash-flow and working-capital ratios are left out, as in the PDF." if bank else ""))
    cols = _columns(data, {"int", "prior", "ttm"})
    if not cols:
        s.note("No fiscal-year data in this payload.")
        return
    s.header(["Ratio"] + [c.head for c in cols] + ["Note"])
    s.row(["Period end"] + [c.end for c in cols], [None] + [DATE] * len(cols), NOTE)
    s.ws.freeze_panes = f"B{s.r}"
    for group, rows in RATIO_GROUPS:
        body = []
        for label, attr, fmt in rows:
            if bank and attr in FIN_DROP:
                continue
            getters, note = INTERIM_RATIOS.get(attr, ({}, ""))
            fy_get = _fy_ratio(data, attr)
            vals = [fy_get(c.obj) if c.kind == "fy" else _value(c, getters) for c in cols]
            if all(v is None for v in vals):
                continue
            computed = note and any(v is not None for c, v in zip(cols, vals) if c.kind != "fy" and
                                    not isinstance(getters.get(c.kind), str))
            body.append(([label] + vals + [note if computed else None], [None] + [fmt] * len(cols)))
        if body:
            s.line(s.r, group, SECTION)
            s.r += 1
            for vals, fmts in body:
                s.row(vals, fmts)
    s.r += 1
    s.note("ROIC = operating profit x (1 - tax rate) / (equity + debt - cash). Accruals ratio = (net profit - "
           "operating cash flow) / average assets. Cash conversion = operating cash flow / net profit.")
    s.fit()


# ---------------------------------------------------------------- valuation
def _grid(s: _Sheet, title: str, g: Optional[ValueGrid], price: float, row_fmt: str, col_fmt: str) -> None:
    if not g or not g.rows or not g.cols:
        return
    s.section(title)
    s.note(f"Rows: {g.row_label}; columns: {g.col_label}.")
    s.header([g.row_label] + list(g.cols), [None] + [col_fmt] * len(g.cols))
    mid_r, mid_c = len(g.rows) // 2, len(g.cols) // 2
    for i, (r, vals) in enumerate(zip(g.rows, g.values)):
        s.put(s.r, 1, r, row_fmt, BOLD)
        for j, v in enumerate(vals):
            fill = None if v is None else UP if v >= price else DOWN
            s.put(s.r, 2 + j, v, PS, BOLD if (i, j) == (mid_r, mid_c) else None, fill)
        s.r += 1
    s.note(f"Value per share in the trading currency; green = at or above today's price ({price:,.2f}); "
           f"bold = base case.")


def _valuation(wb: Workbook, data: TearSheetData) -> None:
    v, q, f = data.valuation, data.quote, data.financials
    rc = ccy(f.currency)
    cur = ccy(v.currency if v else q.currency)
    s = _Sheet(wb, "Valuation", f"Valuation workings: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("statements", "market", "prices", "fx", "rates", "consensus", "assumptions"),
                    "Computed by InvestSync from these inputs; assumptions set by the finance team "
                    "(config/valuation.json, config/rating.json)."),
               f"Per-share values in {cur} (trading currency); statement amounts in {rc} millions.")
    s.ws.freeze_panes = "A4"
    s.section("Market data")
    s.kv(f"Share price ({ccy(q.currency)})", q.price, PS, f"as of {q.as_of.isoformat()}")
    s.kv(f"Market cap ({ccy(q.currency)} mn)", _mn(q.market_cap), MN)
    s.kv(f"Enterprise value ({ccy(q.currency)} mn)", _mn(q.enterprise_value), MN,
         "market cap + net debt + minorities, latest reported balance sheet, at spot FX")
    s.kv("P/E (TTM)", q.pe_ttm, X1)
    s.kv("P/B", q.pb, X)
    s.kv("Dividend yield", q.dividend_yield, PCT2)
    if q.currency != f.currency:
        s.kv(f"FX: {rc} per 1 {ccy(q.currency)}", q.fx_to_reporting, NUM4)
    if not v:
        s.r += 1
        s.note("No DCF / DDM valuation in this payload.")
    else:
        w = v.wacc
        s.section("Discount rate (WACC build-up)")
        s.header(["Item", "Value", "Source / method"])
        s.kv("Risk-free rate", w.risk_free, PCT2, w.risk_free_source)
        s.kv("Beta", w.beta if w.beta is not None else 1.0, "0.00", w.beta_method)
        s.kv("Equity risk premium", w.equity_risk_premium, PCT2, w.erp_source)
        s.kv("Cost of equity", w.cost_of_equity, PCT2, "risk-free rate + beta x equity risk premium", BOLD)
        s.kv("Pre-tax cost of debt", w.pre_tax_cost_of_debt, PCT2, "interest expense / average debt")
        s.kv("Tax rate", w.tax_rate, PCT2, "effective rate of the latest fiscal year (statutory if unavailable)")
        if w.pre_tax_cost_of_debt is not None:
            s.kv("After-tax cost of debt", w.pre_tax_cost_of_debt * (1 - w.tax_rate), PCT2,
                 "computed here: pre-tax cost of debt x (1 - tax rate)")
        s.kv("Equity weight", w.equity_weight, PCT, "market cap / (market cap + debt)")
        s.kv("Debt weight", w.debt_weight, PCT)
        if w.wacc is not None:
            s.kv("WACC", w.wacc, PCT2, "equity weight x cost of equity + debt weight x after-tax cost of debt", BOLD)
        else:
            s.row(["WACC", None, "not meaningful for banks and insurers (the DDM uses the cost of equity)"], font=BOLD)
        d = v.dcf
        if d:
            s.section("DCF")
            s.kv("Method", d.method)
            s.kv("FCF margin (median of the last 3 years)", d.fcf_margin, PCT)
            s.kv("Terminal growth", d.terminal_growth, PCT)
            s.kv(f"Terminal value, end of forecast, undiscounted ({rc} mn)", _mn(d.terminal_value), MN)
            s.kv(f"Enterprise value ({rc} mn)", _mn(d.enterprise_value), MN)
            s.kv(f"Equity value ({rc} mn)", _mn(d.equity_value), MN)
            s.kv(f"Value per share ({cur})", d.value_per_share, PS, font=BOLD)
            s.kv("Upside vs price", d.upside, SPCT)
            if d.forecast:
                s.section(f"DCF forecast ({rc} mn)")
                s.header([""] + [f"FY{x.fiscal_year}E" for x in d.forecast])
                n = len(d.forecast)
                s.row([f"Revenue ({rc} mn)"] + [_mn(x.revenue) for x in d.forecast], [None] + [MN] * n, BOLD)
                s.row(["  Growth"] + [x.growth for x in d.forecast], [None] + [SPCT] * n)
                s.row(["  Basis (consensus or fade to terminal growth)"] + [x.basis for x in d.forecast])
                s.row([f"Free cash flow ({rc} mn)"] + [_mn(x.free_cash_flow) for x in d.forecast], [None] + [MN] * n)
                s.row(["Discount factor"] + [x.discount_factor for x in d.forecast], [None] + [NUM4] * n)
                s.row([f"Present value ({rc} mn)"] + [_mn(x.present_value) for x in d.forecast],
                      [None] + [MN] * n, BOLD)
            b = d.bridge
            if b:
                s.section("EV-to-equity bridge")
                s.header(["Step", "Value", "Unit"])
                s.row([f"PV of {len(d.forecast)}-year free cash flow", _mn(b.pv_forecast), f"{rc} mn"], [None, MN])
                s.row(["+ PV of terminal value", _mn(b.pv_terminal), f"{rc} mn"], [None, MN])
                s.row(["  Terminal value share of EV", b.terminal_share, "%"], [None, PCT])
                s.row(["= Enterprise value", _mn(b.enterprise_value), f"{rc} mn"], [None, MN], BOLD)
                s.row(["- Net debt (latest FY; negative = net cash)", _mn(b.net_debt), f"{rc} mn"], [None, MN])
                s.row(["= Equity value", _mn(b.equity_value), f"{rc} mn"], [None, MN], BOLD)
                s.row(["/ Shares (market cap / price)", _mn(b.shares), "mn shares"], [None, "#,##0.0"])
                s.row([f"FX ({rc} per 1 {cur})", b.fx_to_reporting, "rate"], [None, NUM4])
                s.row(["= Value per share", b.value_per_share, cur], [None, PS], BOLD)
        m = v.ddm
        if m:
            s.section("Dividend discount model")
            s.kv("Method", m.method)
            s.kv(f"Dividend per share, trailing ({cur})", m.dividend_per_share, PS)
            s.kv("Perpetual dividend growth", m.growth, PCT)
            s.kv("Cost of equity", w.cost_of_equity, PCT2)
            s.kv(f"Value per share ({cur})", m.value_per_share, PS, font=BOLD)
            s.kv("Upside vs price", m.upside, SPCT)
        sens = v.sensitivity
        grids = [(f"Sensitivity: value per share ({cur})", sens.discount_growth if sens else None, PCT2, PCT),
                 (f"Sensitivity: FCF margin vs revenue growth shift ({cur})", sens.margin_growth if sens else None,
                  PCT, SPCT)]
        for title, g in ((f"DCF grid ({cur})", d.grid if d else None), (f"DDM grid ({cur})", m.grid if m else None)):
            if g and all(g != x[1] for x in grids):
                grids.append((title, g, PCT2, PCT))
        for title, g, rf, cf in grids:
            _grid(s, title, g, q.price, rf, cf)
        r = v.reverse
        if r:
            hold = r.hold_years or 0
            span = f"FY{r.from_year} to FY{r.to_year}" if r.from_year and r.to_year else f"{r.horizon_years} years"
            s.section(f"Reverse {r.model}: what today's price implies"
                      + ((f" (after the {hold} consensus years, {span})" if hold else
                          f" ({r.horizon_years}-year horizon)") if r.horizon_years else ""))
            if r.model == "DCF":
                s.kv("Implied revenue growth (constant, per year" + (f", {span})" if hold else ")"),
                     r.implied_growth, SPCT)
                s.kv("Model DCF revenue growth (CAGR" + (f", {span})" if hold else ")"), r.model_growth, SPCT)
                s.kv("Implied FCF margin at the model DCF's growth", r.implied_fcf_margin, PCT)
                s.kv("Base case FCF margin", r.model_fcf_margin, PCT)
            else:
                s.kv("Implied perpetual dividend growth", r.implied_growth, PCT)
                s.kv("Base case dividend growth", r.model_growth, PCT)
            if r.note:
                s.note(r.note)
        mc = v.monte_carlo
        if mc:
            s.section(f"Monte Carlo ({mc.model}, seeded)")
            s.kv("Draws (total)", mc.n_draws, INT)
            s.kv("Draws (valid)", mc.n_valid, INT)
            s.kv("Seed", mc.seed, "0")
            for k in sorted(mc.percentiles, key=lambda k: int(k[1:]) if k[1:].isdigit() else 0):
                s.kv(f"{k.upper()} value per share ({cur})", mc.percentiles[k], PS)
            s.kv(f"Mean ({cur})", mc.mean, PS)
            s.kv("Share of draws above today's price", mc.prob_above_price, PCT)
            for k, val in mc.assumptions.items():
                s.kv(f"Input: {k.replace('_', ' ')}", val, PCT2)
            if mc.counts and len(mc.bins) == len(mc.counts) + 1:
                s.section("Monte Carlo histogram")
                s.header([f"From ({cur})", f"To ({cur})", "Draws"])
                for i, c in enumerate(mc.counts):
                    s.row([mc.bins[i], mc.bins[i + 1], c], [PS, PS, INT])
    ff = data.football_field
    if ff and ff.bars:
        s.section(f"Football field ({ccy(ff.currency)} per share; price {ff.price:,.2f})")
        s.header(["Method", "Low", "Mid", "High", "Basis"])
        for b in ff.bars:
            s.row([b.label, b.low, b.mid, b.high, b.basis], [None, PS, PS, PS])
    band = data.pe_band
    if band:
        s.section(f"{band.metric}: history summary (series in the Prices sheet)")
        for label, val, fmt in (("Current", band.current, X1), ("Median", band.median, X1), ("Low", band.low, X1),
                                ("High", band.high, X1), ("Mean", band.mean, X1), ("Standard deviation", band.std, X1),
                                ("Share of history below the current multiple", band.percentile, PCT)):
            s.kv(label, val, fmt)
        if band.note:
            s.note(band.note)
    rt = data.rating
    if rt:
        rcur = ccy(rt.currency)
        s.section("AI rating (set by a fixed rule from the valuation, not by the AI) and fair-value methods")
        s.header(["Method", f"Value per share ({rcur})", "Weight", "Included", "Note"])
        for x in rt.methods:
            s.row([x.label, x.value, x.weight, "yes" if x.included else "no", x.note], [None, PS, PCT])
        s.r += 1
        s.kv("Rating", rt.rating, font=BOLD)
        s.kv(f"Fair value ({rcur})", rt.fair_value, PS, "weighted blend of the included methods", BOLD)
        s.kv("Upside vs price", rt.upside, SPCT)
        s.kv("Confidence", rt.confidence)
        s.kv("Buy threshold (fair value vs price)", rt.buy_threshold, SPCT, "Buy at or above this upside")
        s.kv("Sell threshold (fair value vs price)", rt.sell_threshold, SPCT, "Sell at or below this upside")
        s.kv(f"Buy below ({rcur})", rt.buy_below, PS)
        s.kv(f"Sell above ({rcur})", rt.sell_above, PS)
        s.kv("Reason", rt.reason)
    if v and v.notes:
        s.section("Valuation notes")
        for n in v.notes:
            s.note(n)
    s.fit(cap=70)


# ---------------------------------------------------------------- peers
PEER_COLS = [("Market cap (mn, own currency)", "market_cap", MN), ("Currency", "currency", None),
             ("P/E (TTM)", "pe_ttm", X1), ("EV/EBITDA", "ev_ebitda", X1), ("P/B", "pb", X),
             ("Dividend yield", "dividend_yield", PCT), ("Revenue, trailing (mn)", "revenue", MN),
             ("Revenue currency", "revenue_currency", None), ("Revenue growth", "revenue_growth", SPCT),
             ("Gross margin", "gross_margin", PCT), ("Operating margin", "operating_margin", PCT),
             ("Net margin", "net_margin", PCT), ("ROE", "roe", PCT)]


def _peers(wb: Workbook, data: TearSheetData) -> None:
    c = data.comps
    s = _Sheet(wb, "Peers", f"Peers: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("peers", "market"), c.method if c else ""),
               "Market cap and revenue in millions of each company's own currency; ratios in %, multiples with an x.")
    if not c:
        s.note("No peer comparison in this payload.")
        return
    s.header(["Role", "Ticker", "Name"] + [h for h, _, _ in PEER_COLS])
    s.ws.freeze_panes = f"D{s.r}"
    fmts = [None, None, None] + [f for _, _, f in PEER_COLS]
    for role, rows in (("Target", [c.target]), ("Peer", c.peers), ("Median", [c.median])):
        for x in rows:
            vals = [_mn(getattr(x, a)) if f == MN else getattr(x, a) for _, a, f in PEER_COLS]
            s.row([role, x.ticker, x.name] + vals, fmts, BOLD if role != "Peer" else None)
    attrs = [a for _, a, _ in PEER_COLS]
    prem = {k: val for k, val in c.premium_discount.items() if k in attrs}
    if prem:
        s.row(["Target vs median", None, "premium (+) / discount (-)"] +
              [prem.get(a) for a in attrs], [None, None, None] + [SPCT] * len(attrs), BOLD)
    other = {k: val for k, val in c.premium_discount.items() if k not in attrs}
    for k, val in other.items():
        s.kv(f"Target vs median: {k}", val, SPCT)
    s.r += 1
    s.note(f"How peers were chosen: {c.method}")
    s.fit(cap=40)


# ---------------------------------------------------------------- prices
def _price_blocks(data: TearSheetData) -> list[tuple]:
    """(title, headers, rows, column formats, per-row formats of column 2 or None) per block."""
    blocks = []
    t, b, band = data.technicals, data.benchmark, data.pe_band
    cur = ccy(data.quote.currency)
    if t:
        snap = [("As of", t.as_of, DATE), (f"Price ({cur})", t.price, PS), ("50-day SMA", t.sma50, PS),
                ("200-day SMA", t.sma200, PS), ("RSI (14)", t.rsi14, "0.0"), ("MACD", t.macd, PS),
                ("MACD signal", t.macd_signal, PS), ("Volume / 20-day average", t.volume_ratio, X),
                ("Volatility, 1 year (annualised)", t.volatility_1y, PCT),
                ("Max drawdown, 1 year", t.max_drawdown_1y, SPCT), ("Max drawdown, 3 years", t.max_drawdown_3y, SPCT),
                ("52-week high", t.high_52w, PS), ("52-week low", t.low_52w, PS),
                ("Support (3-month low)", t.support, PS), ("Resistance (3-month high)", t.resistance, PS),
                ("Rule-based reading", t.overall, None)]
        snap = [x for x in snap if x[1] is not None]
        blocks.append(("Technicals snapshot", ["Item", "Value"], [[k, val] for k, val, _ in snap],
                       [None, None], [f for _, _, f in snap]))
    if t and t.chart:
        blocks.append((f"Share price ({cur}), sampled", ["Date", "Close", "50-day SMA", "200-day SMA", "Volume",
                                                         "RSI (14)"],
                       [[p.d, p.close, p.sma50, p.sma200, p.volume, p.rsi] for p in t.chart],
                       [DATE, PS, PS, PS, INT, "0.0"], None))
    if b:
        for per in b.periods:
            st, bm = {p.d: p.v for p in per.stock}, {p.d: p.v for p in per.benchmark}
            days = sorted(set(st) | set(bm))
            blocks.append((f"{per.period} vs {b.name} (start = 100)",
                           ["Date", data.profile.ticker, b.name], [[d, st.get(d), bm.get(d)] for d in days],
                           [DATE, "0.0", "0.0"], None))
    if band and band.series:
        blocks.append((band.metric, ["Date", "P/E"], [[p.d, p.v] for p in band.series], [DATE, X1], None))
    if t and t.returns:
        blocks.append(("Returns vs benchmark", ["Period", "Stock", b.name if b else "Benchmark"],
                       [[r.period, r.stock, r.benchmark] for r in t.returns], [None, SPCT, SPCT], None))
    return blocks


def _series_note(data: TearSheetData) -> str:
    t, b, band = data.technicals, data.benchmark, data.pe_band
    parts = []
    if t and t.chart:
        parts.append(f"share price {len(t.chart)} points from {t.chart[0].d.isoformat()} to "
                     f"{t.chart[-1].d.isoformat()}")
    if b and b.periods:
        parts.append("stock vs " + b.name + " rebased to 100 for " +
                     ", ".join(f"{p.period} ({len(p.stock)} points)" for p in b.periods))
    if band and band.series:
        parts.append(f"trailing P/E {len(band.series)} points")
    if not parts:
        return "This payload holds no price series (only the latest quote)."
    return ("The payload holds sampled series, not every trading day: " + "; ".join(parts) +
            ". For full daily history, use the price source in the Sources sheet.")


def _prices(wb: Workbook, data: TearSheetData) -> None:
    s = _Sheet(wb, "Prices", f"Prices: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("prices",), "Moving averages, RSI, MACD, returns, rebasing and the P/E history "
                                       "computed by InvestSync."), _series_note(data))
    blocks = _price_blocks(data)
    if not blocks:
        return
    col = 1
    for title, heads, rows, fmts, cell_fmts in blocks:
        s.put(4, col, title, font=SECTION)
        s.spill.add((4, col))
        for i, h in enumerate(heads):
            s.put(5, col + i, h, font=HEAD, fill=HEAD_FILL)
        for r, vals in enumerate(rows):
            for i, val in enumerate(vals):
                fmt = cell_fmts[r] if cell_fmts and i == 1 else fmts[i]
                s.put(6 + r, col + i, val, fmt)
        col += len(heads) + 1
    s.ws.freeze_panes = "A6"
    s.fit(cap=36)


# ---------------------------------------------------------------- brokers
def _notes_table(s: _Sheet, notes: list[BrokerNote], cur: str, eps_ccy: str) -> None:
    keys = sorted({k for n in notes for k in n.eps})
    s.header(["Date", "Broker", "Broker (as published)", "Rating", "Rating (as published)", "Previous rating",
              "Action", f"Target ({cur})", f"Previous target ({cur})"] + [f"EPS {k} ({eps_ccy})" for k in keys] +
             ["Title (as published)", "English summary (AI-written, checked)", "Broker's own summary (as published)",
              "Analysts", "Source", "Link"])
    for n in notes:
        s.row([n.on, n.broker, n.broker_local, n.rating, n.rating_original, n.previous_rating, n.action, n.target,
               n.previous_target] + [n.eps.get(k) for k in keys] +
              [n.title, n.summary_en, n.abstract, n.analysts, n.source, n.url],
              [DATE] + [None] * 6 + [PS, PS] + [PS] * len(keys))


def _brokers(wb: Workbook, data: TearSheetData) -> None:
    st, c = data.street, data.consensus
    cur = ccy(data.quote.currency)
    extra = " ".join(x for x in (f"Street view: {st.source}." if st else "",
                                 f"Consensus: {c.source}." if c else "") if x)
    s = _Sheet(wb, "Brokers", f"Broker research and consensus: {data.profile.name} ({data.profile.ticker})",
               _src(data, ("research", "consensus"), extra),
               "Third-party views, credited and linked; not InvestSync views. Targets in the trading currency.")
    s.ws.freeze_panes = "A4"
    if not st and not c:
        s.note("No broker research or analyst consensus in this payload.")
        return
    if st:
        tc, ec = ccy(st.currency or data.quote.currency), ccy(st.eps_currency or data.financials.currency)
        s.section(f"Street view ({st.source}; last {st.window_days} days)")
        s.kv("Source link", st.source_url)
        s.kv("Reports", st.reports, INT)
        s.kv("Brokers", st.brokers, INT)
        s.kv("Latest rating per broker", ", ".join(f"{k} {n}" for k, n in st.rating_counts.items()) or None)
        s.kv("Upgrades", st.upgrades, INT)
        s.kv("Downgrades", st.downgrades, INT)
        s.kv("Price targets", st.targets_n, INT)
        s.kv(f"Target low ({tc})", st.target_low, PS)
        s.kv(f"Target median ({tc})", st.target_median, PS, font=BOLD)
        s.kv(f"Target high ({tc})", st.target_high, PS)
        s.kv("Median target vs price", st.target_upside, SPCT)
        s.kv("Targets older than 90 days", st.stale_targets, INT)
        s.kv(f"InvestSync model fair value ({tc})", st.model_fair_value, PS)
        s.kv("InvestSync model rating", st.model_rating)
        s.kv("Targets above the model", st.targets_above_model, INT)
        s.kv("Agreement", st.agreement, note=st.agreement_reason or "")
        if st.findings:
            s.section("Findings (written by code)")
            for x in st.findings:
                s.note(x)
        if st.synthesis:
            s.section("Where brokers agree / differ (AI-written, checked)")
            s.note(st.synthesis)
        if st.notes:
            s.section("Broker notes (newest first; counted in the street view)")
            _notes_table(s, st.notes, tc, ec)
        if st.writeups:
            s.section("News write-ups of broker notes (shown, not counted)")
            _notes_table(s, st.writeups, tc, ec)
        if st.eps:
            s.section(f"EPS forecasts across brokers ({ec})")
            s.header(["Fiscal year", "Forecasts", "Low", "Median", "High", "Spread (high - low) / median",
                      "Median vs last actual", "Median vs consensus", "Left out (> 3x from median)"])
            for e in st.eps:
                s.row([e.period, e.n, e.low, e.median, e.high, e.spread, e.vs_last_actual, e.vs_consensus,
                       e.excluded], [None, INT, PS, PS, PS, PCT, SPCT, SPCT, INT])
        rv = st.revision
        if rv:
            s.section(f"Estimate trend ({rv.period})")
            s.kv(f"Median EPS, last {rv.recent_days} days ({rv.recent_n} notes)", rv.recent_median, PS)
            s.kv(f"Median EPS, earlier ({rv.earlier_n} notes)", rv.earlier_median, PS)
            s.kv("Change", rv.change, SPCT)
    if c:
        tc, ec = ccy(c.currency or data.quote.currency), ccy(c.estimate_currency or data.financials.currency)
        s.section(f"Analyst consensus ({c.source}; third-party)")
        s.kv(f"Mean target ({tc})", c.target_mean, PS)
        s.kv(f"Median target ({tc})", c.target_median, PS)
        s.kv(f"High target ({tc})", c.target_high, PS)
        s.kv(f"Low target ({tc})", c.target_low, PS)
        s.kv("Analysts", c.analysts, INT)
        s.kv("Recommendation mean (1 = strong buy ... 5 = strong sell)", c.recommendation_mean, "0.00")
        s.kv("Forward P/E", c.forward_pe, X1)
        for k, n in c.distribution.items():
            s.kv(f"Ratings: {k.replace('_', ' ')}", n, INT)
        if c.estimates:
            s.section(f"Consensus estimates (EPS in {ec}; revenue in {ec} mn)")
            s.header(["Period", "EPS mean", "EPS low", "EPS high", "EPS growth", "Revenue mean (mn)",
                      "Revenue growth", "Analysts"])
            for e in c.estimates:
                s.row([e.period, e.eps_avg, e.eps_low, e.eps_high, e.eps_growth, _mn(e.revenue_avg),
                       e.revenue_growth, e.analysts], [None, PS, PS, PS, SPCT, MN, SPCT, INT])
    s.fit(cap=50)


# ---------------------------------------------------------------- sources
def _evidence(wb: Workbook, data: TearSheetData, files: Optional[dict[str, str]] = None) -> None:
    """The research notes cited in the report as [R#], each with its verbatim quote and document."""
    files = files or {}
    s = _Sheet(wb, "Evidence", f"Research evidence: {data.profile.name} ({data.profile.ticker})",
               "Sources: the document named in each row (company filings, official announcements, broker research, "
               "news), read by the research step. Every quote was found word for word in its document by code.",
               "The report cites these notes as [R1], [R2] ... To check one, open its link (or the file in filings/) "
               "and search for the quote. Notes are evidence for the commentary, never for the rating.")
    s.ws.freeze_panes = "A5"
    r = data.research
    if not r or not r.facts:
        s.note("No research notes in this payload (the research step was off or found nothing).")
        s.fit(cap=70)
        return
    s.header(["Note", "Topic", "Fact", "Exact words in the source", "Source", "Document", "Published", "Type",
              "Link", "File in this pack"])
    for f in r.facts:
        s.row([f.id, f.topic, f.text, f.quote, f.source, f.title, f.published, (f.kind or "").replace("_", " "),
               f.url or "", files.get(f.url or "", "")], [None] * 6 + [DATE])
    if r.gaps:
        s.section("Topics with no sourced fact found")
        for g in r.gaps:
            s.row([g])
    s.fit(cap=70)


def _sources(wb: Workbook, data: TearSheetData) -> None:
    s = _Sheet(wb, "Sources", f"Sources: {data.profile.name} ({data.profile.ticker})",
               "Every source used for the report; the [n] numbers match the PDF's citation list.",
               "Retrieval times in UTC; cached data shows the original fetch time.")
    s.ws.freeze_panes = "A4"
    s.section("Citations")
    if data.citations:
        s.header(["#", "Topic", "What", "Publisher", "Accessed via", "Link", "Retrieved (UTC)"])
        for c in data.citations:
            s.row([c.n, c.topic, c.what, c.publisher, c.via, c.url, c.retrieved], [INT] + [None] * 5 +
                  ["yyyy-mm-dd hh:mm"])
    else:
        s.note("This payload has no numbered citations (older schema); see the data sources below.")
    if data.sources:
        s.section("Data sources (summary)")
        for x in data.sources:
            s.row([x])
    s.section("Latest company reports read (filings)")
    if data.filings:
        s.header(["Source", "Title", "Filed", "Link", "Sections excerpted"])
        for f in data.filings:
            s.row([f.source, f.title, f.filed, f.url, ", ".join(f.sections)], [None, None, DATE])
    else:
        s.note("None in this payload.")
    if data.announcements:
        s.section("Official announcements (last 90 days)")
        s.header(["Date", "Title", "Type", "Important", "Source", "Link"])
        for a in data.announcements:
            s.row([a.on, a.title, a.kind, "yes" if a.important else "", a.source, a.url], [DATE])
        if data.announcements_routine:
            s.note(f"{data.announcements_routine} routine filings left out (e.g. daily buyback returns).")
    other = [("Company facts", ", ".join(data.company.sources) if data.company and data.company.sources else None),
             ("Ownership", ", ".join(data.ownership.sources) if data.ownership and data.ownership.sources else None),
             *[(f"Segments ({x.kind}, {x.period})", x.source) for x in data.segments],
             ("Peers", data.comps.method if data.comps else None),
             ("Benchmark", f"{data.benchmark.name} ({data.benchmark.code})" if data.benchmark else None),
             ("Street view", " ".join(x for x in (data.street.source, data.street.source_url or "") if x)
              if data.street else None),
             ("Analyst consensus", data.consensus.source if data.consensus else None)]
    other = [x for x in other if x[1]]
    if other:
        s.section("Other source notes")
        for k, val in other:
            s.row([k, val])
    s.fit(cap=70)


# ---------------------------------------------------------------- README
def _readme(wb: Workbook, data: TearSheetData) -> None:
    p, q, f = data.profile, data.quote, data.financials
    rc, cur = ccy(f.currency), ccy(q.currency)
    ws = wb.create_sheet("README", 0)
    ws.cell(1, 1, f"InvestSync source data pack: {p.name} ({p.ticker})").font = TITLE
    ws.cell(2, 1, "The numbers behind the research report, for digging further. Read this sheet first.").font = NOTE
    years = f.years[-5:]
    lt = f.latest
    rows: list[tuple[str, Optional[str]]] = [
        ("Company", f"{p.name}" + (f" ({p.name_local})" if p.name_local else "") +
         f", {p.ticker}, {p.exchange} ({p.market.value})" + (f"; sector: {p.sector}" if p.sector else "") +
         (f" ({p.sector_scheme})" if p.sector and p.sector_scheme else "")),
        ("Data as of", f"Share price and market data: {q.as_of.isoformat()}. "
                       + (f"Latest fiscal year: FY{years[-1].fiscal_year} (ended {years[-1].period_end.isoformat()}). "
                          if years else "")
                       + (f"Latest interim period: {lt.label} (to {lt.period_end.isoformat()}). " if lt else "")
                       + f"Report generated {_clean(data.generated_at):%Y-%m-%d %H:%M} UTC (schema "
                         f"{data.schema_version})."),
        ("Currency and units", f"Financial statements in {_ccy_long(f.currency)}, in millions ('mn') unless a row "
                               f"says otherwise. Share prices, per-share values, price targets and the valuation per "
                               f"share in the trading currency {_ccy_long(q.currency)}. Ratios and growth rates as % "
                               f"(stored as decimals: 0.253 = 25.3%); multiples with an 'x'. Peers: each company's own "
                               f"currency."
                               + (f" FX used: 1 {cur} = {q.fx_to_reporting:.4f} {rc}."
                                  if q.fx_to_reporting and q.currency != f.currency else "")),
        ("Fiscal-year convention", "FY label = calendar year of the period end"
                                   + (f" (e.g. FY{years[-1].fiscal_year} ended {years[-1].period_end.isoformat()})"
                                      if years else "")
                                   + ". Columns run oldest to newest. EPS is restated onto today's share basis after "
                                     "splits and bonus issues."
                                   + (f" Fiscal year end: {data.company.fiscal_year_end}." if data.company and
                                      data.company.fiscal_year_end else "")),
        ("Accounting standard", f.accounting_standard),
        ("Interim and TTM columns", " ".join(x for x in (
            f"{lt.label}: {lt.months} months to {lt.period_end.isoformat()}, cumulative from the start of the fiscal "
            f"year, next to the same period a year earlier ({_prior_label(lt.label)})."
            + (f" {lt.quarter_label}: the latest quarter on its own." if lt.quarter_label else "") if lt else "",
            f"TTM (trailing twelve months to {f.ttm.period_end.isoformat()}): {f.ttm.basis}." if f.ttm else "")
            if x) or "This payload has no interim or TTM figures."),
        ("Cash definition", f.cash_definition),
        ("Signs and gaps", "Costs and cash outflows (SG&A, R&D, interest, income tax, capex, dividends, buybacks) are "
                           "positive amounts, as stored in the payload; the PDF shows them in brackets. Negative "
                           "numbers are shown in brackets. An empty cell means the source did not provide the figure "
                           "(never a zero); rows with no data at all are left out."),
        ("Computed in this workbook", f"The {MODEL_SHEET} sheet is the one place that calculates: it rebuilds the "
                                      "report's DCF (for banks and insurers, the dividend discount model) with live "
                                      "Excel formulas from the report's own inputs, and gives the report's value per "
                                      "share until you change a yellow input (it says so if an older payload cannot "
                                      "be rebuilt exactly). Every other sheet copies the InvestSync payload "
                                      "(data.json), which is what the PDF report shows; the only arithmetic there: "
                                      "amounts divided by one million; operating, net and FCF margins of the "
                                      "interim / TTM columns (line / revenue, marked in the Ratios sheet); the "
                                      "after-tax cost of debt in the WACC build-up."),
        ("Price series", _series_note(data)),
        ("Banks and insurers", "Cash-flow and working-capital ratios are left out of the Ratios sheet (as in the PDF) "
                               "because they mislead for lenders; the valuation uses a dividend discount model."
         if _is_financial(data) else None),
        ("Sheets", "\n".join(f"{k}: {v}" for k, v in SHEETS.items())),
        ("Files in this pack", f"{_safe(data)}_data.xlsx (this workbook); sources.pdf (how to use the pack, every source and "
                               f"filing link, clickable); "
                               f"data.json (the full payload, as the website API returns it); filings/ (the original "
                               f"documents: the latest reports and the official documents the research notes "
                               f"cite, only when requested)."),
        ("Data sources", "\n".join(data.sources) + ("\n" if data.sources else "") +
         "Numbered citations with links: Sources sheet and sources.pdf."),
        ("Data warnings", "\n".join(data.warnings) or None),
        ("Data audit", f"{data.audit.status} ({len(data.audit.checks)} automatic checks; listed in the PDF)"
         if data.audit else None),
        ("Disclaimer (as in the PDF)", DISCLAIMER),
    ]
    r = 4
    for label, text in rows:
        if not text:
            continue
        ws.cell(r, 1, label).font = BOLD
        c = ws.cell(r, 2, _clean(text))
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(r, 1).alignment = Alignment(vertical="top")
        lines = sum(max(1, math.ceil(_text_width(ln) / 105)) for ln in str(text).split("\n"))
        ws.row_dimensions[r].height = 15 * lines + 2
        r += 1
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 110
    ws.freeze_panes = "A4"


def workbook(data: TearSheetData, files: Optional[dict[str, str]] = None) -> bytes:
    """The Excel workbook (xlsx bytes). ``files``: link -> path of the documents downloaded into the pack."""
    from .datapack_model import model_sheet
    wb = Workbook()
    wb.remove(wb.active)
    for build in (_income, _balance, _cashflow, _ratios, _valuation, model_sheet, _peers, _prices, _brokers):
        build(wb, data)
    _evidence(wb, data, files)
    _sources(wb, data)
    _readme(wb, data)
    wb.calculation.fullCalcOnLoad = True   # the model sheet's formulas are stored without values
    wb.properties.creator = "InvestSync Research Tools"
    wb.properties.title = f"{data.profile.ticker} source data"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- filings and sources.md
class _Doc(NamedTuple):
    filing: FilingExcerpt
    path: str
    content: bytes


def _fetch(url: str, timeout: float) -> bytes:
    """One document, given ``timeout`` seconds in all (the SEC requires the project's User-Agent)."""
    import requests
    from .data.filings import SEC_HEADERS
    host = (urlparse(url).hostname or "").lower()
    headers = SEC_HEADERS if host == "sec.gov" or host.endswith(".sec.gov") else {}
    deadline = time.monotonic() + timeout
    out = io.BytesIO()
    with requests.get(url, headers=headers, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(1 << 16):
            out.write(chunk)
            if out.tell() > MAX_DOC_BYTES:
                raise ValueError(f"larger than {MAX_DOC_BYTES >> 20} MB")
            if time.monotonic() > deadline:
                raise TimeoutError(f"not finished after {timeout:.0f} s")
    if not out.tell():
        raise ValueError("empty response")
    return out.getvalue()


def _doc_name(i: int, f: FilingExcerpt) -> str:
    base = urlparse(f.url).path.rsplit("/", 1)[-1] or "document"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{i:02d}_{f.source}_{f.filed.isoformat() if f.filed else ''}_{base}")


def download_filings(filings: list[FilingExcerpt]) -> tuple[list[_Doc], list[tuple[FilingExcerpt, str]]]:
    """Download every report in parallel; returns (documents, [(filing, why it was skipped)])."""
    todo, skipped, seen = [], [], set()
    for f in filings:
        if not _is_url(f.url):
            skipped.append((f, "no web link"))
        elif f.url not in seen:
            seen.add(f.url)
            todo.append(f)
    if not todo:
        return [], skipped
    timeout = float(settings.filings_timeout)
    docs = []
    with ThreadPoolExecutor(max_workers=min(4, len(todo))) as pool:
        jobs = [(f, pool.submit(_fetch, f.url, timeout)) for f in todo]
        failed = []
        for i, (f, job) in enumerate(jobs, 1):
            try:
                docs.append(_Doc(f, f"filings/{_doc_name(i, f)}", job.result()))
            except Exception:
                failed.append((i, f))
    for i, f in failed:  # one more try each, one at a time (a dropped connection or a burst limit)
        try:
            docs.append(_Doc(f, f"filings/{_doc_name(i, f)}", _fetch(f.url, timeout)))
        except Exception as e:
            log.warning("filing not downloaded: %s (%s)", f.url, type(e).__name__)
            skipped.append((f, f"{type(e).__name__}: {e}"[:200]))
    docs.sort(key=lambda d: d.path)
    return _as_pdf(docs, timeout), skipped


def _as_pdf(docs: list[_Doc], timeout: float) -> list[_Doc]:
    """Web-page filings (the SEC's .htm copies) printed to PDF, which students read more easily; the original stays
    linked in sources.pdf. Without a browser, or on any failure, the web page is kept (PACK_PDF=0 turns this off)."""
    import os
    from .render import html_pdf
    todo = [i for i, d in enumerate(docs) if html_pdf.is_html(d.path, d.content)]
    if not todo or os.getenv("PACK_PDF", "1") != "1" or not html_pdf.browser():
        return docs
    fetch = lambda url: _fetch(url, 60)  # noqa: E731  (images, with the SEC's User-Agent where needed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {i: pool.submit(html_pdf.html_to_pdf, docs[i].content, docs[i].filing.url, fetch, timeout)
                for i in todo}
        for i, job in jobs.items():
            try:
                pdf = job.result()
            except Exception as e:
                log.warning("PDF print failed for %s: %s", docs[i].filing.url, type(e).__name__)
                pdf = None
            if pdf:
                d = docs[i]
                docs[i] = _Doc(d.filing, re.sub(r"\.[A-Za-z]{2,5}$", "", d.path) + ".pdf", pdf)
    return docs


def _one_line(s: Optional[str]) -> str:
    return " ".join(str(s or "").split())


def sources_md(data: TearSheetData, docs: Optional[list[_Doc]] = None,
               skipped: Optional[list[tuple[FilingExcerpt, str]]] = None, tried: bool = False) -> str:
    """Plain list of every source and filing link."""
    p = data.profile
    out = [f"# Sources: {p.name} ({p.ticker})", "",
           f"InvestSync Research Tools source data pack. Market data as of {data.quote.as_of.isoformat()}; report "
           f"generated {_clean(data.generated_at):%Y-%m-%d %H:%M} UTC.", ""]

    def block(title: str, lines: list[str]) -> None:
        if lines:
            out.extend([f"## {title}", "", *lines, ""])

    block("How to use this pack (the files an analyst works from)", [
        "1. Start with the company's own documents (\"Latest company reports\" below and, if included, the "
        "`filings/` folder): the annual report explains the business, its risks and the accounts; the latest "
        "quarterly or interim report and the results release give the newest figures and management's guidance.",
        "2. Check any claim in the report: each [R#] note under \"Research evidence\" gives the exact words and the "
        "document they come from. Open the document and search for the quote to read it in context.",
        f"3. Rebuild the numbers: `{_safe(data)}_data.xlsx` holds the statements, ratios, the valuation workings and "
        f"the peer table (start with its README sheet). In its {MODEL_SHEET} sheet, change an assumption and see "
        "how far the value moves.",
        "4. Read third-party views critically: broker research and news are opinions, linked below with their "
        "dates. Check how old each one is and what it assumes."])

    block("Numbered citations (as in the PDF)", [
        f"{c.n}. {_one_line(c.what)}: {_one_line(c.publisher)}, via {_one_line(c.via)}. {c.url}"
        + (f" (retrieved {_clean(c.retrieved):%Y-%m-%d %H:%M} UTC)" if c.retrieved else "") for c in data.citations])
    block("Data sources", [f"- {_one_line(x)}" for x in data.sources])
    block("Latest company reports (filings)", [
        f"- {f.source}: {_one_line(f.title)}" + (f", filed {f.filed.isoformat()}" if f.filed else "") + f". {f.url}"
        for f in data.filings])
    block("Official announcements (last 90 days)", [
        f"- {a.on.isoformat()} · {a.source} · {_one_line(a.kind)}: {_one_line(a.title)}. {a.url}"
        for a in data.announcements])
    seen, broker = set(), []
    for n in (data.street.notes + data.street.writeups) if data.street else []:
        if n.url and n.url not in seen:
            seen.add(n.url)
            broker.append(f"- {n.on.isoformat()} · {n.broker}: {_one_line(n.title or n.rating_original or n.source)}."
                          f" {n.url}")
    from .data.company_docs import investor_site_note, shareholder_documents
    block("Shareholder documents (filed with the regulator)", [
        f"- {_one_line(f.title)}. {f.url}" for f in shareholder_documents(data)])
    note = investor_site_note(data)
    block("Company investor pages", [note] if note else [])
    block("Broker research links", broker)
    files = {d.filing.url: d.path for d in docs or []}
    rs = data.research.facts if data.research else []
    block("Research evidence (the [R#] notes cited in the report)", [
        f"- {f.id} ({f.published.isoformat() + ', ' if f.published else ''}{_one_line(f.source)}"
        f"{', ' + f.kind.replace('_', ' ') if f.kind else ''}): {_one_line(f.text)} Exact words: "
        f"\"{_one_line(f.quote)}\" Document: {_one_line(f.title)}."
        + (f" {f.url}" if f.url else "") + (f" (in this pack: {files[f.url]})" if f.url in files else "")
        for f in rs])
    block("News", [(f"- {_clean(n.published):%Y-%m-%d} · " if n.published else "- ") +
                   f"{_one_line(n.source) or 'news'}: {_one_line(n.headline_en or n.title)}. {n.url}"
                   for n in data.news if n.url])
    if tried and not data.filings and not research_documents(data):
        block("Documents in this pack", ["- none: the report read no filings or official documents (turned off or "
                                         "unavailable)"])
    elif tried:
        block("Documents in this pack", [f"- {d.path} (from {d.filing.url}"
                                         + (", printed to PDF from the web page" if d.path.endswith(".pdf")
                                            and not d.filing.url.lower().endswith(".pdf") else "") + ")"
                                         for d in docs or []]
              or ["- none"])
        block("Filings not downloaded", [f"- {_one_line(f.title)}: {f.url} ({why})" for f, why in skipped or []]
              or ["- none (all downloaded)"])
    out.extend(["---", "", DISCLAIMER, ""])
    return "\n".join(out)


def build_datapack(data: TearSheetData, include_filing_docs: bool = False, sources_format: str = "pdf") -> bytes:
    """ZIP bytes: <TICKER>_data.xlsx, sources.pdf (sources.md with ``sources_format="md"``), data.json and, if
    asked, filings/ (the original documents)."""
    from .data.company_docs import shareholder_documents
    docs, skipped = (download_filings(data.filings + research_documents(data) + shareholder_documents(data))
                     if include_filing_docs else ([], []))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{_safe(data)}_data.xlsx", workbook(data, {d.filing.url: d.path for d in docs}))
        text = sources_md(data, docs, skipped, include_filing_docs)
        pdf = None
        if sources_format == "pdf":
            try:  # students open a PDF; the text version is the fallback if Typst fails
                from .render.sources_pdf import sources_pdf
                pdf = sources_pdf(text, f"Sources: {data.profile.name} ({data.profile.ticker})")
            except Exception as e:
                log.warning("sources.pdf failed (%s); writing sources.md", type(e).__name__)
        if pdf:
            z.writestr("sources.pdf", pdf, compress_type=zipfile.ZIP_STORED)
        else:
            z.writestr("sources.md", text)
        z.writestr("data.json", data.model_dump_json(indent=2))
        for d in docs:  # PDFs are compressed already
            z.writestr(d.path, d.content, compress_type=zipfile.ZIP_STORED if d.path.lower().endswith(".pdf")
                       else zipfile.ZIP_DEFLATED)
    return buf.getvalue()
