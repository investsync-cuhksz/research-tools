"""Ticker in, TearSheetData out: data -> deterministic metrics -> valuation -> commentary."""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from concurrent.futures import ThreadPoolExecutor

from . import history, provenance, tickers
from .config import settings
from .data import adapters, brokers, extras, filings
from .data import sources as src
from .quant import audit, metrics, overall, ranges, rating, ratios, scorecard, street, technical, valuation
from .schema import Benchmark, Event, FilingExcerpt, TearSheetData

log = logging.getLogger(__name__)


class _Background(threading.Thread):
    """Fetch filings while market data loads (report PDFs can be slow to download)."""

    def __init__(self, canonical: str):
        super().__init__(daemon=True)
        self.canonical = canonical
        self.result: list[FilingExcerpt] = []
        self._fetch = provenance.wrap(filings.fetch)  # keep recording sources in this thread

    def run(self) -> None:
        self.result = self._fetch(self.canonical)


def _range_to_price_date(data: TearSheetData) -> None:
    """Keep the 52-week range on the report's price date. A live quote's range can include today's session, after the
    last close the report uses (round 13, run 4: a 12 Nov intraday low of 148.80 printed as the 52-week low in a report
    priced at the 11 Nov close, whose low was 164.27). The daily history ends at the price date, so a quote figure more
    than 2% outside the history's range (the margin covers the history's dividend adjustment) is replaced by it."""
    q, tech = data.quote, data.technicals
    if q.week52_low and tech.low_52w and q.week52_low < tech.low_52w * 0.98:
        q.week52_low = tech.low_52w
    if q.week52_high and tech.high_52w and q.week52_high > tech.high_52w * 1.02:
        q.week52_high = tech.high_52w


def _quality_news(items: list) -> list:
    """The news the report shows and the writer reads. Since 12 Nov 2026 (run 3) only outlets on the team's list
    (config/news_sources.json, see newssources.py) are kept, even if that leaves none: run 2 showed 179 items, mostly
    Motley Fool, newsletters and auto-generated stories. With the list off (NEWS_ALLOWLIST=0) the old rule applies:
    drop content-farm and crypto/prediction-market sites (the research desk's LOW_TIER list; round-4 news included
    Stocktwits, 24/7 Wall St and a crypto site's "Nov. 11 deadline" about the CEO probe)."""
    from . import newssources
    from .research.desk import LOW_TIER
    kept = [n for n in items if not LOW_TIER.search(f"{n.source or ''} {n.url or ''}")
            and newssources.allowed(n.source or "", n.url or "")]
    if newssources.enabled():
        if len(kept) < len(items):
            log.info("news: kept %d of %d items from the approved outlets", len(kept), len(items))
        return kept
    return kept if kept else items


def _risk_free(data: TearSheetData) -> tuple[dict[str, float], str]:
    """The 10-year yields for the WACC (EastMoney, then Yahoo for the US yield, then the last saved copy) and the
    sources line for them. A data note says when a backup was used, or when none worked: a report without a
    valuation must not look like a complete one."""
    need = valuation.rf_label(data)
    yields, notes = src.risk_free_yields(need)
    data.warnings += notes
    if need not in yields:
        log.warning("valuation skipped for %s: no %s yield from any source", data.profile.ticker, need)
        data.warnings.append(f"Valuation not shown: the risk-free rate ({need} government bond yield) could not be "
                             "fetched from any source, and no earlier copy was saved.")
    return yields, ("US 10-year yield (^TNX) via Yahoo Finance" if notes else
                    "ChinaBond / US Treasury yields via EastMoney")


def build_data(ticker: str, with_filings: bool = True, ai_peers: bool = True) -> TearSheetData:
    """``ai_peers``: let an AI model pick the peers when no curated list exists (PEER_MODE=ai); False keeps the
    automatic list, so the build makes no AI call at all (the data-only edition)."""
    t = tickers.parse(ticker)
    records = provenance.start()
    bg: Optional[_Background] = None
    if with_filings and settings.filings_enabled:
        bg = _Background(t.canonical)
        bg.start()

    try:
        md = adapters.load(t)
    except LookupError:
        raise
    except Exception as e:  # the data libraries crash on codes they do not know (e.g. ZZZZ, 999999.SH)
        log.warning("market data failed for %s: %r", t.canonical, e)
        raise LookupError(f"No market data found for {t.canonical}. Check the code; if it is right, a data "
                          f"source may be down, so try again later.") from e
    if ai_peers and not adapters.curated_peers(t.canonical):
        from .narrative import peers as peer_ai  # imported lazily: dspy is slow to import
        picked = peer_ai.select(t, md)
        if picked:
            md.peers, md.peer_method = picked
            md.comps_target = adapters.comp_row(t)
            md.comps_target.name = adapters._short_name(md.profile.name)
    # round 9: the company's own comps row is fetched live (Yahoo / EastMoney) while the quote is at the last close;
    # put it at the close too, so P/E and forward P/E agree with page 1. A ratio outside 0.8-1.25 means the two
    # market caps are defined differently (e.g. H-shares only vs all shares): left alone.
    tg, q = md.comps_target, md.quote
    if tg is not None and tg.market_cap and q.market_cap and (tg.currency or q.currency) == q.currency:
        k = q.market_cap / tg.market_cap
        if 0.8 < k < 1.25:
            md.comps_target = adapters._at_close_row(tg, k)
    from .data import sec_balance
    sec_note = sec_balance.apply(t, md.financials)  # US: cash and debt as filed (before ratios are computed)
    fin = metrics.finalize_financials(md.financials)
    warnings = list(md.warnings) + metrics.restate_eps_for_splits(fin.years, md.share_actions)
    wb = metrics.warranty_break(fin, t.market)  # A-shares: gross margins across the 2024 warranty reclassification
    if wb:
        warnings.append(wb)
    if sec_note:
        warnings.append(sec_note)
        if all(y.total_debt is not None for y in fin.years):  # SEC filled the years Yahoo's debt history lacks
            warnings = [w for w in warnings if not w.startswith("Debt history from Yahoo")]
    if len(fin.years) < 5:
        warnings.append(f"Only {len(fin.years)} fiscal years available.")

    # Enterprise value = market cap + net debt + minority interests (latest balance sheet, in trading currency).
    # Minorities added 9 Nov 2026 (round-3 review: "use a consistent EV definition (include minorities)"; peers'
    # EVs from Yahoo include them).
    q = md.quote
    latest = fin.years[-1] if fin.years else None
    use_lt = fin.latest is not None and fin.latest.net_debt is not None
    nd = fin.latest.net_debt if use_lt else latest.net_debt if latest else None
    mi = ((fin.latest.minority_interest if use_lt else latest.minority_interest if latest else None) or 0.0)
    if q.market_cap is not None and nd is not None and q.fx_to_reporting:
        q.enterprise_value = q.market_cap + (nd + mi) / q.fx_to_reporting
    q.next_earnings_date = md.earnings_date

    comps = metrics.build_comps(md.comps_target, md.peers, md.peer_method) if md.peers else None
    if comps is None:
        warnings.append("No comparable peers found automatically; a curated peer list is needed (finance team).")
    elif len(md.peers) < 3:
        warnings.append(f"Only {len(md.peers)} peers found.")

    stock = {r.date: float(r.close) for r in md.prices.itertuples()}
    bench = {r.date: float(r.close) for r in md.benchmark.itertuples()}
    name, code = tickers.BENCHMARKS[t.market]
    periods = metrics.rebase_periods(stock, bench)
    benchmark = Benchmark(name=name, code=code, periods=periods) if periods else None

    data = TearSheetData(
        generated_at=datetime.now(timezone.utc),
        profile=md.profile, quote=q, financials=fin,
        dupont=metrics.dupont(fin), earnings_quality=metrics.earnings_quality(fin),
        comps=comps, benchmark=benchmark, news=_quality_news(md.news),
        sources=md.sources, warnings=warnings)

    # Full-report extras load in parallel with the valuation (each one is failure-tolerant)
    pool = ThreadPoolExecutor(max_workers=6)
    sub = lambda *a, **k: provenance.submit(pool, *a, **k)  # noqa: E731 (keeps source recording)
    jobs = {
        "company": sub(extras.safe, extras.company_facts, t),
        "officers": sub(extras.safe, extras.officers, t, default=[]),
        "consensus": sub(extras.safe, extras.consensus, t, data),
        "dividends": sub(extras.safe, extras.dividends, t, default=[]),
        "segments": sub(extras.safe, extras.segments, t, latest.period_end if latest else None, default=[]),
        "ownership": sub(extras.safe, extras.ownership, t),
        "implied_move": sub(extras.safe, extras.implied_move, t, data),  # sets data.quote fields (US)
        "ah_premium": sub(extras.safe, extras.ah_premium, t, data),  # sets data.quote fields (A + H listings)
        "events": sub(extras.safe, extras.events, t, data, default=[]),
        "announcements": sub(extras.safe, extras.announcements, t, default=([], 0)),
        "broker_notes": sub(extras.safe, brokers.load_all, t, adapters._yf_symbol(t), fin.currency,
                            md.profile.name, md.profile.name_local, default=([], [])),
    }

    try:
        yields, rates = _risk_free(data)
        data.valuation = valuation.build(data, stock, bench, yields,
                                         src.yf_revenue_estimates(adapters._yf_symbol(t)))
        if data.valuation:
            data.sources.append(f"{rates}; analyst consensus via Yahoo Finance; equity risk premium: "
                                "Damodaran (Jan 2026)")
    except Exception as e:
        log.exception("valuation failed")
        data.warnings.append(f"Valuation step failed: {type(e).__name__}.")

    statutory = valuation.load_config(t.canonical)
    data.ratios = ratios.ratio_years(fin.years, valuation._pick(statutory, "statutory_tax", fin.currency, 0.25))
    data.technicals = extras.safe(technical.compute, md.prices, bench)
    if data.technicals:
        _range_to_price_date(data)
    if data.technicals and data.quote.week52_high and data.quote.week52_low:
        # the price history is dividend-adjusted (right for returns); the 52-week range must be the traded one,
        # as on page 1 (round-4 review: 163.77 in the table vs 164.27 on page 1)
        data.technicals.high_52w, data.technicals.low_52w = data.quote.week52_high, data.quote.week52_low
    data.pe_band = extras.safe(ranges.pe_band, md.prices, data)
    notes, writeups = [], []
    for name, job in jobs.items():
        if name == "announcements":
            data.announcements, data.announcements_routine = job.result()
        elif name == "broker_notes":
            notes, writeups = job.result() or ([], [])
        elif name in ("implied_move", "ah_premium"):
            job.result()  # writes into data.quote
        else:
            setattr(data, name, job.result())
    pool.shutdown(wait=False)
    if data.consensus is not None and md.prices is not None and not md.prices.empty:
        # close about 90 days before the price date, for the re-rating vs estimate-revision split
        cut = q.as_of - timedelta(days=90)
        before = md.prices[md.prices["date"] <= cut]
        if len(before):
            data.consensus.price_90d_ago = float(before.sort_values("date")["close"].iloc[-1])
    data.football_field = extras.safe(ranges.football_field, data, data.consensus)
    data.rating = extras.safe(rating.compute, data)  # rule-based "AI rating" (the AI only explains it)
    data.street = extras.safe(street.build, data, notes, writeups=writeups)  # brokers vs each other and the model
    # model + recent broker views blended: only with OVERALL_VIEW=1 (page 1 shows the Street separately)
    data.overall = extras.safe(overall.build, data) if settings.overall_view else None
    data.scorecard = extras.safe(scorecard.build, data)           # yes/no checks; never feeds the rating
    data.since_last = extras.safe(history.compare, data)          # vs the previous saved report
    if data.consensus or data.officers or data.dividends:
        data.sources.append("Yahoo Finance (analyst consensus, management, dividends, ownership)")

    if bg is not None:
        bg.join(timeout=settings.filings_timeout)
        if bg.is_alive():
            data.warnings.append("Latest report is still downloading; commentary uses news only this time.")
        else:
            data.filings = bg.result
            if data.filings:
                data.sources.append(", ".join(sorted({f.source for f in data.filings})) + " (latest reports)")
                for f in data.filings:
                    if f.filed:
                        data.events.append(Event(on=f.filed, label=f"Filed: {f.title}", kind="report"))
                data.events.sort(key=lambda e: e.on or date.max)
    from .data import filing_facts  # 1.10: key items as filed; "not reported" where the filed data lacks them
    data.filing_facts = filing_facts.build(t, data)
    data.warnings += provenance.stale_notes(records)  # older copies used because a live source failed
    data.audit = audit.run(data)
    missing = provenance.unregistered(records)
    if missing:
        log.warning("source calls without a citation entry: %s", missing)
    data.citations = provenance.citations(records, data, {
        "price_history": md.prices.attrs.get("source"), "index_history": md.benchmark.attrs.get("source")})
    return data


def build_tearsheet(ticker: str, with_narrative: bool = True, mode: Optional[str] = None,
                    with_filings: bool = True, learner: bool = False,
                    base: Optional[TearSheetData] = None, data_only: bool = False) -> TearSheetData:
    """``mode``: single / two_step / deep. ``learner``: also write the AI notes of the learner's guide.
    ``base``: data saved by an earlier run (generate.py --data-from): no new fetch, its research and house forecast
    are reused, and only the commentary is written again. Two reports of one day then use the same figures (round-4
    review: the simple and deep reports, fetched 39 minutes apart, gave fair values of 251.61 and 268.71 because one
    peer's EV/EBITDA was missing in one fetch).
    ``data_only`` (12 Nov 2026): the data-only edition. No AI call at all (automatic peers; no research desk,
    commentary, news tags, forecast or scenarios) and no verdict (no rating, overall view or model fair value; see
    render/dataonly.py); ``with_narrative``, ``mode`` and ``learner`` are ignored. With ``base`` the saved data is
    used without a new fetch, its AI parts removed. No history snapshot is saved: the snapshots record the rating."""
    if data_only:
        from .render import dataonly
        return dataonly.strip(base if base is not None else build_data(ticker, with_filings=with_filings,
                                                                       ai_peers=False))
    from .narrative import commentary  # imported lazily: dspy is slow to import
    snap = commentary.usage_snapshot()
    prev_brief = None
    if base is not None:
        data = base.model_copy(deep=True)
        prev_brief = base.narrative.brief if base.narrative else None
        data.narrative, data.ai_usage = None, None
        data.audit = audit.run(data)  # as when the base run's writer started (its saved audit also checked its text)
    else:
        data = build_data(ticker, with_filings=with_filings)
    if with_narrative and settings.research_enabled and settings.llm.enabled and data.research is None:
        try:  # read results releases, announcements, broker reports and news first (evidence, never the rating)
            from .research import desk
            desk.english_labels(data)  # Chinese segment names (EastMoney) -> the company's English terms
            from .narrative.commentary import usage_phase
            with usage_phase("research"):  # run 3: ai_usage.by_phase
                data.research = desk.run(data, tickers.parse(ticker))
        except Exception as e:  # research is optional: the report still has the data and the filings
            log.exception("research failed")
            data.warnings.append(f"Research step failed: {type(e).__name__}.")
    if with_narrative:
        try:
            data.narrative = commentary.generate(data, mode=mode, learner=learner, brief=prev_brief)
        except Exception as e:  # never lose the numbers because the LLM step failed
            log.exception("commentary failed")
            data.narrative = commentary.placeholder()
            data.warnings.append(f"Commentary step failed: {type(e).__name__}: {str(e)[:120]}")
    else:
        data.narrative = commentary.placeholder()
    usage = commentary.usage_since(snap)
    data.ai_usage = usage if usage.calls else None
    data.audit = audit.run(data)  # again, now that the commentary check can run
    history.save(data)
    return data
