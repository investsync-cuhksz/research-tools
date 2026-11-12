"""Learner's guide: walks a first-year student through this company's report, step by step.

Built in code from the data (templates filled with the company's own numbers), so every number and
every worked example is exact. Teaching approach (see README): beginners learn best from worked
examples, so each step shows where to look, the numbers, how to read them, a worked calculation,
red flags and a question to ask; exercises at the end let them try it themselves (answers at the
back). Rules of thumb are phrased as comparisons (with peers, with the company's own history),
never as universal cut-offs, and banks / insurers get their own wording.

The optional AI notes (narrative.learner) add "how an analyst connects these numbers" per step.
"""
from __future__ import annotations

from typing import Any, Optional

from ..schema import TearSheetData
from .viewmodel import big, ccy, mult, num, pct

# page-1 boxes each step points to (also used for the numbered markers on page 1)
STEPS = [
    ("business", "What does the company do?"),
    ("growth", "Is it growing?"),
    ("profit", "Is it profitable, and is the profit real?"),
    ("safety", "Is it financially safe?"),
    ("cheap", "Is it cheap?"),
    ("worth", "What is it worth?"),
    ("others", "What do other analysts think?"),
    ("wrong", "What could go wrong?"),
]

GLOSSARY = [
    ("Revenue", "Money from sales before any costs. Also called sales or turnover."),
    ("Gross margin", "Revenue minus the direct cost of what was sold, as a % of revenue. Shows pricing power."),
    ("Operating margin", "Profit from operations (after running costs, before interest and tax) as a % of revenue."),
    ("Net margin", "Profit for shareholders as a % of revenue: what is left of each 100 of sales."),
    ("EPS", "Earnings per share: net profit divided by the number of shares."),
    ("CAGR", "Compound annual growth rate: the steady yearly growth that gets you from the first to the last "
             "value. (Last / First)^(1 / years) - 1."),
    ("ROE", "Return on equity: net profit / shareholders' equity. How much profit each 100 of the owners' money earns."),
    ("DuPont analysis", "Splits ROE into net margin x asset turnover x equity multiplier: is ROE driven by "
                        "profitability, efficiency or borrowing?"),
    ("Asset turnover", "Revenue / total assets: how hard the assets work."),
    ("Equity multiplier", "Total assets / equity: how much of the balance sheet is funded by debt and other "
                          "liabilities. Higher = more leverage."),
    ("Cash conversion", "Cash from operations / net profit. Above 1 means profits are backed by cash."),
    ("Accruals ratio", "How much of profit is not (yet) cash. Persistently high accruals can be a warning sign."),
    ("Net debt", "Debt minus cash. Negative = net cash (more cash than debt)."),
    ("EBITDA", "Earnings before interest, tax, depreciation and amortisation: a rough measure of operating cash "
               "profit."),
    ("Net debt / EBITDA", "Roughly how many years of EBITDA it would take to repay net debt."),
    ("Interest cover", "Operating profit / interest cost: how many times profit covers the interest bill."),
    ("P/E", "Price / earnings per share: how many years of today's profit you pay for a share."),
    ("Forward P/E", "Price / the profit per share analysts expect next year. Lower than the trailing P/E when "
                    "profit is expected to grow."),
    ("P/B", "Price / book value per share: price compared with the accounting value of equity. Common for banks."),
    ("Enterprise value (EV)", "Market cap plus net debt: the price of the whole business, debt included."),
    ("EV/EBITDA", "Enterprise value / EBITDA: a multiple that ignores how the company is financed."),
    ("Dividend yield", "Dividends per share / share price."),
    ("P/S", "Price / sales per share (or market value / revenue): used when a company has no profit yet."),
    ("Buyback", "The company buying its own shares with its cash: another way, besides dividends, of returning "
                "money to shareholders."),
    ("Life-cycle phase", "Where a company is in its life: start-up, fast growth, operating leverage, capital return "
                         "or decline. Decided in code from revenue growth, profit and payouts (see the life-cycle page)."),
    ("Operating leverage", "Profit growing faster than sales because many costs stay fixed as sales rise."),
    ("Peer median", "The middle value of the comparable companies: half are above, half below."),
    ("DCF", "Discounted cash flow: the value today of all future free cash flows, discounted at the WACC."),
    ("WACC", "Weighted average cost of capital: the return investors and lenders require; the discount rate in a DCF."),
    ("Terminal growth", "The growth rate assumed for ever after the forecast years; small changes move a DCF a lot."),
    ("DDM", "Dividend discount model: values a share as the present value of future dividends (used for banks)."),
    ("Reverse DCF", "Turns the DCF around: what growth does today's share price assume?"),
    ("Monte Carlo", "Runs the valuation thousands of times with inputs varied at random to show a range of values."),
    ("Fair value", "The model's estimate of what a share is worth, from the valuation methods."),
    ("Upside", "Fair value / price - 1: how far the model's value is above (or below) today's price."),
    ("Broker target", "A broker's 12-month price target: an opinion, not a fact."),
    ("Max drawdown", "The largest fall from a peak to a trough over the period."),
    ("Volatility", "How much the share price moves around, annualised."),
    ("Beta", "How much the share price tends to move with the market: 1.5 means about 1.5% for every 1% market move."),
    ("AI rating", "Buy / Hold / Sell from the model's fair value versus the price (Buy if the fair value is at "
                  "least 15% above it, Sell if at least 10% below). A model output, not advice."),
    ("Overall view", "The AI rating combined with recent broker views into one score on page 2 (1 = Sell, 5 = Buy)."),
    ("Scenarios (bear / base / bull)", "Three versions of the future: bad, expected and good. Each gets a value "
                                        "and a probability; the probability-weighted average is the fair value."),
]  # F-score and RSI / MACD removed 9 Nov 2026: no longer on page 1, and a blind reviewer asked to drop them for
#   first-year students

CHECKLIST = [
    "I can explain how the company makes money in one sentence.",
    "I know whether revenue and profit are growing, and whether growth is speeding up or slowing down.",
    "I know where ROE comes from (margin, efficiency or debt) and whether profit turns into cash.",
    "I know whether the debt is comfortable (or, for a bank, that the usual debt ratios do not apply).",
    "I have compared the valuation with peers AND with the company's own history.",
    "I know which assumptions drive the fair value and what the price is assuming (reverse DCF).",
    "I know what the brokers think, how recent their views are, and why they may disagree with the model.",
    "I can name the one thing that would prove my view wrong.",
    "I have read the data audit and know which numbers are weak.",
    "I treat the AI rating as a model output, not advice.",
]


def _row(label: str, value: str, note: str = "") -> dict:
    return {"label": label, "value": value, "note": note}


def _first_last(r: list, key: str):
    pts = [(x.fiscal_year, getattr(x, key)) for x in r if getattr(x, key) is not None]
    return (pts[0], pts[-1]) if len(pts) >= 2 else (None, None)


def build(data: TearSheetData) -> dict[str, Any]:
    from ..quant.valuation import is_financial
    p, q, fin = data.profile, data.quote, data.financials
    cur, rep = ccy(q.currency), ccy(fin.currency)
    bank = is_financial(data)
    years = fin.years
    r = sorted(data.ratios, key=lambda x: x.fiscal_year)
    last = r[-1] if r else None
    ly = years[-1] if years else None
    fy = f"FY{ly.fiscal_year}" if ly else ""
    notes = (data.narrative.learner.steps if data.narrative and data.narrative.learner else {}) or {}
    steps: list[dict] = []
    exercises: list[dict] = []

    def step(key: str, look: str, why: str, rows: list, how: list[str], flags: list[str], ask: str,
             worked: Optional[dict] = None) -> None:
        n = len(steps) + 1
        steps.append({"n": str(n), "key": key, "title": dict(STEPS)[key], "look": look, "why": why,
                      "rows": [x for x in rows if x and x["value"] not in ("", "–")], "how": how, "flags": flags,
                      "ask": ask, "worked": worked, "ai": notes.get(key, "")})

    # 1 business ----------------------------------------------------------------------------------
    seg = next((s for s in data.segments if s.kind in ("business", "product") and s.segments), None)
    reg = next((s for s in data.segments if s.kind == "region" and s.segments), None)
    top = max(seg.segments, key=lambda x: x.share or 0) if seg else None
    topr = max(reg.segments, key=lambda x: x.share or 0) if reg else None
    step("business", "Tear sheet (page 2) header (name, sector, exchange) · full report: Company overview",
         "Every number in the report describes a business. If you cannot say how it makes money, the "
         "ratios will not mean much.",
         [_row("Sector", p.sector or "–"), _row("Market value (market cap)", big(q.market_cap, q.currency)),
          _row(f"Largest segment ({seg.period})", f"{top.name}: {pct(top.share, 1)} of revenue") if top and top.share else None,
          _row(f"Largest region ({reg.period})", f"{topr.name}: {pct(topr.share, 1)} of revenue") if topr and topr.share else None],
         ["Say it in one sentence: who pays the company, and for what?",
          "Check concentration: a segment or region above half of revenue drives the whole story.",
          "Read the company's own words in the 'From the latest company report' chapter."],
         ["You cannot explain the business model.", "One customer, product or country dominates and is at risk."],
         "If this company disappeared tomorrow, who would miss it, and would they simply pay someone else?")

    # 2 growth ------------------------------------------------------------------------------------
    worked = None
    rows = []
    if len(years) >= 2 and years[0].revenue and years[-1].revenue:
        a, b, n_ = years[0].revenue, years[-1].revenue, years[-1].fiscal_year - years[0].fiscal_year
        if n_ > 0 and a > 0 and b > 0:
            ratio = b / a
            cagr = ratio ** (1 / n_) - 1
            worked = {"title": f"Revenue CAGR, FY{years[0].fiscal_year} to {fy}",
                      "lines": [f"CAGR = (Revenue {fy} / Revenue FY{years[0].fiscal_year})^(1/{n_}) - 1",
                                f"= ({num(b / 1e6)} / {num(a / 1e6)})^(1/{n_}) - 1   ({rep} mn)",
                                f"= {ratio:.3f}^({1 / n_:.2f}) - 1 = {ratio ** (1 / n_):.3f} - 1 = {pct(cagr, 1)}"]}
            rows.append(_row(f"Revenue FY{years[0].fiscal_year} → {fy}", f"{rep} {num(a / 1e6)}mn → {num(b / 1e6)}mn"))
            exercises.append({"q": f"Work out the revenue CAGR from FY{years[0].fiscal_year} to {fy}.",
                              "where": "Tear sheet (page 2) · 5-year financial summary, Revenue row",
                              "answer": pct(cagr, 1), "working": worked["lines"]})
    yoy = [f"FY{x.fiscal_year} {pct(x.revenue_growth, 1, signed=True)}" for x in r if x.revenue_growth is not None]
    if yoy:
        rows.append(_row("Year-on-year growth", " · ".join(yoy[-4:])))
    lt = data.financials.latest  # the current trend: latest year-to-date and quarter vs a year earlier
    if lt is not None and lt.revenue_growth is not None:
        rows.append(_row(f"Latest: {lt.label} vs a year earlier", pct(lt.revenue_growth, 1, signed=True),
                         "the current trend; read it before the fiscal-year history"))
    if lt is not None and lt.quarter_label and lt.quarter_revenue_growth is not None:
        rows.append(_row(f"Latest quarter: {lt.quarter_label} vs a year earlier",
                         pct(lt.quarter_revenue_growth, 1, signed=True),
                         "faster than the year to date = accelerating; slower = slowing"))
    est = (data.consensus.estimates if data.consensus else [])[:1]
    for e in est:
        if e.revenue_growth is not None:
            rows.append(_row(f"Analysts expect ({e.period})", pct(e.revenue_growth, 1, signed=True), "third-party consensus"))
    c = data.comps
    if c and c.target.revenue_growth is not None and c.median.revenue_growth is not None:
        rows.append(_row("Revenue growth vs peers (latest quarter vs a year earlier)",
                         f"{pct(c.target.revenue_growth, 1, signed=True)} vs {pct(c.median.revenue_growth, 1, signed=True)}"))
    step("growth", "Tear sheet (page 2) · 5-year financial summary (Revenue and YoY rows)",
         "Profits and value follow revenue over time. Growth that is steady and comes from the core business is "
         "worth more than one big jump.",
         rows,
         ["CAGR smooths out the bumps; then read the years one by one: is growth speeding up or slowing down?",
          "Compare with peers and with what analysts expect next year.",
          "Check that profit grows too: revenue growth bought with lower margins is weaker."],
         ["Growth in one year only (an acquisition or one-off).", "Growth slowing every year.",
          "Revenue up but profit down for several years."],
         "What has to happen for growth to continue, and is that in the company's control?", worked)

    # 3 profit ------------------------------------------------------------------------------------
    rows, worked = [], None
    for key, label in ([("net_margin", "Net margin")] if bank else
                       [("gross_margin", "Gross margin"), ("operating_margin", "Operating margin"),
                        ("net_margin", "Net margin")]):
        f0, f1 = _first_last(r, key)
        if f0:
            ch = f1[1] - f0[1]
            rows.append(_row(f"{label} FY{f0[0]} → FY{f1[0]}", f"{pct(f0[1], 1)} → {pct(f1[1], 1)}",
                             f"{'up' if ch > 0 else 'down'} {abs(ch) * 100:.1f}pp"))
    du = data.dupont
    if du and du.roe is not None:
        rows.append(_row(f"ROE (FY{du.fiscal_year})", pct(du.roe, 1),
                         "return on equity: profit for each 100 of the owners' money in the business"))
        if du.net_margin is not None and du.asset_turnover is not None and du.equity_multiplier is not None:
            prod = round(du.net_margin, 3) * round(du.asset_turnover, 2) * round(du.equity_multiplier, 2)
            worked = {"title": f"DuPont: where ROE comes from (FY{du.fiscal_year})",
                      "lines": ["ROE = net margin x asset turnover x equity multiplier",
                                "(profit per 100 of sales) x (sales per 1 of assets) x (assets per 1 of owners' money)",
                                f"= {pct(du.net_margin, 1)} x {num(du.asset_turnover, 2)} x {num(du.equity_multiplier, 2)}",
                                f"= {pct(prod, 1)} (reported {pct(du.roe, 1)}; the small gap is rounding)"]}
    ex = _margin_what_if(r, years, du, rep)
    if ex:
        exercises.append(ex)
    eq = data.earnings_quality
    if last and last.cash_conversion is not None and not bank:
        rows.append(_row(f"Cash conversion (FY{last.fiscal_year})", f"{num(last.cash_conversion, 2)}x",
                         ("cash actually received ÷ profit booked; above 1 = profit backed by cash"
                          if last.cash_conversion >= 1 else
                          "cash actually received ÷ profit booked; below 1 = some profit not yet received as cash")))
        exercises.append({"q": f"Cash conversion is {num(last.cash_conversion, 2)}x. Are this company's profits backed "
                               "by cash? What would worry you?",
                          "where": "Tear sheet (page 2) · Return on equity · DuPont (earnings quality)",
                          "answer": ("Yes: operating cash flow exceeds net profit." if last.cash_conversion >= 1
                                     else "Only partly: operating cash flow is below net profit."),
                          "working": ["Cash conversion = cash from operations / net profit.",
                                      "Worry if it stays below about 0.8 for several years: profit may be "
                                      "booked before cash arrives (receivables, inventory) or be one-off."]})
    if eq and eq.accruals_ratio is not None and not bank:
        rows.append(_row(f"Accruals ratio (FY{eq.fiscal_year})", pct(eq.accruals_ratio, 1, signed=True),
                         "profit not yet backed by cash, as a share of assets; positive = profit ahead of cash"))
    how = (["For a bank, net margin and ROE matter most; compare ROE with the return shareholders require (the "
            "cost of equity in the valuation chapter).",
            "A bank's equity multiplier is naturally high: deposits are its raw material, not a warning sign."]
           if bank else
           ["Margins show pricing power: rising gross margin usually means a better mix or stronger prices.",
            "DuPont tells you whether ROE comes from margin, efficiency (asset turnover) or borrowing (equity multiplier).",
            "Cash conversion checks that accounting profit turns into cash."])
    step("profit", "Tear sheet (page 2) · 5-year financial summary (margins) and Return on equity · DuPont",
         "Two companies with the same profit can be very different investments: one earns it with little capital "
         "and collects it in cash, the other does not.",
         rows, how,
         ["ROE driven mainly by a high equity multiplier (borrowed money)." if not bank else
          "ROE persistently below the cost of equity.",
          "Margins falling while revenue rises.", "Cash conversion below about 0.8 for several years."],
         "Is the margin trend coming from better products and prices, or from cost cuts that cannot repeat?", worked)

    # 4 safety ------------------------------------------------------------------------------------
    rows, worked = [], None
    if bank:
        rows.append(_row("P/B", mult(q.pb)))
        rows.append(_row("Dividend yield", pct(q.dividend_yield, 1)))
        how = ["Banks borrow (deposits) as their business, so net debt, EBITDA and interest cover do not apply.",
               "Safety for a bank is about capital ratios and loan quality (in its annual report, not in this tool); "
               "here, watch ROE, the dividend and the data audit."]
        flags = ["Using industrial-company debt ratios on a bank.", "A dividend that grows faster than profits."]
    else:
        if ly and ly.total_debt is not None and ly.cash_and_equivalents is not None:
            nd = ly.total_debt - ly.cash_and_equivalents
            worked = {"title": f"Net debt ({fy})",
                      "lines": ["Net debt = total debt - cash and short-term investments",
                                f"= {num(ly.total_debt / 1e6)} - {num(ly.cash_and_equivalents / 1e6)}  ({rep} mn)",
                                f"= {num(nd / 1e6)} ({'net debt' if nd > 0 else 'net cash'})"]}
            rows.append(_row(f"Net debt / (cash) {fy}", f"{rep} {num(nd / 1e6)}mn"))
            exercises.append({"q": f"Work out net debt for {fy}. Is the company a net borrower or does it hold net cash?",
                              "where": "Tear sheet (page 2) · 5-year financial summary (Cash and Total debt rows)",
                              "answer": f"{rep} {num(nd / 1e6)}mn ({'net debt' if nd > 0 else 'net cash'})",
                              "working": worked["lines"]})
        lt = data.financials.latest  # round 3: "step 4 uses year-old balance-sheet figures"
        if lt is not None and lt.total_debt is not None and lt.cash_and_equivalents is not None:
            nd_l = lt.total_debt - lt.cash_and_equivalents
            rows.append(_row(f"Net debt / (cash) at {lt.period_end.strftime('%-d %b %Y')}", f"{rep} {num(nd_l / 1e6)}mn",
                             f"latest balance sheet ({lt.label}); debt {num(lt.total_debt / 1e6)}, cash "
                             f"{num(lt.cash_and_equivalents / 1e6)}"))
        # ratios are fiscal-year figures: say which year, so they are not read as the latest quarter's (round-5
        # review: "net cash at 26 Jul … and the current ratio 3.91x", the FY2026 figure)
        ry = f" (FY{last.fiscal_year})" if last else ""
        if last and last.net_debt_to_ebitda is not None:
            rows.append(_row(f"Net debt / EBITDA{ry}", f"{num(last.net_debt_to_ebitda, 2)}x",
                             "years of operating cash profit needed to repay net debt; below 0 = more cash than debt"))
        if last and last.interest_coverage is not None:
            rows.append(_row(f"Interest cover{ry}", f"{num(last.interest_coverage, 1)}x",
                             "how many times operating profit pays the interest bill"))
        if last and last.current_ratio is not None:
            rows.append(_row(f"Current ratio{ry}", f"{num(last.current_ratio, 2)}x", "short-term assets / short-term debts"))
        how = ["Net debt / EBITDA: roughly the years of operating cash profit needed to repay net debt. Compare "
               "with peers in the same industry; utilities can carry more than tech companies.",
               "Interest cover: how many times operating profit pays the interest bill. The thinner it is, the more "
               "a bad year hurts.",
               "Net cash (negative net debt) gives a company room to invest, pay dividends or survive a downturn."]
        flags = ["Debt rising faster than profit.", "Interest cover falling year after year.",
                 "Large debts due soon with little cash."]
    step("safety", "Tear sheet (page 2) · 5-year financial summary (Cash, Total debt, Net debt) · full report: Financial analysis",
         "A good business with too much debt can still be a bad investment: debt holders are paid first.",
         rows, how, flags, "If profit fell by a third next year, could the company still pay its interest and dividends?",
         worked)

    # 5 cheap -------------------------------------------------------------------------------------
    rows, worked = [], None
    if c:
        for key, label in [("pe_ttm", "P/E (TTM)"), ("ev_ebitda", "EV/EBITDA"), ("pb", "P/B")]:
            if bank and key == "ev_ebitda":
                continue
            t, m, d_ = getattr(c.target, key), getattr(c.median, key), c.premium_discount.get(key)
            if t is not None and m is not None and d_ is not None:
                rows.append(_row(f"{label}: company vs peer median", f"{mult(t)} vs {mult(m)}",
                                 f"{pct(d_, 1, signed=True)} ({'premium' if d_ > 0 else 'discount'})"))
        t, m = c.target.pe_ttm, c.median.pe_ttm
        if t and m:
            pd_ = t / m - 1
            worked = {"title": "Premium or discount to peers (P/E)",
                      "lines": ["Premium / discount = company P/E / peer median P/E - 1",
                                f"= {num(t, 1)} / {num(m, 1)} - 1 = {pct(pd_, 1, signed=True)}",
                                "Negative = cheaper than the middle peer; positive = dearer."]}
    band = data.pe_band
    ex = _pe_what_if(band, q.price, cur)
    if ex:
        exercises.append(ex)
    two_pe = ""
    if band:
        rows.append(_row("P/E on the last fiscal year's EPS vs its own 5-year history",
                         f"{mult(band.current)} vs median {mult(band.median)}",
                         f"{pct(band.percentile, 0)} of the last 5 years were lower"))
        ttm = q.pe_ttm
        if ttm and band.current and abs(band.current / ttm - 1) > 0.1:
            # round-6 review: the guide showed 23.6x and 38.1x without saying why they differ
            two_pe = (f"Two P/E figures: the quote box divides the price by the last four quarters' EPS "
                      f"({mult(ttm)}); the 5-year history divides it by the last full fiscal year's EPS "
                      f"({mult(band.current)}), because the history only has fiscal years. When profits are "
                      f"{'rising' if band.current > ttm else 'falling'}, the four-quarter figure is "
                      f"{'lower' if band.current > ttm else 'higher'}. Compare like with like.")
    rows.append(_row("Dividend yield", pct(q.dividend_yield, 1)))
    step("cheap", "Tear sheet (page 2) · Comparable companies and the quote box (P/E · P/B, dividend yield)",
         "A multiple on its own means little. It becomes useful when you compare it with similar companies and "
         "with the company's own past.",
         rows,
         ([two_pe] if two_pe else []) +
         ["Compare with peers (are they really similar businesses?) and with the stock's own history.",
          "Cheaper than peers is only good if the business is not worse than theirs: check growth and margins too.",
          "Use P/B for banks and insurers; P/E is meaningless for a loss-making company."],
         ["A value trap: cheap because profits are about to fall.", "Comparing companies from different industries.",
          "Forgetting that the peer median is the peers' figure, not the company's."],
         "Why is the market willing to pay less (or more) for this company than for its peers?", worked)

    # 6 worth -------------------------------------------------------------------------------------
    rows, worked = [], None
    rt, va = data.rating, data.valuation
    fc = data.forecast
    if fc and fc.years:
        y = fc.years[0]
        if y.consensus_eps and y.eps_vs_consensus is None:  # run 4: not like for like (forecast.compute)
            rows.append(_row(f"Our {y.period} EPS forecast", f"{ccy(fc.currency)} {num(y.eps, 2)}",
                             "includes this year's reported investment gains, which consensus leaves out, so the "
                             "two are not compared"))
        elif y.consensus_eps:
            rows.append(_row(f"Our {y.period} EPS forecast vs consensus",
                             f"{ccy(fc.currency)} {num(y.eps, 2)} vs {num(y.consensus_eps, 2)}",
                             "consensus is on an adjusted basis: compare growth, not the level" if fc.consensus_note
                             else "a forecast above consensus means we expect more than other analysts"))
        else:
            rows.append(_row(f"Our {y.period} EPS forecast", f"{ccy(fc.currency)} {num(y.eps, 2)}"))
    sc = va.scenarios if va else None
    if sc:
        rows.append(_row("Scenarios: bear / base / bull", " / ".join(f"{num(x.value_per_share, 2)}" for x in sc.scenarios),
                         f"probability-weighted {ccy(sc.currency)} {num(sc.weighted_value, 2)}"))
    if va and va.dcf and va.dcf.value_per_share:
        w = va.wacc.wacc
        # with scenarios, "the base case" is the base scenario: the model DCF is only a cross-check (run 1 review)
        rows.append(_row("Model DCF (cross-check, not in the rating)" if sc and rt and rt.basis == "scenarios" else
                         "DCF base case" + (" (model cross-check)" if sc else ""),
                         f"{cur} {num(va.dcf.value_per_share, 2)}",
                         (f"WACC {pct(w, 1)} · " if w else "") + f"terminal growth {pct(va.dcf.terminal_growth, 1)}"))
        # the same grid the report prints (WACC x terminal growth), not the DCF's own 3x3 (round-5 review:
        # "233.50 – 320.72" here vs "225.36 – 338.92" in the report)
        g = (va.sensitivity.discount_growth if va.sensitivity and va.sensitivity.discount_growth else None) or va.dcf.grid
        vals = [v for row in (g.values if g else []) for v in row if v]
        if vals:
            rows.append(_row("DCF range in the sensitivity grid", f"{cur} {num(min(vals), 2)} – {num(max(vals), 2)}",
                             "how much the value moves with WACC and terminal growth"))
    if va and va.ddm and va.ddm.value_per_share:
        rows.append(_row("DDM (dividend model)", f"{cur} {num(va.ddm.value_per_share, 2)}"))
    rev_row = _reverse_row(data)
    if rev_row:
        rows.append(rev_row)
    if va and va.monte_carlo:
        rows.append(_row("Monte Carlo: share of values above the price", pct(va.monte_carlo.prob_above_price, 0)))
    if rt and rt.fair_value and rt.upside is not None:
        scen_set = data.valuation.scenarios if data.valuation else None
        by_scen = rt.basis == "scenarios" and scen_set and scen_set.scenarios
        rows.append(_row("AI rating" + ("" if by_scen else " (rule-based)"),
                         f"{rt.rating} · fair value {ccy(rt.currency)} {num(rt.fair_value, 2)}",
                         f"{pct(rt.upside, 1, signed=True)} vs the price"))
        if by_scen:
            # the rating follows our scenarios: teach the probability-weighted average, the step that sets it
            sc_ = sorted(scen_set.scenarios, key=lambda x: ["bear", "base", "bull"].index(x.name))
            lines = ["Fair value = sum of (probability x scenario value), over bear, base and bull",
                     "= " + " + ".join(f"{pct(x.probability, 0)} x {num(x.value_per_share, 2)}" for x in sc_)
                     + f" = {num(rt.fair_value, 2)}"]
            ex = _weights_what_if(sc_, rt, q.price)
            if ex:
                exercises.append(ex)
        else:
            used = [m for m in rt.methods if m.included]
            lines = ["Fair value = sum of (weight x method value), weights rescaled over the methods used"]
            tw = sum(m.weight for m in used) or 1
            if used:
                lines.append("= " + " + ".join(f"{pct(m.weight / tw, 0)} x {num(m.value, 2)}" for m in used)
                             + f" = {num(rt.fair_value, 2)}")
        lines += [f"Upside = fair value / price - 1 = {num(rt.fair_value, 2)} / {num(q.price, 2)} - 1 = "
                  f"{pct(rt.upside, 1, signed=True)}",
                  f"Rule: Buy at {pct(rt.buy_threshold, 0, signed=True)} or more, Sell at "
                  f"{pct(rt.sell_threshold, 0, signed=True)} or less, otherwise Hold → {rt.rating}"]
        worked = {"title": "From our scenarios to the AI rating" if by_scen else "From methods to the AI rating",
                  "lines": lines}
        exercises.append({"q": f"The share price is {cur} {num(q.price, 2)} and the fair value is "
                               f"{ccy(rt.currency)} {num(rt.fair_value, 2)}. Work out the upside and the rating the "
                               f"rule gives.",
                          "where": "Tear sheet (page 2) · quote box (AI rating) and Valuation view",
                          "answer": f"{pct(rt.upside, 1, signed=True)} → {rt.rating}", "working": lines[-2:]})
    elif rt:
        rows.append(_row("AI rating", rt.rating, rt.reason or ""))
    step("worth", "Tear sheet (page 2) · Intrinsic value, Valuation view and the AI rating in the quote box · full report: Valuation",
         "Valuation turns the business into a price. The answer depends on a few assumptions, so learn which ones "
         "matter and how much they move the value.",
         rows,
         ["A DCF adds up future free cash flows, discounted back at the WACC. Growth, margins, the WACC and the "
          "terminal growth move it most.",
          "Read the sensitivity grid: a 1-point change in WACC can move the value a lot.",
          "The reverse DCF flips the question: what growth is today's price assuming? Compare it with the "
          "company's record.",
          ("The AI rating follows our bear / base / bull scenarios; the other methods are cross-checks. It is a "
           "model output, not advice." if data.rating and data.rating.basis == "scenarios" else
           "The AI rating is set by a fixed rule from the methods; it is a model output, not advice.")],
         ["Most of the DCF value comes from the terminal value (far-future years).",
          "Only one valuation method is available (the rating then says 'Not rated').",
          "Methods that disagree wildly (check the football field in the full report)."],
         "Which assumption would you change, and what does the sensitivity grid say the value is then?", worked)

    # 7 others ------------------------------------------------------------------------------------
    rows, worked = [], None
    ov, st = data.overall, data.street
    if ov:
        rows.append(_row("Overall view (model + recent brokers)", f"{ov.rating} · {ov.score:.2f} / 5", ov.basis))
        model_in = next((i for i in ov.inputs if i.source.startswith("InvestSync") and i.weight > 0), None)
        brk = next((i for i in ov.inputs if i.source.startswith("Brokers") and i.weight > 0), None)
        if model_in and brk and model_in.score is not None and brk.score is not None:
            worked = {"title": "How the overall view is averaged",
                      "lines": ["Scores: Sell 1 · Underperform 2 · Hold 3 · Outperform 4 · Buy 5",
                                f"Overall = model score x model weight + broker score x broker weight",
                                f"= {num(model_in.score, 2)} x {pct(model_in.weight, 0)} + {num(brk.score, 2)} x "
                                f"{pct(brk.weight, 0)} = {ov.score:.2f} → {ov.rating}",
                                f"Only broker views from the last {ov.fresh_days} days count; those older than "
                                f"{ov.full_weight_days} days count half."]}
        if ov.split:
            rows.append(_row("Model vs brokers", "views split", "two or more steps apart: find out why"))
    if st and st.brokers:
        mix = ", ".join(f"{v} {k}" for k, v in st.rating_counts.items() if v)
        rows.append(_row(f"Brokers with a dated view (last {st.window_days} days)", f"{st.brokers}", mix))
        if st.target_median is not None and st.target_upside is not None:
            rows.append(_row("Median broker target", f"{ccy(st.currency)} {num(st.target_median, 2)}",
                             f"{pct(st.target_upside, 1, signed=True)} vs the price"))
    cons = data.consensus
    if cons and cons.analysts:
        # run 1: "31 brokers covering" next to Yahoo's 57 analysts read as a contradiction; they count different things
        rows.append(_row(f"Analysts in {_source_name(cons.source)}'s consensus", f"{cons.analysts}",
                         "a wider count: every analyst in the third-party consensus, dated note or not"))
    if not ov and st and st.target_median and data.rating and data.rating.fair_value:
        gap = data.rating.fair_value / st.target_median - 1
        worked = {"title": "Our value against the brokers'",
                  "lines": [f"Gap = our fair value ÷ brokers' median target − 1",
                            f"= {num(data.rating.fair_value, 2)} ÷ {num(st.target_median, 2)} − 1 = {pct(gap, 1, signed=True)}",
                            "A big gap means we and the brokers assume different things: find which (growth, margins, "
                            "the multiple, or how much risk)."]}
    where = ("Overall view (left of the header)" if ov else "Street view (left of the header)")
    step("others", f"Tear sheet (page 2) · {where} and What brokers say · full report: Broker research",
         "Other analysts may know things the model does not, but their targets are opinions and often optimistic. "
         "The useful part is their reasoning and how it changes.",
         rows,
         ["Only recent views matter: a target from six months ago may reflect a different world.",
          "When the model and the brokers disagree ('views split'), look for the assumption behind the gap: growth, "
          "margins or the multiple.",
          "Upgrades and downgrades tell you which way opinion is moving."],
         ["Treating a broker's target as a fact.", "Counting old views as if they were current."],
         "What do the brokers assume that the model does not, or the other way round?", worked)

    # 8 wrong -------------------------------------------------------------------------------------
    rows = []
    b1 = next((x for x in (data.benchmark.periods if data.benchmark else []) if x.period == "1Y"), None)
    if b1 and b1.stock_return is not None and b1.benchmark_return is not None:
        rows.append(_row(f"1-year return vs {data.benchmark.name}",
                         f"{pct(b1.stock_return, 1, signed=True)} vs {pct(b1.benchmark_return, 1, signed=True)}"))
    tc = data.technicals
    if tc:
        if tc.max_drawdown_1y is not None:
            rows.append(_row("Largest fall in the past year (max drawdown)", pct(tc.max_drawdown_1y, 1)))
        if tc.volatility_1y is not None:
            rows.append(_row("Volatility (1 year)", pct(tc.volatility_1y, 1)))
        rows.append(_row("Technical picture (rule-based)", tc.overall))
    n = data.narrative
    if n and n.risks:
        rows.append(_row("Key risks in this report", "; ".join(b.title for b in n.risks)))
    if data.audit:
        cav = [x.name for x in data.audit.checks if x.status in ("caveat", "fail")]
        # the audit's own words, not "publishable" (round-5 review: the guide called a report with two flags
        # "publishable, no caveats")
        label = {"publishable": "data checks passed", "caveated": "data checks: see notes",
                 "review": "data checks failed"}.get(data.audit.status, data.audit.status)
        flagged = [x.name for x in data.audit.checks if x.status in ("caveat", "fail", "info")]
        rows.append(_row("Data audit", label, ("flags: " + ", ".join(flagged)) if flagged else "no flags"))
    if n and n.deep and n.deep.swing_factor:
        rows.append(_row("Swing factor (AI debate)", n.deep.swing_factor))
    step("wrong", "Tear sheet (page 2) · Key downside risks and Relative performance · full report: data audit"
         + (" and Investment debate" if n and n.deep else ""),
         "Professional analysts write the bear case before they buy. Knowing what would prove you wrong is what "
         "separates a view from a guess.",
         rows,
         ["The share price trend shows what the market currently believes. A model that disagrees with a falling "
          "price needs a clear reason.",
          "Read the data audit: caveats tell you which numbers are weak.",
          "Write down the one thing that would change your mind, and check it each quarter."],
         ["You cannot name a single thing that would make you wrong.", "Ignoring the data audit's caveats."],
         "What would have to happen for you to change your mind?")

    # big picture (AI if available, else built in code)
    big_picture = n.learner.big_picture if n and n.learner and n.learner.big_picture else _plain_summary(data)
    discussion = (n.learner.discussion if n and n.learner and n.learner.discussion else [
        "Which of the eight steps matters most for this company, and why?",
        "If you had to argue the opposite of the AI rating, what would be your best point?",
        "Which single number in the report would you check first in the company's annual report?"])
    # picture-first devices (life-cycle phase, scales, map, segment bar, P/E history, at a glance), built in code
    from . import learner_visuals
    vis = learner_visuals.build(data, bank)
    for s_ in steps:
        s_["scale"] = vis["scales"].get(s_["key"])
    homework = _homework(data, steps)
    return {"steps": steps, "exercises": exercises[:9], "visuals": vis, "questions": homework,
            "glossary": [{"term": t, "meaning": m} for t, m in GLOSSARY
                                                                if not (t == "Overall view" and data.overall is None)
                                                                and not (t.startswith("Scenarios") and not (
                                                                    data.valuation and data.valuation.scenarios))],
            "checklist": CHECKLIST, "big_picture": big_picture, "discussion": discussion,
            "bank": bank, "ai": bool(n and n.learner), "fy_note": fy_note(data)}


# 12 Nov 2026: the analyst questions as the reader's homework. Each points to the step whose numbers help most.
_DATA_STEP = {"revenue_mix": "business", "growth_history": "growth", "consensus_growth": "growth",
              "gross_margin_trend": "profit", "operating_margin_trend": "profit", "cash_conversion": "profit",
              "roic_vs_wacc": "profit", "roe_trend": "profit", "non_operating": "profit", "rnd_intensity": "profit",
              "net_cash": "safety", "receivables_vs_revenue": "safety", "inventory_vs_revenue": "safety",
              "capex_intensity": "safety", "payout": "safety", "share_count": "safety", "pe_vs_history": "cheap",
              "pb_vs_peers": "cheap", "reverse_dcf": "worth", "dcf_vs_price": "worth"}
_LOOK_STEP = {"overview": "business", "competitive": "business", "financials": "profit", "statements": "safety",
              "valuation": "worth", "street": "others", "news": "wrong"}


def _homework(data: TearSheetData, steps: list[dict]) -> list[dict]:
    """The questions an analyst would ask (narrative/questions.py), in plain words: the question, why it matters now
    (evidence ids removed: the guide has no notes table), the figure computed in code as a hint and the step to look
    at. Never the deep report's answers. [] when none can be built (never raises)."""
    import re
    try:
        from ..narrative import questions as qmod
        qs = qmod.for_report(data)
    except Exception:  # noqa: BLE001 - the guide prints without the homework
        return []
    step_n = {s_["key"]: s_ for s_ in steps}
    out = []
    for i, q in enumerate(qs.questions, 1):
        key = _DATA_STEP.get(q.data_key) or _LOOK_STEP.get(q.look or "")
        st = step_n.get(key or "")
        why = re.sub(r"\s*[\[(](?:[RNES]\d{1,3}|(?:BULL|BEAR)-\d{1,2})(?:[^\[\]()]*)[\])]", "", q.why_now or "").strip()
        out.append({"n": str(i), "theme": qmod.theme_label(q.theme, plain=True), "q": q.text, "new": q.source == "new",
                    "why": why, "hint": q.computed if qmod.has_figure(q.computed) else "",
                    "where": f"Step {st['n']}: {st['title']}" if st else ""})
    return out


def _p(x: float) -> str:
    """A probability as printed: whole percent when it is one, else one decimal."""
    return pct(x, 0) if abs(x * 100 - round(x * 100)) < 1e-6 else pct(x, 1)


def _source_name(source: Optional[str]) -> str:
    s = (source or "").strip()
    return {"Yahoo Finance": "Yahoo"}.get(s, s or "the data provider")


def _rule(upside: float, rt) -> str:
    """The rating rule (rating.compute / from_scenarios): Buy at or above the buy threshold, Sell at or below the
    sell threshold, else Hold."""
    return "Buy" if upside >= rt.buy_threshold else ("Sell" if upside <= rt.sell_threshold else "Hold")


def _reverse_row(data: TearSheetData) -> Optional[dict]:
    """Run 1 printed the model DCF's growth labelled "the base case" (41.7% against the base scenario's own path).
    The comparison is our base scenario's growth over the same years when the rating follows the scenarios,
    otherwise the model DCF's; when the reverse DCF holds the consensus years, the row says which years it solves
    for."""
    va, rt = data.valuation, data.rating
    rv = va.reverse if va else None
    if not (rv and rv.implied_growth is not None and rv.model_growth is not None):
        return None
    if rv.model != "DCF":
        return _row("Dividend growth the price assumes (reverse DDM)", f"{pct(rv.implied_growth, 1, signed=True)} a year",
                    f"vs {pct(rv.model_growth, 1, signed=True)} in the model DDM")
    from ..narrative.facts import base_scenario_cagr
    got = None
    if rt is not None and rt.basis == "scenarios":
        try:
            got = base_scenario_cagr(data)
        except Exception:  # noqa: BLE001 - fall back to the model DCF's figure
            got = None
    comp, where = (got[0], "in our base case") if got else (rv.model_growth, "in the model DCF")
    hold = rv.hold_years or 0
    if hold and rv.from_year and rv.to_year:
        return _row(f"Growth the price assumes after the {hold} consensus years (reverse DCF)",
                    f"{pct(rv.implied_growth, 1, signed=True)} a year, FY{rv.from_year}–FY{rv.to_year}",
                    f"vs {pct(comp, 1, signed=True)} {where} over the same years")
    return _row("Growth the price assumes (reverse DCF)", f"{pct(rv.implied_growth, 1, signed=True)} a year",
                f"vs {pct(comp, 1, signed=True)} {where}")


WHAT_IF_SHIFT = 0.10


def _weights_what_if(sc_: list, rt, price: Optional[float]) -> Optional[dict]:
    """Exercise: move 10 points of probability from the base case to the bear case; the new fair value and whether
    the rule's rating changes (the worked example already shows today's weighted value). The bear case's real
    probability is printed only when it pulls the value more than the bull case does (run 1 printed a hard-coded
    "28% bear case"). None when the inputs are missing."""
    by = {x.name: x for x in sc_}
    if not ({"bear", "base", "bull"} <= set(by) and price and rt.fair_value and rt.buy_threshold is not None
            and rt.sell_threshold is not None):
        return None
    bear, base, bull = by["bear"], by["base"], by["bull"]
    if base.probability < WHAT_IF_SHIFT - 1e-9:
        return None
    k = WHAT_IF_SHIFT
    new_p = {"bear": bear.probability + k, "base": base.probability - k, "bull": bull.probability}
    fv = rt.fair_value + k * (bear.value_per_share - base.value_per_share)
    up = fv / price - 1
    new = _rule(up, rt)
    same = new == rt.rating
    cur = ccy(rt.currency)
    down = bear.probability * (base.value_per_share - bear.value_per_share)
    lift = bull.probability * (bull.value_per_share - base.value_per_share)
    pull = (f"At today's weights the {_p(bear.probability)} bear case is the biggest pull on the value: "
            f"{_p(bear.probability)} x ({num(base.value_per_share, 2)} - {num(bear.value_per_share, 2)}) = "
            f"{num(down, 2)} down, against {num(lift, 2)} up from the bull case."
            if down > lift else "Each scenario counts in proportion to how likely we think it is.")
    return {"q": f"What if we were less sure of the base case? Move {round(k * 100)} percentage points of probability from the base "
                 f"case to the bear case (the bull case stays at {_p(bull.probability)}). What is the new fair value, "
                 f"and does the rating change?",
            "where": "Full report: Valuation · Analyst scenarios; this guide, step 6 (worked example)",
            "answer": (f"{cur} {num(fv, 2)} ({pct(up, 1, signed=True)} vs the price) → {new}"
                       + (" (no change)" if same else f" (changes from {rt.rating})")),
            "working": [f"New weights: bear {_p(new_p['bear'])}, base {_p(new_p['base'])}, bull {_p(new_p['bull'])}",
                        "New fair value = " + " + ".join(f"{_p(new_p[x.name])} x {num(x.value_per_share, 2)}"
                                                         for x in (bear, base, bull)) + f" = {num(fv, 2)}",
                        f"Upside = {num(fv, 2)} / {num(price, 2)} - 1 = {pct(up, 1, signed=True)} → {new}",
                        pull]}


def _pe_what_if(band, price: Optional[float], cur: str) -> Optional[dict]:
    """Exercise: the share price at which the P/E (on the last fiscal year's EPS) would equal its own 5-year median.
    The same EPS, so price x median / today's P/E. None when the inputs are missing."""
    if not (band and price and band.current and band.current > 0 and band.median and band.median > 0):
        return None
    eps = price / band.current
    at = band.median * eps
    return {"q": f"Today's P/E on the last fiscal year's EPS is {mult(band.current)} and its 5-year median is "
                 f"{mult(band.median)}. At what share price would the P/E equal its median, with the same EPS?",
            "where": "This guide, step 5 · P/E against its own 5-year history",
            "answer": f"{cur} {num(at, 2)} ({pct(at / price - 1, 1, signed=True)} vs today's {num(price, 2)})",
            "working": [f"EPS = price / P/E = {num(price, 2)} / {num(band.current, 2)} = {num(eps, 2)}",
                        f"Price at the median P/E = median P/E x EPS = {num(band.median, 2)} x {num(eps, 2)} = "
                        f"{num(at, 2)}",
                        "A price above today's means the shares trade below their usual multiple; below today's, "
                        "above it. Check whether growth has changed before calling that cheap or dear."]}


def _margin_what_if(r: list, years: list, du, rep: str) -> Optional[dict]:
    """Exercise: net profit (and ROE, with the DuPont parts) if the latest fiscal year's net margin moved back to
    its median of the three fiscal years before it. None when fewer than four years of net margin or no revenue."""
    pts = [(x.fiscal_year, x.net_margin) for x in r if x.net_margin is not None]
    if len(pts) < 4:
        return None
    (fy_l, m_l), prior = pts[-1], pts[-4:-1]
    rev = next((y.revenue for y in years if y.fiscal_year == fy_l and y.revenue), None)
    if not rev or rev <= 0:
        return None
    vals = sorted(m for _, m in prior)
    med = round(vals[1], 4)  # as printed (two decimals of a percent), so the working can be redone by hand
    now, then = rev * m_l, rev * med
    lines = [f"Median of FY{prior[0][0]}–FY{prior[-1][0]} net margins ({', '.join(pct(m, 2) for _, m in prior)}) "
             f"= the middle one = {pct(med, 2)}",
             f"Net profit = revenue x net margin = {num(rev / 1e6)} x {pct(med, 2)} = {num(then / 1e6)}  ({rep} mn)",
             f"Against {num(now / 1e6)} at FY{fy_l}'s {pct(m_l, 2)}: {pct(then / now - 1, 1, signed=True)}"
             if now > 0 else f"Against {num(now / 1e6)} at FY{fy_l}'s {pct(m_l, 2)}"]
    roe = ""
    if du and du.fiscal_year == fy_l and du.roe is not None and du.net_margin and du.net_margin > 0:
        # ROE = margin x turnover x multiplier: with the other two held, ROE moves in proportion to the margin (exact;
        # a bank's asset turnover of about 0.02 printed to two decimals would not be)
        new_roe = du.roe * med / du.net_margin
        roe = f"; ROE about {pct(new_roe, 1)}"
        lines.append(f"ROE moves in proportion to the margin (same asset turnover and equity multiplier): "
                     f"{pct(du.roe, 1)} x {pct(med, 2)} / {pct(du.net_margin, 2)} = {pct(new_roe, 1)}")
    return {"q": f"What if FY{fy_l}'s net margin ({pct(m_l, 1)}) moved back to its median of the three years before "
                 f"(FY{prior[0][0]}–FY{prior[-1][0]})? What would net profit be on the same revenue"
                 + (", and what would ROE become with the same asset turnover and equity multiplier?" if roe else "?"),
            "where": "Tear sheet (page 2) · 5-year financial summary (margins) and Return on equity · DuPont",
            "answer": f"{rep} {num(then / 1e6)}mn" + (f" ({pct(then / now - 1, 1, signed=True)})" if now > 0 else "")
                      + roe,
            "working": lines}


def fy_note(data: TearSheetData) -> str:
    """How to read the report's dates: when this company's fiscal year ends and what FY, E and TTM mean (final check,
    11 Nov 2026: a round-9 reviewer asked the guide to explain fiscal years; the Opus guide was praised for it)."""
    years = data.financials.years
    if not years:
        return ""
    y = years[-1]
    end = y.period_end
    if end.month == 12 and end.day >= 28:
        when = f"The company's fiscal (financial) year is the calendar year: FY{y.fiscal_year} = January to December {end.year}."
    else:
        when = (f"The company's fiscal (financial) year does not follow the calendar: FY{y.fiscal_year} is the 12 months "
                f"to {end.day} {end.strftime('%B %Y')}"
                + (f", so most of it falls in calendar {end.year - 1}." if end.month <= 6 else "."))
    lt = data.financials.latest
    latest = (f" The latest period in the report, {lt.label}, runs from the start of the fiscal year to "
              f"{lt.period_end.day} {lt.period_end.strftime('%B %Y')}." if lt and lt.period_end else "")
    return (when + latest + f" 'FY' means fiscal year. A year marked 'E' (for example FY{y.fiscal_year + 1}E) is an "
            "estimate, a forecast rather than a reported result. 'TTM' (trailing twelve months) means the latest four "
            "quarters added together, so it is more up to date than the last fiscal year.")


def _plain_summary(data: TearSheetData) -> str:
    p, rt, ov = data.profile, data.rating, data.overall
    parts = [f"{p.name} is listed on {p.exchange or p.market.value}" + (f" in the {p.sector} sector." if p.sector else ".")]
    fin = data.financials
    if fin.revenue_cagr is not None and fin.cagr_years:
        parts.append(f"Revenue grew {pct(fin.revenue_cagr, 1)} a year over {fin.cagr_years} years.")
    if rt:
        if rt.fair_value and rt.upside is not None:
            parts.append(f"The model values a share at {ccy(rt.currency)} {num(rt.fair_value, 2)}, "
                         f"{pct(rt.upside, 1, signed=True)} against the price, so the rule-based AI rating is {rt.rating}.")
        else:
            parts.append("The model does not give an AI rating for this stock.")
    if ov:
        parts.append(f"Combining the model with recent broker views gives an overall view of {ov.rating}"
                     + (", but the model and the brokers disagree." if ov.split else "."))
    return " ".join(parts)
