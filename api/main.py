"""REST API for the club website, plus a local test page.

  uvicorn api.main:app --port 8000      then open http://localhost:8000 (test page)
                                        or http://localhost:8000/docs (API docs)

  GET /v1/tearsheets/{ticker}           TearSheetData JSON
  GET /v1/tearsheets/{ticker}/pdf       the PDF: full report (default) or ?layout=tearsheet for page 1 only;
                                        ?layout=data for the data-only edition (no AI call, no AI text, no rating)
  GET /v1/tearsheets/{ticker}/datapack  ZIP: Excel workbook of the numbers, sources.pdf, data.json (?docs=true: original documents)
  (every /v1/tearsheets endpoint takes ?data_only=true: the data-only build, cached apart from the AI builds)
  POST /v1/runs {"ticker": ...}        all three reports in one go (deep, then standard + learner from its data),
                                        a background job; GET /v1/runs/{id} for its progress, GET /v1/runs for recent ones
  GET /v1/archive                      every saved report, newest first; GET /v1/archive/{id}/{file} serves one file
  GET /v1/archive/{id}/pack            its source data pack (ZIP: Excel, sources.pdf, data.json; ?documents=true: + filings)
  GET /archive                         the archive page
  GET /v1/status                       what is configured (models, mode, filings)
  GET /health
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api import jobs
from investsync import archive, tickers
from investsync.config import settings
from investsync.datapack import build_datapack
from investsync.pipeline import build_tearsheet
from investsync.render.render import render_pdf
from investsync.schema import SCHEMA_VERSION, TearSheetData

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="InvestSync Research Tools API",
    version=SCHEMA_VERSION,
    description="Equity research reports (one-page tear sheet + full report) for HK, A-share and US equities.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")],
    expose_headers=["Content-Disposition"],  # lets the website read the data-pack file name
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")  # the test page's logo and icon

_TTL = int(os.getenv("TEARSHEET_TTL_SECONDS", "900"))
Key = tuple[str, bool, str, bool, bool, bool]
_store: dict[Key, tuple[float, TearSheetData]] = {}
_locks: dict[Key, threading.Lock] = {}
_guard = threading.Lock()
Mode = Literal["single", "two_step", "deep"]
Layout = Literal["report", "tearsheet", "learner", "data"]


def _data_only_query():
    return Query(False, description="The data-only edition: no AI call at all (automatic peers, no commentary, "
                                    "research notes, news tags, forecast or scenarios) and no rating; the data and "
                                    "the calculations only. Cached apart from the AI builds.")


def _get_entry(ticker: str, ai: bool, mode: Optional[str], filings: bool, refresh: bool,
               learner: bool = False, data_only: bool = False) -> tuple[Key, float, TearSheetData]:
    """The cached build for this request shape (or a new one): its cache key, when it was built, and the data."""
    # a data-only build ignores ai / mode / learner: one cache entry per (ticker, filings), never shared with AI builds
    key: Key = ((ticker.upper(), False, "data_only", filings, False, True) if data_only else
                (ticker.upper(), ai, mode or settings.narrative_mode, filings, learner, False))
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:  # one build per request shape at a time; others wait for the cached result
        hit = _store.get(key)
        if hit and not refresh and time.time() - hit[0] < _TTL:
            return key, hit[0], hit[1]
        try:
            data = (build_tearsheet(ticker, with_filings=filings, data_only=True) if data_only else
                    build_tearsheet(ticker, with_narrative=ai, mode=mode, with_filings=filings, learner=learner))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e))
        built = time.time()
        _store[key] = (built, data)
        return key, built, data


def _get(ticker: str, ai: bool, mode: Optional[str], filings: bool, refresh: bool,
         learner: bool = False, data_only: bool = False) -> TearSheetData:
    return _get_entry(ticker, ai, mode, filings, refresh, learner, data_only)[2]


# ---------------------------------------------------------------- archive: each build's report saved once
# (cache key, build time, layout) -> archive entry id; a second download of the same build serves the saved PDF
_archived: dict[tuple[Key, float, str], str] = {}
_pdf_locks: dict[tuple[Key, float, str], threading.Lock] = {}


def _kind(data: TearSheetData, layout: str) -> str:
    if layout in ("data", "tearsheet", "learner"):
        return layout
    n = data.narrative
    return "deep" if n is not None and n.mode == "deep" and n.status != "placeholder" else "standard"


def _pdf_once(key: Key, built: float, data: TearSheetData, layout: str, data_only: bool) -> bytes:
    """The PDF of this build in this layout: drawn and archived the first time, then served from the archive."""
    ref = (key, built, layout)
    with _guard:
        lock = _pdf_locks.setdefault(ref, threading.Lock())
    with lock:  # the page's preview and a quick download of one build: drawn and archived once
        return _pdf_locked(ref, data, layout, data_only)


def _pdf_locked(ref: tuple[Key, float, str], data: TearSheetData, layout: str, data_only: bool) -> bytes:
    saved = _archived.get(ref)
    if saved:
        meta = archive.entry(saved)
        pdf = next((f["name"] for f in (meta or {}).get("files", []) if f.get("type") == "pdf"), None)
        path = archive.file_path(saved, pdf) if pdf else None
        if path is not None:
            return path.read_bytes()
    pdf = render_pdf(data, None, layout, data_only)
    if archive.enabled():
        if data_only:
            from investsync.render import dataonly
            data = dataonly.strip(data)  # the archived JSON is what the PDF shows: no AI parts, no rating
        meta = archive.save_report(data, pdf, _kind(data, layout), source="web")
        if meta:
            _archived[ref] = meta["id"]
            # the source pack (Excel, sources.pdf) is built from the saved JSON in the background: no fetch, no AI
            threading.Thread(target=archive.add_pack, args=(meta["id"],), daemon=True).start()
    return pdf


@app.get("/", include_in_schema=False)
def test_page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "schema_version": SCHEMA_VERSION}


@app.get("/v1/status")
def status() -> dict:
    return {
        "primary_model": {"model": settings.llm.model, "configured": settings.llm.enabled},
        "fallback_model": {"model": settings.llm_fallback.model or None, "configured": settings.llm_fallback.enabled},
        "narrative_mode": settings.narrative_mode,
        "filings_enabled": settings.filings_enabled,
        "guardrail_attempts": settings.guardrail_attempts,
    }


@app.get("/v1/tearsheets/{ticker}", response_model=TearSheetData)
async def tearsheet(ticker: str,
                    ai: bool = Query(True, description="Include AI commentary"),
                    mode: Optional[Mode] = Query(None, description="single, two_step or deep (analyst, bull / bear "
                                                                    "debate, judge and reviewer; ~2-4 min; default "
                                                                    "from config)"),
                    filings: bool = Query(True, description="Read the latest annual/interim report"),
                    refresh: bool = Query(False, description="Ignore the 15-minute result cache"),
                    learner: bool = Query(False, description="Also write the AI notes of the learner's guide"),
                    data_only: bool = _data_only_query()):
    return await run_in_threadpool(_get, ticker, ai, mode, filings, refresh, learner, data_only)


@app.get("/v1/tearsheets/{ticker}/pdf", response_class=Response,
         responses={200: {"content": {"application/pdf": {}}}})
async def tearsheet_pdf(ticker: str, ai: bool = Query(True), mode: Optional[Mode] = Query(None),
                        filings: bool = Query(True), refresh: bool = Query(False),
                        layout: Layout = Query("report", description="report (full, default), tearsheet (page 1), "
                                                                  "learner (page 1 with step markers + learner's guide) "
                                                                  "or data (the data-only edition of the report)"),
                        download: Optional[bool] = False, data_only: bool = _data_only_query()):
    data_only = data_only or layout == "data"
    if data_only and layout == "learner":
        raise HTTPException(status_code=400, detail="The learner's guide has no data-only edition: use layout=data "
                                                    "(full report) or layout=tearsheet.")
    if data_only and layout == "report":
        layout = "data"
    key, built, data = await run_in_threadpool(_get_entry, ticker, ai, mode, filings, refresh, layout == "learner",
                                               data_only)
    pdf = await run_in_threadpool(_pdf_once, key, built, data, layout, data_only)
    name = f"{data.profile.ticker.replace('.', '_')}_{layout}{'_data' if data_only and layout != 'data' else ''}.pdf"
    disp = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{name}"'})


@app.get("/v1/tearsheets/{ticker}/datapack", response_class=Response,
         responses={200: {"content": {"application/zip": {}}}})
async def tearsheet_datapack(ticker: str, ai: bool = Query(True), mode: Optional[Mode] = Query(None),
                             filings: bool = Query(True), refresh: bool = Query(False),
                             learner: bool = Query(False),
                             layout: Optional[Layout] = Query(None, description="as for /pdf; only layout=learner "
                                                                                "and layout=data matter (same cached "
                                                                                "result)"),
                             data_only: bool = _data_only_query(),
                             docs: bool = Query(False, description="Also download the original documents into "
                                                                   "filings/: the latest reports and the official "
                                                                   "documents the research notes cite (slower: "
                                                                   "HKEXnews can take minutes)")):
    """Source data pack (ZIP) for students who want to dig further: an Excel workbook of the numbers behind the
    report (statements, ratios, valuation workings, peers, prices, brokers, the research evidence behind each [R#]
    note, sources), sources.pdf (how to use the pack, every link, each note's exact quote) and data.json. One pack
    serves all three reports of a company (standard, deep, learner): they share the data. Uses the same cached
    result as the JSON and PDF endpoints. With data_only=true (or layout=data) it is the data-only build's pack:
    the same figures without the AI parts and the rating."""
    data_only = data_only or layout == "data"
    data = await run_in_threadpool(_get, ticker, ai, mode, filings, refresh, learner or layout == "learner", data_only)
    pack = await run_in_threadpool(build_datapack, data, docs)
    name = f"{data.profile.ticker.replace('.', '_')}_datapack.zip"
    return Response(pack, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- all three reports in one go (api/jobs.py)
class RunRequest(BaseModel):
    ticker: str


@app.post("/v1/runs", status_code=202)
def start_run(req: RunRequest) -> dict:
    """Start the deep report, then the standard report and the learner's guide from its data (about 35-40 minutes
    and USD 0.50 of AI credit on run 2's settings). One job at a time; poll GET /v1/runs/{id}."""
    try:
        t = tickers.parse(req.ticker.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not settings.llm.enabled:
        raise HTTPException(status_code=400, detail="No AI key is configured on this server, so the AI reports "
                                                    "cannot be written. Add a key (see .env.example) and restart "
                                                    "the server; the data-only report needs no key.")
    try:
        job = jobs.start(t.canonical)
    except jobs.Busy as e:
        raise HTTPException(status_code=409, detail=str(e))
    return job.view()


@app.get("/v1/runs")
def list_runs() -> dict:
    return {"runs": [j.view() for j in jobs.recent()]}


@app.get("/v1/runs/{job_id}")
def run_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job on this server (jobs are kept until it restarts; "
                                                    "finished reports are in the archive).")
    return job.view()


# ---------------------------------------------------------------- archive (investsync/archive.py)
@app.get("/archive", include_in_schema=False)
def archive_page() -> FileResponse:
    return FileResponse(STATIC / "archive.html")


@app.get("/v1/archive")
def archive_list(ticker: Optional[str] = None, kind: Optional[str] = None) -> dict:
    """Every saved report, newest first: generated on this site (source "web") or by a paid run ("run")."""
    out = archive.entries()
    if ticker:
        out = [e for e in out if (e.get("ticker") or "").upper() == ticker.strip().upper()]
    if kind:
        out = [e for e in out if e.get("kind") == kind]
    return {"entries": out}


@app.get("/v1/archive/{entry_id}/pack", response_class=Response)
async def archive_pack(entry_id: str, documents: bool = Query(False, description="with the original filings "
                                                                                  "(downloaded the first time: minutes)")):
    """An entry's source data pack (ZIP): built from its saved JSON the first time it is asked for, then kept."""
    if archive.entry(entry_id) is None:
        raise HTTPException(status_code=404, detail="No such report in the archive.")
    meta = await run_in_threadpool(archive.add_pack, entry_id, documents)
    want = "zip_docs" if documents else "zip"
    name = next((f["name"] for f in (meta or {}).get("files") or [] if f.get("type") == want), None)
    path = archive.file_path(entry_id, name) if name else None
    if path is None:
        raise HTTPException(status_code=422, detail="A data pack could not be built for this report (an older format).")
    return FileResponse(path, media_type="application/zip", filename=name, content_disposition_type="attachment")


@app.get("/v1/archive/{entry_id}/{name}")
def archive_file(entry_id: str, name: str, download: bool = False) -> FileResponse:
    """One file of an entry (only the files the entry lists, only inside its folder)."""
    path = archive.file_path(entry_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail="No such file in the archive.")
    media = {".pdf": "application/pdf", ".json": "application/json", ".zip": "application/zip",
             ".md": "text/markdown; charset=utf-8",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(
        path.suffix.lower(), "application/octet-stream")
    if path.suffix.lower() in (".zip", ".xlsx"):
        download = True  # a browser cannot show these inline
    return FileResponse(path, media_type=media, filename=name,
                        content_disposition_type="attachment" if download else "inline")
