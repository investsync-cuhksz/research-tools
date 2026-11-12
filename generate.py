"""Command-line entry point.

  python generate.py --ticker 0700.HK --output output/tencent_tearsheet.pdf
  python generate.py --batch covered_tickers.txt --output-dir output/
  python generate.py --ticker NVDA --json output/nvda.json --no-ai
  python generate.py --ticker 0700.HK --layout tearsheet           # page 1 only
  python generate.py --ticker 0700.HK --mode deep                  # analyst, bull / bear debate, judge, reviewer
  python generate.py --ticker 0700.HK --layout learner             # page 1 + learner's guide for beginners
  python generate.py --ticker 0700.HK --datapack output/0700_HK_datapack.zip [--datapack-docs]
                                                                   # + source data (Excel, links, JSON[, filings])
  python generate.py --ticker 0700.HK --data-only                  # data-only edition: no AI call, no AI text,
                                                                   # no rating; boxes for the reader's own view
  python generate.py --from-json output/nvda.json --data-only      # the same from saved data (no fetch)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from investsync.datapack import build_datapack
from investsync.pipeline import build_tearsheet
from investsync.render.render import render_pdf
from investsync.schema import TearSheetData


def _datapack(data: TearSheetData, out: Path, docs: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_datapack(data, include_filing_docs=docs))
    print(f"data pack {out}")


def _pdf(data: TearSheetData, out: Path, layout: str, data_only: bool) -> None:
    if data_only and layout == "tearsheet":
        render_pdf(data, out, layout="tearsheet", data_only=True)
    else:
        render_pdf(data, out, layout="data" if data_only else layout)


def _one(ticker: str, pdf_out: Path | None, json_out: Path | None, ai: bool,
         mode: str | None = None, filings: bool = True, layout: str = "report",
         datapack: Path | None = None, datapack_docs: bool = False, base: TearSheetData | None = None,
         data_only: bool = False) -> TearSheetData:
    t0 = time.time()
    if data_only:  # no AI call at all, no rating (pipeline.build_tearsheet)
        data = build_tearsheet(ticker, with_filings=filings, base=base, data_only=True)
    else:
        data = build_tearsheet(ticker, with_narrative=ai, mode=mode, with_filings=filings,
                               learner=layout == "learner", base=base)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    if pdf_out:
        _pdf(data, pdf_out, layout, data_only)
    if datapack:
        _datapack(data, datapack, datapack_docs)
    n = "data-only" if data_only else data.narrative.status if data.narrative else "none"
    val = data.valuation and (data.valuation.dcf and "DCF" or data.valuation.ddm and "DDM") or "-"
    print(f"{data.profile.ticker:>10}  {data.profile.name[:32]:<32}  commentary={n:<11} "
          f"val={val} reports={len(data.filings)} {time.time() - t0:5.1f}s  -> {pdf_out or json_out}")
    for w in data.warnings:
        print(f"{'':>12}note: {w}")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="InvestSync tear sheet generator")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ticker", help="e.g. 0700.HK, 600519.SH, NVDA")
    src.add_argument("--batch", type=Path, help="file with one ticker per line")
    src.add_argument("--from-json", type=Path, help="render a saved TearSheetData JSON (no data fetch)")
    src.add_argument("--data-from", type=Path, metavar="JSON",
                     help="write new AI commentary (e.g. --mode deep) on the data saved in a JSON, without fetching "
                          "again, so two reports of one day use the same figures")
    ap.add_argument("--output", type=Path, help="PDF path (single ticker)")
    ap.add_argument("--output-dir", type=Path, default=Path("output"), help="directory for batch output")
    ap.add_argument("--json", type=Path, help="also write the JSON payload here (single ticker)")
    ap.add_argument("--no-ai", action="store_true", help="skip the AI commentary")
    ap.add_argument("--data-only", action="store_true",
                    help="the data-only edition: no AI call at all (automatic peers, no commentary, research, news "
                         "tags, forecast or scenarios), no rating; the PDF has 'Your analysis' boxes to write in. "
                         "With --from-json, the saved data's AI parts and rating are left out")
    ap.add_argument("--mode", choices=["single", "two_step", "deep"],
                    help="commentary mode (default: NARRATIVE_MODE); deep = analyst, bull / bear debate, judge, reviewer")
    ap.add_argument("--no-filings", action="store_true", help="do not read the latest annual/interim report")
    ap.add_argument("--layout", choices=["report", "tearsheet", "learner"], default="report",
                    help="report = tear sheet + full research report (default); tearsheet = page 1 only; "
                         "learner = page 1 with step markers + learner's guide")
    ap.add_argument("--datapack", type=Path, metavar="PATH.zip",
                    help="also write the source data pack: Excel workbook (statements, ratios, valuation workings, "
                         "peers, prices, brokers, sources), sources.pdf and the JSON (with --ticker or --from-json)")
    ap.add_argument("--datapack-docs", action="store_true",
                    help="also download the original filings into the data pack (slower: HKEXnews can take minutes)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    if a.datapack and a.batch:
        ap.error("--datapack works with --ticker or --from-json")
    if a.datapack_docs and not a.datapack:
        ap.error("--datapack-docs needs --datapack PATH.zip")
    if a.data_only and a.layout == "learner":
        ap.error("--data-only has no learner's guide: use --layout report (default) or tearsheet")
    if a.data_only and a.mode:
        ap.error("--data-only makes no AI call, so --mode does not apply")
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    if a.from_json:
        data = TearSheetData.model_validate_json(a.from_json.read_text(encoding="utf-8"))
        out = a.output or a.from_json.with_suffix(".pdf")
        if a.data_only:
            from investsync.render import dataonly
            data = dataonly.strip(data)  # the data pack too: no AI parts, no rating
            _pdf(data, out, a.layout, True)
        else:
            render_pdf(data, out, layout=a.layout)
        print(f"rendered {out}")
        if a.datapack:
            _datapack(data, a.datapack, a.datapack_docs)
        return 0

    if a.data_from:
        base = TearSheetData.model_validate_json(a.data_from.read_text(encoding="utf-8"))
        t = base.profile.ticker
        _one(t, a.output or Path("output") / f"{t.replace('.', '_').upper()}.pdf", a.json, not a.no_ai, a.mode,
             not a.no_filings, a.layout, a.datapack, a.datapack_docs, base=base, data_only=a.data_only)
        return 0

    if a.ticker:
        safe = a.ticker.replace(".", "_").upper()
        _one(a.ticker, a.output or Path("output") / f"{safe}.pdf", a.json, not a.no_ai, a.mode, not a.no_filings,
             a.layout, a.datapack, a.datapack_docs, data_only=a.data_only)
        return 0

    tickers = [ln.split("#")[0].strip() for ln in a.batch.read_text(encoding="utf-8").splitlines()]
    tickers = [t for t in tickers if t]
    failures = []
    for t in tickers:
        safe = t.replace(".", "_").upper()
        try:
            _one(t, a.output_dir / f"{safe}.pdf", a.output_dir / f"{safe}.json", not a.no_ai, a.mode,
                 not a.no_filings, a.layout, data_only=a.data_only)
        except Exception as e:  # keep going; report at the end
            failures.append((t, e))
            print(f"{t:>10}  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"\n{len(tickers) - len(failures)}/{len(tickers)} tear sheets generated in {a.output_dir}/")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
