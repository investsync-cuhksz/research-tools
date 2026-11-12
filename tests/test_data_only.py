"""The data-only edition (12 Nov 2026): no AI call, no AI text, no rating; "Your analysis" boxes to write in.
Offline: no network, no AI model."""
import io
import json
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from investsync import pipeline
from investsync.render import dataonly, report_vm, viewmodel
from investsync.render.render import count_pages, render_pdf
from investsync.schema import Bullet, Narrative, TearSheetData

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
RUN2 = ROOT / "fixtures" / "runs" / "run2_NVDA_simple.json"

# words that would mean AI text, an unfinished AI section or a verdict of ours in the data-only edition
FORBIDDEN = re.compile(r"AI RATING|AI rating|Our fair value|Fair value \(|InvestSync model|AI section|\bpending\b|"
                       r"Commentary not generated|once it is configured|Why this rating|OVERALL VIEW|STREET VIEW ·|"
                       r"AI-condensed|our forecast implies")


def load(name: str) -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def ai_data() -> TearSheetData:
    """A report with every AI part and a verdict: rating (Buy, from scenarios), AI forecast and scenarios, written
    sections, AI news tags and AI-written peer reasons."""
    d = load("NVDA_deep.json")
    d.narrative = Narrative(status="generated", model="test-model", dupont_commentary="Margins drive returns.",
                            comps_commentary="Cheaper than peers on forward earnings.",
                            catalysts=[Bullet(title="Results", text="Quarterly results are due.")],
                            risks=[Bullet(title="Demand", text="Spending could slow.")],
                            tagline="Growth holds, with limited upside", thesis="We think growth mostly holds.",
                            valuation_overview="The DCF says the stock is cheap.", rating_rationale="Buy because.")
    for n in d.news[:3]:
        n.headline_en, n.category, n.sentiment, n.relevant = "AI headline", "earnings", "positive", True
    d.comps.method = ("Peers with the same business model (selected with AI assistance). Why each: AMD (AMD): an "
                      "AI-written reason; AVGO (Broadcom): another. Left out by the code's screens: XYZ (Xyz): too small.")
    d.warnings.append("Commentary step failed: TimeoutError: slow")
    return d


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return " ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages).split())


# ---------------------------------------------------------------- pipeline: no AI call at all
class _Stop(Exception):
    pass


def _stop_after_peers(monkeypatch):
    """build_data up to the peer choice: market data from a stub, then stop (the rest needs the network)."""
    from investsync.data import sec_balance
    from investsync.narrative import peers
    calls = []
    md = SimpleNamespace(comps_target=None, quote=None, financials=None)
    monkeypatch.setattr(pipeline.adapters, "load", lambda t: md)
    monkeypatch.setattr(pipeline.adapters, "curated_peers", lambda canonical: None)
    monkeypatch.setattr(peers, "select", lambda t, m: calls.append(t.canonical))
    monkeypatch.setattr(sec_balance, "apply", lambda t, fin: (_ for _ in ()).throw(_Stop()))
    return calls


def test_build_data_without_ai_peers_never_asks_the_ai(monkeypatch):
    calls = _stop_after_peers(monkeypatch)
    with pytest.raises(_Stop):
        pipeline.build_data("NVDA", with_filings=False, ai_peers=False)
    assert calls == []
    with pytest.raises(_Stop):  # the default still asks (PEER_MODE decides inside peers.select)
        pipeline.build_data("NVDA", with_filings=False)
    assert calls == ["NVDA"]


def _no_ai(monkeypatch):
    """Every way the pipeline reaches an AI model fails the test."""
    import litellm
    from investsync import history
    from investsync.narrative import commentary, peers
    from investsync.research import desk

    def boom(*a, **k):
        raise AssertionError("an AI model was called")
    monkeypatch.setattr(commentary, "generate", boom)
    monkeypatch.setattr(commentary, "make_lm", boom)
    monkeypatch.setattr(commentary, "tag_news", boom)
    monkeypatch.setattr(peers, "select", boom)
    monkeypatch.setattr(desk, "run", boom)
    monkeypatch.setattr(desk, "english_labels", boom)
    monkeypatch.setattr(litellm, "completion", boom)
    monkeypatch.setattr(history, "save", boom)  # no snapshot either: snapshots record the rating


def test_data_only_build_makes_no_ai_call_and_has_no_verdict(monkeypatch):
    _no_ai(monkeypatch)
    seen = {}

    def fake_build_data(ticker, with_filings=True, ai_peers=True):
        seen.update(ticker=ticker, with_filings=with_filings, ai_peers=ai_peers)
        return ai_data()
    monkeypatch.setattr(pipeline, "build_data", fake_build_data)
    d = pipeline.build_tearsheet("NVDA", with_narrative=True, mode="deep", learner=True, with_filings=False,
                                 data_only=True)
    assert seen == {"ticker": "NVDA", "with_filings": False, "ai_peers": False}
    assert d.narrative is None and d.research is None and d.forecast is None and d.ai_usage is None
    assert d.rating is None and d.overall is None and d.since_last is None
    assert d.valuation.scenarios is None and d.valuation.dcf is not None  # the calculation stays
    assert d.football_field is not None and d.comps is not None
    assert not any(n.headline_en or n.category or n.sentiment for n in d.news)
    assert "Why each" not in d.comps.method and "Left out by the code's screens: XYZ." in d.comps.method
    assert not any(c.name.startswith("AI ") for c in d.audit.checks)
    assert not any(w.startswith("Commentary step failed") for w in d.warnings)


def test_data_only_from_saved_data_strips_it_without_a_fetch(monkeypatch):
    _no_ai(monkeypatch)
    monkeypatch.setattr(pipeline, "build_data", lambda *a, **k: pytest.fail("no fetch with base"))
    base = ai_data()
    d = pipeline.build_tearsheet("NVDA", base=base, data_only=True)
    assert d.rating is None and d.narrative is None
    assert base.rating is not None and base.narrative is not None  # the saved data is left as it was


def test_strip_clears_the_brokers_model_comparison():
    if not RUN2.exists():
        pytest.skip("run 2 data not present")
    d = dataonly.strip(TearSheetData.model_validate_json(RUN2.read_text(encoding="utf-8")))
    st = d.street
    assert st.model_fair_value is None and st.synthesis is None
    assert not any("InvestSync model" in f for f in st.findings)
    assert not any(n.summary_en for n in [*st.notes, *st.writeups])
    assert not any("fair value" in c.detail.lower() for a in d.scorecard.areas for c in a.checks if c.passed is not None)


# ---------------------------------------------------------------- view models
def test_view_models_have_no_rating_or_ai_text():
    d = dataonly.strip(ai_data())
    vm = viewmodel.build(d, data_only=True)
    assert vm["data_only"] is True and vm["rating"] is None and vm["narrative"] is None
    assert vm["overall"] is None and vm["debate"] is None
    assert set(vm["ask"]) == {"valuation", "catalysts", "risks"}
    assert "no AI-written text and no rating" in vm["footer"]["disclaimer"]
    assert "calculation" in vm["valuation"]["title"]
    rvm = report_vm.build_report(d, data_only=True)
    assert rvm["data_only"] is True and rvm["summary"]["rating"] is None
    assert "fair_x" not in rvm["summary"]["football"] and rvm["summary"]["football"]["bars"]
    assert rvm["deep"] is None and rvm["pillars"] is None and rvm["forecast"] is None
    assert rvm["analyst_scenarios"] is None and rvm["since_last"] is None and rvm["overall"] is None
    assert rvm["disclosures"]["history"] == [] and rvm["disclosures"]["distribution"] == ""
    ai = rvm["ai"]
    assert ai["status"] == "data_only" and ai["model"] == ""
    for key in [*report_vm.AI_SECTIONS, "catalysts", "risks"]:
        box = ai[key]
        assert box["value"] is None and box["title"] and box["desc"].endswith(("?", ".")), key
        assert box["lines"] >= 3
    method = " ".join(rvm["methodology"])
    assert "no AI-written text and no rating" in method
    assert "AI model only writes" not in method and "Buy-below" not in method and "Overall view" not in method
    text = json.dumps({"page1": vm, "report": rvm}, ensure_ascii=False)
    assert "test-model" not in text and "We think growth" not in text and "AI headline" not in text
    assert not FORBIDDEN.search(text.replace("AI_SECTIONS", "")), FORBIDDEN.search(text)


def test_compact_levels_shorten_the_writing_space():
    d = dataonly.strip(ai_data())
    full = report_vm.build_report(d, data_only=True)["ai"]["thesis"]["lines"]
    short = report_vm.build_report(d, compact=2, data_only=True)["ai"]["thesis"]["lines"]
    assert 3 <= short < full


def test_the_ai_edition_is_unchanged():
    d = ai_data()
    vm = viewmodel.build(d)
    assert vm["data_only"] is False and vm["ask"] is None and vm["rating"]["rating"] == "Buy"
    rvm = report_vm.build_report(d)
    assert rvm["data_only"] is False and rvm["ai"]["status"] == "generated"
    assert rvm["ai"]["catalysts"]["value"] is None  # chapter 9 prints the catalysts list itself


# ---------------------------------------------------------------- PDF
def test_data_only_pdf_renders_without_rating_or_ai_text():
    pdf = render_pdf(ai_data(), layout="data")
    text = _text(pdf)
    assert "DATA EDITION" in text and "YOUR ANALYSIS" in text and "Your investment case".upper() in text
    assert "no AI-written text and no rating" in text
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)
    assert "We think growth" not in text and "AI headline" not in text and "Buy because" not in text
    n = count_pages(pdf)
    assert n is not None and 8 <= n <= 16


def test_data_only_tear_sheet_is_one_page():
    pdf = render_pdf(ai_data(), layout="tearsheet", data_only=True)
    assert count_pages(pdf) == 1
    text = _text(pdf)
    assert "DATA EDITION" in text and "YOUR ANALYSIS" in text and not FORBIDDEN.search(text)


def test_learner_has_no_data_only_edition():
    with pytest.raises(ValueError):
        render_pdf(ai_data(), layout="learner", data_only=True)


def test_run2_data_only_pdf_fits():
    if not RUN2.exists():
        pytest.skip("run 2 data not present")
    pdf = render_pdf(TearSheetData.model_validate_json(RUN2.read_text(encoding="utf-8")), layout="data")
    text = _text(pdf)
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)
    assert count_pages(pdf) <= 16


# ---------------------------------------------------------------- API and CLI
def test_api_data_only_is_cached_apart_and_never_runs_the_ai(monkeypatch, tmp_path):
    monkeypatch.setenv("INVESTSYNC_ARCHIVE_DIR", str(tmp_path / "archive"))  # the PDFs are archived (never in output/)
    from fastapi.testclient import TestClient
    import api.main as main
    from investsync import datapack
    builds = []

    def fake_build(ticker, **kw):
        builds.append(kw)
        d = ai_data()
        return dataonly.strip(d) if kw.get("data_only") else d
    monkeypatch.setattr(main, "build_tearsheet", fake_build)
    monkeypatch.setattr(main, "_store", {})
    monkeypatch.setattr(datapack, "_fetch", lambda url, timeout: b"%PDF-1.7 fake")
    client = TestClient(main.app)
    assert client.get("/v1/tearsheets/NVDA", params={"ai": "false"}).status_code == 200
    r = client.get("/v1/tearsheets/NVDA", params={"ai": "true", "data_only": "true"})
    assert r.status_code == 200 and r.json()["rating"] is None and r.json()["narrative"] is None
    assert len(builds) == 2 and builds[-1] == {"with_filings": True, "data_only": True}
    r = client.get("/v1/tearsheets/NVDA/pdf", params={"layout": "data"})  # same cached data-only build
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'filename="NVDA_data.pdf"' in r.headers["content-disposition"]
    assert "DATA EDITION" in _text(r.content)
    r = client.get("/v1/tearsheets/NVDA/datapack", params={"data_only": "true"})
    assert r.status_code == 200
    pack = zipfile.ZipFile(io.BytesIO(r.content))
    assert json.loads(pack.read("data.json"))["rating"] is None
    assert len(builds) == 2
    assert client.get("/v1/tearsheets/NVDA/pdf", params={"layout": "learner", "data_only": "true"}).status_code == 400
    r = client.get("/v1/tearsheets/NVDA/pdf", params={"ai": "false"})  # the AI-edition cache is untouched
    assert r.status_code == 200 and len(builds) == 2


def test_web_page_offers_the_data_only_card():
    page = (ROOT / "api" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'name="report" value="data"' in page and "Data only" in page
    assert 'p.set("data_only", "true")' in page and '<option value="data">' in page


def test_cli_data_only_from_json(monkeypatch, tmp_path):
    import generate
    seen = []
    monkeypatch.setattr(generate, "render_pdf", lambda data, out, layout="report", data_only=False:
                        seen.append((layout, data_only, data.rating)))
    src = tmp_path / "ai.json"
    src.write_text(ai_data().model_dump_json(), encoding="utf-8")
    pack = tmp_path / "pack.zip"
    assert generate.main(["--from-json", str(src), "--data-only", "--output", str(tmp_path / "x.pdf"),
                          "--datapack", str(pack)]) == 0
    assert seen == [("data", False, None)]
    assert json.loads(zipfile.ZipFile(pack).read("data.json"))["rating"] is None
    assert generate.main(["--from-json", str(src), "--data-only", "--layout", "tearsheet"]) == 0
    assert seen[-1] == ("tearsheet", True, None)
    with pytest.raises(SystemExit):
        generate.main(["--from-json", str(src), "--data-only", "--layout", "learner"])
