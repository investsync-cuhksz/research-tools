"""All three reports in one go (12 Nov 2026, Karel: "make an option where they can run all 3 in one go").

One background job per ticker, the way run 2's run script made it:
  1. deep: ``generate.py --ticker T --mode deep --layout report`` with RUN_BUDGET_USD 0.60 (past it, the judgement
     steps fall back to the primary model);
  2. standard + learner's guide from the deep run's saved data (``--data-from deep.json --mode single --layout
     learner``), so all three share one price, research, forecast, scenarios, fair value and rating. Budget as run.sh:
     deep cost D <= 0.55 -> RUN_BUDGET_USD = 0.80 - D; D <= 0.78 -> no judgement model (LLM_JUDGE_MODEL and
     LLM_LEARNER_MODEL empty); above 0.78 -> stop after the deep report;
  3. the standard PDF from the same JSON (free).
Each step runs in its own process, as in run.sh: its spend counter (RUN_BUDGET_USD) and settings are its own, and the
server's settings are never changed. The models are the server's own (its environment). Paid steps are never rerun
automatically (run.sh reruns once; here the user decides); a failed render is redone free from the saved JSON. The
finished reports go into the archive (investsync/archive.py). One job at a time.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from investsync import archive

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DEEP_BUDGET = float(os.getenv("DEEP_BUDGET", "0.60"))   # run.sh: RUN_BUDGET_USD for the deep step
SET_BUDGET = 0.80     # run.sh: standard + learner get 0.80 - (deep's cost)
JUDGE_LINE = 0.55     # deep cost above this: standard + learner without the judgement model
STOP_LINE = 0.78      # deep cost above this: stop after the deep report
STAGE_TIMEOUT = int(os.getenv("RUN_STAGE_TIMEOUT_SECONDS", str(90 * 60)))
STAGES = ("deep", "standard + learner", "rendering")


def runs_dir() -> Path:
    return Path(os.getenv("INVESTSYNC_RUNS_DIR") or ROOT / "output" / "runs")


@dataclass
class Job:
    id: str
    ticker: str
    folder: Path
    stage: str = "queued"       # queued / deep / standard + learner / rendering / done / failed
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    cost_usd: float = 0.0       # billed cost of the finished AI steps (from each JSON's ai_usage)
    note: str = ""
    error: str = ""
    failed_stage: str = ""      # the step that stopped the job
    reports: list = field(default_factory=list)   # archive entries: {kind, label, id, pdf, json}
    company: str = ""

    def view(self) -> dict:
        now = time.time()
        end = self.finished or now
        return {"id": self.id, "ticker": self.ticker, "company": self.company, "stage": self.stage,
                "stages": list(STAGES), "running": self.stage not in ("done", "failed"),
                "started": datetime.fromtimestamp(self.started, timezone.utc).isoformat(),
                "finished": datetime.fromtimestamp(self.finished, timezone.utc).isoformat() if self.finished else None,
                "elapsed_s": round(end - self.started), "age_s": round(now - end),
                "cost_usd": round(self.cost_usd, 4), "note": self.note, "error": self.error,
                "failed_stage": self.failed_stage, "reports": self.reports}


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def current() -> Optional[Job]:
    with _lock:
        return next((j for j in _jobs.values() if j.stage not in ("done", "failed")), None)


def get(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)


def recent(n: int = 10) -> list[Job]:
    return sorted(_jobs.values(), key=lambda j: j.started, reverse=True)[:n]


class Busy(RuntimeError):
    pass


def start(ticker: str, background: bool = True) -> Job:
    """Start a job (raises Busy when one is running). ``background=False`` runs it here (tests)."""
    with _lock:
        running = next((j for j in _jobs.values() if j.stage not in ("done", "failed")), None)
        if running:
            raise Busy(f"An all-three job is already running for {running.ticker} (stage: {running.stage}, "
                       f"{round((time.time() - running.started) / 60)} min so far). One paid job runs at a time: "
                       f"wait for it to finish.")
        now = datetime.now(timezone.utc)
        job_id = f"{now.astimezone():%Y%m%d-%H%M%S}-{archive._ticker_part(ticker)}"
        folder = runs_dir() / job_id
        folder.mkdir(parents=True, exist_ok=True)
        job = Job(id=job_id, ticker=ticker.strip().upper(), folder=folder)
        _jobs[job_id] = job
    if background:
        threading.Thread(target=run, args=(job,), daemon=True, name=f"all-three {job_id}").start()
    else:
        run(job)
    return job


# ---------------------------------------------------------------- the steps
def _execute(cmd: list[str], env: dict, log_path: Path, timeout: int) -> int:
    """Run one generate.py step in its own process; its output goes to the job's run.log."""
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"\n=== {datetime.now():%H:%M:%S} {' '.join(cmd[1:])}\n")
        fh.flush()
        try:
            return subprocess.run(cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            fh.write(f"=== stopped after {timeout} s\n")
            return 124


def _gen(*args: str) -> list[str]:
    return [sys.executable, str(ROOT / "generate.py"), *args]


def _env(**changes: str) -> dict:
    env = dict(os.environ)
    env.pop("RUN_BUDGET_USD", None)
    env.update(changes)
    return env


def _read(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _status(d: Optional[dict]) -> Optional[str]:
    return ((d or {}).get("narrative") or {}).get("status")


def _cost(d: Optional[dict]) -> float:
    return float(((d or {}).get("ai_usage") or {}).get("est_cost_usd") or 0.0)


def _step(job: Job, cmd: list[str], env: dict, js: Path, pdf: Path, layout: str) -> Optional[dict]:
    """One paid step, then its JSON. A failed render after a saved, written JSON is redone free from the JSON."""
    rc = _execute(cmd, env, job.folder / "run.log", STAGE_TIMEOUT)
    d = _read(js)
    if (rc != 0 or not pdf.is_file()) and _status(d) == "generated":
        _execute(_gen("--from-json", str(js), "--output", str(pdf), "--layout", layout), _env(),
                 job.folder / "run.log", STAGE_TIMEOUT)
    return d


def run(job: Job) -> None:
    f = job.folder
    try:
        # 1. deep
        job.stage = "deep"
        deep = _step(job, _gen("--ticker", job.ticker, "--mode", "deep", "--layout", "report",
                               "--json", str(f / "deep.json"), "--output", str(f / "deep.pdf")),
                     _env(RUN_BUDGET_USD=f"{DEEP_BUDGET:.2f}"), f / "deep.json", f / "deep.pdf", "report")
        job.company = ((deep or {}).get("profile") or {}).get("name", "")
        st = _status(deep)
        if st != "generated" or not (f / "deep.pdf").is_file():
            raise RuntimeError("The deep report did not finish: " + (
                f"its commentary is '{st}'" if st else "no data was saved (see run.log)") +
                ". Nothing more was spent; start the job again to retry (calls that worked are replayed free).")
        d_cost = _cost(deep)
        job.cost_usd = d_cost
        group = f"All three · {datetime.fromtimestamp(job.started).strftime('%-d %b %H:%M')}"
        if d_cost > STOP_LINE:
            job.note = (f"The deep report cost USD {d_cost:.2f}, over the USD {STOP_LINE:.2f} line: stopped after it "
                        "(as run.sh does), so the standard report and the learner's guide were not written.")
            _archive(job, group, deep_only=True)
            job.stage = "done"
            return

        # 2. standard + learner from the deep run's data
        job.stage = "standard + learner"
        if d_cost <= JUDGE_LINE:
            env = _env(RUN_BUDGET_USD=f"{SET_BUDGET - d_cost:.3f}")
        else:
            env = _env(LLM_JUDGE_MODEL="", LLM_LEARNER_MODEL="")
            job.note = (f"The deep report cost USD {d_cost:.2f} (over USD {JUDGE_LINE:.2f}): the standard report and "
                        "the learner's guide were written without the judgement model, as run.sh does.")
        simple = _step(job, _gen("--data-from", str(f / "deep.json"), "--mode", "single", "--layout", "learner",
                                 "--json", str(f / "simple.json"), "--output", str(f / "learner.pdf")),
                       env, f / "simple.json", f / "learner.pdf", "learner")
        if simple is None or not (f / "learner.pdf").is_file():
            raise RuntimeError("The standard report and the learner's guide did not finish (see run.log). The deep "
                               "report is kept in the job folder.")
        job.cost_usd = d_cost + _cost(simple)
        if _status(simple) != "generated":
            job.note = (job.note + " " if job.note else "") + (
                f"The standard commentary is '{_status(simple)}': read it with care (run.sh would rerun it once).")

        # 3. the standard PDF from the same JSON (free)
        job.stage = "rendering"
        _execute(_gen("--from-json", str(f / "simple.json"), "--output", str(f / "simple.pdf"), "--layout", "report"),
                 _env(), f / "run.log", STAGE_TIMEOUT)
        if not (f / "simple.pdf").is_file():
            raise RuntimeError("The standard PDF could not be drawn (see run.log); the deep report and the learner's "
                               "guide are in the job folder.")
        _archive(job, group)
        job.stage = "done"
    except Exception as e:  # noqa: BLE001
        log.exception("all-three job %s failed", job.id)
        job.error = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
        job.failed_stage = job.stage if job.stage in STAGES else STAGES[0]
        job.stage = "failed"
    finally:
        job.finished = time.time()
        try:
            (f / "status.json").write_text(json.dumps(job.view(), indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _archive(job: Job, group: str, deep_only: bool = False) -> None:
    f = job.folder
    todo = [("deep", f / "deep.pdf", f / "deep.json", None)]
    if not deep_only:
        todo += [("standard", f / "simple.pdf", f / "simple.json", "standard + learner written together"),
                 ("learner", f / "learner.pdf", f / "simple.json", "included in the standard report's cost")]
    for kind, pdf, js, cost_note in todo:
        d = _read(js)
        meta = archive.add_files(kind, pdf, js, source="web", group=group, note=job.note or None,
                                 cost_usd=None if kind == "learner" else _cost(d), cost_note=cost_note)
        if meta:
            meta = archive.add_pack(meta["id"]) or meta  # the source pack too (Excel, sources.pdf; no fetch, no AI)
            files = {x["type"]: x["name"] for x in meta["files"]}
            job.reports.append({"kind": kind, "label": archive.LABELS[kind], "id": meta["id"],
                                "pdf": f"/v1/archive/{meta['id']}/{files['pdf']}",
                                "json": f"/v1/archive/{meta['id']}/{files['json']}"})
