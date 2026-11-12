# InvestSync exercise pack: NVIDIA (NVDA), deep report

Built 12 Nov 2026 from the InvestSync report data of 2026-11-12. Prices are as of 2026-11-11.

What this file is: the facts the InvestSync report writers were given for this stock, word for word. The report's
own text (thesis, sections, debate, learner notes) is NOT in it: writing that text is the exercise. Use it with
SKILL.md (skill/investsync-research-notes).

What is fixed: every number, our three-year forecast, the bear / base / bull scenarios, the fair value and the rating
were set before the writing. Explain them; never change them.

Ids you can cite: [R..] research notes (dated, with their source), [E..] numbered facts below, [S..] signals computed
in code (each with the side its sign supports).

Sections: 1. Facts and signals · 2. Filing excerpts · 3. Recent news


## 1. Facts and signals

Signals computed in code (the stance is the side the figure's sign supports, by a fixed rule):
[S1] Revenue 4Y CAGR: 68.3% (sign supports the bull case)
[S2] Revenue growth FY2026: +65.5% (sign supports the bull case)
[S3] EPS growth FY2026: +66.7% (sign supports the bull case)
[S4] Consensus EPS growth FY2027E (third party): +95.4% (sign supports the bull case)
[S5] Revenue growth 1H FY2027 vs a year earlier: +95.8% (sign supports the bull case)
[S6] Revenue growth Q2 FY2027 vs a year earlier: +105.9% (sign supports the bull case)
[S7] Net profit growth 1H FY2027 vs a year earlier: +161.1% (sign supports the bull case)
[S8] Gross margin 1H FY2027 vs a year earlier: 66.6% to 75.0% (+8.3pp) (sign supports the bull case)
[S9] Free cash flow 1H FY2027 vs a year earlier: +76.5% (sign supports the bull case)
[S10] Net cash at 26 Jul 2026 (USD mn): 23,220 (sign supports the bull case)
[S11] Gross margin FY2022 to FY2026: 64.9% to 71.1% (+6.1pp) (sign supports the bull case)
[S12] Operating margin FY2022 to FY2026: 37.3% to 60.4% (+23.1pp) (sign supports the bull case)
[S13] Net margin FY2022 to FY2026: 36.2% to 55.6% (+19.4pp) (sign supports the bull case)
[S14] ROE FY2023 to FY2026: 17.9% to 101.5% (+83.6pp) (sign supports the bull case)
[S15] Cash conversion (CFO / net profit) FY2026: 0.86x
[S16] Net debt / EBITDA FY2026: -0.31x (sign supports the bull case)
[S17] Interest cover FY2026: 503.4x (sign supports the bull case)
[S18] P/E (TTM) vs peer median: 22.0x vs 49.8x (-55.9%) (sign supports the bull case)
[S19] P/E (forward) vs peer median: 10.8x vs 20.4x (-46.7%) (sign supports the bull case)
[S20] EV/EBITDA vs peer median: 22.0x vs 42.3x (-48.0%) (sign supports the bull case)
[S21] P/B vs peer median: 18.3x vs 10.6x (+72.5%) (sign supports the bear case)
[S22] Dividend yield vs peer median: 0.3% vs 0.4% (sign supports the bear case)
[S23] P/E vs its own 5-year history: 35.5x vs median 64.0x (4% of history below) (sign supports the bull case)
[S24] Model DCF (mechanical: consensus, then fade) vs price: USD 222.36 (+28.0%; WACC 11.8%, terminal growth 2.5%, FCF margin 43.3%) (sign supports the bull case)
[S25] Growth the price implies after the 2 consensus years (from FY2029 to FY2036) vs our base scenario: +7.0% a year vs +10.2% (-3.2pp) (sign supports the bull case)
[S26] Monte Carlo draws above today's price: 65% (sign supports the bull case)
[S27] AI rating (rule-based, set in code): Hold, fair value USD 196.26 (+13.0%) (sign supports the bull case)
[S28] Broker median target (third party): USD 317.00 (+82.5%) (sign supports the bull case)
[S29] 1Y share price return vs S&P 500: -9.8% vs +11.3% (sign supports the bear case)
[S30] Technical picture (rule-based): neutral
[S31] Max drawdown, 1 year: -29.4%

Facts (numbered):
Company: NVIDIA (NVDA, NASDAQ, sector: Semiconductors)
Business: NVIDIA Corporation operates as a data center scale AI infrastructure company in the United States, Taiwan, China, Hong Kong, Europe, and internationally. It operates through Compute & Networking, and Graphics segments.

Market data:
[E1] - Share price: USD 173.73
[E2] - Market cap: USD 4.20tn
[E3] - Enterprise value: USD 4.17tn
[E4] - 52-week range: 148.80 – 243.37
[E5] - P/E (TTM) · P/B: 22.0x · 18.3x
[E6] - Dividend yield (fwd): 0.6%
[E7] - Next scheduled results: 17 November 2026

Financial summary (USD mn (EPS in USD); US GAAP):
[E8] - Revenue: FY2022 26,914 | FY2023 26,974 | FY2024 60,922 | FY2025 130,497 | FY2026 215,938; 4Y CAGR 68.3%
[E9] - YoY growth: FY2023 +0.2% | FY2024 +125.9% | FY2025 +114.2% | FY2026 +65.5%
[E10] - Gross margin: FY2022 64.9% | FY2023 56.9% | FY2024 72.7% | FY2025 75.0% | FY2026 71.1%
[E11] - Net profit: FY2022 9,752 | FY2023 4,368 | FY2024 29,760 | FY2025 72,880 | FY2026 120,067; 4Y CAGR 87.3%
[E12] - Net margin: FY2022 36.2% | FY2023 16.2% | FY2024 48.8% | FY2025 55.8% | FY2026 55.6%
[E13] - Diluted EPS: FY2022 0.39 | FY2023 0.17 | FY2024 1.19 | FY2025 2.94 | FY2026 4.90
[E14] - Cash & ST investments: FY2022 21,208 | FY2023 13,296 | FY2024 25,984 | FY2025 43,210 | FY2026 49,670
[E15] - Total debt: FY2022 10,946 | FY2023 10,953 | FY2024 9,709 | FY2025 8,463 | FY2026 8,468
[E16] - Net debt / (cash): FY2022 (10,262) | FY2023 (2,343) | FY2024 (16,275) | FY2025 (34,747) | FY2026 (41,202)

Latest reported period: 1H FY2027 (to 26 Jul 2026; USD mn; vs 1H FY2026). These are the most recent results; prefer them to fiscal-year figures when describing the current trend:
[E17] - Revenue: 177,837 vs 90,805 (+95.8%)
[E18] - Gross margin: 75.0% vs 66.6% (+8.3pp)
[E19] - Operating profit: 117,270 vs 50,078 (+134.2%)
[E20] - Net profit (attributable): 118,010 vs 45,197 (+161.1%)
[E21] - Operating cash flow: 74,421 vs 42,779 (+74.0%)
[E22] - Capex: 4,434 vs 3,122 (+42.0%)
[E23] - Free cash flow: 69,987 vs 39,657 (–)
Latest quarter alone (Q2 FY2027 vs a year earlier):
[E24] - Revenue: 96,221 vs 46,743 (+105.9%)
[E25] - Gross margin: 75.0% vs 72.4% (+2.6pp)
[E26] - Net profit (attributable): 59,688 vs 26,422 (+125.9%)
[E27] Balance sheet at 26 Jul 2026: Cash and marketable securities 56,586; Total debt 33,366; Net cash 23,220; Debt / equity 0.15x
[E28] Trailing twelve months (FY2026 + 1H FY2027 - the same period a year earlier): Revenue 302,970; Net profit 192,880; Operating cash flow 134,360; Free cash flow 127,006; FCF margin 41.9%
[E29] - Earnings quality: 1H FY2027 net profit (118,010mn) is 101% of operating profit (117,270mn), so income below the operating line (investment gains, interest or other one-offs) is unusually large this period; the filing shows gains on investments of 23,707mn for the 6 months to 26 Jul 2026 (7,771mn in the quarter to 26 Jul 2026), about 20% of net profit; these sit below operating profit, so they lift net profit and EPS but NOT the operating margin. Quote the period total, not one quarter. They are accounting gains (mostly fair-value changes on stakes still held), NOT cash: operating cash flow deducts them, and only the proceeds of stakes actually sold are cash; never call them cash or cash earnings; operating profit grew +134.2% against net profit +161.1%: use operating-profit growth for the trend and do not credit the net-profit jump to the business.
[E30] - Cash conversion: 1H FY2027 operating cash flow / net profit 0.63x (same months a year earlier 0.95x); FY2026 0.86x. Use the latest period's ratio for the current picture, not the fiscal year's.
- Cash definition: cash and cash equivalents + current marketable debt securities, from the company's SEC filings (equity stakes excluded)

FILING DATA (key items from the company's own filed data, SEC XBRL (the company's 10-Q / 10-K); use these figures with the period shown. Where an item is NOT IN THE TAGGED DATA, do not give a figure for it from a news story or an older period: give it only if a KEY FACT from the latest results documents states it, otherwise leave it out or say it was not found in the data read; never write that the company did not disclose it, since the filing's text may give it):
[E31] - Cash spent on share buybacks (6 months to 26 Jul 2026): USD 39.0bn.
[E32] - Dividends paid (6 months to 26 Jul 2026): USD 6,290mn.
[E33] - Buyback authorisation remaining (at 26 Jul 2026): USD 99.3bn (as at the period end; a later announcement may have changed it).
[E34] - Gains (losses) on investments, below operating profit (6 months to 26 Jul 2026): USD 23.7bn.
[E35] - Gains (losses) on investments, below operating profit (quarter to 26 Jul 2026): USD 7,771mn.
[E36] - Total non-operating income (expense) (6 months to 26 Jul 2026): USD 24.1bn.
[E37] - Purchase obligations (commitments not on the balance sheet) (at 26 Jul 2026): NOT IN THE TAGGED DATA (not reported in the filing's XBRL data for this period).
[E38] - Guarantees, maximum exposure (at 26 Jul 2026): USD 108.5bn.
[E39] - Share-based compensation (6 months to 26 Jul 2026): USD 3,954mn.
[E40] - Listed equity stakes (fair value) (at 26 Jul 2026): USD 42.8bn.
[E41] - Non-marketable equity stakes (carrying value) (at 26 Jul 2026): USD 47.9bn.
[E42] - Equity-method investments (at 26 Jul 2026): NOT IN THE TAGGED DATA (not reported in the filing's XBRL data for this period).

[E43] DuPont decomposition (FY2026, average balances): Net margin 55.6%; Asset turnover 1.36x; Equity multiplier 1.35x; ROE 101.5%
[E44] Earnings quality: Cash conversion (CFO / net profit) 0.86x; Accruals ratio +10.9%

Relative valuation (Peers with the same business model (selected with AI assistance from the industry and named competitors, each checked to be listed and profitable; multiples from EastMoney and Yahoo Finance). The reason for each peer is in the full report (competitive landscape). Left out by the code's screens: MU, SKHY.):
[E45] - P/E TTM: NVDA 22.0x vs peer median 49.8x (premium/discount -55.9%)
[E46] - P/E forward (next-year consensus): NVDA 10.8x vs peer median 20.4x (premium/discount -46.7%)
[E47] - EV/EBITDA (TTM): NVDA 22.0x vs peer median 42.3x (premium/discount -48.0%)
[E48] - P/B: NVDA 18.3x vs peer median 10.6x (premium/discount +72.5%)
[E49] - Div yield: NVDA 0.3% vs peer median 0.4% (premium/discount -33.1%)
- Peers: Advanced Micro… (AMD), Broadcom (AVGO), Marvell (MRVL), QUALCOMM (QCOM)

Intrinsic value (DCF, illustrative, computed in code):
[E50] - Risk-free rate (US 10Y): 4.98%
[E51] - Beta (2Y weekly, adjusted): 1.53
[E52] - Equity risk premium: 4.46%
[E53] - Cost of equity: 11.8%
[E54] - Cost of debt (after tax): 4.2%
[E55] - Debt / capital: 0.8%
[E56] - WACC: 11.8%
[E57] - FCF margin (3Y median): 43.3%
[E58] - Terminal growth: 2.5%
[E59] - Revenue path: consensus FY2027–2028, then fades
[E60] - The rating's DCF method is the probability-weighted value of our scenarios: USD 196.26 vs share price USD 173.73 (+13.0%); bear USD 77.36 (30%); base (our forecast) USD 209.92 (50%); bull USD 340.47 (20%)
[E61] - The model's mechanical DCF (consensus revenue, then a fade; the assumptions above) gives USD 222.36 per share: a cross-check, not in the rating. Call it 'the model's mechanical DCF', never 'our base case'; the reverse DCF and the Monte Carlo below use it too.
[E62] - Range across WACC and Terminal growth sensitivities: 195.00 to 259.85

[E63] AI rating (from our probability-weighted scenarios, computed in code; you explain it, you do not choose it): Hold; fair value (our scenarios) USD 196.26 (+13.0% vs the share price); confidence low.
[E64] - Confidence comes from the spread of our scenarios and how far the peer multiples sit from our value (Our scenarios: bear USD 77.36 (30%); base USD 209.92 (50%); bull USD 340.47 (20%); probability-weighted spread 47% of the value; peer multiples (median) +66% vs our value, outside the rating).
[E65] - The same thresholds give Buy at or below USD 170.66 and Sell at or above USD 218.07.

Broker views (third-party opinions, compared in code; attribute them to the brokers):
[E66] - 30 brokers acted on the stock in the last 180 days (67 rating or target actions).
[E67] - Latest ratings: 16 Buy, 11 Outperform, 3 Hold (90% positive).
[E68] - Rating changes in the window: 0 upgrades and 3 downgrades.
[E69] - Price targets from 30 brokers range USD 186.00–515.00; the median USD 317.00 is +82.5% vs the share price (6 older than 90 days).
[E70] - The InvestSync model's fair value (USD 196.26) is inside the brokers' range (29 of 30 targets are higher).
[E71] - Most bullish target: Raymond James (USD 515.00); most cautious: Evercore ISI Group (USD 186.00).

Share price performance vs S&P 500:
[E72] - 1Y: stock -9.8%, benchmark +11.3%, relative -21.1pp
[E73] - 3Y: stock +258.4%, benchmark +72.7%, relative +185.7pp
[E74] - 5Y: stock +474.2%, benchmark +63.9%, relative +410.3pp

[E75] Data gaps: FY2022 EPS restated for a 10-for-1 share split.; Cash (cash, cash equivalents and current marketable debt securities; equity stakes excluded) and debt are taken from the company's SEC filings (XBRL).

Sector playbook (how an analyst reads this kind of company; guidance only, not data about this company):
- Lead with the latest reported period (quarter or half-year) and how it compares with a year earlier; annual figures alone are stale.
- Separate reported figures from adjusted ones (non-IFRS, non-GAAP) and never mix the two bases in one comparison.
- Check that free cash flow follows profit; when capex jumps, say whether it is maintenance or growth spending.
- State net cash or net debt on the company's own definition and its date.
- Explain what the share price already implies before arguing it is cheap or expensive.
- Compare multiples only on the same basis (trailing with trailing, forward with forward).
- Never give a cause for a change unless the facts or filings state it.
- Revenue by end market (data centre, gaming, automotive, PC / phone) and by product generation drives the story; the latest quarter and next-quarter guidance matter most.
- Gross margin shows pricing power and product mix; inventory charges and new-product ramps move it.
- Customer concentration: a few hyperscalers can be a large share of sales; their capex plans are a leading indicator.
- Supply chain: foundry capacity, advanced packaging and memory supply can cap shipments.
- Export controls and geopolitics affect what can be sold where.
- Peers should share the business model: chip designers versus foundries versus memory makers are valued very differently, and memory makers are deeply cyclical, so their trailing multiples look low at peak earnings.
- Use forward earnings for fast growers; trailing multiples overstate how expensive they are.

[E76] Revenue by product (FY2026, USD): Data Center 89.7% (193.7bn); Gaming 7.4% (16.0bn); Professional Visualization GPUs 1.5% (3.2bn); Automotive GPUs and related products 1.1% (2.3bn); OEM and Other 0.3% (619.0mn)
[E77] Revenue by region (FY2026, USD): United States 69.3% (149.6bn); Taiwan 19.6% (42.3bn); Mainland China & Hong Kong 9.1% (19.7bn); Other 2.0% (4.3bn)

Key ratios (FY2022, FY2023, FY2024, FY2025, FY2026):
[E78] - Gross margin: FY2022 64.9% | FY2023 56.9% | FY2024 72.7% | FY2025 75.0% | FY2026 71.1%
[E79] - Operating margin: FY2022 37.3% | FY2023 15.7% | FY2024 54.1% | FY2025 62.4% | FY2026 60.4%
[E80] - EBITDA margin: FY2022 41.7% | FY2023 21.4% | FY2024 56.6% | FY2025 63.8% | FY2026 61.7%
[E81] - Net margin: FY2022 36.2% | FY2023 16.2% | FY2024 48.8% | FY2025 55.8% | FY2026 55.6%
[E82] - FCF margin: FY2022 30.2% | FY2023 14.1% | FY2024 44.4% | FY2025 46.6% | FY2026 44.8%
[E83] - SG&A / revenue: FY2022 8.0% | FY2023 9.0% | FY2024 4.4% | FY2025 2.7% | FY2026 2.1%
[E84] - R&D / revenue: FY2022 19.6% | FY2023 27.2% | FY2024 14.2% | FY2025 9.9% | FY2026 8.6%
[E85] - ROE: FY2023 17.9% | FY2024 91.5% | FY2025 119.2% | FY2026 101.5%
[E86] - ROA: FY2023 10.2% | FY2024 55.7% | FY2025 82.2% | FY2026 75.4%
[E87] - ROIC: FY2022 60.2% | FY2023 21.4% | FY2024 108.7% | FY2025 158.5% | FY2026 95.3%
[E88] - Revenue growth: FY2023 +0.2% | FY2024 +125.9% | FY2025 +114.2% | FY2026 +65.5%
[E89] - EPS growth: FY2023 -55.8% | FY2024 +600.0% | FY2025 +147.1% | FY2026 +66.7%
[E90] - Current ratio: FY2022 6.65x | FY2023 3.52x | FY2024 4.17x | FY2025 4.44x | FY2026 3.91x
[E91] - Debt / equity: FY2022 0.41x | FY2023 0.50x | FY2024 0.23x | FY2025 0.11x | FY2026 0.05x
[E92] - Liabilities / assets: FY2022 39.8% | FY2023 46.3% | FY2024 34.6% | FY2025 28.9% | FY2026 23.9%
[E93] - Net debt / EBITDA: FY2022 -0.92x | FY2023 -0.41x | FY2024 -0.47x | FY2025 -0.42x | FY2026 -0.31x
[E94] - Interest cover (EBIT / interest): FY2022 42.5x | FY2023 16.1x | FY2024 128.3x | FY2025 329.8x | FY2026 503.4x
[E95] - Asset turnover: FY2023 0.63x | FY2024 1.14x | FY2025 1.47x | FY2026 1.36x
[E96] - Receivable days: FY2023 57 | FY2024 41 | FY2025 46 | FY2026 52
[E97] - Inventory days: FY2023 122 | FY2024 115 | FY2025 86 | FY2026 92
[E98] - Capex / revenue: FY2022 3.6% | FY2023 6.8% | FY2024 1.8% | FY2025 2.5% | FY2026 2.8%
[E99] - Cash conversion (CFO / NP): FY2022 0.93x | FY2023 1.29x | FY2024 0.94x | FY2025 0.88x | FY2026 0.86x
[E100] - Accruals ratio: FY2023 -3.0% | FY2024 +3.1% | FY2025 +9.9% | FY2026 +10.9%
[E101] - Effective tax rate: FY2022 1.9% | FY2023 -4.5% | FY2024 12.0% | FY2025 13.3% | FY2026 15.1%
[E102] - Dividend payout: FY2022 4.1% | FY2023 9.1% | FY2024 1.3% | FY2025 1.1% | FY2026 0.8%
[E103] - Total payout (div. + buybacks): FY2022 4.1% | FY2023 238.9% | FY2024 33.4% | FY2025 47.4% | FY2026 34.2%

[E104] Reverse DCF: After the 2 consensus years, today's price implies revenue growth of 7.0% a year from FY2029 to FY2036. Implied revenue growth, FY2029–FY2036 (constant, per year) +7.0%; Model DCF revenue growth over the same years (CAGR) +10.2%; Our base scenario's revenue growth (CAGR, same years) +10.2%; Implied FCF margin at the model DCF's growth 33.7%; Model DCF FCF margin 43.3%
[E105] What the price implies vs our base case (computed in code): after the 2 consensus years, the price needs revenue growth of 7.0% a year from FY2029 to FY2036 at the model's margins; our base case grows 10.2% a year over those years (gap -3.2 percentage points). The market is pricing LESS growth than our base case, so the price discounts a slower path than ours; say so.
The reverse DCF compares the price with the model's mechanical DCF (a cross-check), not with our scenarios. Never call that growth 'our base case'; our base case is the base scenario, whose revenue path is our forecast.
[E106] Monte Carlo of the DCF value: Draws (valid / total) 5,000 / 5,000; 10th percentile USD 98.50; 25th percentile USD 143.17; Median USD 219.49; 75th percentile USD 337.19; 90th percentile USD 503.26; Share of draws above today's price 65%
[E107] P/E history (5 years; price divided by the last published fiscal-year EPS, a different basis from the TTM P/E in the market data, so never compare the two): today's P/E on this basis is below its 5-year median; Current (price / last fiscal-year EPS) 35.5x; 5-year median 64.0x; Range 29.1x – 557.2x; Percentile of history 4%
[E108] Analyst consensus (Yahoo Finance, a wider set than the dated broker notes; third party): Mean target USD 309.72; Median target USD 302.50; Range 180.00 – 515.00; Analysts 56; Implied vs price +78.3%
[E109] - Consensus FY2027E: EPS 9.32 (USD), EPS growth +95.4%, revenue 412.1bn, revenue growth +90.8%
[E110] - Consensus FY2028E: EPS 15.93 (USD), EPS growth +70.9%, revenue 692.3bn, revenue growth +68.0%
[E111] Consensus by quarter (third party, Yahoo Finance; EPS on the analysts' adjusted basis): Q3 FY2027E (results 17 Nov 2026): revenue USD 109,043mn (+91.3% y/y), EPS 2.48 (44 analysts); Q4 FY2027E: revenue USD 124,920mn (+83.4% y/y), EPS 2.75 (42 analysts)
[E112] Over 90 days, consensus FY2028E EPS went from 12.82 to 15.93 (+24.2%) while the share price went from 225.05 to 173.73 (-22.8%): the P/E on FY2028E EPS moved from 17.6x to 10.9x, so the multiple fell: a de-rating, not lower estimates (Yahoo Finance consensus).
[E113] Options expiring 18 Nov 2026 (after the results) price a move of about ±11.3% from the last close (at-the-money straddle; includes ordinary volatility to that date).

[E114] Value ranges per share (USD): 52-week trading range 148.80 – 243.37; Analyst price targets 180.00 – 515.00; Peer P/E (forward) 270.89 – 401.39; Peer EV/EBITDA 233.71 – 504.66; Peer P/B 71.62 – 133.42; DCF (sensitivity range) 190.85 – 270.20; Monte Carlo (P10-P90) 98.50 – 503.26
[E115] Rating methods: DCF (analyst scenarios, probability-weighted) 196.26 (weight 100%); DCF (model, mechanical) 222.36 (cross-check: +13% vs our value); Peer P/E (median) 326.16 (cross-check: +66% vs our value); Peer EV/EBITDA (median) 356.16 (excluded: not used even as a cross-check: +60% vs the median of the methods (outlier rule)); Peer P/B (median) 100.74 (excluded: not used even as a cross-check: -55% vs the median of the methods (outlier rule))

[E116] Technical picture (11 Nov 2026): overall Neutral; Trend (price vs 200-day average) Negative; Moving-average cross (50 vs 200-day) Positive; Short-term trend (price vs 50-day average) Negative; RSI 14 (overbought >= 70, oversold <= 30) Positive; MACD histogram Negative
[E117] Returns vs S&P 500: 1M -23.2% vs -2.4%; 3M -22.4% vs -1.7%; 6M -22.9% vs +2.4%; YTD -6.6% vs +11.3%; 1Y -9.8% vs +11.3%; 3Y +258.4% vs +72.7%; 5Y +474.2% vs +63.9%
[E118] Risk: Volatility (1Y, annualised) 38.6%; Beta vs benchmark (2Y weekly, adjusted) 1.53; Max drawdown, 1 year -29.4% (largest peak-to-trough fall within the period, not a return over it); Max drawdown, 3 years -36.9% (largest peak-to-trough fall within the period, not a return over it)

[E119] Operating comparison (Yahoo Finance: revenue growth and operating margin are the latest quarter; gross margin and ROE trailing twelve months): NVIDIA: latest-quarter revenue growth +105.9%, gross margin 74.7%, latest-quarter operating margin 65.2%, ROE 117.2%; Advanced Micro Devices: latest-quarter revenue growth +44.7%, gross margin 56.0%, latest-quarter operating margin 17.8%, ROE 12.0%; Broadcom: latest-quarter revenue growth +85.5%, gross margin 75.5%, latest-quarter operating margin 48.8%, ROE 44.2%; Marvell Technology: latest-quarter revenue growth +36.5%, gross margin 52.2%, latest-quarter operating margin 16.8%, ROE 16.5%; QUALCOMM: latest-quarter revenue growth -8.4%, gross margin 53.1%, latest-quarter operating margin 20.8%, ROE 52.8%; Peer median: latest-quarter revenue growth +40.6%, gross margin 54.6%, latest-quarter operating margin 19.3%, ROE 30.4%

[E120] Short interest: 1.2% of the free float, 2.7 days to cover (-10% vs the prior month), as of 30 Oct 2026 (exchange data via Yahoo Finance).

[E121] Largest institutional holders (13F): Blackrock Inc. 8.06%; Vanguard Capital Management LLC 6.39%; FMR, LLC 4.26%; State Street Corporation 4.19%; Geode Capital Management, LLC 2.52%
[E122] Upcoming / recent events: 25 Feb 2026 Filed: 10-K filed 2026-02-25; 26 Aug 2026 Filed: 10-Q filed 2026-08-26; 10 Sep 2026 Last ex-dividend date (annual rate USD 1.00); 17 Nov 2026 Next scheduled results (date confirmed by the company)

[E123] Official announcements (last 90 days): 2026-11-12 8-K: Director or officer change: 8-K: Director or officer change; 2026-08-26 Quarterly report (10-Q): Quarterly report (10-Q); 2026-08-26 8-K: Results of operations: 8-K: Results of operations; 2026-08-17 8-K: Material agreement; New financial obligation; Regulation FD disclosure: 8-K: Material agreement; New financial obligation; Regulation FD disclosure

Data caveats to keep visible: AI rating: Hold from our probability-weighted scenarios, low confidence; cross-checks (not in the rating): DCF (model, mechanical), Peer P/E (median), Peer EV/EBITDA (median), Peer P/B (median)

KEY FACTS from the latest results documents (read in full; e.g. NVIDIA Announces Financial Results for Second Quarter Fiscal 2027 (8-K filed 2026-08-26, E, 2026-08-26). They are the current figures as of the results date: they override any older note, press report or earlier quarter on the same item; a company announcement listed under UPDATES below supersedes them on its item; date management's statements by these documents; notes sourced 'Earnings call, as reported by ...' are management's statements on the call (company guidance):
[E124] - Guidance (2026-08-26, SEC EDGAR): Management expects third-quarter fiscal 2027 revenue of $108.0 billion, plus or minus 2%, and is not assuming any Data Center compute revenue from China in its outlook.
[E125] - Guidance (2026-08-26, SEC EDGAR): Management expects third-quarter fiscal 2027 GAAP and non-GAAP gross margins of 74.0%, plus or minus 50 basis points.
[E126] - Guidance (2026-08-26, SEC EDGAR): Management expects third-quarter fiscal 2027 GAAP operating expenses of approximately $9.2 billion and non-GAAP operating expenses of approximately $9.0 billion.
[E127] - Guidance (2026-08-26, SEC EDGAR): For the full year fiscal 2027, NVIDIA expects GAAP and non-GAAP tax rates to be between 16.0% and 18.0%, excluding any discrete items and material changes to NVIDIA's tax environment.
[E128] - Guidance (2026-08-26, Earnings call, as reported by Yahoo Finance): Management said on the call that fourth-quarter gross margin is expected to bottom in the 71% to 72% range.
[E129] - Guidance (2026-08-26, Earnings call, as reported by Yahoo Finance): Management said on the call that it guides fiscal 2028 revenue growth of approximately 70%, driven by robust demand and supply chain expansion.
[E130] - Results driver (2026-08-26, SEC EDGAR): Data Center revenue for the second quarter was a record $89.0 billion, up 117% from a year ago and up 18% sequentially.
[E131] - Results driver (2026-08-26, SEC EDGAR): Edge Computing revenue for the second quarter was $7.2 billion, up 27% from a year ago and up 13% sequentially.
[E132] - Results driver (2026-08-26, SEC EDGAR): Data Center revenue growth was driven by the ramp of Blackwell Ultra infrastructure.
[E133] - Results driver (2026-08-26, SEC EDGAR): ACIE revenue increased 138% from a year ago and 25% sequentially driven by end-demand from AI natives, enterprises, and sovereign customers, as well as hyperscalers utilizing AI clouds.
[E134] - Results driver (2026-08-26, SEC EDGAR): Edge Computing increases were driven by strong sales of Blackwell workstations, partially offset by slower consumer PC sales that were tempered by elevated memory and systems prices.
[E135] - Results driver (2026-08-26, SEC EDGAR): GAAP and non-GAAP gross margins for the second quarter increased from a year ago on improved mix from Blackwell Ultra.
[E136] - Results driver (2026-08-26, SEC EDGAR): GAAP and non-GAAP gross margins were approximately flat sequentially as the Blackwell architecture remains the vast majority of revenue.
[E137] - Results driver (2026-08-26, SEC EDGAR): Operating expense increases were driven by higher compute infrastructure and compensation and benefits costs.
[E138] - Results driver (2026-08-26, SEC EDGAR): Shipments of Data Center Hopper products to China during the quarter were less than 1% of Data Center revenue.
[E139] - Demand / customers (2026-08-26, SEC EDGAR): Supply and capacity commitments increased from $119 billion last quarter to $279 billion, primarily related to the procurement of memory.
[E140] - Demand / customers (2026-08-26, SEC EDGAR): The maximum gross exposure under all land, power, and shell guarantee agreements for AI cloud partners is $3.5 billion.
[E141] - Demand / customers (2026-08-26, SEC EDGAR): In August 2026, NVIDIA entered into guarantees to provide credit support on the land, power, and shell buildout to secure approximately 4.25 gigawatts (GW) at SB Energy's PORTS-Pike Technology Campus in Ohio, with guarantee obligations capped at a total of $105 billion.
[E142] - Earnings quality (2026-08-26, SEC EDGAR): Net gains from equity securities for the second quarter were $7.8 billion.
[E143] - Earnings quality (2026-08-26, SEC EDGAR): Beginning in the first quarter of fiscal 2027, NVIDIA's non-GAAP financial measures no longer exclude stock-based compensation expense, and the historical non-GAAP financial information presented has been updated to include stock-based compensation expense.
[E144] - Earnings quality (2026-08-26, SEC EDGAR): During the second quarter NVIDIA reclassified a company from AI Clouds, Industrial, & Enterprise (ACIE) to Hyperscale due to a change in their business model and recast the prior period revenue associated with this company.
[E145] - Earnings quality (2026-08-26, SEC EDGAR): H20 charges/(releases), net, were ($180 million) and insignificant for the second quarter of fiscal years 2026 and 2027, respectively, and $4.5 billion and none for the first quarter.
[E146] - Event (2026-08-26, SEC EDGAR): During the second quarter of fiscal 2027, NVIDIA returned approximately $26.0 billion to shareholders in the form of shares repurchased and cash dividends. (as of the results date; see the later update under UPDATES below)
[E147] - Event (2026-08-26, SEC EDGAR): As of the end of the second quarter, the company had approximately $99.0 billion remaining under its share repurchase authorization. (as of the results date; see the later update under UPDATES below)
[E148] - Event (2026-08-26, SEC EDGAR): NVIDIA will pay its next quarterly cash dividend of $0.25 per share on October 1, 2026, to all shareholders of record on September 10, 2026. (as of the results date; see the later update under UPDATES below)
[E149] - Capex / investment (2026-08-26, SEC EDGAR): NVIDIA issued $25.0 billion of senior unsecured notes in the second quarter to be used for general corporate purposes.
[E150] - Capex / investment (2026-08-26, SEC EDGAR): Cash, cash equivalents, and marketable debt securities were $56.6 billion, up from $53.6 billion a year ago and up from $50.3 billion a quarter ago.

UPDATES SINCE THE LATEST RESULTS (company announcements dated after the key facts; on the same item they supersede the key fact: give the newer figure and date both):
[E151] - Guidance (reported 2026-10-01; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): NVIDIA added $150 billion to its share repurchase authorization, bringing the remaining authorization to $235 billion, with the company planning to execute the program through fiscal 2028.
[E152] - Event (2026-09-03, SEC EDGAR): On September 2, 2026, NVIDIA Corporation entered into a definitive agreement to acquire Hugging Face, Inc.
[E153] - Event (2026-09-03, SEC EDGAR): NVIDIA expects the Hugging Face acquisition to close in the first half of 2027, subject to customary closing conditions including receipt of required regulatory approvals.
[E154] - Event (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): Nvidia's board said it is investigating whether CEO Jensen Huang was the target of a foreign intelligence effort, and said it has no reason to believe Nvidia's secrets were compromised and has confidence in Huang.
[E155] - Event (reported 2026-09-29; when it happened is not stated, Bing News: The Globe and Mail (company statement reported by The Globe and Mail: it is company guidance; write that management said it, as reported by The Globe and Mail)): On Sept. 28, NVIDIA authorized an additional $150 billion for stock buybacks, the largest increase in a share repurchase authorization in history, surpassing Apple Inc.'s $110 billion authorization in 2024.
[E156] - Event (reported 2026-09-29; when it happened is not stated, Bing News: Mint (company statement reported by Mint: it is company guidance; write that management said it, as reported by Mint)): NVIDIA said it expects to execute the total remaining buyback programme through fiscal year 2028.

Research notes (dated facts read from results releases, announcements, broker reports and news; each has a verbatim source quote; attribute views and forecasts to whoever made them):
[E157] - Guidance (2026-08-26, SEC EDGAR): NVIDIA reported record Q2 FY27 revenue of $96.2 billion, up 106% year over year and 18% sequentially.
[E158] - Guidance (2026-08-26, SEC EDGAR): NVIDIA's forward-looking statements cover expectations for the PORTS-Pike Technology Campus buildout, related guarantees and anticipated NVIDIA deployments, revenue and upgrade cycles, as well as revenue under agreements with AI clouds and its financing arrangements.
[E159] - Guidance (2026-05-20, SEC EDGAR): NVIDIA's Q2 FY2027 outlook, given in the Q1 FY2027 CFO commentary dated 2026-05-20, guides GAAP gross margin of 74.9% and non-GAAP gross margin of 75.0%.
[E160] - Guidance (2026-05-20, SEC EDGAR): For the second quarter of fiscal 2027, management expects GAAP and non-GAAP operating expenses of approximately $8.5 billion and $8.3 billion, respectively.
[E161] - Guidance (reported 2026-11-09; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): Management's gross margin guidance falls from 75% in Q2 FY2027 to 71% to 72% in Q4.
[E162] - Guidance (reported 2026-10-22; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Analysts expect Nvidia's revenue to surge 91% to a record $109 billion, in line with the $108 billion guidance Nvidia itself offered two months ago.
[E163] - Guidance (reported 2026-10-01; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): In the second quarter of fiscal 2027, NVIDIA's revenues jumped 106% year over year to $96.2 billion, while Data Center revenues surged 117% to $89 billion.
[E164] - Guidance (reported 2026-10-01; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): NVIDIA's GAAP and non-GAAP gross margins were both 75% in the second quarter of fiscal 2027.
[E165] - Results driver (2026-05-20, SEC EDGAR): NVIDIA reported record first-quarter fiscal 2027 revenue of $81.6 billion, up 85% from a year ago and up 20% sequentially.
[E166] - Results driver (2026-05-20, SEC EDGAR): Data Center revenue for the first quarter was a record $75.2 billion, up 92% from a year ago and up 21% sequentially, driven by the ramp of Blackwell 300 products and demand for InfiniBand, Spectrum-X Ethernet, and NVLink solutions.
[E167] - Results driver (2026-05-20, SEC EDGAR): Hyperscale revenue increased sequentially and remained at approximately 50% of Data Center revenue, while the remaining 50% came from a continued diversification of customers, including AI Clouds, industrial, enterprise, and sovereign customers.
[E168] - Results driver (2026-05-20, SEC EDGAR): No shipments of Data Center Hopper products to China occurred during the first quarter of fiscal 2027, compared with $4.6 billion in the first quarter of fiscal year 2026.
[E169] - Results driver (2026-05-20, SEC EDGAR): GAAP and non-GAAP gross margins for the first quarter increased from a year ago on lower inventory provisions, primarily due to the prior year's $4.5 billion charge associated with H20 excess inventory and purchase obligations.
[E170] - Results driver (2026-05-20, SEC EDGAR): Inventory was $25.8 billion, up from $21.4 billion sequentially, and total supply-related commitments were $119.0 billion, as NVIDIA strategically secured inventory and capacity to meet demand beyond the next several quarters.
[E171] - Results driver (reported 2026-11-09; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): In Q2 FY2027, Nvidia's non-GAAP EPS came in at $2.22 against a $2.0887 consensus estimate, revenue reached $96.22 billion ahead of the $92.07 billion estimate, and Data Center revenue grew 117%.
[E172] - Results driver (reported 2026-11-04; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): Nvidia's fiscal second-quarter release showed approximately $96.2 billion in revenue and a 75% non-GAAP gross margin.
[E173] - Demand / customers (2026-08-26, SEC EDGAR): NVIDIA says each generation of NVIDIA infrastructure deployed at PORTS-Pike could represent approximately 1.5 million NVIDIA GPUs, or approximately $150 billion to $200 billion in NVIDIA revenue, and that over 20 years the site can support multiple infrastructure upgrade cycles.
[E174] - Demand / customers (2026-08-26, SEC EDGAR): NVIDIA has entered into arrangements helping select AI cloud and model maker customers secure land, power and data center capacity, under which it will earn revenue on the upfront sale of its infrastructure and, if certain criteria are met, participate in revenue share generated by the AI clouds from their third-party customers.
[E175] - Demand / customers (2026-08-26, SEC EDGAR): CEO Jensen Huang said demand is accelerating, with multiple frontier labs scaling in parallel, a thriving open-model ecosystem and physical AI coming online, and that the AI infrastructure buildout is at full steam with Vera Rubin now in full production.
[E176] - Demand / customers (2026-08-26, SEC EDGAR): NVIDIA announced strategic partnerships to establish independent compute financing platforms with Apollo, BlackRock, Blackstone, Brookfield, Goldman Sachs and KKR to mobilize over $500 billion of third-party capital for the buildout of AI infrastructure over time, subject to definitive agreements.
[E177] - Demand / customers (2026-08-17, SEC EDGAR): An affiliate of OpenAI Group PBC will be the tenant at the Portsmouth Site, and NVIDIA will pay the shortfall between the guaranteed minimum lease value and amounts recovered through a replacement lease or sale if OpenAI becomes insolvent or fails to make lease payments.
[E178] - Demand / customers (2026-08-17, SEC EDGAR): OpenAI has agreed to reimburse and indemnify NVIDIA for any and all amounts actually paid by NVIDIA to the Lessor under the Agreements.
[E179] - Demand / customers (reported 2026-11-11; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Baird said capital expenditure growth among large cloud computing companies could slow to 40% or slightly less in 2027, compared with the stronger expansion previously anticipated.
[E180] - Demand / customers (reported 2026-11-10; when it happened is not stated, Bing News: The Straits Times (press report: attribute it, and prefer company figures where they differ)): Nvidia is investigating whether CEO Jensen Huang was the target of foreign spying after October media reports alleged a close relationship with Alice Huang, a former executive of Singapore-based Megaspeed International who is reportedly monitored by US authorities over suspected help to China in evading limits on advanced AI chips.
[E181] - Earnings quality (2026-05-20, SEC EDGAR): Net gains from equity securities for the first quarter were $15.9 billion, driven by unrealized gains in publicly-held and non-marketable equity securities.
[E182] - Earnings quality (2026-08-26, SEC EDGAR): NVIDIA's tax expense included an impact from OBBBA (One Big Beautiful Bill Act).
[E183] - Earnings quality (2026-05-20, SEC EDGAR): Cash flow from operating activities was $50.3 billion, up from $27.4 billion a year ago and up from $36.2 billion a quarter ago, with the sequential increase driven by higher revenue and lower cash taxes.
[E184] - Policy (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, News feed: CNN Business (press report: attribute it, and prefer company figures where they differ)): Megaspeed was under federal investigation for allegedly diverting highly coveted US semiconductors to entities in China in violation of US export controls.
[E185] - Policy (reported 2026-11-10; when it happened is not stated, Bing News: The Straits Times (press report: attribute it, and prefer company figures where they differ)): Washington bans the export of Nvidia's top-end Blackwell and Rubin GPUs to China, citing security concerns.
[E186] - Policy (reported 2026-11-10; when it happened is not stated, Bing News: The Straits Times (press report: attribute it, and prefer company figures where they differ)): US conditions have made it difficult for H200 shipments to be approved, and Beijing is reportedly reluctant to buy H200s as its own chip industry gains momentum.
[E187] - Policy (2026-09-03, SEC EDGAR): NVIDIA has committed to keep Hugging Face's platform open, with Hugging Face continuing to permit model makers, developers and users to upload and download models and datasets of their choosing and to support other silicon vendors.
[E188] - Policy (2026-09-03, SEC EDGAR): NVIDIA warns that other parties are actively lobbying the U.S. Government and other stakeholders to adopt legislative or regulatory measures that would restrict or disadvantage open-source models and their customers.
[E189] - Policy (2026-09-03, SEC EDGAR): NVIDIA says many of the world's most popular open-source models originated in China, and any regulatory control limiting its ability to support models derived from any region, including China, could materially impact Hugging Face's platform and NVIDIA's business, operating results and financial condition.
[E190] - Policy (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, News feed: Reuters (press report: attribute it, and prefer company figures where they differ)): Alibaba and Tencent shares tumbled 6.7% and 2.6% respectively in Hong Kong amid concerns that Washington may curb access to offshore datacentres with the most advanced processors.
[E191] - Policy (reported 2026-11-11; when it happened is not stated, Bing News: The Globe and Mail (press report: attribute it, and prefer company figures where they differ)): President Donald Trump wrote on Truth Social that he is 100% in favor of artificial intelligence infrastructure, calling data centers "GOLD" and pledging to help states expand capacity, in comments carried by CNBC.
[E192] - Event (2026-09-03, SEC EDGAR): The transaction includes an approximately $11.9 billion purchase price payable to Hugging Face stockholders, subject to certain adjustments.
[E193] - Event (2026-05-20, SEC EDGAR): On May 18, 2026, NVIDIA's Board of Directors approved an increase to its quarterly dividend from $0.01 per share to $0.25 per share and an additional $80.0 billion to its share repurchase authorization, without expiration.
[E194] - Event (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): The Wall Street Journal reported that Nvidia's board is preparing to oust founder and CEO Jensen Huang and met as soon as Wednesday evening to decide his fate, with no official outcome or board statement confirmed.
[E195] - Event (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): On Sunday, Jensen Huang told staff in a letter that he had been unfaithful to his wife and apologized for breaking the trust of his family and employees, and the affair involved Alice Huang, an executive at Singapore-based data company Megaspeed, a major Nvidia customer.
[E196] - Event (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, News feed: Reuters (press report: attribute it, and prefer company figures where they differ)): Nvidia's board met to decide the fate of long-time CEO Jensen Huang after a spy scandal threatened to oust him, sending the company's shares diving nearly 7% in premarket US trading on November 12, 2026.
[E197] - Event (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, News feed: Reuters (press report: attribute it, and prefer company figures where they differ)): Nvidia shares plunged almost 10% overnight on reports its board may oust CEO Jensen Huang, with the Wall Street Journal reporting the board was about to remove him after meeting late on Wednesday.
[E198] - Event (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, News feed: Reuters (press report: attribute it, and prefer company figures where they differ)): The pressure on Jensen Huang followed his confession to having an affair with a businesswoman alleged to be spying for China, and a New York Times report of a second affair with a more junior Nvidia executive.
[E199] - Event (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Jensen Huang admitted on Sunday to an affair with Alice Huang, an alleged Chinese spy, and The New York Times reported on Wednesday that Huang had another affair with Kimberly Powell, vice president of health care at Nvidia, who reported to him.
[E200] - Capex / investment (reported 2026-10-01; when it happened is not stated, Bing News: Yahoo Finance (company statement reported by Yahoo Finance: it is company guidance; write that management said it, as reported by Yahoo Finance)): In the second quarter of fiscal 2027, NVIDIA generated operating cash flow of $24.08 billion and free cash flow of $21.34 billion, and in the first half of fiscal 2027 it generated operating and free cash flows of $74.42 billion and $69.9 billion, respectively.
[E201] - Competition (2026-05-20, SEC EDGAR): NVIDIA announced that BYD, Geely, Isuzu and Nissan are building level 4-ready vehicles on the NVIDIA DRIVE Hyperion platform, and introduced NVIDIA Halos OS, a unified safety architecture for AI-driven vehicles.
[E202] - Competition (2026-05-20, SEC EDGAR): NVIDIA expanded its partnership with Hyundai Motor Company and Kia for next-generation autonomous driving built on the NVIDIA DRIVE Hyperion platform, and expanded its partnership with Uber to launch a fleet of autonomous vehicles powered by full-stack NVIDIA DRIVE AV software.
[E203] - Competition (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): William Blair analysts upgraded AMD to Outperform, saying Nvidia faces increased scrutiny and a potential leadership vacuum and that AMD could benefit from custom programs as an opportunity for CPU attach.
[E204] - Competition (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): William Blair analysts said AMD's Instinct share gains offer additional upside as AMD stays focused on execution while its largest competitor, Nvidia, contends with a growing leadership and regulatory imbroglio.
[E205] - Competition (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Cloud providers have increasingly looked to AMD's custom chip designs as an alternative to Nvidia's standard GPUs, and continued uncertainty at Nvidia could speed that diversification.
[E206] - Competition (reported 2026-11-10; when it happened is not stated, Bing News: The Straits Times (press report: attribute it, and prefer company figures where they differ)): Huawei said in September that its next-generation AI chip would be ready in the first quarter of 2027, three quarters earlier than planned.
[E207] - Competition (reported 2026-11-09; when it happened is not stated, Bing News: The Straits Times (press report: attribute it, and prefer company figures where they differ)): Nvidia is offering more specialised chip systems, including its own CPUs and chips focused on the inference stage of AI using technology acquired from start-up Groq.
[E208] - Competition (reported 2026-11-04; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): A Trefis review put the Vera Rubin rollout in focus, with the challenge being turning another product transition into profitable growth.
[E209] - Street / share price (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Nvidia shares tumbled more than 6% in premarket trading by 05:57 ET on November 12, 2026, while AMD and Broadcom rose 3.6% and 2.5%, respectively.
[E210] - Street / share price (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, News feed: Reuters (press report: attribute it, and prefer company figures where they differ)): If out-of-hours trading is confirmed after the bell today, the cumulative Nvidia share price loss this week would mean well over half a trillion dollars wiped off its market cap.
[E211] - Street / share price (reported 2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it; when it happened is not stated, News feed: Reuters (press report: attribute it, and prefer company figures where they differ)): Nvidia shares plunged 6% in premarket trading on November 12, 2026 after reports that its board was weighing the ouster of CEO Jensen Huang following reports of two extramarital affairs involving its longtime leader.
[E212] - Street / share price (reported 2026-11-11; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Baird downgraded Nvidia Corp (NASDAQ:NVDA, XETRA:NVD) to Neutral from Outperform on 2026-11-11 and cut its price target by 60% to US$200 from US$500.
[E213] - Street / share price (reported 2026-11-11; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Nvidia shares fell roughly 5% in after-hours trading on November 11, 2026 amid reports that Nvidia is considering ousting CEO Jensen Huang following internal scrutiny into his extramarital affairs.
[E214] - Street / share price (reported 2026-11-11; when it happened is not stated, Bing News: CNBC (press report: attribute it, and prefer company figures where they differ)): Dan Ives of Yorkville Ives & Co. said he believes Nvidia's value is $300 per share with Jensen as CEO and $225 per share without Jensen as CEO.
[E215] - Street / share price (reported 2026-11-10; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Goldman Sachs warned in a note read out on CNBC's Squawk on the Street on Nov. 6 that by 2028 there won't be enough data center shells—land, power and shell—and therefore likely too many semiconductors for them to go into.
[E216] - Street / share price (reported 2026-11-10; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): NVIDIA had lost nearly $1.4 trillion of market value from its October record by the close on Nov. 5, after a 9% drop that day on midterm data center fears.
[E217] - Other (2026-08-17, SEC EDGAR): NVIDIA made an investment in SB Energy as part of the partnership announced in the 2026-08-17 filing.
[E218] - Other (reported 2026-11-11; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Baird identified a possible new ban on exports of Nvidia's H200 processors to China as one of two principal regulatory risks.
[E219] - Other (reported 2026-11-11; when it happened is not stated, Bing News: Yahoo Finance (press report: attribute it, and prefer company figures where they differ)): Baird believes some shipments are reaching warehouses in Asia, where inventories may be awaiting Chinese customers, potentially exposing Nvidia to a US$5 billion write-down.
[E220] - Other (reported 2026-09-03; when it happened is not stated, Bing News: The Globe and Mail (company statement reported by The Globe and Mail: it is company guidance; write that management said it, as reported by The Globe and Mail)): During the second-quarter earnings call, NVIDIA management stated pricing conditions have become more difficult than previously expected.
Not found in the documents read (say so rather than guess): Which dated events are coming up; Not stated in the latest results documents.

HOUSE FORECAST (drivers set by the AI analyst, figures computed in code; USD millions except per-share figures):
[E221] - FY2027E: revenue 412,010mn (+90.8%); consensus 412,055mn, ours -0.0% vs consensus; gross margin 73.7%; operating margin 65.2%; below the operating line +0.8% of revenue; net profit 246,290mn; EPS 10.17 (+107.6%), consensus 9.32 (+95.4%)
[E222] - FY2028E: revenue 700,416mn (+70.0%); consensus 692,257mn, ours +1.2% vs consensus; gross margin 72.5%; operating margin 64.5%; below the operating line +0.8% of revenue; net profit 379,619mn; EPS 15.92, consensus 15.93 (+70.9%), ours -0.0% vs consensus
[E223] - FY2029E: revenue 947,664mn (+35.3%); gross margin 72.5%; operating margin 64.0%; below the operating line +0.8% of revenue; net profit 509,691mn; EPS 21.70 (+36.3%)
[E224] - Revenue drivers: FY2027 starts from 1H actual revenue of 177,837mn and Q3 guidance of $108.0bn (R1), with Q4 implied at roughly $126.2bn to reach our +90.8% full-year growth; Data Center Blackwell Ultra ramp (R18) and supply commitments of $279bn (R33) support the run-rate. FY2028 uses management’s ~70% revenue growth guidance (R6), driven by Vera Rubin now in full production (R38), AI infrastructure financing platforms mobilizing over $500bn (R39), and PORTS-Pike potential of $150bn-$200bn per deployment cycle (R36). FY2029 fades to +35.3%, reflecting Baird’s view that large cloud capex growth could slow to 40% or less in 2027 (R42), Goldman’s warning of data-center shell constraints by 2028 (R92), and continuing China export restrictions on top-end GPUs (R52).
[E225] - Margin drivers: FY2027 gross margin of 73.7% blends 1H actual 75.0% (R15, R10), Q3 guidance of 74.0% ±50bp (R2), and the Q4 trough of 71%-72% (R5, R12); Blackwell Ultra mix helped 1H margins (R21, R22), while higher memory commitments (R33) and more difficult pricing (R97) pressure Q4. FY2028-29 gross margin is held at 72.5% as the Q4 FY2027 trough is followed by only modest recovery on Vera Rubin (R38), with memory costs (R33) and pricing (R97) limiting upside; operating margin steps down as opex grows with compute infrastructure and compensation (R23) and includes stock-based compensation (R45). Tax is 17.0% in FY2027 per the 16%-18% guidance (R4), and we hold that rate thereafter, including the OBBBA impact noted in R49.
[E226] - Versus consensus: FY2027 revenue of 412,055mn is in line with the 412,055mn consensus in the history, resting on 1H actual 177,837mn, Q3 guidance of 108,000mn (R1), and implied Q4 of about 126,218mn. FY2028 revenue of about 700,494mn is +1.2% versus the 692,257mn consensus because we start from management’s ~70% growth guidance (R6). FY2029 has no consensus figure provided; our +35.3% fade reflects Baird’s slower-capex view (R42) and Goldman’s shell-constraint warning (R92). EPS is supported by the $235bn buyback authorization to be executed through FY2028 (R7, R65, R66) and the 17% tax rate (R4).
[E227] - Key risk to the forecast: The assumption most likely to be wrong is FY2028 revenue growth of ~70% (R6). Early warning would be Q4 FY2027 revenue below the roughly $126bn implied by our FY2027 bridge and softer Q1 FY2028 guidance, alongside hyperscaler capex commentary like Baird’s expected slowdown (R42), slower conversion of the $279bn supply commitments (R33), or tighter data-center shell availability (R92); a Q4 gross margin below the guided 71%-72% trough (R5, R12) would also flag margin risk.
[E228] - The FY2027E revenue forecast implies revenue of 234,173mn for the second half (+87.1% year on year), against +95.8% reported so far this year. Consensus for those quarters (Q3 FY2027E + Q4 FY2027E) is 233,963mn, so our forecast is +0.1% versus the Street for the second half.

[E229] Results are due on 17 November 2026, 6 days after the last close. Make the first events_to_monitor item a short results preview: what management guided for the period, what our forecast implies, and the one figure most likely to decide the share-price reaction.

SCENARIOS (assumptions by the AI, values computed in code; not the rating):
[E230] - Bear (30%): revenue growth +82.0%, +35.0%, -4.7% over 3 years, FCF margin 34.0% -> USD 77.36 (-55.5% vs price). Gross margin also falls below the guided 71% to 72% Q4 trough [R5] because pricing is more difficult than expected [R97], and the CEO exit reported on 12 Nov disrupts execution [BEAR-5]. Probability: 30%, raised by the Baird capex slowdown view [R42], the guided margin step-down [R12] and the CEO turmoil [R64], and held down by Q3 revenue guidance of $108.0 billion, plus or minus 2% [R1], and the $279 billion of supply commitments [R33].
[E231] - Base (50%): revenue growth +90.8%, +70.0%, +35.3% over 3 years, FCF margin 40.0% -> USD 209.92 (+20.8% vs price). Management delivers the Q3 FY2027 revenue guide of $108.0 billion [R1] and about 70% FY2028 growth [R6] as the Blackwell Ultra ramp [R18] gives way to Vera Rubin, now in full production [R38]. The FCF margin drifts below the trailing level as gross margin troughs at 71% to 72% in Q4 [R5], memory costs rise [R33] and pricing stays harder [R97]. Probability: 50%, raised by the record Q2 results [R16] and the $235 billion buyback programme through fiscal 2028 [R7], and held down by Baird's slower-capex view [R42] and the board's investigation into allegations about CEO Jensen Huang [R64].
[E232] - Bull (20%): revenue growth +95.0%, +85.0%, +55.3% over 3 years, FCF margin 45.0% -> USD 340.47 (+96.0% vs price). Each PORTS-Pike deployment generation brings $150 billion to $200 billion in revenue [R36], and gross margin recovers after the Q4 trough. Probability: 20%, raised by Data Center revenue up 117% in Q2 [R16] and ACIE growth of 138% [R19], and held down by guided margin compression [R12] and the lack of any China Data Center compute in the outlook [R1].
[E233] - Probability-weighted value: USD 196.26 (+13.0% vs price).
[E234] - After year 3 each scenario's growth above terminal growth halves every year.
The rating's fair value IS the probability-weighted scenario value above (our forecasts); the peer multiples and the mechanical DCF are cross-checks outside the rating.
[E235] VALUE BRIDGE (computed in code; why our fair value differs from the model DCF): Model DCF (consensus revenue, model FCF margins) USD 222.36; Our revenue forecast instead of consensus +2.68; Our base case's FCF margin -15.13; Bear and bull cases at their probabilities -13.66; = Our fair value (probability-weighted) USD 196.26.
[E236] RATING SENSITIVITY (computed in code; at today's price): it is Hold now; it would be Buy if the bull case's probability rose from 20% to 23% (taken from the base case); Sell if the bear case's rose from 30% to 61%.
In the valuation overview, explain the gap to the model DCF with the value bridge's largest step and the evidence behind it, and say how far the rating is from changing.

[E237] Closes on recent sessions (code; the price chart skips some sessions, so a close-to-close change is given only where the previous session is known): 19 Oct 2026 (Mon) 217.09; 21 Oct 2026 (Wed) 221.97; 23 Oct 2026 (Fri) 210.96; 27 Oct 2026 (Tue) 217.94; 29 Oct 2026 (Thu) 213.66; 2 Nov 2026 (Mon) 202.06; 4 Nov 2026 (Wed) 200.13; 6 Nov 2026 (Fri) 186.64; 10 Nov 2026 (Tue) 168.89; 11 Nov 2026 (Wed) 173.73 +2.9%. Date a share-price move by its session; a weekend or holiday announcement moved the price on the next session.
[E238] Net cash bridge (code, USD): net cash (cash and investments minus debt) went from 41,202mn (25 Jan 2026) to 23,220mn (26 Jul 2026): cash and investments changed by +6,916mn, debt by +24,898mn. Give the change in net cash with these two components; never name another cause unless a note states it.
[E239] Statistic labels (code): today's P/E on last fiscal year's EPS is 35.5x; the 5-year median is 64.0x. Never swap them.

WHAT DECIDES FY2029E (the lead analyst's driver analysis of the year our valuation rests on; each line cites its note; use it in the thesis and the risks):
[E240] - Hyperscaler and AI cloud capex growth (puts our base case at risk): Baird said capital expenditure growth among large cloud computing companies could slow to 40% or slightly less in 2027 [R42], while management guides fiscal 2028 revenue growth of approximately 70% [R6].
[E241] - Supply commitments and data center capacity (unclear): Supply and capacity commitments increased from $119 billion last quarter to $279 billion, primarily related to the procurement of memory [R33]; Goldman Sachs warned that by 2028 there won't be enough data center shells [R92].
[E242] - Product ramp: Blackwell Ultra to Vera Rubin (supports our base case): Data Center revenue for the second quarter was a record $89.0 billion, up 117% from a year ago [R16]; Jensen Huang said Vera Rubin is now in full production [R38].
[E243] - China export policy and competition (puts our base case at risk): Management is not assuming any Data Center compute revenue from China in its outlook [R1]; Huawei said its next-generation AI chip would be ready in the first quarter of 2027 [R83].
[E244] - Pricing pressure and gross margin (puts our base case at risk): Management said gross margin is expected to bottom in the 71% to 72% range in the fourth quarter [R5]; management stated pricing conditions have become more difficult than previously expected [R97].
[E245] - Verdict: For +35.3% in FY2029E, customer capex and AI infrastructure financing must keep expanding after the ~70% fiscal 2028 guide, with power, shells and memory supply not limiting shipments, and Vera Rubin ramping without share loss. Hyperscaler and AI cloud spending matters most; China, pricing and leadership uncertainty are risks.

Recent news (third-party reports; attribute them, and prefer company figures where they differ):
[E246] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (management, negative) Yahoo Finance panel discusses open questions after Jensen Huang stepped down as Nvidia CEO | original: Why replacing Jensen Huang is an impossible task | Yahoo Finance Executive Editor Brian Sozzi is joined by Julie Hyman and Deirdre Bosa at Yahoo Finance's 2026 Invest conference to discuss the questions that remain after Jensen Huang stepped down as N
[E247] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (regulation, negative) Democrats ask Trump administration to preserve all records on Nvidia dealings ahead of taking power | original: Planning Nvidia investigations, top Democrats tell Trump administration to 'preserve all records' | Democrats have formally asked the Trump administration to "preserve all records" related to its dealings with Nvidia as Democrats prepare to take power on Capitol Hill.
[E248] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (management, negative) Nvidia stock hit by downgrades and price-target cuts after CEO revelations | original: Nvidia Stock Hammered As CEO Resigns In Disgrace | Nvidia stock received another round of downgrades and price-target cuts on Wall Street in the wake of the latest CEO revelations.
[E249] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (management, neutral) Elon Musk offers to hire Jensen Huang as pressure mounts on Nvidia CEO; prediction markets bet on Huang | original: Musk Offers To Hire Huang; Prediction Markets Capitalize On Scandal | Elon Musk shows support for Jensen Huang as pressure mounts on the Nvidia CEO. Prediction markets bet on Huang, Nvidia's future.
[E250] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (market, negative) Futures fall on Trump Iran remarks; Nvidia plunges 10% as Jensen Huang resigns | original: Stock Market Today: Futures Fall On Trump Oil Remarks; Nvidia Plunges As Jensen Huang Resigns (Live Coverage) | Futures drop premarket Thursday on Trump's Iran comments as Nvidia stock plunges 10% on the resignation of Jensen Huang.
[E251] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (management, negative) Jensen Huang's departure from Nvidia triggers AI industry earthquake | original: Jensen Huang's ouster triggers an AI earthquake | Jensen Huang's departure from Nvidia has plunged the AI industry into uncharted territory — a corporate earthquake that dwarfs even the chaos unleashed by Sam Altman's temporary firing from OpenAI in
[E252] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (market, negative) Wall Street set to open lower after Nvidia CEO Jensen Huang steps down | original: Wall St set to open lower after Nvidia CEO steps down | Nov 12 (Reuters) - Wall Street's main indexes were set to open sharply lower on Thursday after Nvidia said CEO Jensen Huang was stepping down, leaving the AI industry without its biggest champion.
[E253] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (market, negative) SPY down 0.7% pre-bell as Nvidia leadership uncertainty weighs on futures | original: Exchange-Traded Funds, Equity Futures Lower Pre-Bell Thursday Amid Nvidia Leadership Uncertainty | The broad market exchange-traded fund SPDR S&P 500 ETF Trust (SPY) was down 0.7% and the actively tr
[E254] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (management, negative) Jensen Huang resigns as Nvidia CEO after reported affairs, including one with purported Chinese spy | original: Jensen Huang, an architect of the AI boom, resigns as Nvidia CEO | Jensen Huang resigned as CEO of Nvidia after he reportedly had two affairs, including one with a purported Chinese spy.
[E255] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (management, negative) Help wanted: AI firms court ex-spies as Nvidia crisis spotlights security risks | By Toby Sterling AMSTERDAM, Nov 12 (Reuters) - AI firms are hiring former intelligence operatives to help shield them from espionage, a risk thrust into the spotlight as Nvidia axed its CEO Jensen
[E256] - [2026-11-12 · AFTER THE PRICE DATE: not a cause of moves up to it] (management, neutral) Factbox: Nvidia finance chief Colette Kress to take over as interim CEO from Jensen Huang | original: Factbox-Who is Nvidia interim CEO Colette Kress? | Nov 12 (Reuters) - Nvidia finance chief Colette Kress is set to take over as interim CEO from Jensen Huang, the company said on Thursday, putting her in charge of the chipmaker whose processors power
[E257] - [2026-11-05] (market, neutral) Jim Cramer says Nvidia has not gone all in on its own stock | original: Nvidia has not gone all in when it comes to its own stock, says Jim Cramer | 'Mad Money' host Jim Cramer on what changed for AI investors after the midterms that led to the day's market selloff.
[E258] - [2026-10-15] (other, neutral) Nvidia and Cisco confirm multimillion-dollar donations to Trump's White House ballroom | Big Tech gave millions to Trump's White House ballroom, documents show

## 2. Filing excerpts (latest annual / interim report)

[SEC EDGAR · 10-Q filed 2026-08-26 · filed 2026-08-26]
### Latest quarter MD&A
and Analysis of Financial Condition and Results of OperationsForward-Looking StatementsThis Quarterly Report on Form 10-Q contains forward-looking statements within the meaning of Section 27A of the Securities Act of 1933, as amended, and Section 21E of the Securities Exchange Act of 1934, as amended, which are subject to the “safe harbor” created by those sections based on management’s beliefs and assumptions and on information currently available to management. In some cases, you can identify forward-looking statements by terms such as “may,” “will,” “should,” “could,” “goal,” “would,” “expect,” “plan,” “anticipate,” “believe,” “estimate,” “project,” “predict,” “potential” and similar expressions intended to identify forward-looking statements. These statements involve known and unknown risks, uncertainties and other factors, which may cause our actual results, performance, time frames or achievements to be materially different from any future results, performance, time frames or achievements expressed or implied by the forward-looking statements. We discuss many of these risks, uncertainties and other factors in this Quarterly Report on Form 10-Q and our Annual Report on Form 10-K for the fiscal year ended January 25, 2026 in greater detail under the heading “Risk Factors” of such reports. Given these risks, uncertainties, and other factors, you should not place undue reliance on these forward-looking statements. Also, these forward-looking statements represent our estimates and assumptions only as of the date of this filing. You should read this Quarterly Report on Form 10-Q completely and understand that our actual future results may be materially different from what we expect. We hereby qualify our forward-looking statements by these cautionary statements. Except as required by law, we assume no obligation to update these forward-looking statements publicly, or to update the reasons actual results could differ materially from those anticipated in these forward-looking statements, even if new information becomes available in the future.All references to “NVIDIA,” “we,” “us,” “our” or the “Company” mean NVIDIA Corporation and its subsidiaries.In addition, statements that “we believe” and similar statements reflect our beliefs and opinions on the relevant subject.

[SEC EDGAR · 10-K filed 2026-02-25 · filed 2026-02-25]
### Risk factors
The following risk factors should be considered in addition to the other information in this Annual Report on Form 10-K. The following risks could harm our business, financial condition, results of operations or reputation, which could cause our stock price to decline. Additional risks, trends and uncertainties not presently known to us or that we currently believe are immaterial may also harm our business, financial condition, results of operations or reputation.Risk Factors SummaryRisks Related to Our Industry and Markets•Failure to meet the evolving needs of our industry and markets may adversely impact our financial results.•Competition could adversely impact our market share and financial results.Risks Related to Demand, Supply, and Manufacturing•Long manufacturing lead times and uncertain supply and capacity availability, combined with a failure to estimate customer demand accurately has led and could lead to mismatches between supply and demand.12Table of Contents•Dependency on third-party suppliers and their technology to manufacture, assemble, test, or package our products reduces our control over product quantity and quality, manufacturing yields, and product delivery schedules and could harm our business.•Defects in our products have caused and could cause us to incur significant expenses to remediate and could damage our business.Risks Related to Our Global Operating Business•Adverse economic conditions may harm our business.•International sales and operations are a significant part of our business, which exposes us to risks that could harm our business. •Product, system security and data protection incidents or breaches, as well as cyber-attacks could disrupt our operations and adversely affect our financial condition, stock price and reputation.

[SEC EDGAR · 10-K filed 2026-02-25 · filed 2026-02-25]
### Management discussion
and Analysis of Financial Condition and Results of OperationsThe following discussion and analysis of our financial condition and results of operations should be read in conjunction with “Item 1A. Risk Factors,” our Consolidated Financial Statements and related Notes thereto, as well as other cautionary statements and risks described elsewhere in this Annual Report on Form 10-K, before deciding to purchase, hold, or sell shares of our common stock.OverviewOur Company and Our BusinessesNVIDIA pioneered accelerated computing to help solve the most challenging computational problems. Since our original focus on PC graphics, we have expanded to several other large and important computationally intensive fields. Fueled by the sustained demand for exceptional 3D graphics and the scale of the gaming market, NVIDIA has leveraged its GPU architecture to create platforms for scientific computing, AI, data science, autonomous vehicles, robotics, and digital twin applications. NVIDIA is now a data center scale AI infrastructure company reshaping all industries.Our two operating segments are "Compute & Networking" and "Graphics." Refer to Note 16 of the Notes to the Consolidated Financial Statements in Part IV, Item 15 of this Annual Report on Form 10-K for additional information.Headquartered in Santa Clara, California, NVIDIA was incorporated in California in April 1993 and reincorporated in Delaware in April 1998.Recent Developments, Future Objectives and ChallengesRevenue growth in fiscal year 2026 was driven by data center compute and networking platforms for accelerated computing and AI solutions. Our Blackwell architectures represented the majority of our Data Center revenue.The availability of data centers, energy, and capital to support the buildout of NVIDIA AI infrastructure by our customers and partners is crucial, and any shortage of these or other necessary resources could impact our future revenue and financial performance. Expanding energy capacity to meet demand is a complex, multi-year process that involves significant regulatory, technical, and construction challenges. In addition, access to capital can be particularly constrained for less-capitalized companies, which may face difficulties securing financing for large-scale infrastructure projects. These limitations could delay customer and partner deployments or reduce the scale of accelerated computing and AI adoption.We continue to execute Data Center compute product introductions, bringing new advanced architectures on a one-year product cadence, including our Rubin platform.

## 3. Recent news

The news items are in section 1 (after the numbered facts).
