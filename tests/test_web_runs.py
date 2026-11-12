"""The web app's report archive, its "All three reports" background job and the honest time labels (12 Nov 2026).
Offline: no network and no AI model (the job's generate.py steps are replaced by a fake that writes files)."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from investsync import archive
from investsync.schema import AIUsage, Bullet, Narrative, TearSheetData

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
PAGE = (ROOT / "api" / "static" / "index.html").read_text(encoding="utf-8")


def load(name: str = "NVDA_deep.json") -> TearSheetData:
    return TearSheetData.model_validate_json((FIX / name).read_text(encoding="utf-8"))


def written(mode: str = "single", status: str = "generated", cost: float = 0.1) -> TearSheetData:
    d = load()
    d.narrative = Narrative(status=status, model="test-model", mode=mode, dupont_commentary="", comps_commentary="",
                            catalysts=[Bullet(title="Results", text="Due.")], risks=[])
    d.ai_usage = AIUsage(calls=3, est_cost_usd=cost, models=["test/flash", "test/judge"])
    return d


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTSYNC_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("INVESTSYNC_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("INVESTSYNC_ARCHIVE", raising=False)
    return tmp_path


# ---------------------------------------------------------------- archive
def test_save_list_and_serve_only_listed_files(store):
    meta = archive.save_report(written(cost=0.12), b"%PDF-1.7 a", "standard", source="web")
    assert meta["kind"] == "standard" and meta["ticker"] == "NVDA" and meta["rating"] == "Buy"
    assert meta["cost_usd"] == 0.12 and meta["model"] == "test/flash, test/judge" and meta["source"] == "web"
    assert meta["id"].endswith("_NVDA_standard") and len(meta["files"]) == 2
    folder = store / "archive" / meta["id"]
    assert {p.name for p in folder.iterdir()} == {"NVDA_standard.pdf", "NVDA_standard.json", "meta.json"}
    assert archive.file_path(meta["id"], "NVDA_standard.pdf").read_bytes() == b"%PDF-1.7 a"
    for eid, name in ((meta["id"], "meta.json"), (meta["id"], "../meta.json"), ("..", "NVDA_standard.pdf"),
                      (meta["id"], "x/NVDA_standard.pdf"), ("../archive", "NVDA_standard.pdf"),
                      (meta["id"], "missing.pdf"), ("nope", "NVDA_standard.pdf")):
        assert archive.file_path(eid, name) is None, (eid, name)
    second = archive.save_report(load(), b"%PDF b", "standard")  # same second: its own folder
    assert second["id"] != meta["id"] and second["rating"] == "Buy" and second["ai"] is False
    assert [e["id"] for e in archive.entries()][0] == second["id"]  # newest first


def test_saving_can_be_turned_off(store, monkeypatch):
    monkeypatch.setenv("INVESTSYNC_ARCHIVE", "0")
    assert archive.save_report(load(), b"%PDF", "data") is None and archive.entries() == []


def _run_folder(base: Path, folder: str, deep_cost=0.3, simple_cost=0.2, fixed=("learner.pdf",)):
    d = base / folder / "XYZ"
    d.mkdir(parents=True)
    (d / "deep.json").write_text(written("deep", cost=deep_cost).model_dump_json(), encoding="utf-8")
    (d / "simple.json").write_text(written(cost=simple_cost).model_dump_json(), encoding="utf-8")
    for n in ("deep.pdf", "simple.pdf", "learner.pdf"):
        (d / n).write_bytes(b"%PDF " + n.encode())
    if fixed:
        (base / folder / "XYZ_fixed").mkdir()
        for n in fixed:
            (base / folder / "XYZ_fixed" / n).write_bytes(b"%PDF fixed")


def test_seed_copies_the_paid_runs_once(store):
    src = store / "output"
    _run_folder(src, archive.RUNS[0][0], fixed=("simple.pdf", "learner.pdf"))
    _run_folder(src, archive.RUNS[1][0], deep_cost=0.32, simple_cost=0.18)
    added = archive.seed(src)
    assert len(added) == 5 + 4
    by = {(e["group"].split(" (")[0], e["kind"], bool(e.get("note"))): e for e in added}
    deep2 = by[("Run 2", "deep", False)]
    assert deep2["cost_usd"] == 0.32 and deep2["source"] == "run" and deep2["mode"] == "deep"
    assert by[("Run 2", "standard", False)]["cost_note"] == "standard + learner written together"
    learner = by[("Run 2", "learner", False)]
    assert learner["cost_usd"] is None and "standard report's cost" in learner["cost_note"]
    fixed = by[("Run 2", "learner", True)]
    assert fixed["note"].startswith("Corrected version") and fixed["cost_usd"] == 0.0
    assert fixed["id"].endswith("_NVDA_learner_corrected_run2")  # the ticker from the data, not the folder
    assert archive.file_path(fixed["id"], "NVDA_learner.pdf").read_bytes() == b"%PDF fixed"
    assert ("Run 1", "standard", True) in by and ("Run 1", "deep", True) not in by  # only files that exist
    assert archive.seed(src) == [] and len(archive.entries()) == 9  # idempotent


def test_api_archive_lists_filters_and_serves(store):
    from fastapi.testclient import TestClient
    import api.main as main
    a = archive.save_report(written(), b"%PDF-1.7 a", "standard")
    archive.save_report(load(), b"%PDF b", "data")
    client = TestClient(main.app)
    assert len(client.get("/v1/archive").json()["entries"]) == 2
    only = client.get("/v1/archive", params={"kind": "data"}).json()["entries"]
    assert [e["kind"] for e in only] == ["data"]
    assert client.get("/v1/archive", params={"ticker": "nvda"}).json()["entries"]
    r = client.get(f"/v1/archive/{a['id']}/NVDA_standard.pdf")
    assert r.status_code == 200 and r.content == b"%PDF-1.7 a" and r.headers["content-type"] == "application/pdf"
    assert "attachment" in client.get(f"/v1/archive/{a['id']}/NVDA_standard.pdf",
                                      params={"download": "true"}).headers["content-disposition"]
    assert client.get(f"/v1/archive/{a['id']}/NVDA_standard.json").json()["profile"]["ticker"] == "NVDA"
    for bad in (f"/v1/archive/{a['id']}/meta.json", f"/v1/archive/{a['id']}/..%2Fmeta.json",
                f"/v1/archive/..%2F{a['id']}/NVDA_standard.pdf", "/v1/archive/nope/x.pdf"):
        assert client.get(bad).status_code == 404, bad
    page = client.get("/archive")
    assert page.status_code == 200 and "Every report we have generated" in page.text and 'href="/"' in page.text


def test_each_build_is_archived_once_not_per_download(store, monkeypatch):
    from fastapi.testclient import TestClient
    import api.main as main
    builds, renders = [], []
    monkeypatch.setattr(main, "build_tearsheet", lambda ticker, **kw: builds.append(kw) or written())
    monkeypatch.setattr(main, "render_pdf", lambda data, out, layout, data_only=False:
                        renders.append(layout) or b"%PDF-" + layout.encode())
    monkeypatch.setattr(main, "_store", {})
    client = TestClient(main.app)
    for _ in range(3):  # the preview, "open in new tab" and the download
        r = client.get("/v1/tearsheets/NVDA/pdf", params={"ai": "true"})
        assert r.status_code == 200 and r.content == b"%PDF-report"
    assert len(builds) == 1 and renders == ["report"]
    client.get("/v1/tearsheets/NVDA/pdf", params={"ai": "true", "layout": "tearsheet"})
    client.get("/v1/tearsheets/NVDA/pdf", params={"ai": "true", "refresh": "true"})  # a new build: a new entry
    kinds = sorted(e["kind"] for e in archive.entries())
    assert kinds == ["standard", "standard", "tearsheet"] and len(builds) == 2


def test_web_deep_and_learner_kinds():
    import api.main as main
    assert main._kind(written("deep"), "report") == "deep"
    assert main._kind(written("deep", status="placeholder"), "report") == "standard"
    assert main._kind(written(), "learner") == "learner" and main._kind(load(), "data") == "data"


# ---------------------------------------------------------------- the all-three job
class FakeSteps:
    """Stands in for the generate.py processes: records each command and its budget, writes the files it would."""

    def __init__(self, deep_cost=0.3, simple_cost=0.18, deep_status="generated", fail=()):
        self.calls, self.deep_cost, self.simple_cost, self.deep_status, self.fail = [], deep_cost, simple_cost, \
            deep_status, set(fail)

    def __call__(self, cmd, env, log_path, timeout):
        args = cmd[2:]
        assert Path(cmd[1]).name == "generate.py"
        opt = lambda k: args[args.index(k) + 1] if k in args else None  # noqa: E731
        self.calls.append((args, env.get("RUN_BUDGET_USD"), env.get("LLM_JUDGE_MODEL", "(server's)")))
        step = "deep" if "--ticker" in args else "standard" if "--data-from" in args else "render"
        if step in self.fail:
            return 1
        if step == "deep":
            Path(opt("--json")).write_text(written("deep", status=self.deep_status, cost=self.deep_cost)
                                           .model_dump_json(), encoding="utf-8")
        elif step == "standard":
            assert Path(opt("--data-from")).name == "deep.json"
            Path(opt("--json")).write_text(written(cost=self.simple_cost).model_dump_json(), encoding="utf-8")
        Path(opt("--output")).write_bytes(b"%PDF " + Path(opt("--output")).name.encode())
        return 0


def _job(monkeypatch, steps):
    from api import jobs
    monkeypatch.setattr(jobs, "_execute", steps)
    monkeypatch.setattr(jobs, "_jobs", {})
    return jobs.start("NVDA", background=False)


def test_all_three_job_runs_like_run_sh(store, monkeypatch):
    steps = FakeSteps(deep_cost=0.3, simple_cost=0.18)
    job = _job(monkeypatch, steps)
    v = job.view()
    assert v["stage"] == "done" and not v["running"] and v["error"] == "" and v["cost_usd"] == pytest.approx(0.48)
    (deep, b1, j1), (sl, b2, j2), (render, b3, _) = steps.calls
    assert deep[:6] == ["--ticker", "NVDA", "--mode", "deep", "--layout", "report"] and b1 == "0.60"
    assert sl[:6] == ["--data-from", str(job.folder / "deep.json"), "--mode", "single", "--layout", "learner"]
    assert b2 == "0.500" and j2 == "(server's)"           # run.sh: 0.80 - the deep report's cost, judge kept
    assert render[:2] == ["--from-json", str(job.folder / "simple.json")] and render[-2:] == ["--layout", "report"]
    assert b3 is None
    assert [r["kind"] for r in v["reports"]] == ["deep", "standard", "learner"]
    entries = {e["kind"]: e for e in archive.entries()}
    assert set(entries) == {"deep", "standard", "learner"}
    assert entries["deep"]["cost_usd"] == 0.3 and entries["learner"]["cost_usd"] is None
    assert len({e["group"] for e in entries.values()}) == 1 and entries["deep"]["group"].startswith("All three")
    assert json.loads((job.folder / "status.json").read_text())["stage"] == "done"


def test_costly_deep_drops_the_judge_then_stops(store, monkeypatch):
    steps = FakeSteps(deep_cost=0.62)
    job = _job(monkeypatch, steps)
    assert job.stage == "done" and steps.calls[1][1] is None and steps.calls[1][2] == ""  # Flash only, as run.sh
    assert "without the judgement model" in job.note
    steps = FakeSteps(deep_cost=0.9)
    job = _job(monkeypatch, steps)
    assert job.stage == "done" and len(steps.calls) == 1 and "stopped after it" in job.note
    assert [r["kind"] for r in job.reports] == ["deep"]


def test_unwritten_deep_report_stops_before_spending_more(store, monkeypatch):
    steps = FakeSteps(deep_status="placeholder")
    job = _job(monkeypatch, steps)
    v = job.view()
    assert v["stage"] == "failed" and v["failed_stage"] == "deep" and "'placeholder'" in v["error"]
    assert len(steps.calls) == 1 and archive.entries() == []


def test_failed_render_after_a_saved_json_is_redone_free(store, monkeypatch):
    steps = FakeSteps()
    real = steps.__call__

    def flaky(cmd, env, log_path, timeout):  # the deep step saves its JSON, then its PDF fails once
        rc = real(cmd, env, log_path, timeout)
        if "--ticker" in cmd:
            Path(cmd[cmd.index("--output") + 1]).unlink()
            return 1
        return rc
    job = _job(monkeypatch, flaky)
    assert job.stage == "done"
    assert steps.calls[1][0][:2] == ["--from-json", str(job.folder / "deep.json")]  # the free re-render


def test_one_job_at_a_time(store, monkeypatch):
    from api import jobs
    monkeypatch.setattr(jobs, "_jobs", {"x": jobs.Job(id="x", ticker="AAPL", folder=store, stage="deep")})
    with pytest.raises(jobs.Busy, match="already running for AAPL"):
        jobs.start("NVDA", background=False)


def test_api_runs(store, monkeypatch):
    from fastapi.testclient import TestClient
    import api.main as main
    from api import jobs
    monkeypatch.setattr(jobs, "_execute", FakeSteps())
    monkeypatch.setattr(jobs, "_jobs", {})
    client = TestClient(main.app)
    monkeypatch.setattr(main, "settings", SimpleNamespace(llm=SimpleNamespace(enabled=False), narrative_mode="single"))
    r = client.post("/v1/runs", json={"ticker": "NVDA"})
    assert r.status_code == 400 and "No AI key" in r.json()["detail"]
    monkeypatch.setattr(main, "settings", SimpleNamespace(llm=SimpleNamespace(enabled=True), narrative_mode="single"))
    assert client.post("/v1/runs", json={"ticker": "not a ticker!"}).status_code == 400
    r = client.post("/v1/runs", json={"ticker": "nvda"})
    assert r.status_code == 202
    job_id = r.json()["id"]
    for _ in range(100):
        v = client.get(f"/v1/runs/{job_id}").json()
        if not v["running"]:
            break
        time.sleep(0.05)
    assert v["stage"] == "done" and len(v["reports"]) == 3 and v["ticker"] == "NVDA"
    assert client.get(v["reports"][0]["pdf"]).status_code == 200
    assert client.get("/v1/runs").json()["runs"][0]["id"] == job_id
    assert client.get("/v1/runs/nope").status_code == 404
    monkeypatch.setattr(jobs, "_jobs", {"x": jobs.Job(id="x", ticker="AAPL", folder=store, stage="deep")})
    r = client.post("/v1/runs", json={"ticker": "NVDA"})
    assert r.status_code == 409 and "One paid job runs at a time" in r.json()["detail"]


# ---------------------------------------------------------------- the web page
def test_page_has_honest_times_the_fifth_card_and_the_archive_link():
    assert "2–4 MIN" not in PAGE and "2-4 min" not in PAGE and "takes a few minutes" not in PAGE
    for text in ("About 20–25 min", "About 15–25 min", "About 1–2 min", "About 35–40 min",
                 "measured on run 2", "about USD 0.30", "about USD 0.50", "free (no AI)"):
        assert text in PAGE, text
    assert 'name="report" value="all"' in PAGE and 'href="/archive"' in PAGE
    assert 'id="confirm"' in PAGE and "window.confirm" not in PAGE and "confirm(" not in PAGE.replace('"confirm"', "")
    assert 'fetch("/v1/runs", { method: "POST"' in PAGE and "pollJob" in PAGE


def test_seed_dev_imports_the_deepseek_rounds_once(store):
    src = store / "output"
    base = src / "compare_2026-11-08"
    # a round with one company per sub-folder, a nested listed round inside it, and an extra V4 Pro deep report
    for folder in ("deepseek_v4/NVDA", "deepseek_v4/first_nvda", "deepseek"):
        d = base / folder
        d.mkdir(parents=True)
        (d / "simple.json").write_text(written(cost=0.2).model_dump_json(), encoding="utf-8")
        (d / "simple.pdf").write_bytes(b"%PDF s")
        (d / "learner.pdf").write_bytes(b"%PDF l")
    (base / "deepseek" / "deep_pro.json").write_text(written("deep", cost=0.4).model_dump_json(), encoding="utf-8")
    (base / "deepseek" / "deep_pro.pdf").write_bytes(b"%PDF p")
    added = archive.seed_dev(src)
    groups = sorted({e["group"].split(" (")[0] for e in added})
    assert groups == ["DeepSeek v1", "DeepSeek v4", "DeepSeek v4, first attempt"]
    assert len(added) == 2 + 2 + 3   # first_nvda is not imported a second time under "DeepSeek v4"
    assert all(e["source"] == "dev" and e["note"].startswith("Development round") for e in added)
    pro = [e for e in added if e["kind"] == "deep"]
    assert len(pro) == 1 and "V4 Pro" in pro[0]["note"] and pro[0]["cost_usd"] == 0.4
    assert archive.seed_dev(src) == []   # idempotent


def test_each_entry_gets_its_source_pack_and_the_api_serves_it(store):
    from fastapi.testclient import TestClient
    import api.main as main
    meta = archive.save_report(written(), b"%PDF-1.7 a", "standard", source="web")
    full = archive.add_pack(meta["id"])
    types = {f["type"]: f["name"] for f in full["files"]}
    assert {"pdf", "json", "xlsx", "sources", "zip"} <= set(types)
    assert archive.file_path(meta["id"], types["xlsx"]).read_bytes()[:2] == b"PK"      # a real workbook
    assert archive.add_pack(meta["id"])["files"] == full["files"]                         # built once
    client = TestClient(main.app)
    r = client.get(f"/v1/archive/{meta['id']}/pack")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and "attachment" in \
        r.headers["content-disposition"]
    x = client.get(f"/v1/archive/{meta['id']}/{types['xlsx']}")
    assert x.status_code == 200 and "attachment" in x.headers["content-disposition"]
    assert client.get("/v1/archive/nope/pack").status_code == 404
    assert archive.add_packs() == 0                                                       # nothing missing
