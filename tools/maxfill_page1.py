"""Stress-test page 1: fill every AI field to its word limit (dummy text) and render.

  python tools/maxfill_page1.py output/report_batch_ai/0700_HK.json /tmp/max.pdf [--deep] [--layout tearsheet]

--deep adds a deep-mode verdict, so the extra "AI debate" line on page 1 is included (worst case).
Prints the page count; page 1 must stay ONE page (`--layout tearsheet`).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PdfReader

from investsync.narrative.commentary import SECTIONS
from investsync.quant import overall as overall_view
from investsync.render.render import render_pdf
from investsync.schema import Bullet, DeepAnalysis, GuardrailReport, Narrative, TearSheetData

WORDS = ("The business keeps compounding as services with higher margins grow faster than the group while capital "
         "returns continue").split()


def words(n: int) -> str:
    return " ".join((WORDS * (n // len(WORDS) + 1))[:n]) + "."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--layout", default="tearsheet")
    a = ap.parse_args()
    d = TearSheetData.model_validate_json(a.src.read_text(encoding="utf-8"))
    from investsync.config import settings
    # the blended overall view is off by default since 9 Nov 2026 (OVERALL_VIEW=0): page 1 shows the Street line
    d.overall = (d.overall or overall_view.build(d)) if settings.overall_view else None
    d.narrative = Narrative(
        status="generated", model="dummy-max-length", dupont_commentary=words(55), comps_commentary=words(60),
        catalysts=[Bullet(title="Video Accounts monetisation", text=words(35)) for _ in range(3)],
        risks=[Bullet(title="Regulatory scrutiny", text=words(35)) for _ in range(2)],
        guardrail=GuardrailReport(passed=True, attempts=1), key_takeaways=[words(22)] * 6,
        events_to_monitor=[Bullet(title="Results", text=words(30))] * 4,
        **{k: words(lim) for k, (_, lim) in SECTIONS.items()})
    if a.deep:
        d.narrative.deep = DeepAnalysis(stronger_side="balanced", conviction="medium", verdict="x", swing_factor="y",
                                        rating_alignment="disagrees")
    if d.street:
        for n in d.street.notes[:12] + d.street.writeups:
            n.summary_en = words(28)
        d.street.synthesis = words(90)
    render_pdf(d, a.out, layout=a.layout)
    print(f"{a.src.name}: {len(PdfReader(a.out).pages)} page(s) -> {a.out}")


if __name__ == "__main__":
    main()
