"""Automatic data checks shown at the front of the full report, in the spirit of FinRobot's
numeric audit. Each check is cheap, deterministic and explained in one line, so a reader can
see what the numbers were tested against before relying on them.

Status per check: pass / caveat (usable, read the note) / fail (do not rely on it) / info.
Overall: "review" if anything failed, "caveated" if anything needs a note, else "publishable".
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from ..render.viewmodel import ccy, mult, num, pct
from ..schema import Audit, AuditCheck, TearSheetData


def _months(a: date, b: date) -> float:
    return (b - a).days / 30.44


def _fv_kind(r) -> str:
    return "fair value (our scenarios)" if getattr(r, "basis", "blend") == "scenarios" else "blended fair value"


def model_vs_street(data: TearSheetData, band: float = 0.25) -> Optional[tuple[str, str]]:
    """(status, sentence) comparing the blended fair value with the range of broker targets, for the AI's facts
    (the audit row "Model vs brokers" below covers the report). The rating is not changed: a value far outside
    every broker's target is flagged so the text must explain it."""
    r, st = data.rating, data.street
    if r is None or not r.fair_value or st is None or (st.targets_n or 0) < 3 or not st.target_high or not st.target_low:
        return None
    cur = st.currency or data.quote.currency
    fv = r.fair_value
    if st.target_high < fv <= st.target_high * (1 + band):
        return "caveat", (f"The model's {_fv_kind(r)} ({cur} {fv:,.2f}) is above every one of {st.targets_n} dated broker "
                          f"notes' targets (highest {cur} {st.target_high:,.2f}; Yahoo's wider consensus range is "
                          f"separate and may go higher: write 'above all {st.targets_n} dated broker targets', never "
                          f"'above every broker'); say what the model assumes that brokers do not.")
    if st.target_low * (1 - band) <= fv < st.target_low:
        return "caveat", (f"The model's {_fv_kind(r)} ({cur} {fv:,.2f}) is below every one of {st.targets_n} dated broker "
                          f"notes' targets (lowest {cur} {st.target_low:,.2f}; Yahoo's wider consensus range is separate and may go "
                          f"lower: write 'below all {st.targets_n} dated broker targets', never 'below every broker' or "
                          f"'every analyst'); say what the model assumes that brokers do not.")
    if fv > st.target_high * (1 + band):
        return "caveat", (f"The model's {_fv_kind(r)} ({cur} {fv:,.2f}) is {fv / st.target_high - 1:.0%} above the "
                          f"highest of {st.targets_n} broker targets ({cur} {st.target_high:,.2f}); " + (
                          "name the scenario assumption behind the gap." if getattr(r, "basis", "blend") == "scenarios"
                          else "check which model input drives the gap before relying on it."))
    if fv < st.target_low * (1 - band):
        return "caveat", (f"The model's {_fv_kind(r)} ({cur} {fv:,.2f}) is {1 - fv / st.target_low:.0%} below the "
                          f"lowest of {st.targets_n} broker targets ({cur} {st.target_low:,.2f}); " + (
                          "name the scenario assumption behind the gap." if getattr(r, "basis", "blend") == "scenarios"
                          else "check which model input drives the gap before relying on it."))
    return "pass", (f"The model's {_fv_kind(r)} ({cur} {fv:,.2f}) lies within or near the broker target range "
                    f"({cur} {st.target_low:,.2f}-{st.target_high:,.2f}, {st.targets_n} targets).")


def run(data: TearSheetData, today: Optional[date] = None) -> Audit:
    today = today or datetime.now(timezone.utc).date()
    checks: list[AuditCheck] = []
    add = lambda name, status, detail: checks.append(AuditCheck(name=name, status=status, detail=detail))  # noqa: E731
    fin, q = data.financials, data.quote
    latest = fin.years[-1] if fin.years else None

    # 1. Freshness
    if latest:
        age = _months(latest.period_end, today)
        add("Latest annual statements", "pass" if age <= 15 else "caveat",
            f"FY{latest.fiscal_year} (period ended {latest.period_end:%-d %b %Y}, {age:.0f} months ago)"
            + ("" if age <= 15 else "; a newer annual report may be out"))
    else:
        add("Latest annual statements", "fail", "No annual statements found.")
    lag = (today - q.as_of).days
    add("Market data", "pass" if lag <= 7 else "caveat",
        f"Prices as of {q.as_of:%-d %b %Y}" + ("" if lag <= 7 else f" ({lag} days old)"))

    if latest:
        # 2. Balance sheet coherence
        if latest.total_assets and latest.total_equity is not None:
            ok = 0 < latest.total_equity < latest.total_assets
            add("Balance sheet", "pass" if ok else "caveat",
                f"Equity {pct(latest.total_equity / latest.total_assets)} of total assets"
                + ("" if ok else " (negative or above assets: check the source)"))
        missing = [k for k in ("revenue", "net_income", "total_assets", "total_equity", "operating_cash_flow",
                               "cash_and_equivalents", "total_debt", "diluted_eps")
                   if getattr(latest, k) is None]
        add("Key fields present", "pass" if not missing else "caveat",
            "All key FY fields reported" if not missing else "Missing: " + ", ".join(m.replace("_", " ") for m in missing))

        # 3. Cross-checks between independent sources
        if latest.diluted_eps and latest.diluted_eps > 0 and q.pe_ttm and q.fx_to_reporting:
            implied = q.price / (latest.diluted_eps / q.fx_to_reporting)
            gap = implied / q.pe_ttm - 1
            lt = data.financials.latest
            grew = (gap > 0.35 and lt is not None and lt.net_income_growth is not None
                    and lt.net_income_growth > 0.2)
            add("P/E cross-check", "pass" if abs(gap) <= 0.35 or grew else "caveat",
                f"Price / FY{latest.fiscal_year} EPS = {mult(implied)} vs quoted P/E (TTM) {mult(q.pe_ttm)}"
                + ("" if abs(gap) <= 0.35 else
                   f"; the gap is earnings growth since FY{latest.fiscal_year} ({lt.label} net profit "
                   f"{lt.net_income_growth:+.1%} year on year), not a data problem: TTM EPS is the last four "
                   f"quarters" if grew else "; large gap (interim results, one-offs or share basis)"))
        if q.market_cap and q.price and latest.net_income and latest.diluted_eps:
            quote_shares = q.market_cap / q.price
            stmt_shares = latest.net_income / latest.diluted_eps
            gap = quote_shares / stmt_shares - 1
            add("Share count cross-check", "pass" if abs(gap) <= 0.10 else "caveat",
                f"Market cap / price = {num(quote_shares / 1e6, 0)}mn shares vs net profit / EPS = "
                f"{num(stmt_shares / 1e6, 0)}mn"
                + ("" if abs(gap) <= 0.10 else
                   "; may reflect buybacks, dual listings (A/H) or a market cap covering one share class"))

        # 4. Earnings quality
        e = data.earnings_quality
        if e and e.cfo_to_net_income is not None:
            add("Cash backing of earnings", "pass" if e.cfo_to_net_income >= 0.8 else "caveat",
                f"Operating cash flow / net profit {mult(e.cfo_to_net_income, 2)}"
                + ("" if e.cfo_to_net_income >= 0.8 else "; profits are not fully backed by cash"))

    # 5. Currency and EV definitions
    if fin.currency != q.currency:
        add("Currency", "info" if q.fx_to_reporting else "caveat",
            f"Statements in {ccy(fin.currency)}, shares trade in {ccy(q.currency)}"
            + (f"; converted at {num(q.fx_to_reporting, 4)} {ccy(fin.currency)} per {ccy(q.currency)} (spot)"
               if q.fx_to_reporting else "; no FX rate found"))
    if q.enterprise_value is not None:
        lt = fin.latest
        when = (f"net debt at {lt.period_end:%-d %b %Y} ({lt.label} balance sheet)" if lt and lt.net_debt is not None
                else "latest FY net debt")
        add("Enterprise value", "info",
            f"Market cap + {when}; debt excludes lease liabilities. Cash: {fin.cash_definition or 'cash and short-term investments'}")
    elif latest and latest.total_debt is None:
        add("Enterprise value", "caveat", "Debt not reported by the source, so EV and EV-based ratios are omitted")

    # 6. Peers and valuation
    n_peers = len(data.comps.peers) if data.comps else 0
    add("Peer set", "pass" if n_peers >= 3 else "caveat",
        f"{n_peers} peers" + ("" if n_peers >= 3 else "; peer medians are not reliable"))
    v = data.valuation
    if v is None:
        add("Intrinsic value", "caveat", "Valuation inputs unavailable (risk-free rate or statements)")
    elif v.dcf or v.ddm:
        model = v.dcf or v.ddm
        kind = "DCF" if v.dcf else "DDM"
        detail = f"{kind} base case {ccy(v.currency)} {num(model.value_per_share, 2)}"
        status = "pass"
        if v.dcf and v.dcf.bridge and v.dcf.bridge.terminal_share > 0.8:
            status = "caveat"
            detail += f"; terminal value is {pct(v.dcf.bridge.terminal_share, 0)} of EV (highly assumption-driven)"
        add("Intrinsic value", status, detail)
    else:
        add("Intrinsic value", "caveat", (v.notes[0] if v.notes else "Model withheld"))

    # 7. Rating
    rt = data.rating
    if rt is not None:
        if rt.rating == "Not rated":
            add("AI rating", "caveat", f"Not rated: {rt.reason}")
        else:
            used = [m for m in rt.methods if m.included]
            out = [m.label for m in rt.methods if not m.included]
            if rt.basis == "scenarios":
                add("AI rating", "pass" if rt.confidence != "low" else "caveat",
                    f"{rt.rating} from our probability-weighted scenarios, {rt.confidence} confidence"
                    + (f"; cross-checks (not in the rating): {', '.join(out)}" if out else ""))
            else:
                add("AI rating", "pass" if rt.confidence != "low" else "caveat",
                    f"{rt.rating} from {len(used)} methods, {rt.confidence} confidence (rule-based)"
                    + (f"; excluded as outlier: {', '.join(out)}" if out else ""))

    # 7b. Brokers vs the model: a big gap is worth a second look at our inputs (or theirs)
    st = data.street
    if st is not None and st.targets_n >= 3 and st.model_fair_value and st.target_median:
        gap = st.model_fair_value / st.target_median - 1
        lo, hi = st.target_low or 0, st.target_high or 0
        outside = not (lo <= st.model_fair_value <= hi)
        add("Model vs brokers", "caveat" if outside and abs(gap) > 0.25 else "info",
            f"Model fair value {pct(gap, 0, signed=True)} vs the brokers' median target ({st.targets_n} targets)"
            + ("; outside their whole range: check growth and discount-rate inputs" if outside else ""))
    elif st is not None:
        add("Broker coverage", "info", f"{st.brokers} brokers, {st.reports} notes; "
            + (f"{st.targets_n} price target(s)" if st.targets_n else "no price targets to compare"))

    # 7c. Accounting quality (Piotroski F-score); a low score is a flag, not a verdict
    sc = data.scorecard
    if sc is not None and sc.piotroski is not None and sc.piotroski.available >= 7:
        f = sc.piotroski
        add("Accounting quality", "caveat" if f.score <= 3 else "pass",
            f"Piotroski F-score {f.score} of {f.available}"
            + (" (weak: profitability, funding or efficiency deteriorated)" if f.score <= 3 else ""))

    # 8. Commentary
    n = data.narrative
    if n is None or n.status == "placeholder":
        add("AI commentary", "info", "Not generated for this report (numbers only)")
    elif n.status == "flagged":
        bad = n.guardrail.unmatched_numbers if n.guardrail else []
        hard = [t for t in (n.guardrail.text_issues if n.guardrail else [])
                if not t.startswith(("[momentum]", "[sector]", "[debate]", "[struck]", "[fact]"))]
        add("AI commentary", "fail", "Still wrong after the rewrites: "
            + "; ".join(([f"figures not in the data: {', '.join(bad)}"] if bad else []) + hard)[:400])
    else:
        add("AI commentary", "pass",
            f"Every number in the AI text was found in the data (code check, {n.guardrail.attempts if n.guardrail else 1} "
            "attempt(s)); wording checked for direction, currency and period. This does not prove each statement right")
        # the fact sweep's log of deleted sentences ("[struck] …", run 2) is a record, not an open issue: count it only
        log = n.guardrail.text_issues if n.guardrail else []
        soft = [t for t in log if not t.startswith(("[struck]", "[fact]"))]
        struck = sum(1 for t in log if t.startswith("[struck]"))
        if soft:  # run 4 (round 12: the raw log read as "tool residue"): a count, the details stay in the JSON
            add("AI wording checks", "caveat", f"{len(soft)} AI statement(s) kept with a caveat after the checks, for "
                "example a scenario reason the sources do not state in so many words")
        if struck:
            add("AI fact sweep", "info", f"{struck} AI-written sentence(s) removed by code checks (dates of price moves, "
                "labels, fractions, guidance wording, scenario weights, buyback figures)")
    if n is not None and n.deep is not None:
        da = n.deep
        fixed = sum(1 for r in da.review if r.resolved)
        add("AI debate", "info",
            f"{len(da.bull)} bull and {len(da.bear)} bear arguments kept, {len(da.dropped)} removed by the evidence "
            f"checks; judge: {da.stronger_side} ({da.conviction} conviction), {da.rating_alignment} with the rating; "
            f"reviewer raised {len(da.review)} issue(s), {fixed} fixed in revision")

    statuses = {c.status for c in checks}
    overall = "review" if "fail" in statuses else "caveated" if "caveat" in statuses else "publishable"
    return Audit(status=overall, checks=checks)
