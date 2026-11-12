"""Exercise pack: the facts our report writers read, as ONE text file a free AI chat can take, with none of our
own report text in it. For the "write the notes yourself" exercise (skill/investsync-research-notes/SKILL.md).

    .venv/bin/python tools/exercise_pack.py output/archive/2026-11-12_225950_NVDA_standard_run4/NVDA_standard.json
    .venv/bin/python tools/exercise_pack.py output/archive/2026-11-12_225950_NVDA_deep_run4/NVDA_deep.json

Writes output/exercise_pack/exercise_pack_<TICKER>_<standard|deep>.md (or --out PATH). Free: no AI, no network; built
from a saved report JSON with the same functions the pipeline uses for its writers (commentary._assemble, the deep
evidence set, the learner guide). The numbers in it (our forecast, scenarios, fair value, rating) are fixed; the AI
writes the words around them.

Why a separate file and not the source data pack: the pack's data.json holds the report's own text
(``narrative``), so an AI given it could copy our notes, and at ~110k tokens it is too big for free accounts.
This file is ~20k tokens. The script stops (exit 1) if any of our report's text is found in it.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from investsync.narrative import commentary, evidence, learner  # noqa: E402
from investsync.render import learner_vm  # noqa: E402
from investsync.schema import TearSheetData  # noqa: E402

# parts of the saved narrative that are code-made data shared with the inputs, not our writing
_NOT_WRITING = ("deep.scenarios", "deep.evidence", "deep.review", "guardrail", "status", "model", "mode")


def _strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def leaks(narrative: dict, text: str) -> list[str]:
    """Paths of our report's own sentences that appear in ``text``: the start, middle and end (60 characters each) of
    a long string must all be found. Only the start is not enough: a writer may open a sentence with a source's own
    words (run 4's catalyst "Colette Kress is set to take over as interim CEO from Jensen Huang, the company said; in
    our view ..." starts with a Reuters line that is in the pack)."""
    out, flat = [], " ".join(text.split())
    for path, s in _strings(narrative or {}):
        if any(path == p or path.startswith(p + ".") or path.startswith(p + "[") for p in _NOT_WRITING):
            continue
        s = " ".join(s.split())
        if len(s) < 60:
            continue
        mid = len(s) // 2 - 30
        if all(w in flat for w in (s[:60], s[mid:mid + 60], s[-60:])):
            out.append(path)
    return out


HEADER = """# InvestSync exercise pack: {name} ({ticker}), {kind} report

Built {built} from the InvestSync report data of {generated}. Prices are as of {asof}.

What this file is: the facts the InvestSync report writers were given for this stock, word for word. The report's
own text (thesis, sections, debate, learner notes) is NOT in it: writing that text is the exercise. Use it with
SKILL.md (skill/investsync-research-notes).

What is fixed: every number, our three-year forecast, the bear / base / bull scenarios, the fair value and the rating
were set before the writing. Explain them; never change them.

Ids you can cite: [R..] research notes (dated, with their source), [E..] numbered facts below, [S..] signals computed
in code (each with the side its sign supports).

Sections: 1. Facts and signals · 2. Filing excerpts · 3. Recent news{guide_line}
"""


def build(path: Path) -> tuple[str, str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    narrative = raw.get("narrative") or {}
    deep = (narrative.get("mode") == "deep") or bool(narrative.get("deep"))
    raw["narrative"] = None                      # nothing below may read our own text
    data = TearSheetData.model_validate(raw)
    vm, rvm, facts, filings, *_ = commentary._assemble(data)
    news = commentary.tagged_news_text(data) or ""
    news_ev = ("\n\nRecent news (third-party reports; attribute them, and prefer company figures where they "
               "differ):\n" + news) if news.startswith("- [") else ""
    ev = evidence.build(data, facts + news_ev).text
    guide = "" if deep else learner.guide_text(learner_vm.build(data))
    p, q = data.profile, data.quote
    kind = "deep" if deep else "standard"
    parts = [HEADER.format(name=p.name, ticker=p.ticker, kind=kind, built=datetime.now().strftime("%d %b %Y"),
                           generated=str(raw.get("generated_at", ""))[:10], asof=q.as_of,
                           guide_line=" · 4. Learner guide (for the learner's notes)" if guide else ""),
             "## 1. Facts and signals\n\n" + ev,
             "## 2. Filing excerpts (latest annual / interim report)\n\n"
             + re.sub(r"(?m)^## ", "### ", filings or "None"),
             "## 3. Recent news\n\n" + ("The news items are in section 1 (after the numbered facts)."
                                        if news_ev else (news or "None"))]
    if guide:
        parts.append("## 4. Learner guide: the 8 steps with this company's numbers\n\n" + guide)
    text = "\n\n".join(parts).strip() + "\n"
    bad = leaks(narrative, text)
    if bad:
        raise SystemExit(f"STOP: our report's own text is in the pack ({', '.join(bad[:8])}); not written")
    return text, p.ticker.replace(".", "_"), kind


def main() -> None:
    logging.basicConfig(level=logging.ERROR)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_json", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    text, ticker, kind = build(a.report_json)
    out = a.out or ROOT / "output" / "exercise_pack" / f"exercise_pack_{ticker}_{kind}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"{out}  {len(text):,} characters (~{len(text) // 4:,} tokens); no report text found in it")


if __name__ == "__main__":
    main()
