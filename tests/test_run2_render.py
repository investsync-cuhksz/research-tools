"""Run 2, WP4: page fit, the thesis pillars, the deep-only exhibits, labels, TTM dividend yield, news rule,
placeholder guard and safe sections. Offline (no AI, no network)."""
import io
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from investsync.data import adapters
from investsync.narrative import scenarios as scen
from investsync.render import render as R
from investsync.render import report_vm as RV
from investsync.render.render import count_pages, page_limit, render_pdf
from investsync.schema import (Bullet, DebateArgument, DeepAnalysis, Narrative, NewsItem, ResearchBrief,
                               ResearchFact, ReverseDCF, ReviewNote, TearSheetData)

PLACEHOLDER = re.compile(r"AI SECTION|·\s*PENDING|once it is configured", re.I)   # as final_v9/accept.py
ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
RUN1 = ROOT / "fixtures" / "runs" / "run1_NVDA"   # run 1 (final_v8/NVDA), saved as fixtures

# run 1's saved analyst brief (NVDA standard and deep reports, 11 Nov 2026), as the report stores it
RUN1_BRIEF = """ANALYST BRIEF (the lead analyst's view, decided before writing: build the tagline, thesis, risks, valuation and rating text on it; every figure in it is from `facts`, `news` or `filings`):
- Central question: Does FY2028 revenue growth of about 70% hold as customer financing and cash conversion stretch, enough to justify a price that implies only 37.1% growth?
- Our answer: Yes, mostly: Hold at fair value USD 191.54. Q3 is guided to $108.0 billion and supply commitments are $279 billion.
- What the price implies: At USD 168.89 the price implies 37.1% revenue growth a year for 5 years; our base case grows 42.0%.
- Pillar 1: Demand is visible through the guided period and the price discounts less than we forecast. Evidence: 1H FY2027 revenue 177,837mn (+95.8%); Q3 guide $108.0 billion ±2%; commitments $279 billion; reverse DCF implies +37.1% vs our +42.0%.. Breaks if: Q3 results or Q4 guidance miss the $108.0 billion guide, or FY2028 growth falls well below management's ~70% view..
- Pillar 2: Cash conversion and customer financing are the weak link in the quality of growth. Evidence: 1H operating cash flow / net profit 0.63x (0.95x a year earlier); DSO 60 days vs 45; guarantees USD 108.5bn; investment gains 23,707mn.. Breaks if: DSO keeps rising or OpenAI/PORTS-Pike lease payments slip so guarantees are called..
- Pillar 3: CEO and policy overhang justifies Hold despite the cheap multiple. Evidence: Shares are 29.4% below the October record; board probe into Huang; Democrats won both chambers in the midterms and the state data-center moratorium pledges threaten planned capacity.. Breaks if: The probe clears with no business impact and policy risk eases, lifting the bull case odds from 20% to 23%..
- Beyond our forecast years: Bull: the platforms sustain growth. Bear: AI funding turns cautious.
- What to watch: 17 November results."""


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def _flat(pdf: bytes) -> str:
    return " ".join(_text(pdf).split())


def _narrative(**kw) -> Narrative:
    base = dict(status="generated", model="test-model", dupont_commentary="Margins drive returns.",
                comps_commentary="Cheaper than peers on forward earnings.",
                catalysts=[Bullet(title="Results", text="Quarterly results are due.")],
                risks=[Bullet(title="Demand", text="Spending could slow.")],
                tagline="Growth holds, with limited upside",
                thesis="The question is whether growth holds. We think it mostly does.")
    base.update(kw)
    return Narrative(**base)


def _deep() -> DeepAnalysis:
    arg = lambda i, side: DebateArgument(id=f"{side}-{i}", claim=f"{side.title()} claim {i}",  # noqa: E731
                                         reasoning="Because of the evidence.", assumption="It persists",
                                         breaks_if="It stops")
    return DeepAnalysis(bull=[arg(1, "BULL")], bear=[arg(1, "BEAR")], verdict="Balanced on the evidence.",
                        stronger_side="balanced", conviction="medium", swing_factor="Demand.",
                        change_my_mind="A miss.", priced_in="Little growth is priced in.",
                        variant_view="Close to the brokers.", pre_mortem="Demand fell.",
                        review=[ReviewNote(section="thesis", quote="grows 50%", fix="It grows 40%.", resolved=True,
                                           problem="wrong (check 3): the growth figure is the model's")])


def deep_data() -> TearSheetData:
    d = load("NVDA_deep.json")
    d.narrative = _narrative(mode="deep", deep=_deep())
    return d


def simple_data() -> TearSheetData:
    d = load("NVDA_deep.json")
    d.narrative = _narrative()
    return d


# ---------------------------------------------------------------- thesis pillars
def test_pillars_parse_run1_brief():
    p = RV.parse_brief(RUN1_BRIEF)
    assert p is not None and len(p["rows"]) == 3
    assert p["question"].startswith("Does FY2028 revenue growth") and p["question"].endswith("?")
    claim, ev, brk = p["rows"][0]
    assert claim == "Demand is visible through the guided period and the price discounts less than we forecast"
    assert ev.startswith("1H FY2027 revenue") and ev.endswith("vs our +42.0%")   # the brief's ".." is tidied
    assert brk.endswith("~70% view")
    assert p["rows"][2][0].startswith("CEO and policy overhang")


def test_pillars_omitted_when_brief_missing_or_malformed():
    assert RV.parse_brief(None) is None and RV.parse_brief("") is None
    assert RV.parse_brief("- Central question: Why?\n- Pillar 1: Only one. Evidence: a. Breaks if: b.") is None
    assert RV.parse_brief("- Pillar 1: no evidence part\n- Pillar 2: neither") is None


def test_pillars_printed_under_the_thesis_and_unchecked_figures_dropped():
    d = simple_data()
    d.narrative.brief = ("- Central question: Does demand hold?\n"
                         "- Pillar 1: Demand is visible. Evidence: orders and guidance. Breaks if: guidance is cut.\n"
                         "- Pillar 2: Margins hold. Evidence: pricing power and mix. Breaks if: prices fall.\n"
                         "- Pillar 3: An invented figure. Evidence: revenue of 987,654.3mn. Breaks if: never.")
    p = RV.build_report(d)["pillars"]
    assert p["question"] == "Does demand hold?"
    assert [r[0] for r in p["rows"]] == ["Demand is visible", "Margins hold"]   # 987,654.3mn is in no data
    text = _flat(render_pdf(d))
    assert "WHAT OUR VIEW RESTS ON" in text and "The question: Does demand hold?" in text
    assert "What would break it" in text and "invented figure" not in text


def test_pillars_not_printed_for_a_placeholder_narrative():
    d = simple_data()
    d.narrative.status = "placeholder"
    d.narrative.brief = RUN1_BRIEF
    assert RV.build_report(d)["pillars"] is None


# ---------------------------------------------------------------- deep-only exhibits
def _fake_paths(data):
    s = data.valuation.scenarios
    n = len(data.valuation.dcf.forecast)
    return [{"name": x.name, "probability": x.probability, "revenue_growth": (list(x.revenue_growth) + [0.03] * n)[:n],
             "fcf_margin": x.fcf_margin, "pv_explicit": x.value_per_share * 1e9 * 0.4,
             "pv_terminal": x.value_per_share * 1e9 * 0.6, "terminal_share": 0.6,
             "value_per_share": x.value_per_share} for x in s.scenarios]


def _fake_fragility(data, buy=0.15, sell=-0.10):
    bear, bull = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40], [0.10, 0.15, 0.20, 0.25, 0.30]
    cells = [[{"value": 100.0 + 10 * j - 10 * i, "upside": 0.0, "rating": "Buy" if j > i else "Hold"}
              for j in range(len(bull))] for i in range(len(bear))]
    return {"bear": bear, "bull": bull, "cells": cells, "current": [1, 2]}


def test_deep_exhibits_omitted_when_scenarios_functions_are_missing(monkeypatch):
    monkeypatch.delattr(scen, "paths", raising=False)
    monkeypatch.delattr(scen, "fragility", raising=False)
    dp = RV.build_report(deep_data())["deep"]
    assert dp is not None and dp["model"] is None and dp["flip"] is None
    text = _flat(render_pdf(deep_data()))
    assert "INVESTMENT DEBATE" in text.upper() and "SCENARIO MODEL" not in text and "WHERE THE RATING FLIPS" not in text


def test_deep_exhibits_omitted_when_they_fail(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("not merged")
    monkeypatch.setattr(scen, "paths", boom, raising=False)
    monkeypatch.setattr(scen, "fragility", lambda *a, **k: {"bear": [0.2], "bull": [0.1, 0.2], "cells": [[{}]]},
                        raising=False)  # malformed grid
    dp = RV.build_report(deep_data())["deep"]
    assert dp is not None and dp["model"] is None and dp["flip"] is None


def test_deep_exhibits_printed_from_the_scenario_model(monkeypatch):
    monkeypatch.setattr(scen, "paths", _fake_paths, raising=False)
    monkeypatch.setattr(scen, "fragility", _fake_fragility, raising=False)
    d = deep_data()
    dp = RV.build_report(d)["deep"]
    m, f = dp["model"], dp["flip"]
    n = len(d.valuation.dcf.forecast)
    assert len(m["years"]) == n and m["years"][0] == f"FY{d.valuation.dcf.forecast[0].fiscal_year}E"
    assert [r["label"].split(" ")[0] for r in m["growth"]] == ["Bear", "Base", "Bull"]
    assert "mn" in m["head"][3] and m["summary"][0][5] == "60%"
    assert f["cols"] == ["10%", "15%", "20%", "25%", "30%"] and [r["label"] for r in f["rows"]][0] == "15%"
    assert f["rows"][1]["cells"][2]["current"] and sum(c["current"] for r in f["rows"] for c in r["cells"]) == 1
    text = _flat(render_pdf(d))
    assert "SCENARIO MODEL" in text and "WHERE THE RATING FLIPS" in text and "Outlined: today's weights" in text
    # the standard report has no debate chapter, so no deep-only exhibit
    assert "SCENARIO MODEL" not in _flat(render_pdf(simple_data()))


# ---------------------------------------------------------------- labels
def test_review_log_prints_the_problem_without_the_check_number():
    dp = RV.build_report(deep_data())["deep"]
    assert dp["review"][0]["problem"] == "wrong: the growth figure is the model's"


def test_reverse_dcf_headline_names_the_held_consensus_years():
    d = simple_data()
    fc = d.valuation.dcf.forecast
    d.valuation.reverse = ReverseDCF(model="DCF", horizon_years=len(fc) - 2, implied_growth=0.067, model_growth=0.102,
                                     hold_years=2, from_year=fc[2].fiscal_year, to_year=fc[-1].fiscal_year)
    rv = RV.build_report(d)["valuation"]["reverse"]
    assert rv["headline"] == (f"After the 2 consensus years, today's price implies revenue growth of 6.7% a year "
                              f"from FY{fc[2].fiscal_year} to FY{fc[-1].fiscal_year}")
    assert rv["rows"][0][0].startswith(f"Implied revenue growth, FY{fc[2].fiscal_year}–FY{fc[-1].fiscal_year}")
    d.valuation.reverse.hold_years = 0   # old behaviour unchanged
    rv = RV.build_report(d)["valuation"]["reverse"]
    assert rv["headline"].startswith("Today's price implies revenue growth of 6.7% a year for")


def test_comps_footnote_calls_the_margins_trailing():
    text = _flat(render_pdf(simple_data()))
    assert "operating margin = latest quarter" not in text
    assert "Operating margin, gross margin, net margin and ROE: trailing twelve months (Yahoo Finance)" in text


# ---------------------------------------------------------------- placeholder guard
def test_generated_narrative_with_empty_sections_shows_no_pending_box():
    d = simple_data()
    d.narrative.thesis = ""
    d.narrative.catalysts = []
    d.narrative.risks = []
    d.narrative.news_summary = ""
    text = _flat(render_pdf(d))
    assert not PLACEHOLDER.search(text), PLACEHOLDER.search(text)


# ---------------------------------------------------------------- TTM dividend yield
def test_ttm_dividend_yield_from_a_fixed_series():
    idx = pd.to_datetime(["2025-06-11", "2025-09-11", "2025-12-04", "2026-03-11", "2026-06-04", "2026-09-10"]
                         ).tz_localize("America/New_York")
    s = pd.Series([0.01, 0.01, 0.01, 0.01, 0.25, 0.25], index=idx)
    y = adapters.ttm_dividend_yield(s, 168.89, on=date(2026, 11, 11))
    assert y == pytest.approx(0.52 / 168.89) and round(y * 100, 2) == 0.31
    assert adapters.ttm_dividend_yield(None, 168.89) is None
    assert adapters.ttm_dividend_yield(pd.Series(dtype=float), 168.89) is None
    assert adapters.ttm_dividend_yield(s, None) is None


def test_comp_row_falls_back_to_yahoo_field_without_a_series(monkeypatch):
    info = {"longName": "Example Corp", "currentPrice": 100.0, "trailingAnnualDividendYield": 0.002,
            "currency": "USD"}
    monkeypatch.setattr(adapters.src, "yf_info", lambda s: info)
    monkeypatch.setattr(adapters.src, "yf_dividends", lambda s: None)
    assert adapters._yf_comp("EXM", "EXM", "Example").dividend_yield == pytest.approx(0.002)
    recent = pd.Series([0.5, 0.5], index=pd.to_datetime([date.today() - timedelta(days=100),
                                                          date.today() - timedelta(days=10)]))
    monkeypatch.setattr(adapters.src, "yf_dividends", lambda s: recent)
    assert adapters._yf_comp("EXM", "EXM", "Example").dividend_yield == pytest.approx(0.01)


# ---------------------------------------------------------------- news: company news only by headline
def test_news_counts_as_company_news_only_when_the_headline_names_it():
    d = simple_data()
    now = d.generated_at
    name = d.profile.name.split()[0]
    d.news = [NewsItem(published=now - timedelta(days=1), title=f"{name} beats estimates", source="X"),
              NewsItem(published=now - timedelta(days=1), title="Futures rise on chip rally", source="Y",
                       summary=f"{name} and others gained."),
              NewsItem(published=now - timedelta(days=2), title=f"{name} named in a market wrap", source="Z",
                       relevant=False)]
    rows = RV.build_report(d)["news"]["news"]
    own = [r["title"] for r in rows if r["relevant"]]
    assert own == [f"{name} beats estimates"]
    assert any(r["title"] == "Futures rise on chip rally" and not r["relevant"] for r in rows)  # grey filler


# ---------------------------------------------------------------- safe sections
def test_a_failing_optional_section_is_omitted_not_fatal(monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad data")
    for name in ("_research", "_street", "_deep", "_forecast", "_disclosures", "_pillars"):
        monkeypatch.setattr(RV, name, boom)
    d = deep_data()
    rvm = RV.build_report(d)
    assert rvm["research"] == {"rows": [], "gaps": [], "note": ""} and rvm["deep"] is None
    assert rvm["street"] is None and rvm["pillars"] is None and rvm["disclosures"] is None
    assert "debate" not in rvm["num"] and rvm["num"]["overview"] == "2"   # chapter numbers stay consecutive
    assert count_pages(render_pdf(d)) >= 8


# ---------------------------------------------------------------- page fit
def _long_research(d: TearSheetData, n: int = 60) -> TearSheetData:
    long = ("Management said the order book for the next two quarters is fully committed and that supply "
            "constraints, not demand, will set shipments, with pricing held across the product range. ")
    d.research = ResearchBrief(facts=[ResearchFact(id=f"R{i}", topic="guidance", text=long + f"Note {i}.",
                                                   quote="x", source="press", title="t",
                                                   published=date(2026, 11, 1), key="")
                                      for i in range(1, n + 1)], docs_read=10, chunks_read=40)
    d.narrative.thesis += " " + " ".join(f"[R{i}]" for i in range(1, n + 1))   # every note cited
    return d


def test_page_limits_and_override(monkeypatch):
    monkeypatch.delenv("REPORT_MAX_PAGES", raising=False)
    assert page_limit(simple_data(), "report") == 15
    assert page_limit(deep_data(), "report") == 28
    assert page_limit(simple_data(), "learner") == 16
    assert page_limit(simple_data(), "tearsheet") is None
    monkeypatch.setenv("REPORT_MAX_PAGES", "12")
    assert page_limit(deep_data(), "report") == 12
    monkeypatch.setenv("REPORT_MAX_PAGES", "standard=14, deep=26")
    assert page_limit(simple_data(), "report") == 14 and page_limit(deep_data(), "report") == 26
    assert page_limit(simple_data(), "learner") == 16
    monkeypatch.setenv("REPORT_MAX_PAGES", "lots")
    assert page_limit(simple_data(), "report") == 15


def test_compact_levels_shorten_the_long_tables():
    d = _long_research(simple_data())
    full, c1, c2 = (RV.build_report(d, compact=k)["research"]["rows"] for k in (0, 1, 2))
    assert len(full) == 60 and len(c1) == 14 and len(c2) == 8
    assert "Shown: 14 of the notes cited in the text" in RV.build_report(d, compact=1)["research"]["note"]


def test_report_over_its_limit_is_compacted(monkeypatch):
    d = _long_research(simple_data())
    monkeypatch.setenv("REPORT_MAX_PAGES", "99")
    n_full = count_pages(render_pdf(d))
    monkeypatch.setenv("REPORT_MAX_PAGES", str(n_full - 1))
    n_fit = count_pages(render_pdf(d))
    assert n_fit <= n_full - 1


def test_a_failed_page_count_never_blocks_the_pdf(monkeypatch):
    monkeypatch.setattr(R, "count_pages", lambda pdf: None)
    pdf = render_pdf(simple_data())
    assert pdf[:4] == b"%PDF"


@pytest.mark.skipif(not Path(f"{RUN1}_simple.json").exists(), reason="run 1's saved report not present")
def test_run1_standard_report_fits_15_pages(monkeypatch):
    monkeypatch.delenv("REPORT_MAX_PAGES", raising=False)
    d = TearSheetData.model_validate_json(Path(f"{RUN1}_simple.json").read_text(encoding="utf-8"))
    pdf = render_pdf(d)
    assert count_pages(pdf) <= 15
    text = _flat(pdf)
    assert "WHAT OUR VIEW RESTS ON" in text and not PLACEHOLDER.search(text)
