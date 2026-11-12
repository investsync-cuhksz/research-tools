"""Compile TearSheetData into a PDF with the Typst template."""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from ..schema import TearSheetData
from . import viewmodel

log = logging.getLogger(__name__)

RENDER_ROOT = Path(__file__).resolve().parent
TEMPLATE = RENDER_ROOT / "template" / "tearsheet.typ"
BUILD_DIR = RENDER_ROOT / "build"
FONT_DIR = RENDER_ROOT / "fonts"


# "data" (12 Nov 2026): the data-only edition of the report: the report layout without AI text or a verdict, with
# "Your analysis" boxes to write in (render/dataonly.py)
LAYOUTS = {"report": "report.typ", "tearsheet": "tearsheet.typ", "learner": "learner.typ", "data": "report.typ"}
PAGE_LIMITS = {"standard": 15, "deep": 28, "learner": 16, "data": 16}

import re as _re
from pydantic import BaseModel as _BaseModel

# "118,010mn" in a sentence -> "118.0bn" (round-6/7 reviews: "numbers in the prose read like 608,945mn"). Display only:
# the AI text was checked against the data before this; the value is the same, rounded to one decimal of a bn
# (two of a tn). Tables built in code keep their mn units.
_MN = _re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{5,})(\.\d+)?\s?mn\b")


_GROUP = _re.compile(r"\s?[\(\[]([^()\[\]]{1,80})[\)\]]")
_CODE = _re.compile(r"^(?:[ES]\d{1,3}(?:[–-][ES]?\d{1,3})?|…|\.\.\.)$")


_RIDS = _re.compile(r"([(\[])\s*(R\d+)\s*[,;]\s*(R\d+)(?:\s*[,;]\s*R\d+)+\s*([)\]])")


def strip_codes(text: str) -> str:
    """Remove debate evidence codes from printed sentences: "(S5, E24)" -> "", "(R6, E24)" -> "(R6)" (round-7 review:
    "the text is cluttered with evidence codes"). Research-note ids [R6] stay: the notes are printed in the report,
    but a run of three or more is cut to the first two (round 9: "(R54,R55,R59,R60)" read as machine clutter)."""
    if text and "R" in text:
        text = _RIDS.sub(lambda m: f"{m.group(1)}{m.group(2)}, {m.group(3)}{m.group(4)}", text)
    if not text or not _re.search(r"\b[ES]\d", text):
        return text

    def rep(m):
        parts = [x.strip() for x in _re.split(r"[,;]", m.group(1))]
        if not any(_CODE.match(x) for x in parts if x):
            return m.group(0)
        keep = [x for x in parts if x and not _CODE.match(x)]
        if not keep:
            return ""
        return m.group(0)[0] if m.group(0)[0] != " " else " " + m.group(0)[1] + ", ".join(keep) + m.group(0)[-1]
    return _GROUP.sub(rep, text)  # the group pattern takes the space before it, so "guide (E110)." -> "guide."


def readable_amounts(text: str) -> str:
    def rep(m):
        v = float((m.group(1) + (m.group(2) or "")).replace(",", ""))
        if v < 10_000:
            return m.group(0)
        return f"{v / 1e6:,.2f}tn" if v >= 1_000_000 else f"{v / 1e3:,.1f}bn"
    return _MN.sub(rep, text) if text and "mn" in text else text


# a template marker an AI step wrote into its answer ("[[ NOTES_PLACEHOLDER ]]", "[[ ## answer ## ]]"): never printed
# (round-11 review, 12 Nov 2026: the learner's 60-second summary ended with one)
_MARKER = _re.compile(r"[ \t]*\[\[[^\[\]\n]{0,80}\]\]")


def strip_markers(text: str) -> str:
    return _MARKER.sub("", text).rstrip() if text and "[[" in text else text


def _readable(obj):
    if isinstance(obj, str):
        return readable_amounts(strip_codes(strip_markers(obj)))
    if isinstance(obj, list):
        return [_readable(x) for x in obj]
    if isinstance(obj, dict):  # e.g. the learner notes per step
        return {k: _readable(v) for k, v in obj.items()}
    if isinstance(obj, _BaseModel):
        for name in type(obj).model_fields:
            val = getattr(obj, name)
            new = _readable(val)
            if new is not val:
                try:
                    setattr(obj, name, new)
                except Exception:
                    pass
        return obj
    return obj


def _display_copy(data: TearSheetData) -> TearSheetData:
    """The data as printed: AI-written text (commentary, forecast drivers, scenario drivers) with large mn amounts in
    bn / tn."""
    d = data.model_copy(deep=False)
    if data.narrative is not None:
        d.narrative = _readable(data.narrative.model_copy(deep=True))
    if data.forecast is not None:
        d.forecast = _readable(data.forecast.model_copy(deep=True))
    if data.valuation is not None and data.valuation.scenarios is not None:
        d.valuation = data.valuation.model_copy(deep=False)
        d.valuation.scenarios = _readable(data.valuation.scenarios.model_copy(deep=True))
    if data.analyst_questions is not None:  # the why-now lines and the deep answers (AI text)
        d.analyst_questions = _readable(data.analyst_questions.model_copy(deep=True))
    return d


def _is_deep(data: TearSheetData) -> bool:
    n = data.narrative
    return bool(n and n.deep and (n.deep.bull or n.deep.bear))


def page_limit(data: TearSheetData, layout: str) -> Optional[int]:
    """Most pages allowed: standard report 15, deep report 28, learner 16 (run 2: run 1's 16-page report was marked
    down), data-only edition 16 (its writing boxes take room). ``REPORT_MAX_PAGES`` overrides: one number for every
    layout ("15"), or per kind ("standard=15,deep=28,learner=16,data=16"). None for the one-page tear sheet."""
    if layout == "report":
        kind = "deep" if _is_deep(data) else "standard"
    elif layout in ("learner", "data"):
        kind = layout
    else:
        return None
    limit = PAGE_LIMITS[kind]
    env = (os.getenv("REPORT_MAX_PAGES") or "").strip()
    if env:
        try:
            if "=" in env:
                pairs = dict(p.split("=", 1) for p in env.replace(";", ",").split(",") if "=" in p)
                pairs = {k.strip().lower(): v.strip() for k, v in pairs.items()}
                if kind in pairs:
                    limit = int(pairs[kind])
            else:
                limit = int(env)
        except ValueError:
            log.warning("REPORT_MAX_PAGES=%r not understood; using %d pages", env, limit)
    return limit


def count_pages(pdf: bytes) -> Optional[int]:
    """Pages in a PDF, or None when they cannot be counted (never raises)."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(pdf)).pages)
    except Exception as e:
        log.warning("page count failed: %s", e)
        return None


def _build_and_compile(vm: dict, layout: str) -> bytes:
    BUILD_DIR.mkdir(exist_ok=True)
    job = BUILD_DIR / f"{uuid.uuid4().hex}.json"
    job.write_text(json.dumps(vm, ensure_ascii=False), encoding="utf-8")
    try:  # the data-only edition is the report template, told by the view model's data_only flag
        return _compile(job, TEMPLATE.parent / LAYOUTS[layout], "report" if layout == "data" else layout)
    finally:
        job.unlink(missing_ok=True)


def render_pdf(data: TearSheetData, output: str | Path | None = None, layout: str = "report",
               data_only: bool = False) -> bytes:
    """Render the PDF; returns the bytes and writes them to ``output`` if given.

    ``layout``: "report" (page 1 tear sheet + full report, default), "tearsheet" (page 1 only),
    "learner" (page 1 with step markers + the learner's guide for first-year students) or "data" (the data-only
    edition of the report: no AI text, no rating, "Your analysis" boxes to write in). ``data_only=True`` asks for the
    data-only edition of "report" (= "data") or "tearsheet"; the learner's guide has none. Any data can be printed
    as a data-only edition: its AI parts and verdict are taken out first (render/dataonly.py).

    Page fit (run 2): a report over its page limit (``page_limit``) is rebuilt with shorter tables
    (``build_report(compact=1)``, then 2 and 3): at most four compiles. If it is still over, the last PDF is kept
    and a warning logged; a failed count or a failed compact compile never blocks the PDF. A learner over its limit is
    only logged (its view model has no compact form).
    """
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {sorted(LAYOUTS)}")
    if data_only and layout == "report":
        layout = "data"
    data_only = data_only or layout == "data"
    if data_only and layout == "learner":
        raise ValueError("the learner's guide has no data-only edition; use layout 'data' or 'tearsheet'")
    if data_only:
        from . import dataonly
        data = dataonly.strip(data)
    data = _display_copy(data)
    vm = viewmodel.build(data, data_only=data_only)
    if layout in ("report", "data"):
        from .report_vm import build_report
        vm["report"] = build_report(data, data_only=data_only)
    elif layout == "learner":
        from .learner_vm import build as build_learner
        vm["learner"] = build_learner(data)
    pdf = _build_and_compile(vm, layout)
    limit = page_limit(data, layout)
    n = count_pages(pdf) if limit else None
    if n is not None and n > limit:
        if layout in ("report", "data"):
            for level in (1, 2, 3):
                try:
                    vm["report"] = build_report(data, compact=level, data_only=data_only)
                    pdf2 = _build_and_compile(vm, layout)
                except Exception as e:  # keep the PDF we have
                    log.warning("compact report (level %d) failed: %s", level, e)
                    break
                pdf, n2 = pdf2, count_pages(pdf2)
                log.info("report had %d pages (limit %d); compact level %d gives %s", n, limit, level, n2)
                n = n2
                if n is None or n <= limit:
                    break
        if n is not None and n > limit:
            log.warning("%s PDF has %d pages, over its limit of %d", layout, n, limit)
    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(pdf)
    return pdf


def _compile(job: Path, template: Path = TEMPLATE, layout: str = "tearsheet") -> bytes:
    data_arg = f"/build/{job.name}"
    font_paths = [str(FONT_DIR)] if FONT_DIR.exists() else []
    inputs = {"data": data_arg, "layout": layout}
    try:
        import typst  # Python bindings bundle the compiler
        return typst.compile(str(template), root=str(RENDER_ROOT), font_paths=font_paths, sys_inputs=inputs)
    except ImportError:
        pass
    exe = shutil.which("typst")
    if not exe:
        raise RuntimeError("Typst not found: pip install typst, or install the Typst CLI.")
    cmd = [exe, "compile", "--root", str(RENDER_ROOT)]
    for k, val in inputs.items():
        cmd += ["--input", f"{k}={val}"]
    for fp in font_paths:
        cmd += ["--font-path", fp]
    cmd += [str(template), "-"]
    return subprocess.run(cmd, check=True, capture_output=True).stdout
