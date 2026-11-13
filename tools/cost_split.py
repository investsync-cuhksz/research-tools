"""The AI cost of each report in an all-three set (run 3, 12 Nov 2026).

Karel: "divided into 3, showing which contributes to which; if 2 reports share the same tokens (e.g. the research
extraction) you can divide that cost equally".

    python tools/cost_split.py DEEP.json SIMPLE.json [--out cost_split.json]

How the set is made (api/jobs.py): the deep run comes first; the
standard report and the learner's guide are then written in ONE second run on the deep run's saved data, reusing its
research, forecast, scenarios, thesis memo and chosen analyst questions. So:
  * deep run, shared phases (SHARED3)   -> split equally over the three reports;
  * deep run, every other phase         -> the deep report;
  * second run, "learner coach"         -> the learner's guide;
  * second run, every other phase       -> split equally between the standard report and the learner's guide.
Needs ai_usage.by_phase (run 3 on; schema 1.12). Older JSON files only have the coarser by_step, which cannot be
split this way: the tool says so and stops.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# "deciding year" (run 4): made once in the deep run; the standard report and the guide print the same table
SHARED3 = {"research", "peers", "forecast", "scenarios", "scenario check", "analyst brief", "questions", "deciding year"}
LEARNER_ONLY = {"learner coach"}
REPORTS = ("standard", "learner", "deep")


def split(deep: dict, simple: dict) -> dict:
    rows = []
    for run, d in (("deep run", deep), ("second run", simple)):
        phases = ((d.get("ai_usage") or {}).get("by_phase") or {})
        if not phases and (d.get("ai_usage") or {}).get("calls"):
            raise ValueError(f"{run}: no ai_usage.by_phase (made before run 3), so the cost cannot be split by report")
        for name, p in sorted(phases.items(), key=lambda kv: -kv[1].get("est_cost_usd", 0)):
            c = float(p.get("est_cost_usd") or 0)
            if run == "deep run":
                share = ({r: c / 3 for r in REPORTS} if name in SHARED3 else {"deep": c})
                rule = "shared by all three" if name in SHARED3 else "deep report only"
            else:
                share = ({"learner": c} if name in LEARNER_ONLY else {"standard": c / 2, "learner": c / 2})
                rule = "learner's guide only" if name in LEARNER_ONLY else "shared by standard and learner"
            rows.append({"run": run, "phase": name, "cost_usd": round(c, 5), "calls": p.get("calls", 0),
                         "tokens_in": p.get("prompt_tokens", 0), "tokens_out": p.get("completion_tokens", 0),
                         "thinking": p.get("reasoning_tokens", 0), "models": p.get("models", []), "rule": rule,
                         "share": {r: round(share.get(r, 0.0), 5) for r in REPORTS}})
    totals = {r: round(sum(x["share"][r] for x in rows), 4) for r in REPORTS}
    by_model: dict[str, float] = {}
    for x in rows:  # a phase with a fallback can have two models: its cost goes to the first listed
        m = (x["models"] or ["?"])[0]
        by_model[m] = round(by_model.get(m, 0.0) + x["cost_usd"], 5)
    return {"reports": totals, "total_usd": round(sum(totals.values()), 4), "by_model": by_model, "rows": rows}


def table(res: dict) -> str:
    out = ["| Run | Phase | Models | Calls | Tokens in / out | USD | Standard | Learner | Deep |",
           "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for x in res["rows"]:
        out.append(f"| {x['run']} | {x['phase']} | {', '.join(m.split('/')[-1] for m in x['models'])} | {x['calls']} | "
                   f"{x['tokens_in']:,} / {x['tokens_out']:,} | {x['cost_usd']:.4f} | {x['share']['standard']:.4f} | "
                   f"{x['share']['learner']:.4f} | {x['share']['deep']:.4f} |")
    t = res["reports"]
    out.append(f"| | **Total** | | | | **{res['total_usd']:.4f}** | **{t['standard']:.4f}** | **{t['learner']:.4f}** | "
               f"**{t['deep']:.4f}** |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("deep", type=Path)
    ap.add_argument("simple", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        res = split(json.loads(a.deep.read_text()), json.loads(a.simple.read_text()))
    except ValueError as e:
        print(e)
        return 1
    print(table(res))
    print("by model:", res["by_model"])
    if a.out:
        a.out.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
