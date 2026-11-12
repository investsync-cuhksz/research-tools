"""The report archive (12 Nov 2026, Karel: "have an archive page of all we have generated (based on the runs)").

Every report the web app makes is saved once per build: ``output/archive/<YYYY-MM-DD_HHMMSS>_<TICKER>_<kind>/`` with
the PDF, the JSON it was drawn from and ``meta.json`` (ticker, company, kind, when, price and its date, rating and fair
value if any, AI cost if known, source "web" or "run"). The paid runs made with run.sh are copied in once by
``python -m investsync.archive seed`` (idempotent). ``output/`` is git-ignored.

``INVESTSYNC_ARCHIVE_DIR`` moves the archive (tests use a temporary folder); ``INVESTSYNC_ARCHIVE=0`` turns saving off.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .schema import TearSheetData

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("standard", "deep", "learner", "data", "tearsheet")
LABELS = {"standard": "Standard report", "deep": "Deep report", "learner": "Learner's guide",
          "data": "Data only (no AI)", "tearsheet": "Tear sheet (1 page)"}
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")

# The paid runs made with run.sh (folders under output/compare_2026-11-08/): the folder, and the run's number.
# Inside each, every <TICKER>/ folder holds the official files and <TICKER>_fixed/ the free re-renders made after a
# template fix (labelled as the corrected version).
RUNS = (("compare_2026-11-08/final_v8", 1), ("compare_2026-11-08/final_v9", 2), ("compare_2026-11-08/final_v10", 3),
        ("compare_2026-11-08/final_v11", 4))
# Since 13 Nov 2026 these folders are seeded into output/archive/ (which ships with the repository) and the run folders
# themselves are no longer kept; seed() skips a folder that is missing.
# run.sh's file names: (kind, PDF, the JSON it was drawn from)
RUN_FILES = (("deep", "deep.pdf", "deep.json"), ("standard", "simple.pdf", "simple.json"),
             ("learner", "learner.pdf", "simple.json"))


def root() -> Path:
    return Path(os.getenv("INVESTSYNC_ARCHIVE_DIR") or ROOT / "output" / "archive")


def enabled() -> bool:
    return os.getenv("INVESTSYNC_ARCHIVE", "1") != "0"


def safe_name(s: str) -> bool:
    """A single file or folder name: letters, digits, '.', '_' and '-' only, never '..' or a path."""
    return bool(s) and bool(_SAFE.match(s)) and ".." not in s


def _stamp(t: datetime) -> str:
    return t.astimezone().strftime("%Y-%m-%d_%H%M%S")


def _ticker_part(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", ticker).strip("_").upper() or "X"


def summary(data: TearSheetData) -> dict[str, Any]:
    """What the archive lists about a report's data (no AI text)."""
    q, rt, n, u = data.quote, data.rating, data.narrative, data.ai_usage
    return {"ticker": data.profile.ticker, "company": data.profile.name, "currency": q.currency,
            "price": q.price, "as_of": q.as_of.isoformat() if q.as_of else None,
            "data_time": data.generated_at.isoformat(),
            "rating": rt.rating if rt else None, "fair_value": rt.fair_value if rt else None,
            "upside": rt.upside if rt else None,
            "ai": bool(n and n.status != "placeholder"), "status": n.status if n else None,
            "mode": n.mode if n and n.status != "placeholder" else None,
            "model": ", ".join(u.models) if u and u.models else n.model if n and n.model else None,
            "cost_usd": u.est_cost_usd if u and u.est_cost_usd is not None else (0.0 if not (n and n.model) else None)}


def _new_dir(ticker: str, kind: str, when: datetime, suffix: str = "") -> Path:
    base = f"{_stamp(when)}_{_ticker_part(ticker)}_{kind}{suffix}"
    d, i = root() / base, 2
    while d.exists():  # two reports of one kind in the same second
        d, i = root() / f"{base}_{i}", i + 1
    d.mkdir(parents=True)
    return d


def _write_meta(d: Path, meta: dict) -> dict:
    meta["id"] = d.name
    (d / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return meta


def save_report(data: TearSheetData, pdf: bytes, kind: str, source: str = "web", group: Optional[str] = None,
                note: Optional[str] = None, cost_note: Optional[str] = None, cost_usd: Optional[float] = None,
                json_text: Optional[str] = None) -> Optional[dict]:
    """Save one report (its PDF, its JSON and meta.json); returns the entry's meta, or None when saving is off or
    fails (the archive must never cost the reader the report)."""
    if not enabled():
        return None
    try:
        now = datetime.now(timezone.utc)
        d = _new_dir(data.profile.ticker, kind, now)
        stem = f"{_ticker_part(data.profile.ticker)}_{kind}"
        (d / f"{stem}.pdf").write_bytes(pdf)
        (d / f"{stem}.json").write_text(json_text if json_text is not None else data.model_dump_json(indent=1),
                                        encoding="utf-8")
        meta = {**summary(data), "kind": kind, "label": LABELS.get(kind, kind), "created": now.isoformat(),
                "source": source, "group": group, "note": note, "cost_note": cost_note,
                "files": [{"name": f"{stem}.pdf", "type": "pdf"}, {"name": f"{stem}.json", "type": "json"}]}
        if cost_usd is not None or cost_note:
            meta["cost_usd"] = cost_usd
        return _write_meta(d, meta)
    except Exception as e:  # noqa: BLE001
        log.warning("archive: could not save the %s report: %s", kind, e)
        return None


def add_files(kind: str, pdf: Path, data_json: Path, source: str, group: Optional[str] = None,
              note: Optional[str] = None, cost_usd: Optional[float] = None, cost_note: Optional[str] = None,
              entry_id: Optional[str] = None, created: Optional[datetime] = None) -> Optional[dict]:
    """Copy a finished report (PDF + its JSON) into the archive. ``entry_id``: a fixed id (the seed import), skipped
    when it exists already."""
    data = TearSheetData.model_validate_json(data_json.read_text(encoding="utf-8"))
    if entry_id is not None:
        d = root() / entry_id
        if d.exists():
            return None
        d.mkdir(parents=True)
    else:
        d = _new_dir(data.profile.ticker, kind, created or datetime.now(timezone.utc))
    stem = f"{_ticker_part(data.profile.ticker)}_{kind}"
    shutil.copy2(pdf, d / f"{stem}.pdf")
    shutil.copy2(data_json, d / f"{stem}.json")
    meta = {**summary(data), "kind": kind, "label": LABELS.get(kind, kind),
            "created": (created or datetime.now(timezone.utc)).isoformat(), "source": source, "group": group,
            "note": note, "cost_note": cost_note,
            "files": [{"name": f"{stem}.pdf", "type": "pdf"}, {"name": f"{stem}.json", "type": "json"}]}
    if cost_usd is not None or cost_note:
        meta["cost_usd"] = cost_usd
    return _write_meta(d, meta)


def entries() -> list[dict]:
    """Every entry's meta, newest first (an unreadable entry is skipped)."""
    out = []
    base = root()
    for d in (base.iterdir() if base.exists() else []):
        m = d / "meta.json"
        if d.is_dir() and m.exists():
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
                meta["id"] = d.name
                out.append(meta)
            except Exception as e:  # noqa: BLE001
                log.warning("archive: skipped %s: %s", d.name, e)
    return sorted(out, key=lambda x: x.get("created") or "", reverse=True)


def entry(entry_id: str) -> Optional[dict]:
    if not safe_name(entry_id):
        return None
    m = root() / entry_id / "meta.json"
    if not m.exists():
        return None
    meta = json.loads(m.read_text(encoding="utf-8"))
    meta["id"] = entry_id
    return meta


def file_path(entry_id: str, name: str) -> Optional[Path]:
    """The file ``name`` of entry ``entry_id``, only if the entry lists it and it lies inside the entry's folder."""
    if not (safe_name(entry_id) and safe_name(name)):
        return None
    meta = entry(entry_id)
    if meta is None or name not in {f.get("name") for f in meta.get("files") or []}:
        return None
    folder = (root() / entry_id).resolve()
    p = (folder / name).resolve()
    if p.parent != folder or not p.is_file():
        return None
    return p


# ---------------------------------------------------------------- the source data pack (12 Nov 2026)
# Karel: "where did the pack go? the raw resources, pdfs/excels e.t.c it should be displayed in the archives too".
# Each entry gets the student source pack built from its own saved JSON (no fetch, no AI): the ZIP as the web page
# offers it, plus its Excel workbook and sources.pdf as files of their own. The pack with the original filings is
# built only when someone asks for it (downloads take minutes) and is then kept.
PACK_TYPES = {"xlsx": "Excel workbook", "sources": "Sources (PDF)", "zip": "Data pack (.zip)",
              "zip_docs": "Data pack + original documents (.zip)"}


def _report_json(meta: dict) -> Optional[Path]:
    for f in meta.get("files") or []:
        if f.get("type") == "json":
            p = root() / meta["id"] / f["name"]
            if p.is_file():
                return p
    return None


def add_pack(entry_id: str, documents: bool = False) -> Optional[dict]:
    """Build and keep the source pack of one entry (``documents``: with the original filings). Returns the updated
    meta, or None when the entry has no JSON or the pack cannot be built. Already built: nothing to do."""
    meta = entry(entry_id)
    if meta is None:
        return None
    kind = "zip_docs" if documents else "zip"
    if any(f.get("type") == kind for f in meta.get("files") or []):
        return meta
    js = _report_json(meta)
    if js is None:
        return None
    try:
        import io
        import zipfile
        from .datapack import build_datapack
        data = TearSheetData.model_validate_json(js.read_text(encoding="utf-8"))
        pack = build_datapack(data, include_filing_docs=documents)
    except Exception as e:  # noqa: BLE001 - an old report the pack builder cannot read: no pack, never an error
        log.warning("archive: no data pack for %s: %s: %s", entry_id, type(e).__name__, e)
        return None
    d = root() / entry_id
    stem = js.stem
    zname = f"{stem}_datapack{'_documents' if documents else ''}.zip"
    (d / zname).write_bytes(pack)
    files = list(meta.get("files") or [])
    if not documents:
        with zipfile.ZipFile(io.BytesIO(pack)) as z:
            for n in z.namelist():
                if n.endswith(".xlsx"):
                    (d / f"{stem}_data.xlsx").write_bytes(z.read(n))
                    files.append({"name": f"{stem}_data.xlsx", "type": "xlsx"})
                elif n in ("sources.pdf", "sources.md"):
                    out = f"{stem}_{n}"
                    (d / out).write_bytes(z.read(n))
                    files.append({"name": out, "type": "sources"})
    files.append({"name": zname, "type": kind})
    meta["files"] = files
    meta.pop("id", None)
    return _write_meta(d, meta)


def add_packs(documents: bool = False) -> int:
    """Build the missing packs of every entry (the seed and older entries). Returns how many were built."""
    n = 0
    for m in entries():
        if not any(f.get("type") == "zip" for f in m.get("files") or []) and add_pack(m["id"], documents):
            n += 1
    return n


# ---------------------------------------------------------------- the paid runs, copied in once
def _run_label(n: int, data_time: datetime) -> str:
    t = data_time.astimezone()
    return f"Run {n} ({t.day} {t:%b})"


CORRECTED_NOTE = ("Corrected version: re-rendered free from the run's saved data after a template fix (no new AI "
                  "call). The original, as reviewed, is listed separately.")


def seed(base: Optional[Path] = None) -> list[dict]:
    """Copy the paid runs' reports into the archive (only files that exist; an entry already there is skipped, so
    running it again adds nothing). Returns the entries added."""
    base = base or ROOT / "output"
    added = []
    for folder, n in RUNS:
        run_dir = base / folder
        if not run_dir.is_dir():
            continue
        for sub in sorted(p for p in run_dir.iterdir() if p.is_dir() and not p.name.endswith("_fixed")):
            for fixed in (False, True):
                src = run_dir / (sub.name + "_fixed") if fixed else sub
                if not src.is_dir():
                    continue
                for kind, pdf_name, json_name in RUN_FILES:
                    pdf, js = src / pdf_name, sub / json_name
                    if not (pdf.is_file() and js.is_file()):
                        continue
                    data = TearSheetData.model_validate_json(js.read_text(encoding="utf-8"))
                    # one AI step wrote the standard report and the learner's notes (run.sh: --layout learner),
                    # so its cost is shown once, on the standard report
                    meta = add_files(
                        kind, pdf, js, source="run", group=_run_label(n, data.generated_at),
                        note=CORRECTED_NOTE if fixed else None,
                        cost_usd=0.0 if fixed else (summary(data)["cost_usd"] if kind != "learner" else None),
                        cost_note=("free re-render" if fixed else
                                   "standard + learner written together" if kind == "standard" else
                                   "included in the standard report's cost" if kind == "learner" else None),
                        entry_id=(f"{_stamp(data.generated_at)}_{_ticker_part(data.profile.ticker)}_{kind}"
                                  + ("_corrected" if fixed else "") + f"_run{n}"),
                        created=datetime.fromtimestamp(pdf.stat().st_mtime, timezone.utc))
                    if meta:
                        added.append(meta)
    return added


# The DeepSeek development rounds before run 1 (8-9 Nov 2026, under output/compare_2026-11-08/): the folder, its label
# and a note. Each folder holds a company's simple/deep/learner files as run.sh wrote them. deepseek_v5_round6/ is a
# byte-for-byte copy of deepseek_v5/ and is left out; the Opus, Gemini and human reports are not ours and are left out.
DEV_NOTE = ("Development round: an earlier version of the tool, kept for comparison. Its rating and text are not a "
            "current view.")
DEV_RUNS = (
    ("deepseek", "DeepSeek v1", None),
    ("deepseek_v2/run1", "DeepSeek v2, first attempt", None),
    ("deepseek_v2/run1/300750_SZ/flagged_run", "DeepSeek v2, first attempt", "A flagged attempt, re-run afterwards."),
    ("deepseek_v2", "DeepSeek v2", None),
    ("deepseek_v3", "DeepSeek v3", None),
    ("deepseek_v4/first_nvda", "DeepSeek v4, first attempt", None),
    ("deepseek_v4", "DeepSeek v4", None),
    ("deepseek_v4r", "DeepSeek v4, reprocessed",
     "The same AI run as DeepSeek v4 (same time and cost), reprocessed from its saved data."),
    ("deepseek_v5", "DeepSeek v5", None),
    ("deepseek_v6_deep/high_round7", "DeepSeek v6 deep, round 7", None),
    ("deepseek_v6_deep/high", "DeepSeek v6 deep, high effort", None),
    ("deepseek_v7", "DeepSeek v7 (with V4 Pro)", None),
    ("cost_exp/A", "Cost experiment A", None),
    ("cost_exp/B", "Cost experiment B", None),
)
# extra file pairs some rounds have: (kind, PDF, JSON, note)
DEV_EXTRA = (("deep", "deep_pro.pdf", "deep_pro.json", "Deep report written with DeepSeek V4 Pro (an experiment)."),)


def _dev_dirs(folder: Path, listed: set) -> list[Path]:
    """The report folders of one development round: the folder itself if it holds reports, else its direct
    sub-folders that do (a company per folder), except sub-folders listed as rounds of their own."""
    has = lambda d: any((d / f).is_file() for _, f, _ in RUN_FILES)  # noqa: E731
    if has(folder):
        return [folder]
    return sorted(d for d in folder.iterdir() if d.is_dir() and has(d) and d.resolve() not in listed)


def seed_dev(base: Optional[Path] = None) -> list[dict]:
    """Copy the DeepSeek development rounds' reports into the archive (idempotent, like ``seed``)."""
    base = (base or ROOT / "output") / "compare_2026-11-08"
    added = []
    listed = {(base / f).resolve() for f, _, _ in DEV_RUNS}
    for folder, label, extra_note in DEV_RUNS:
        root_dir = base / folder
        if not root_dir.is_dir():
            continue
        slug = re.sub(r"[^A-Za-z0-9]+", "-", folder).strip("-").lower()
        for d in _dev_dirs(root_dir, listed):
            pairs = [(k, pdf, js, None) for k, pdf, js in RUN_FILES] + list(DEV_EXTRA)
            for kind, pdf_name, json_name, pair_note in pairs:
                pdf, js = d / pdf_name, d / json_name
                if not (pdf.is_file() and js.is_file()):
                    continue
                try:
                    data = TearSheetData.model_validate_json(js.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001 - an old schema the model no longer reads: skip it
                    log.warning("archive: %s not imported: %s", js, type(e).__name__)
                    continue
                when = data.generated_at.astimezone()
                note = " ".join(x for x in (DEV_NOTE, extra_note, pair_note) if x)
                tag = "_pro" if pdf_name.startswith("deep_pro") else ""
                meta = add_files(
                    kind, pdf, js, source="dev", group=f"{label} ({when.day} {when:%b})", note=note,
                    cost_usd=summary(data)["cost_usd"] if kind != "learner" else None,
                    cost_note=("standard + learner written together" if kind == "standard" else
                               "included in the standard report's cost" if kind == "learner" else
                               None) if summary(data)["cost_usd"] is not None else "cost not recorded",
                    entry_id=f"{_stamp(data.generated_at)}_{_ticker_part(data.profile.ticker)}_{kind}{tag}_{slug}",
                    created=datetime.fromtimestamp(pdf.stat().st_mtime, timezone.utc))
                if meta:
                    added.append(meta)
    return added


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["seed"]:
        added = seed() + seed_dev()
        for m in added:
            print(f"added {m['id']}  ({m['group']}{' · corrected' if (m.get('note') or '').startswith('Corrected') else ''})")
        print(f"{len(added)} entr{'y' if len(added) == 1 else 'ies'} added; {len(entries())} in {root()}")
        return 0
    if argv[:1] == ["packs"]:
        print(f"{add_packs()} data pack(s) built; {len(entries())} entries in {root()}")
        return 0
    if argv[:1] == ["list"]:
        for m in entries():
            print(f"{m['id']:<48} {m.get('group') or m.get('source')}")
        return 0
    print("usage: python -m investsync.archive seed | packs | list")
    return 2


if __name__ == "__main__":
    sys.exit(main())
