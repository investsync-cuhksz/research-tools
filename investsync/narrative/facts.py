"""Build the 'facts' text the LLM receives: every figure it may quote, pre-formatted."""
from __future__ import annotations

import re
from typing import Any, Optional

from ..render.viewmodel import latest_vm, num, pct
from ..schema import Market, NewsItem, TearSheetData


def facts_text(vm: dict[str, Any], data: TearSheetData) -> str:
    c = vm["company"]
    lines = [f"Company: {c['name']} ({c['ticker']}, {c['exchange']}"
             + (f", sector: {c['sector']}" if c["sector"] else "") + ")"]
    if c["description"]:
        lines.append(f"Business: {c['description']}")

    lines.append("\nMarket data:")
    lines += [f"- {k}: {v}" for k, v in vm["quote_items"] if v != "–"]
    if data.quote.next_earnings_date:
        lines.append(f"- Next scheduled results: {data.quote.next_earnings_date.strftime('%-d %B %Y')}")

    fin = vm["fin"]
    lines.append(f"\nFinancial summary ({fin['unit']}; {fin['standard'] or 'reported basis'}):")
    for r in fin["rows"]:
        vals = " | ".join(f"{y} {v}" for y, v in zip(fin["years"], r["values"]) if v != "–")
        if vals:
            cagr = f"; {fin['cagr_label']} {r['cagr']}" if r["cagr"] else ""
            lines.append(f"- {r['label'].strip()}: {vals}{cagr}")

    lv = latest_vm(data)
    if lv:
        lines.append(f"\nLatest reported period: {lv['label']} (to {lv['period_end']}; {lv['unit']}; "
                     f"vs {lv['prior_label']}). These are the most recent results; prefer them to fiscal-year figures "
                     "when describing the current trend:")
        lines += [f"- {k}: {a} vs {b} ({c})" for k, a, b, c in lv["rows"]]
        if lv["quarter"]:
            lines.append(f"Latest quarter alone ({lv['quarter']['label']} vs a year earlier):")
            lines += [f"- {k}: {a} vs {b} ({c})" for k, a, b, c in lv["quarter"]["rows"]]
        if lv["balance"]:
            lines.append(f"Balance sheet at {lv['period_end']}: " + "; ".join(f"{k} {v}" for k, v in lv["balance"]))
        if lv["ttm"]:
            lines.append(f"Trailing twelve months ({lv['ttm_basis']}): " + "; ".join(f"{k} {v}" for k, v in lv["ttm"]))
        if lv["capex_note"]:
            lines.append(f"- Data gap: {lv['capex_note']} Do not state an interim free-cash-flow figure.")
        bl = below_the_line_note(data)
        if bl:
            lines.append(f"- Earnings quality: {bl}")
        cc = latest_cash_conversion(data)
        if cc:
            lines.append(f"- Cash conversion: {cc}")
        if data.financials.cash_definition:
            lines.append(f"- Cash definition: {data.financials.cash_definition}")
    if getattr(data, "filing_facts", None):
        from ..data.filing_facts import text as _filing_text
        lines.append("\n" + _filing_text(data.filing_facts))

    if vm["dupont"]:
        d = vm["dupont"]
        lines.append(f"\nDuPont decomposition ({d['fy']}, average balances): "
                     + "; ".join(f"{k} {v}" for k, v in d["items"] if v != "–"))
    if vm["quality"]:
        lines.append("Earnings quality: " + "; ".join(f"{k} {v}" for k, v in vm["quality"] if v != "–"))

    odd = [y.fiscal_year for y in data.financials.years
           if y.operating_income is not None and y.gross_profit is not None and y.operating_income > y.gross_profit]
    if odd:
        lines.append("Margin baseline caveat: in " + ", ".join(f"FY{y}" for y in odd) + " operating profit was larger "
                     "than gross profit, so it includes non-operating gains (e.g. investment disposals); do not use "
                     "those years' operating or net margins as a baseline for trends or causes.")

    if vm["comps"]:
        cp = vm["comps"]
        hdr = ["P/E TTM", "P/E forward (next-year consensus)", "EV/EBITDA (TTM)", "P/B", "Div yield"]
        assert len(hdr) == len(cp["target"]["cells"]) - 3, "comps columns changed: update these labels"
        t, med, prem = cp["target"]["cells"], cp["median"]["cells"], cp["premium"]
        lines.append(f"\nRelative valuation ({cp['method']}):")
        for i, h in enumerate(hdr):
            if t[3 + i] != "–" or med[3 + i] != "–":
                lines.append(f"- {h}: {c['ticker']} {t[3 + i]} vs peer median {med[3 + i]}"
                             + (f" (premium/discount {prem[3 + i]})" if prem[3 + i] != "–" else ""))
        lines.append("- Peers: " + ", ".join(f"{r['cells'][0]} ({r['cells'][1]})" for r in cp["peers"]))

    if vm.get("valuation") and vm["valuation"].get("kind"):
        v = vm["valuation"]
        lines.append(f"\nIntrinsic value ({v['kind']}, illustrative, computed in code):")
        lines += [f"- {k}: {val}" for k, val in v["wacc_rows"] + v["assumptions"]]
        if v.get("model_value"):  # RATING_BASIS=scenarios
            lines.append(f"- The rating's DCF method is the probability-weighted value of our scenarios: {v['value']} vs "
                         f"share price {v['price']} ({v['upside']}); " + "; ".join(f"{k} {val}" for k, val
                                                                                 in v["short_assumptions"][:-1]))
            lines.append(f"- The model's mechanical DCF (consensus revenue, then a fade; the assumptions above) gives "
                         f"{v['model_value']} per share: a cross-check, not in the rating. Call it 'the model's "
                         f"mechanical DCF', never 'our base case'; the reverse DCF and the Monte Carlo below use it too.")
        else:
            lines.append(f"- Base-case value per share {v['value']} vs share price {v['price']} ({v['upside']})")
        if v.get("grid"):
            flat = [x for row in v["grid"]["rows"] for x in row[1:] if x != "–"]
            if flat:
                lines.append(f"- Range across {v['grid']['row_label']} and {v['grid']['col_label']} "
                             f"sensitivities: {min(flat, key=lambda t: float(t.replace(',', '')))} to "
                             f"{max(flat, key=lambda t: float(t.replace(',', '')))}")

    if vm.get("rating"):
        r = vm["rating"]
        scen = bool(data.rating and data.rating.basis == "scenarios")
        how = ("from our probability-weighted scenarios, computed in code; you explain it, you do not choose it"
               if scen else "set by a fixed rule, not by you")
        if r["rating"] == "Not rated":
            lines.append(f"\nAI rating ({how}): Not rated. {r['reason']}")
        else:
            lines.append(f"\nAI rating ({how}): {r['rating']}; {'fair value (our scenarios)' if scen else 'blended fair value'} "
                         f"{r['fair_value']} ({r['upside']} vs the share price); confidence {r['confidence']}.")
            if data.rating and data.rating.reason:
                lines.append((f"- Confidence comes from the spread of our scenarios and how far the peer multiples sit "
                              f"from our value ({data.rating.reason.rstrip('.')})." if scen else
                              f"- Confidence is set only by how far apart the valuation methods are "
                              f"({data.rating.reason.rstrip('.')}); nothing else (not the terminal-value share) sets it."))
            if r.get("buy_below"):
                lines.append(f"- The same thresholds give Buy at or below {r['buy_below']} and Sell at or above "
                             f"{r['sell_above']}.")
            from ..quant.audit import model_vs_street
            mvs = model_vs_street(data)
            if mvs and mvs[0] == "caveat":
                # "do not present the fair value as reliable" made the deep report call its own value unreliable while
                # publishing it (round-4 review); with our scenarios the gap is a view to explain, not a defect
                lines.append(f"- Model check (code): {mvs[1]} Say this plainly in the thesis or valuation text and name "
                             + ("the scenario assumption that drives it (e.g. the bear case's weight, growth beyond our "
                                "forecast years): this is where our view differs from the brokers'."
                                if data.rating and data.rating.basis == "scenarios" else
                                "the input that drives it; do not present the fair value as reliable."))

    ov = data.overall
    if ov:
        lines.append(f"\nOverall view (computed in code from the AI rating and every broker's latest view from the last "
                     f"{ov.fresh_days} days; refer to it as \"the overall view\", never as a rating): {ov.rating}, "
                     f"{ov.score:.2f} on a 1-5 scale ({ov.basis}).")
        for i in ov.inputs:
            lines.append(f"- {i.source}: {i.rating or 'none'}"
                         + (f", score {i.score:.2f}" if i.score is not None else "") + f"; {i.detail}.")
        if ov.split_note:
            lines.append(f"- {ov.split_note}")
        if ov.stale:
            lines.append(f"- Left out as out of date: {len(ov.stale)} broker view(s) older than {ov.fresh_days} days.")

    if data.street and data.street.findings:
        lines.append("\nBroker views (third-party opinions, compared in code; attribute them to the brokers):")
        lines += [f"- {f}" for f in data.street.findings]
    if vm.get("scorecard"):
        lines.append("\nScorecard (yes/no checks computed in code): "
                     + "; ".join(f"{a['title']} {a['score']}" for a in vm["scorecard"]["areas"]))

    if vm["chart"]:
        ch = vm["chart"]
        lines.append(f"\nShare price performance vs {ch['bench_name']}:")
        lines += [f"- {p}: stock {s}, benchmark {b}, relative {r}" for p, s, b, r in ch["returns"]]

    if data.warnings:
        lines.append("\nData gaps: " + "; ".join(data.warnings))
    from ..quant.valuation import is_financial
    from .playbooks import playbook_for
    pb = playbook_for(data.profile.sector, is_financial(data))
    if pb:
        lines.append("\nSector playbook (how an analyst reads this kind of company; guidance only, not data about "
                     "this company):\n" + pb)
    return "\n".join(lines)


def filings_text(filings, max_chars: int = 9000) -> str:
    """Report excerpts for the model, newest first, capped in total length."""
    if not filings:
        return "None"
    parts, used = [], 0
    for f in sorted(filings, key=lambda x: x.filed or 0, reverse=True):
        head = f"[{f.source} · {f.title}" + (f" · filed {f.filed.isoformat()}" if f.filed else "") + "]"
        for name, text in f.sections.items():
            room = max_chars - used
            if room <= 200:
                break
            chunk = text[:room]
            parts.append(f"{head}\n## {name}\n{chunk}")
            used += len(chunk)
    from .guardrail import annotate_cn_amounts
    return annotate_cn_amounts("\n\n".join(parts)) if parts else "None"


_LEGAL = re.compile(r"\b(holdings?|group|limited|ltd|inc|corp(oration)?|co|plc|company|technology)\b\.?", re.I)


def company_terms(data: TearSheetData) -> list[str]:
    return profile_terms(data.profile)


def profile_terms(p) -> list[str]:
    """Words that identify the company in a headline: ticker, code, short English and local names."""
    short = _LEGAL.sub("", p.name).strip(" ,.") or p.name
    terms = {p.ticker, p.ticker.split(".")[0], p.name, short, short.split()[0] if short.split() else "",
             p.name_local or ""}
    return [t.lower() for t in terms if t and len(t) > 2]


def mentions_company(n: NewsItem, terms: list[str]) -> bool:
    text = f"{n.title} {n.summary or ''}".lower()
    return any(t in text for t in terms)


def spread_by_week(items: list[NewsItem], n: int) -> list[NewsItem]:
    """Up to ``n`` items spread over the weeks covered (newest week first, newest item first within a
    week, taking one per week in turn), so a busy day does not crowd out the rest of the month."""
    from collections import OrderedDict
    weeks: "OrderedDict[tuple, list]" = OrderedDict()
    for it in sorted(items, key=lambda x: x.published.timestamp() if x.published else 0, reverse=True):
        key = it.published.isocalendar()[:2] if it.published else (0, 0)
        weeks.setdefault(key, []).append(it)
    out, queues = [], [list(v) for v in weeks.values()]
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0))
    return sorted(out, key=lambda x: x.published.timestamp() if x.published else 0, reverse=True)


def rank_news(data: TearSheetData, limit: Optional[int] = None) -> list[NewsItem]:
    """Items that mention the company first, spread across the weeks covered; then the rest."""
    terms = company_terms(data)
    own = [n for n in data.news if mentions_company(n, terms)]
    rest = [n for n in data.news if not mentions_company(n, terms)]
    items = spread_by_week(own, limit or len(own)) + rest
    return items[:limit] if limit else items


def after_close(published, as_of) -> str:
    """Tag for news dated after the price date: it cannot explain the share-price move to that date (round-4
    review: a CEO probe announced on 8 Nov was given as a cause of the fall to the 6 Nov close)."""
    d = published.date() if hasattr(published, "date") and callable(published.date) else published
    return " · AFTER THE PRICE DATE: not a cause of moves up to it" if d and as_of and d > as_of else ""


def news_text(items: list[NewsItem], limit: int = 12, about: tuple[str, ...] = (), as_of=None) -> str:
    """Up to ``limit`` items, those that mention the company (``about`` terms) first."""
    if not items:
        return "No recent news available."
    terms = [t.lower() for t in about if t and len(t) > 2]

    def mentions(n: NewsItem) -> bool:
        text = f"{n.title} {n.summary or ''}".lower()
        return any(t in text for t in terms)
    ranked = [n for n in items if mentions(n)] + [n for n in items if not mentions(n)] if terms else items
    out = []
    for n in [n for n in ranked if n.published][:limit]:  # run 4: an undated item is not used
        when = n.published.strftime("%Y-%m-%d") if n.published else "undated"
        summary = f" | {n.summary[:220]}" if n.summary else ""
        out.append(f"- [{when}{after_close(n.published, as_of)}] {n.title}{summary}")
    from .guardrail import annotate_cn_amounts
    return annotate_cn_amounts("\n".join(out))


def report_facts_text(rvm: dict[str, Any], data: TearSheetData) -> str:
    """Extra figures for the full-report sections, formatted exactly as the report prints them."""
    lines: list[str] = []
    ov = rvm.get("overview") or {}
    for seg in ov.get("segments", []):
        lines.append(f"Revenue by {seg['title'].replace('By ', '')} ({seg['period']}, {seg['currency']}): "
                     + "; ".join(f"{it['name']} {it['share']} ({it['revenue']})" for it in seg["items"]))
    st = rvm.get("statements") or {}
    if st.get("ratios"):
        yrs = st["years"]
        lines.append(f"\nKey ratios ({', '.join(yrs)}):")
        for g in st["ratios"]:
            for row in g["rows"]:
                vals = " | ".join(f"{y} {v}" for y, v in zip(yrs, row["values"]) if v not in ("–", ""))
                if vals:
                    lines.append(f"- {row['label']}: {vals}")
    v = rvm.get("valuation") or {}
    if v.get("reverse"):
        lines.append(f"\nReverse {v.get('kind') or 'DCF'}: {v['reverse']['headline']}. "
                     + "; ".join(f"{k} {val}" for k, val in v["reverse"]["rows"]))
        ivb = implied_vs_base(data)
        if ivb:
            lines.append(ivb)
        if (data.valuation and data.valuation.scenarios) or rvm.get("analyst_scenarios"):
            # the writer called the mechanical DCF's growth "our base case" in four places (round-4 review)
            lines.append("The reverse DCF compares the price with the model's mechanical DCF (a cross-check), not "
                         "with our scenarios. Never call that growth 'our base case'; our base case is the base "
                         "scenario, whose revenue path is our forecast.")
    if v.get("mc"):
        lines.append(f"Monte Carlo of the {v['mc']['model']} value: " + "; ".join(f"{k} {val}" for k, val in v["mc"]["rows"]))
    if v.get("band"):
        b = v["band"]
        lines.append(f"P/E history (5 years; price divided by the last published fiscal-year EPS, a different basis "
                     f"from the TTM P/E in the market data, so never compare the two): today's P/E on this basis is "
                     f"{b['reading']} its 5-year median; " + "; ".join(f"{k} {val}" for k, val in b["rows"]))
    if v.get("consensus"):
        c = v["consensus"]
        # round-7 review: two broker medians ($322.50 and $315) and "brokers are unanimous" while Yahoo showed 2 Hold and
        # 1 Sell: name the two datasets so the writer can say which one a figure comes from
        lines.append("Analyst consensus (Yahoo Finance, a wider set than the dated broker notes; third party): "
                     + "; ".join(f"{k} {val}" for k, val in c["targets"]))
        for e in c["estimates"]:
            lines.append(f"- Consensus {e[0]}: EPS {e[1]} ({c['estimate_ccy']}), EPS growth {e[3]}, revenue {e[4]}, "
                         f"revenue growth {e[5]}")
    cq = data.consensus.quarters if data.consensus else []
    if cq:  # results preview: the quarter to be reported next, and the one after (third party)
        ne = data.quote.next_earnings_date
        qc = data.consensus.estimate_currency or ""
        lines.append("Consensus by quarter (third party, Yahoo Finance; EPS on the analysts' adjusted basis): " + "; ".join(
            f"{q.period}{' (results ' + ne.strftime('%-d %b %Y') + ')' if i == 0 and ne else ''}: revenue "
            f"{qc} {q.revenue_avg / 1e6:,.0f}mn" + (f" ({q.revenue_growth:+.1%} y/y)" if q.revenue_growth is not None else "")
            + (f", EPS {q.eps_avg:.2f}" if q.eps_avg is not None else "")
            + (f" ({q.analysts} analysts)" if q.analysts else "")
            for i, q in enumerate(cq) if q.revenue_avg))
    from ..quant.ranges import rerating
    rr = rerating(data)
    if rr:
        lines.append(rr)
    qq = data.quote
    if qq.h_share and qq.h_share_price and qq.h_premium is not None:
        lines.append(f"H-share {qq.h_share}: HKD {qq.h_share_price:,.2f} on the same date, {qq.h_premium:+.1%} vs the "
                     "A-share in CNY (H premium when positive).")
    if qq.implied_move and qq.implied_move_expiry:
        lines.append(f"Options expiring {qq.implied_move_expiry.strftime('%-d %b %Y')} (after the results) price a move "
                     f"of about ±{qq.implied_move:.1%} from the last close (at-the-money straddle; includes ordinary "
                     "volatility to that date).")
    s = rvm.get("summary") or {}
    if s.get("football"):
        ff = s["football"]
        lines.append(f"\nValue ranges per share ({ff['currency']}): "
                     + "; ".join(f"{b['label']} {b['low']} – {b['high']}" for b in ff["bars"]))
    r = data.rating
    if r and r.methods:
        lines.append("Rating methods: " + "; ".join(
            f"{m.label} {num(m.value, 2)}" + (f" (weight {pct(m.weight, 0)})" if m.included else
                                               f" ({m.note})" if (m.note or "").startswith("cross-check") else
                                               f" (excluded: {m.note or ''})")
            for m in r.methods))
    t = rvm.get("technical") or {}
    if t:
        lines.append(f"\nTechnical picture ({t['as_of']}): overall {t['overall']}; "
                     + "; ".join(f"{n} {rd}" for n, rd, _ in t["signals"]))
        lines.append("Returns vs " + t["bench"] + ": " + "; ".join(f"{p} {a} vs {b}" for p, a, b, _ in t["returns"]))
        # "Max drawdown" was quoted as a one-month fall ("down 24% in a month", round-4 review): say what it is
        lines.append("Risk: " + "; ".join(
            (f"{k} {val} (largest peak-to-trough fall within the period, not a return over it)"
             if k.startswith("Max drawdown") else f"{k} {val}") for k, val in t["risk"]))
    cp = rvm.get("competitive") or {}
    if cp.get("rows"):
        # growth is the latest quarter vs the same quarter a year earlier (Yahoo), margins are TTM (round-6 review:
        # "TTM revenue growth of 105.9%" was the latest quarter's growth)
        lines.append("\nOperating comparison (Yahoo Finance: revenue growth and operating margin are the latest "
                     "quarter; gross margin and ROE trailing twelve months): " + "; ".join(
            f"{row['cells'][0]}: latest-quarter revenue growth {row['cells'][3]}, gross margin {row['cells'][4]}, "
            f"latest-quarter operating margin {row['cells'][5]}, ROE {row['cells'][7]}" for row in cp["rows"]))
    ow = rvm.get("ownership") or {}
    if ow.get("short"):
        lines.append(f"\n{ow['short']}")
    if ow.get("holders"):
        lines.append(f"\n{ow.get('holders_title', 'Major holders')}: "
                     + "; ".join(f"{h[0]} {h[3]}" for h in ow["holders"][:5]))
    ev = (rvm.get("news") or {}).get("events") or []
    if ev:
        lines.append("Upcoming / recent events: " + "; ".join(f"{d} {lab}" for d, lab in ev))
    imp = [a for a in data.announcements if a.important][:12]
    if imp:
        lines.append("\nOfficial announcements (last 90 days): " + "; ".join(
            f"{a.on.isoformat()} {a.kind}: {a.title}" for a in imp))
    if data.audit:
        notes = [f"{c.name}: {c.detail}" for c in data.audit.checks if c.status in ("caveat", "fail")]
        if notes:
            lines.append("\nData caveats to keep visible: " + "; ".join(notes))
    return "\n".join(lines)


def below_the_line_note(data) -> str:
    """Round-6 review: 1H net profit (+161%) included ~USD 23.7bn of equity-investment gains that no section flagged,
    and the P/E cross-check credited the jump to "earnings growth". For a non-financial company net profit is normally
    well below operating profit (tax); net profit at or above ~90% of operating profit means large income below the
    operating line (investment gains, interest, one-offs), so operating-profit growth is the cleaner measure."""
    lt = getattr(data.financials, "latest", None)
    if lt is None or not lt.operating_income or lt.operating_income <= 0 or lt.net_income is None:
        return ""
    from ..quant.valuation import is_financial
    if is_financial(data):
        return ""
    ratio = lt.net_income / lt.operating_income
    if ratio < 0.9:
        return ""
    unit = 1e6
    txt = (f"{lt.label} net profit ({lt.net_income / unit:,.0f}mn) is {ratio:.0%} of operating profit "
           f"({lt.operating_income / unit:,.0f}mn), so income below the operating line (investment gains, interest or "
           f"other one-offs) is unusually large this period")
    ff = {f.key: f for f in (getattr(data, "filing_facts", None) or []) if f.value is not None}
    g = ff.get("investment_gains_ytd")
    if g and data.profile.market != Market.CN:
        q = ff.get("investment_gains_quarter")
        txt += (f"; the filing shows gains on investments of {g.value / unit:,.0f}mn for the {g.period}"
                + (f" ({q.value / unit:,.0f}mn in the {q.period})" if q else "")
                + ", about " + f"{g.value / lt.net_income:.0%} of net profit; these sit below operating profit, so "
                  "they lift net profit and EPS but NOT the operating margin. Quote the period total, not one quarter. "
                  "They are accounting gains (mostly fair-value changes on stakes still held), NOT cash: operating "
                  "cash flow deducts them, and only the proceeds of stakes actually sold are cash; never call them "
                  "cash or cash earnings")
    if lt.prior_operating_income and lt.prior_operating_income > 0 and lt.prior_net_income and lt.prior_net_income > 0:
        txt += (f"; operating profit grew {lt.operating_income / lt.prior_operating_income - 1:+.1%} against net profit "
                f"{lt.net_income / lt.prior_net_income - 1:+.1%}: use operating-profit growth for the trend and do not "
                f"credit the net-profit jump to the business")
    return txt + "."


def latest_cash_conversion(data) -> str:
    """Round-7 review: the report argued earnings quality from FY cash conversion (0.86x) while the latest half-year was
    0.63x. Operating cash flow / net profit for the latest period, next to the same months a year earlier and the last
    fiscal year."""
    lt = getattr(data.financials, "latest", None)
    if lt is None or not lt.operating_cash_flow or not lt.net_income or lt.net_income <= 0:
        return ""
    txt = f"{lt.label} operating cash flow / net profit {lt.operating_cash_flow / lt.net_income:.2f}x"
    if lt.prior_operating_cash_flow and lt.prior_net_income and lt.prior_net_income > 0:
        txt += f" (same months a year earlier {lt.prior_operating_cash_flow / lt.prior_net_income:.2f}x)"
    fy = data.financials.years[-1] if data.financials.years else None
    if fy and fy.operating_cash_flow and fy.net_income and fy.net_income > 0:
        txt += (f"; FY{fy.fiscal_year} {fy.operating_cash_flow / fy.net_income:.2f}x. Use the latest period's ratio for the "
                f"current picture, not the fiscal year's.")
    return txt


def reverse_window(rv) -> tuple[int, int]:
    """(held years, solved years) of a reverse DCF; reports saved before run 2 have no held years."""
    hold = int(getattr(rv, "hold_years", 0) or 0)
    return max(hold, 0), int(rv.horizon_years or 0)


def reverse_years_text(rv) -> str:
    """'from FY2029 to FY2036' when the reverse DCF's solved years are known, else ''."""
    a, b = getattr(rv, "from_year", None), getattr(rv, "to_year", None)
    return f"from FY{a} to FY{b}" if a and b else ""


def base_scenario_cagr(data) -> Optional[tuple[float, int]]:
    """Our base scenario's revenue CAGR over the reverse DCF's solved years (its first years, then the model's halving
    fade to terminal growth), so the price's implied growth is compared like for like: when the reverse DCF holds the
    consensus years, the CAGR runs over the years after them. Returns (CAGR, number of years); None without
    scenarios."""
    v = data.valuation
    rv, sc = (v.reverse if v else None), (v.scenarios if v else None)
    if not (rv and rv.model == "DCF" and sc and sc.scenarios and v.dcf):
        return None
    base = next((x for x in sc.scenarios if x.name == "base"), None)
    if base is None or not base.revenue_growth:
        return None
    from ..quant import valuation as _v
    hold, k = reverse_window(rv)
    n, g = hold + k, v.dcf.terminal_growth
    if k <= 0:
        return None
    path, prev = list(base.revenue_growth[:3]), base.revenue_growth[min(2, len(base.revenue_growth) - 1)]
    while len(path) < n:
        prev = _v.fade_step(prev, g)
        path.append(prev)
    level = 1.0
    for x in path[hold:n]:
        level *= 1 + x
    return level ** (1 / k) - 1, k


SMALL_GAP = 0.03  # round-8 review: a 1pp gap between implied and base growth was headlined as the variant view


def implied_vs_base(data) -> str:
    """Round-7 review: the headline said "the market prices a durable deceleration" while our own reverse DCF said the
    price needs ~40% growth a year. State in code which way round it is: the price's implied growth vs our base case's
    growth over the same years (same model margins). Round 8: a gap under 3pp is no variant view at all."""
    rv = data.valuation.reverse if data.valuation else None
    got = base_scenario_cagr(data)
    if not got or rv is None or rv.implied_growth is None:
        return ""
    ours, n = got
    gap = rv.implied_growth - ours
    hold, _ = reverse_window(rv)
    span = reverse_years_text(rv) or f"for {n} years"
    if hold:
        head = (f"What the price implies vs our base case (computed in code): after the {hold} consensus years, the "
                f"price needs revenue growth of {rv.implied_growth:.1%} a year {span} at the model's margins; our base "
                f"case grows {ours:.1%} a year over those years (gap {gap * 100:+.1f} percentage points). ")
    else:
        head = (f"What the price implies vs our base case (computed in code): the price needs revenue growth of "
                f"{rv.implied_growth:.1%} a year for {n} years at the model's margins; our base case grows {ours:.1%} a "
                f"year over the same {n} years (gap {gap * 100:+.1f} percentage points). ")
    if abs(gap) < SMALL_GAP:
        return head + ("The two are close: the price already discounts roughly our base case, so growth is NOT a "
                       "variant view here. Never headline this gap or call it what the market misses; build the "
                       "thesis on the swing factor and the evidence for it (what would have to be true for the bull "
                       "or the bear case), and say the stock looks fairly priced on growth.")
    more = gap > 0
    return head + (f"The market is pricing {'MORE' if more else 'LESS'} growth than our base case, so "
                   + ("never write that the price discounts a slowdown or a cliff; say it already prices strong growth."
                      if more else "the price discounts a slower path than ours; say so."))
