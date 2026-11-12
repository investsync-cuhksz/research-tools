"""Source data pack: ZIP contents, workbook numbers vs the payload, gaps, filings download, API and CLI (offline)."""
import io
import re
import zipfile
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

from investsync import datapack
from investsync.schema import FilingExcerpt, InterimPeriod, TTMFigures, TearSheetData

FIX = Path(__file__).resolve().parent.parent / "fixtures"
SHEETS = ["README", "Income statement", "Balance sheet", "Cash flow", "Ratios", "Valuation", "Model (editable)",
          "Peers", "Prices", "Brokers", "Evidence", "Sources"]


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No network and no browser in these tests: no SEC shareholder-document lookup, no PDF printing."""
    from investsync.data import company_docs
    from investsync.render import html_pdf
    monkeypatch.setattr(company_docs, "shareholder_documents", lambda data: [])
    monkeypatch.setattr(html_pdf, "browser", lambda: None)


def unpack(data: TearSheetData, **kw) -> tuple[zipfile.ZipFile, object]:
    kw.setdefault("sources_format", "md")  # the text version, for reading in tests (the default is sources.pdf)
    z = zipfile.ZipFile(io.BytesIO(datapack.build_datapack(data, **kw)))
    safe = data.profile.ticker.replace(".", "_")
    return z, load_workbook(io.BytesIO(z.read(f"{safe}_data.xlsx")))


def find(ws, label: str) -> tuple:
    """Values of the first row whose column A is ``label``."""
    for row in ws.iter_rows(values_only=True):
        if row[0] == label:
            return row
    raise AssertionError(f"no row {label!r} in {ws.title}")


def has(ws, label: str) -> bool:
    return any(row[0] == label for row in ws.iter_rows(values_only=True))


def header(ws) -> list:
    return [c for c in next(ws.iter_rows(min_row=4, max_row=4, values_only=True)) if c is not None]


def text(ws) -> str:
    return "\n".join(str(c) for row in ws.iter_rows(values_only=True) for c in row if c is not None)


def with_interim() -> TearSheetData:
    d = load("0700_HK_full.json")
    f = d.financials
    f.latest = InterimPeriod(
        period_end=date(2026, 9, 30), label="9M 2026", months=9, revenue=600e9, gross_profit=330e9,
        operating_income=200e9, net_income=180e9, operating_cash_flow=250e9, capex=80e9, capex_complete=False,
        prior_revenue=540e9, prior_gross_profit=290e9, prior_operating_income=170e9, prior_net_income=150e9,
        prior_operating_cash_flow=220e9, prior_capex=60e9, quarter_label="Q3 2026", quarter_revenue=210e9,
        quarter_revenue_prior=190e9, quarter_net_income=60e9, cash_and_equivalents=400e9, total_debt=390e9,
        total_equity=1200e9, minority_interest=90e9, revenue_growth=600 / 540 - 1, net_income_growth=0.2,
        gross_margin=0.55, prior_gross_margin=290 / 540, free_cash_flow=170e9, prior_free_cash_flow=160e9,
        net_debt=-10e9)
    f.ttm = TTMFigures(period_end=date(2026, 9, 30), basis="FY2025 + 9M 2026 - 9M 2025", revenue=811.8e9,
                       net_income=254.8e9, operating_cash_flow=333e9, capex=132.9e9, free_cash_flow=200.1e9,
                       fcf_margin=0.2465)
    f.cash_definition = "Cash and cash equivalents plus term deposits over three months."
    f.years[-1].minority_interest = 85e9
    return d


# ---------------------------------------------------------------- contents and numbers
def test_zip_holds_workbook_sources_and_payload():
    d = load("0700_HK_full.json")
    z, wb = unpack(d)
    assert sorted(z.namelist()) == ["0700_HK_data.xlsx", "data.json", "sources.md"]
    assert wb.sheetnames == SHEETS
    assert TearSheetData.model_validate_json(z.read("data.json")) == d
    md = z.read("sources.md").decode()
    assert d.filings[0].url in md and "Interim Report 2026" in md
    assert all(s in md for s in d.sources)
    readme = text(wb["README"])
    assert "This tear sheet is produced automatically" in readme  # the PDF's disclaimer
    assert "FY label = calendar year of the period end" in readme and "RMB (CNY)" in readme
    assert "sampled series, not every trading day" in readme
    for name in SHEETS[1:-1]:
        assert wb[name]["A2"].value.startswith("Sources:"), name   # every sheet names its sources
    assert wb["Income statement"].freeze_panes == "B6"


def test_workbook_numbers_equal_the_payload():
    d = load("0700_HK_full.json")
    _, wb = unpack(d)
    y = d.financials.years[-1]
    inc = wb["Income statement"]
    assert header(inc) == ["RMB mn"] + [f"FY{x.fiscal_year}" for x in d.financials.years[-5:]]
    rev = find(inc, "Revenue")
    assert rev[5] == pytest.approx(y.revenue / 1e6) and rev[1] == pytest.approx(d.financials.years[0].revenue / 1e6)
    assert inc.cell(6, 6).number_format == datapack.MN and isinstance(inc.cell(6, 6).value, (int, float))
    assert find(inc, "  Gross margin (%)")[5] == pytest.approx(y.gross_margin)
    assert "%" in inc.cell(9, 6).number_format
    assert find(wb["Balance sheet"], "Total assets")[5] == pytest.approx(y.total_assets / 1e6)
    assert find(wb["Cash flow"], "Free cash flow")[5] == pytest.approx(y.free_cash_flow / 1e6)
    assert find(wb["Ratios"], "ROE")[5] == pytest.approx(d.ratios[-1].roe)
    val = wb["Valuation"]
    v = d.valuation
    assert find(val, "WACC")[1] == pytest.approx(v.wacc.wacc)
    assert find(val, "After-tax cost of debt")[1] == pytest.approx(v.wacc.pre_tax_cost_of_debt * (1 - v.wacc.tax_rate))
    assert find(val, "= Value per share")[1] == pytest.approx(v.dcf.bridge.value_per_share)
    assert find(val, "Present value (RMB mn)")[1] == pytest.approx(v.dcf.forecast[0].present_value / 1e6)
    g = v.sensitivity.discount_growth
    assert find(val, g.rows[0])[1:6] == pytest.approx(tuple(g.values[0]))
    peers = wb["Peers"]
    assert find(peers, "Target")[5] == pytest.approx(d.comps.target.pe_ttm)
    assert sum(1 for r in peers.iter_rows(values_only=True) if r[0] == "Peer") == len(d.comps.peers)
    prices = wb["Prices"]
    assert prices["D5"].value == "Date" and prices["E5"].value == "Close"   # after the snapshot block (A-B)
    assert prices["D6"].value.date() == d.technicals.chart[0].d and prices["E6"].value == d.technicals.chart[0].close
    for ws in wb.worksheets:  # no formulas (outside the model sheet), no numbers stored as text
        for row in ws.iter_rows():
            if ws.title == datapack.MODEL_SHEET:
                break
            for c in row:
                assert c.data_type != "f", (ws.title, c.coordinate)
                if isinstance(c.value, str) and c.number_format not in ("General", "@"):
                    assert not c.value.replace(",", "").replace(".", "").lstrip("-").isdigit(), c.coordinate


def test_bank_payload_leaves_out_missing_rows_and_cash_flow_ratios():
    d = load("0005_HK.json")
    _, wb = unpack(d)
    inc, ratios, val = wb["Income statement"], wb["Ratios"], wb["Valuation"]
    assert not has(inc, "Gross profit") and has(inc, "Net profit to shareholders")
    assert not has(ratios, "FCF margin") and not has(ratios, "Current ratio") and has(ratios, "ROE")
    wacc = find(val, "WACC")
    assert wacc[1] is None and "banks" in wacc[2]
    assert find(val, "Value per share (HKD)")[1] == pytest.approx(d.valuation.ddm.value_per_share)
    assert not has(val, "FX: USD per 1 USD")
    assert "Banks and insurers" in text(wb["README"])


def test_interim_ttm_and_minority_interest_columns():
    d = with_interim()
    _, wb = unpack(d)
    inc = wb["Income statement"]
    assert header(inc)[-5:] == ["9M 2026", "9M 2025", "Q3 2026", "Q3 2025", "TTM"]
    assert find(inc, "Revenue")[-5:] == pytest.approx((600e3, 540e3, 210e3, 190e3, 811.8e3))
    ni = find(inc, "Net profit to shareholders")[-5:]
    assert ni[:3] == pytest.approx((180e3, 150e3, 60e3)) and ni[3] is None and ni[4] == pytest.approx(254.8e3)
    bal = wb["Balance sheet"]
    assert header(bal)[-1] == "9M 2026"
    assert find(bal, "Minority interest (non-controlling)")[-2:] == pytest.approx((85e3, 90e3))
    assert "term deposits over three months" in text(bal)
    cf = wb["Cash flow"]
    assert header(cf)[-3:] == ["9M 2026", "9M 2025", "TTM"]
    assert find(cf, "Capital expenditure")[-3:] == pytest.approx((80e3, 60e3, 132.9e3))
    assert "capex and free cash flow are incomplete" in text(cf)
    ratios = wb["Ratios"]
    op = find(ratios, "Operating margin")
    assert op[6:8] == pytest.approx((200 / 600, 170 / 540)) and "computed here" in op[-1]
    assert find(ratios, "Gross margin")[-1] is None   # payload value, no note
    assert find(ratios, "FCF margin")[8] == pytest.approx(0.2465)
    assert find(ratios, "Net profit growth")[6] == pytest.approx(0.2)
    readme = text(wb["README"])
    assert "9M 2026: 9 months to 2026-09-30" in readme and "FY2025 + 9M 2026 - 9M 2025" in readme
    assert "term deposits over three months" in readme


def test_gaps_never_become_zero_and_text_is_never_a_formula():
    d = load("NVDA.json")  # schema 1.0: no ratios, valuation, citations or technicals
    d.financials.years[2].revenue = None
    d.comps = None
    d.benchmark = None
    d.filings = [FilingExcerpt(source="SEC EDGAR", title="=HYPERLINK(\"http://x\")", url="https://www.sec.gov/x.htm",
                               sections={})]
    z, wb = unpack(d)
    assert wb.sheetnames == SHEETS
    assert find(wb["Income statement"], "Revenue")[3] is None
    assert "No peer comparison" in text(wb["Peers"]) and "No DCF / DDM valuation" in text(wb["Valuation"])
    assert "holds no price series" in text(wb["README"])
    assert "No broker research" in text(wb["Brokers"])
    cell = next(c for row in wb["Sources"].iter_rows() for c in row if c.value == d.filings[0].title)
    assert cell.data_type == "s"
    assert "SEC EDGAR" in z.read("sources.md").decode()


# ---------------------------------------------------------------- filings
def test_filing_documents_downloaded_in_parallel_and_failures_listed(monkeypatch):
    d = load("0700_HK_full.json")
    ok = d.filings[0]
    bad = FilingExcerpt(source="CNINFO", title="2025年年度报告", filed=date(2026, 3, 30),
                        url="http://static.cninfo.com.cn/finalpage/2026-03-30/1.PDF", sections={})
    d.filings = [ok, bad]
    calls = []

    def fake(url, timeout):
        calls.append((url, timeout))
        if "cninfo" in url:
            raise TimeoutError("not finished after 300 s")
        return b"%PDF-1.7 fake"
    monkeypatch.setattr(datapack, "_fetch", fake)
    z, _ = unpack(d, include_filing_docs=True)
    docs = [n for n in z.namelist() if n.startswith("filings/")]
    assert docs == ["filings/01_HKEXnews_2026-08-25_2026082500556.pdf"]
    assert z.read(docs[0]) == b"%PDF-1.7 fake"
    md = z.read("sources.md").decode()
    assert "Filings not downloaded" in md and bad.url in md and "TimeoutError" in md
    assert {u for u, _ in calls} == {ok.url, bad.url} and all(t >= 60 for _, t in calls)


def test_fetch_sends_the_sec_user_agent_only_to_the_sec(monkeypatch):
    import requests
    from investsync.data.filings import SEC_HEADERS
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b"abc"
            yield b"def"

    def fake_get(url, headers=None, timeout=None, stream=False):
        seen[url] = headers
        assert stream and timeout
        return Resp()
    monkeypatch.setattr(requests, "get", fake_get)
    assert datapack._fetch("https://www.sec.gov/Archives/x.htm", 5) == b"abcdef"
    assert datapack._fetch("https://www1.hkexnews.hk/x.pdf", 5) == b"abcdef"
    assert seen["https://www.sec.gov/Archives/x.htm"] == SEC_HEADERS
    assert seen["https://www1.hkexnews.hk/x.pdf"] == {}


# ---------------------------------------------------------------- API and CLI
def test_api_datapack_reuses_the_cached_report(monkeypatch):
    from fastapi.testclient import TestClient
    import api.main as main
    builds = []

    def fake_build(ticker, **kw):
        builds.append((ticker, kw))
        return load("0700_HK_full.json")
    monkeypatch.setattr(main, "build_tearsheet", fake_build)
    monkeypatch.setattr(main, "_store", {})
    monkeypatch.setattr(datapack, "_fetch", lambda url, timeout: b"%PDF-1.7 fake")
    client = TestClient(main.app)
    assert client.get("/v1/tearsheets/0700.HK", params={"ai": "false"}).status_code == 200
    r = client.get("/v1/tearsheets/0700.HK/datapack", params={"ai": "false"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="0700_HK_datapack.zip"'
    assert "0700_HK_data.xlsx" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(builds) == 1  # same cache as the JSON endpoint: no second fetch, no second AI run
    r = client.get("/v1/tearsheets/0700.HK/datapack", params={"ai": "false", "docs": "true"})
    assert any(n.startswith("filings/") for n in zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    client.get("/v1/tearsheets/0700.HK/datapack", params={"ai": "false", "layout": "learner"})
    assert len(builds) == 2 and builds[-1][1]["learner"] is True


def test_cli_writes_datapack_from_json(monkeypatch, tmp_path):
    import generate
    monkeypatch.setattr(generate, "render_pdf", lambda data, out, layout="report": None)
    out = tmp_path / "pack.zip"
    assert generate.main(["--from-json", str(FIX / "0005_HK.json"), "--output", str(tmp_path / "x.pdf"),
                          "--datapack", str(out)]) == 0
    assert "0005_HK_data.xlsx" in zipfile.ZipFile(out).namelist()
    with pytest.raises(SystemExit):
        generate.main(["--from-json", str(FIX / "0005_HK.json"), "--datapack-docs"])


# ---------------------------------------------------------------- research evidence (11 Nov 2026)
def _with_research(d: TearSheetData) -> TearSheetData:
    from investsync.schema import ResearchBrief, ResearchFact
    d.research = ResearchBrief(facts=[
        ResearchFact(id="R1", topic="guidance", text="Management guided revenue up next quarter.",
                     quote="we expect revenue to grow", source="SEC EDGAR", title="Results press release",
                     url="https://www.sec.gov/Archives/edgar/data/1/0001/pr.htm", published=date(2026, 8, 27),
                     kind="results_release"),
        ResearchFact(id="R2", topic="street", text="A broker raised its target.", quote="we raise our target",
                     source="EastMoney research centre: Some Securities", title="Broker note",
                     url="https://pdf.dfcfw.com/pdf/H3_1.pdf", published=date(2026, 9, 1), kind="broker_report"),
        ResearchFact(id="R3", topic="events", text="A news story on a deal.", quote="signed a deal",
                     source="Bing News: Reuters", title="Deal story", url="https://www.reuters.com/x",
                     published=date(2026, 9, 2), kind="news")], gaps=["policy"])
    return d


def test_evidence_sheet_and_sources_md_list_every_research_note():
    d = _with_research(load("0700_HK_full.json"))
    z, wb = unpack(d)
    ev = wb["Evidence"]
    assert ev["A2"].value.startswith("Sources:")
    assert find(ev, "R1")[3] == "we expect revenue to grow" and find(ev, "R3")[7] == "news"
    md = z.read("sources.md").decode()
    assert "How to use this pack" in md and "Research evidence" in md
    assert '"we raise our target"' in md and "https://www.reuters.com/x" in md


def test_official_research_documents_are_downloaded_but_broker_and_news_stay_links(monkeypatch):
    d = _with_research(load("0700_HK_full.json"))
    got = []

    def fake(url, timeout):
        got.append(url)
        return b"<html>doc</html>"
    monkeypatch.setattr(datapack, "_fetch", fake)
    z, wb = unpack(d, include_filing_docs=True)
    assert "https://www.sec.gov/Archives/edgar/data/1/0001/pr.htm" in got
    assert not any("dfcfw" in u or "reuters" in u for u in got)  # third-party: links only
    pr = [n for n in z.namelist() if n.startswith("filings/") and n.endswith("pr.htm")]
    assert len(pr) == 1 and find(wb["Evidence"], "R1")[9] == pr[0]
    assert f"(in this pack: {pr[0]})" in z.read("sources.md").decode()


# ---------------------------------------------------------------- editable model (11 Nov 2026)
from openpyxl.utils import range_boundaries  # noqa: E402

from investsync import datapack_model  # noqa: E402
from investsync.quant import valuation as V  # noqa: E402

MODEL = datapack.MODEL_SHEET
_TOKEN = re.compile(r'\s*(?:(?P<num>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|(?P<str>"[^"]*")|(?P<fn>[A-Z]+)\(|'
                    r'(?P<ref>\$?[A-Z]{1,3}\$?\d+)|(?P<op><=|>=|<>|[-+*/^(),:<>=]))')


class XL:
    """openpyxl does not calculate, and neither LibreOffice nor a Python formula engine is installed here: a tiny
    evaluator for exactly what the model sheet uses (+ - * / ^, comparisons, cell references, ranges, SUM,
    SUMPRODUCT, MIN, MAX, lazy IF), with Excel's precedence and blank cells counted as 0. Anything else fails."""

    def __init__(self, ws):
        self.ws, self.cache = ws, {}

    def __call__(self, coord: str):
        coord = coord.replace("$", "")
        if coord not in self.cache:
            v = self.ws[coord].value
            self.cache[coord] = self.eval(v[1:]) if isinstance(v, str) and v.startswith("=") else v
        return self.cache[coord]

    def eval(self, text: str):
        pos, self.toks, self.i = 0, [], 0
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            assert m and m.end() > pos, f"cannot read {text[pos:]!r}"
            pos = m.end()
            self.toks.append((m.lastgroup, m.group(m.lastgroup)))
        tree = self._binary(0)
        assert self.i == len(self.toks), text
        return self._run(tree)

    LEVELS = [("<", "<=", ">", ">=", "=", "<>"), ("+", "-"), ("*", "/"), ("^",)]

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def _take(self, want=None):
        tok = self.toks[self.i]
        assert want is None or tok[1] == want, (tok, want)
        self.i += 1
        return tok

    def _binary(self, level):
        nxt = (lambda: self._binary(level + 1)) if level + 1 < len(self.LEVELS) else self._unary
        left = nxt()
        while self._peek()[0] == "op" and self._peek()[1] in self.LEVELS[level]:
            left = ("bin", self._take()[1], left, nxt())
        return left

    def _unary(self):   # Excel: unary minus binds tighter than ^
        if self._peek() == ("op", "-"):
            self._take()
            return ("neg", self._unary())
        kind, val = self._take()
        if kind == "num":
            return ("num", float(val))
        if kind == "str":
            return ("str", val[1:-1])
        if kind == "ref":
            if self._peek() == ("op", ":"):
                self._take()
                return ("range", val, self._take()[1])
            return ("ref", val)
        if kind == "fn":
            args = []
            while self._peek() != ("op", ")"):
                args.append(self._binary(0))
                if self._peek() == ("op", ","):
                    self._take()
            self._take(")")
            return ("fn", val, args)
        assert val == "(", val
        inner = self._binary(0)
        self._take(")")
        return inner

    def _run(self, t):
        kind = t[0]
        if kind in ("num", "str"):
            return t[1]
        if kind == "ref":
            v = self(t[1])
            return 0.0 if v is None else v
        if kind == "range":
            c1, r1, c2, r2 = range_boundaries(f"{t[1]}:{t[2]}".replace("$", ""))
            return [0.0 if (v := self(self.ws.cell(r, c).coordinate)) is None else v
                    for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        if kind == "neg":
            return -self._run(t[1])
        if kind == "fn":
            name, args = t[1], t[2]
            if name == "IF":
                return self._run(args[1] if self._run(args[0]) else args[2])
            vals = [self._run(a) for a in args]
            flat = [x for v in vals for x in (v if isinstance(v, list) else [v])]
            if name == "SUMPRODUCT":
                assert len(vals) == 2 and len(vals[0]) == len(vals[1])
                return sum(a * b for a, b in zip(*vals))
            return {"SUM": sum, "MIN": min, "MAX": max}[name](flat)
        op, a, b = t[1], self._run(t[2]), self._run(t[3])
        return {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b, "^": lambda: a ** b,
                "<": lambda: a < b, "<=": lambda: a <= b, ">": lambda: a > b, ">=": lambda: a >= b,
                "=": lambda: a == b, "<>": lambda: a != b}[op]()


def test_evaluator_follows_excel():
    from openpyxl import Workbook
    ws = Workbook().active
    ws["A1"], ws["A2"], ws["A3"] = 2, 3, None
    xl = XL(ws)
    assert xl.eval("-A1^2") == 4 and xl.eval("2+3*A1^2") == 14 and xl.eval("1/(1+A1)^A1") == pytest.approx(1 / 9)
    assert xl.eval("SUMPRODUCT(A1:A2,A1:A2)/SUM(A1:A3)") == pytest.approx(13 / 5)
    assert xl.eval('IF(A1-A1<1,"n/a",1/(A1-A1))') == "n/a" and xl.eval("MIN(MAX(A1,5),4)") == 4


def model(d: TearSheetData):
    _, wb = unpack(d)
    ws = wb[MODEL]
    return ws, XL(ws)


def cell(ws, label: str, col: int = 2):
    for row in ws.iter_rows():
        if row[0].value == label:
            return ws.cell(row[0].row, col)
    raise AssertionError(f"no row {label!r} in the model sheet")


def is_input(c) -> bool:
    return c.fill.fgColor.rgb.endswith("FFF2CC") and c.comment is not None and "Change me" in c.comment.text


def grid(ws, xl, prefix: str) -> list[list]:
    top = next(r[0].row for r in ws.iter_rows() if isinstance(r[0].value, str) and r[0].value.startswith(prefix))
    return [[xl(ws.cell(top + 1 + i, 2 + j).coordinate) for j in range(5)] for i in range(5)]


def test_model_sheet_follows_valuation_and_the_readme_describes_it():
    _, wb = unpack(load("0700_HK_full.json"))
    assert wb.sheetnames.index(MODEL) == wb.sheetnames.index("Valuation") + 1
    readme = text(wb["README"])
    assert f"{MODEL}: The report's valuation as a live Excel model" in readme
    assert "Nothing new is modelled" not in readme and f"The {MODEL} sheet is the one place that calculates" in readme
    assert wb.calculation.fullCalcOnLoad


def test_model_inputs_are_the_reports_and_marked_change_me():
    d = load("0700_HK_full.json")
    ws, _ = model(d)
    v, q = d.valuation, d.quote
    w, dcf = v.wacc, v.dcf
    expect = {"Risk-free rate": w.risk_free, "Beta": w.beta, "Equity risk premium": w.equity_risk_premium,
              "Pre-tax cost of debt": w.pre_tax_cost_of_debt, "Tax rate": w.tax_rate, "Debt weight": w.debt_weight,
              "Terminal growth (per year, forever)": dcf.terminal_growth,
              "Revenue in FY2025, the last reported year (RMB mn)": d.financials.years[-1].revenue / 1e6,
              "- Net debt (RMB mn; negative = net cash)": dcf.bridge.net_debt / 1e6,
              "/ Shares (millions)": dcf.bridge.shares / 1e6, "/ FX: RMB per 1 HKD": q.fx_to_reporting,
              "Share price (HKD)": q.price}
    for label, val in expect.items():
        c = cell(ws, label)
        assert c.value == pytest.approx(val) and is_input(c), label
    for label, vals in (("Revenue growth", [f.growth for f in dcf.forecast]),
                        ("FCF margin", [dcf.fcf_margin] * len(dcf.forecast))):
        cells = [cell(ws, label, 2 + i) for i in range(len(vals))]
        assert [c.value for c in cells] == pytest.approx(vals) and all(is_input(c) for c in cells), label
    for label in ("= Cost of equity", "= WACC", "= Value per share (HKD)", "= Upside (+) / downside (-)"):
        assert cell(ws, label).data_type == "f" and not is_input(cell(ws, label)), label
    assert ws.freeze_panes and int(ws.freeze_panes[1:]) < cell(ws, "Risk-free rate").row   # result stays in view


@pytest.mark.parametrize("name", ["NVDA_deep.json", "0700_HK_full.json"])
def test_model_formulas_reproduce_the_reports_dcf(name):
    d = load(name)
    ws, xl = model(d)
    v, q = d.valuation, d.quote
    dcf, b = v.dcf, v.dcf.bridge
    cur, rc = q.currency, {"CNY": "RMB"}.get(d.financials.currency, d.financials.currency)
    vps = cell(ws, f"= Value per share ({cur})").coordinate
    assert xl(vps) == pytest.approx(dcf.value_per_share, rel=1e-9)            # well within the 0.5% asked
    assert xl(cell(ws, "= WACC").coordinate) == pytest.approx(v.wacc.wacc, rel=1e-9)
    assert xl(cell(ws, "= Cost of equity").coordinate) == pytest.approx(v.wacc.cost_of_equity, rel=1e-9)
    assert xl(cell(ws, f"= Enterprise value ({rc} mn)").coordinate) == pytest.approx(dcf.enterprise_value / 1e6)
    assert xl(cell(ws, f"= Equity value ({rc} mn)").coordinate) == pytest.approx(dcf.equity_value / 1e6)
    assert xl(cell(ws, "= Upside (+) / downside (-)").coordinate) == pytest.approx(dcf.upside, rel=1e-9)
    assert xl(cell(ws, "Your value vs the report's").coordinate) == pytest.approx(0, abs=1e-12)
    n = len(dcf.forecast)
    counted = [xl(cell(ws, "Cash flow counted", 2 + i).coordinate) for i in range(n)]
    assert counted == pytest.approx([f.free_cash_flow / 1e6 for f in dcf.forecast])
    roll = xl(cell(ws, "x Carried forward to the price date: (1 + WACC)^years").coordinate)
    pv_tv = xl(cell(ws, f"Present value of the terminal value ({rc} mn)").coordinate)
    assert pv_tv * roll == pytest.approx(b.pv_terminal / 1e6)
    g = grid(ws, xl, "WACC (down)")
    assert g[2][2] == pytest.approx(dcf.value_per_share, rel=1e-9)
    sens = v.sensitivity.discount_growth
    if sens.rows[2] == v.wacc.wacc:      # this payload's grid is centred on the exact WACC: every cell agrees
        for mine, theirs in zip(g, sens.values):
            assert [None if x == "n/a" else x for x in mine] == pytest.approx(theirs, rel=1e-9)

    # live: change inputs and the value follows the report's own DCF function
    path = dcf.margin_path or [dcf.fcf_margin] * n
    claims = b.net_debt + (b.minority_interest or 0) - (b.investments or 0)
    stub = dcf.stub_years or 1.0
    ws[cell(ws, "Terminal growth (per year, forever)").coordinate] = 0.03
    growth = [f.growth for f in dcf.forecast]
    growth[0] += 0.10
    ws[cell(ws, "Revenue growth").coordinate] = growth[0]
    revs, r = [], d.financials.years[-1].revenue
    for x in growth:
        r *= 1 + x
        revs.append(r)
    cs = V.stub_cash_share(d, revs[0], stub) if dcf.stub_cash_share is not None else stub
    want = V._dcf_value(revs, path, v.wacc.wacc, 0.03, claims, b.fx_to_reporting, b.shares, 0.005, stub,
                        b.roll_forward_years or 0.0, cs)[2]
    xl = XL(ws)
    assert xl(vps) == pytest.approx(want, rel=1e-9) and abs(want / dcf.value_per_share - 1) > 0.01


def test_model_scenarios_and_rating_are_live():
    d = load("NVDA_deep.json")
    ws, xl = model(d)
    sc, rt = d.valuation.scenarios, d.rating
    for sn in sc.scenarios:
        p = cell(ws, sn.name.title())
        assert p.value == pytest.approx(sn.probability) and is_input(p)
        assert xl(cell(ws, sn.name.title(), 7).coordinate) == pytest.approx(sn.value_per_share, rel=1e-9)
        assert cell(ws, sn.name.title(), 9).value == sn.drivers
    wv = cell(ws, "= Probability-weighted value (USD)").coordinate
    assert xl(wv) == pytest.approx(sc.weighted_value, rel=1e-9)
    assert cell(ws, "The AI rating's fair value, as in the report (USD)").value == pytest.approx(rt.fair_value)
    assert xl(cell(ws, "= Fair value with your inputs (USD)").coordinate) == pytest.approx(rt.fair_value, rel=1e-9)
    live = cell(ws, "= Rating by the rule, with your inputs").coordinate
    assert xl(live) == rt.rating == "Buy"
    # the student makes the bear case likelier: the weighted value falls and the rule says Hold
    ws[cell(ws, "Bear").coordinate] = 0.5
    probs = {"bear": 0.5, "base": 0.55, "bull": 0.25}
    want = sum(probs[s.name] * s.value_per_share for s in sc.scenarios) / sum(probs.values())
    xl = XL(ws)
    assert xl(wv) == pytest.approx(want, rel=1e-9)
    assert xl(live) == ("Buy" if want / d.quote.price - 1 >= rt.buy_threshold else "Hold") == "Hold"
    # a higher WACC moves every scenario, as in the report's own scenario code
    ws = model(d)[0]
    ws[cell(ws, "Risk-free rate").coordinate] = d.valuation.wacc.risk_free + 0.01
    xl = XL(ws)
    assert all(xl(cell(ws, s.name.title(), 7).coordinate) < s.value_per_share - 1 for s in sc.scenarios)


def test_bank_model_uses_the_dividend_discount_model():
    d = load("0005_HK.json")
    ws, xl = model(d)
    v = d.valuation
    assert V.is_financial(d) and not any(r[0].value == "= WACC" for r in ws.iter_rows())
    assert xl(cell(ws, "= Cost of equity").coordinate) == pytest.approx(v.wacc.cost_of_equity, rel=1e-9)
    dps = cell(ws, "Dividend per share, last 12 months (HKD)")
    assert dps.value == pytest.approx(v.ddm.dividend_per_share) and is_input(dps)
    assert xl(cell(ws, "= Value per share (HKD)").coordinate) == pytest.approx(v.ddm.value_per_share, rel=1e-9)
    ke, g, gap = v.wacc.cost_of_equity, v.ddm.growth, 0.03
    want = [[None if k - gg < gap else v.ddm.dividend_per_share * (1 + gg) / (k - gg)
             for gg in (g + s for s in (-0.01, -0.005, 0, 0.005, 0.01))]
            for k in (ke + s for s in (-0.01, -0.005, 0, 0.005, 0.01))]
    mine = [[None if x == "n/a" else x for x in row] for row in grid(ws, xl, "Cost of equity (down)")]
    assert mine == [pytest.approx(row, rel=1e-9) for row in want]
    assert "Banks and insurers are valued on the dividends" in text(ws)


def test_model_says_so_when_it_cannot_rebuild_the_value():
    ws, _ = model(load("NVDA.json"))            # schema 1.0: no valuation at all
    assert "No DCF / DDM valuation in this payload" in text(ws)
    d = load("0700_HK_full.json")
    d.valuation.dcf = None
    d.valuation.notes = ["DCF not shown: free cash flow has been negative."]
    ws, xl = model(d)
    assert "no value per share to rebuild" in text(ws) and "DCF not shown: free cash flow" in text(ws)
    assert xl(cell(ws, "= WACC").coordinate) == pytest.approx(d.valuation.wacc.wacc, rel=1e-9)
    d = load("NVDA_deep.json")
    d.valuation.scenarios.scenarios[1].value_per_share *= 1.05   # a scenario method this sheet cannot repeat
    ws, xl = model(d)
    assert xl(cell(ws, "= Value per share (USD)").coordinate) == pytest.approx(d.valuation.dcf.value_per_share)
    base = cell(ws, "Base", 7)
    assert base.data_type == "n" and base.value == pytest.approx(d.valuation.scenarios.scenarios[1].value_per_share)
    assert "cannot be rebuilt exactly" in text(ws)
    d.valuation.dcf.value_per_share *= 1.05                       # a DCF made with an older method
    ws, xl = model(d)
    assert "earlier version of the method" in text(ws)
    assert xl(cell(ws, "Your value vs the report's").coordinate) == pytest.approx(1 / 1.05 - 1)


def test_model_never_writes_payload_text_as_a_formula():
    d = load("NVDA_deep.json")
    evil = '=HYPERLINK("http://x.example","click")'
    d.valuation.scenarios.scenarios[0].drivers = evil
    d.valuation.scenarios.note = evil
    d.valuation.notes = [evil]
    d.valuation.wacc.risk_free_source = evil
    d.valuation.dcf.margin_basis = evil
    d.rating.methods[2].note = evil
    d.rating.methods[3].label = evil
    ws, xl = model(d)
    allowed = re.compile(r'=(?:\$?[A-Z]{1,3}\$?\d+|\d+(?:\.\d+)?|(?:SUMPRODUCT|SUM|MIN|MAX|IF)\(|"[^"]*"|'
                         r'[-+*/^(),:<>=])+')
    texts = 0
    for row in ws.iter_rows():
        for c in row:
            if c.data_type == "f":
                assert allowed.fullmatch(c.value), (c.coordinate, c.value)
                assert set(re.findall(r'"([^"]*)"', c.value)) <= set(datapack_model.WORDS), c.coordinate
            elif isinstance(c.value, str) and "HYPERLINK" in c.value:
                assert c.data_type == "s"
                texts += 1
    assert texts >= 6
    assert xl(cell(ws, "= Value per share (USD)").coordinate) == pytest.approx(d.valuation.dcf.value_per_share)


# ---------------------------------------------------------------- PDFs for students (11 Nov 2026)
def test_default_pack_has_sources_pdf_not_markdown():
    import shutil
    import subprocess
    d = load("0700_HK_full.json")
    z = zipfile.ZipFile(io.BytesIO(datapack.build_datapack(d)))
    names = z.namelist()
    assert "sources.pdf" in names and "sources.md" not in names
    pdf = z.read("sources.pdf")
    assert pdf.startswith(b"%PDF")
    if shutil.which("pdftotext"):
        txt = subprocess.run(["pdftotext", "-", "-"], input=pdf, capture_output=True).stdout.decode()
        assert "How to use this pack" in txt and d.filings[0].url[:40] in txt.replace("\n", "")


def test_web_page_filings_are_printed_to_pdf_and_shareholder_documents_added(monkeypatch):
    from investsync.data import company_docs
    from investsync.render import html_pdf
    d = load("0700_HK_full.json")
    d.filings = [FilingExcerpt(source="SEC EDGAR", title="10-Q filed 2026-08-26", filed=date(2026, 8, 26),
                               url="https://www.sec.gov/Archives/edgar/data/1/2/q.htm", sections={})]
    ars = FilingExcerpt(source="SEC EDGAR", title="Annual report to shareholders (PDF) (ARS), filed 2026-05-12",
                        filed=date(2026, 5, 12), url="https://www.sec.gov/Archives/edgar/data/1/3/ar.pdf", sections={})
    monkeypatch.setattr(company_docs, "shareholder_documents", lambda data: [ars])
    monkeypatch.setattr(html_pdf, "browser", lambda: "/fake/chrome")
    monkeypatch.setattr(html_pdf, "html_to_pdf", lambda content, url, fetch, timeout=180: b"%PDF-1.7 printed")
    monkeypatch.setattr(datapack, "_fetch", lambda url, timeout: b"%PDF-1.7 ars" if url.endswith(".pdf")
                        else b"<html><body>10-Q</body></html>")
    z, _ = unpack(d, include_filing_docs=True)
    names = [n for n in z.namelist() if n.startswith("filings/")]
    assert any(n.endswith("q.pdf") for n in names) and not any(n.endswith(".htm") for n in names)
    assert any(n.endswith("ar.pdf") for n in names)
    md = z.read("sources.md").decode()
    assert "printed to PDF from the web page" in md and "Shareholder documents" in md and ars.url in md


def test_without_a_browser_the_web_page_is_kept(monkeypatch):
    d = load("0700_HK_full.json")
    d.filings = [FilingExcerpt(source="SEC EDGAR", title="10-K", filed=date(2026, 2, 25),
                               url="https://www.sec.gov/Archives/edgar/data/1/2/k.htm", sections={})]
    monkeypatch.setattr(datapack, "_fetch", lambda url, timeout: b"<html><body>10-K</body></html>")
    z, _ = unpack(d, include_filing_docs=True)
    assert [n for n in z.namelist() if n.startswith("filings/")] == ["filings/01_SEC_EDGAR_2026-02-25_k.htm"]
