# Methodology and design notes

> The design document of InvestSync Research Tools, written 6–12 November 2026 (it was the README until 13 Nov).
> Some figures here (page counts, timings) describe earlier versions. The [README](../README.md) is the current
> overview and setup guide.

## 📌 Executive Summary

Modern equity research teams spend hours aggregating financial line items across fragmented disclosures, aligning disparate accounting standards (US GAAP, CAS, and HKFRS), and formatting summary tables.

**InvestSync Research Tools** is an institutional-grade, multi-agent equity tear sheet generator. By inputting any equity ticker across **Hong Kong (`0700.HK`)**, **Mainland China (`600519.SH`)**, or the **US (`NVDA`)**, the engine generates a publication-ready **A4 vector PDF**: a one-page tear sheet followed by a full research report (investment summary, company overview, financial analysis and statements, valuation with sensitivities and Monte Carlo, competitors, technicals, catalysts and news, ownership and governance, latest-report excerpts, data audit). It covers every chapter of FinRobot's equity report, adds Hong Kong and A-share coverage, and keeps every number computed in code.

Rather than relying on basic web scraping scripts or opaque generative wrappers, this system is built on **verifiable academic frameworks** and **deterministic financial computation**.

---

## 🏛️ Academic & Open-Source Foundations

| Institution / Origin | Framework / Paper | Core Role in This Project |
| :--- | :--- | :--- |
| **Columbia University / NYU** (AI4Finance) | **[FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)** | Provides the multi-agent orchestration architecture that strictly separates deterministic mathematical computation from qualitative narrative synthesis. |
| **University of Chicago** (Booth School of Business) | **[Financial Statement Analysis with LLMs](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4835311)** *(Kim, Muhn, & Nikolaev, 2024; withdrawn Feb 2025, under review)* | Implements structured Financial Chain-of-Thought (CoT): DuPont ratio decomposition ($\text{ROE} = \text{Net Margin} \times \text{Asset Turnover} \times \text{Leverage}$) and accrual earnings quality verification. |
| **Stanford University** (Stanford NLP) | **[DSPy](https://github.com/stanford-nlp/dspy)** | Typed DSPy signatures plus a check-and-retry guardrail loop as an anti-hallucination layer, ensuring every number in the commentary strictly matches the underlying financial records. |
| **Rust Community** | **[Typst](https://github.com/typst/typst)** | Ultra-fast document compiler generating pixel-perfect vector PDFs in $<300\text{ ms}$, styled according to InvestSync's brand specifications. |

---

## 🔬 Framework Deep Dive

What each framework offers, and the specific parts this project takes from it.

### FinRobot · AI4Finance Foundation
*Open-source AI agent platform for finance (current V2 on PydanticAI). Equity research method: Zhou et al., ICAIF 2024.*

**What it provides**
- Four-layer stack: agents, financial LLM algorithms, LLMOps/DataOps, foundation models
- Perception → Brain → Action agent loop, coordinated by a Smart Scheduler
- Equity research chain: Data-CoT, Concept-CoT and Thesis-CoT agents
- Valuation pipelines (DCF, DDM, LBO, comps, WACC) with code-computed tables
- US-focused data connectors: SEC EDGAR, yfinance, FMP, Finnhub

**What we use**
- The core rule: numbers are computed in code, and the LLM only writes about them
- The Data → Concept → Thesis chain: data and quant engine in code, then either one DeepSeek call or two (Concept, then Thesis: `NARRATIVE_MODE=two_step`)
- Its bull / bear / judge agent rules (V2 ships the prompts but no code that runs them): our **deep mode** runs the full debate, checks every argument in code, and adds an AI reviewer and a revision step, which FinRobot does not have
- Its audit-operator idea (direction, currency, period, momentum, sector checks on the AI's wording), rebuilt for our data
- Its valuation scope (DCF, DDM, WACC), rebuilt with real inputs: consensus forecasts, bond yields, measured beta, a value grid instead of one number
- Its comps tables and report structure as a layout reference
- **Not used:** the codebase, AutoGen, trading agents. Our pipeline runs on DeepSeek, with AKShare for HK and A-shares.

### Financial Statement Analysis with LLMs · Kim, Muhn & Nikolaev (Chicago Booth, 2024)
*Working paper testing whether GPT-4 can analyse financial statements like a professional analyst.*

> **Status:** Withdrawn by the authors in February 2025 after a co-author found inconsistencies in the data and analyses; under review. We use only its prompt design, not its results.

**What it provides**
- Inputs: standardized, anonymized balance sheets and income statements
- A four-step analyst prompt: (i) notable changes, (ii) key ratios with formulas, (iii) interpretation, (iv) synthesis
- Output: next-year earnings direction, rationale, magnitude and confidence
- Reported 60.35% accuracy, about 7 points above analysts (now under review)

**What we use**
- Steps (i), (iii) and (iv) as the structure of the commentary
- Step (ii) moves into code (Workstream A), so the LLM never calculates
- Our additions, not from the paper: DuPont decomposition (ROE = Net Margin × Asset Turnover × Leverage) and an accruals check (net income vs. operating cash flow)
- **Not used:** earnings prediction, anonymized inputs

### DSPy · Stanford NLP
*Framework for programming LLMs with typed modules instead of hand-written prompts. Current version: 3.4.*

**What it provides**
- Signatures: typed inputs and outputs instead of hand-written prompts
- Modules: `Predict`, `ChainOfThought`, `ReAct`, `Refine`, `BestOfN`
- `Refine`: reruns a module with feedback until a reward function passes. It replaced `dspy.Assert` in DSPy 2.6.
- Optimizers (MIPROv2, GEPA) and `dspy.Evaluate` for tuning and scoring
- `dspy.LM` for connecting any model provider

**What we use**
- One typed signature per narrative task, feeding the Typst template directly
- A check-and-retry guardrail loop: every number in a draft must match the payload, and any figure that does not is sent back to the model by name for a rewrite. After N failed tries the tear sheet is flagged, not published. (We tried `dspy.Refine` first; its generic advice step cannot see which figures failed.)
- `dspy.LM` on DeepSeek's OpenAI-compatible API, with an automatic backup model (e.g. GLM or Qwen) if DeepSeek fails
- `dspy.Module` to compose the single-step and two-step (Concept → Thesis) programs
- **Later:** `dspy.Evaluate` and an optimizer, once reviewed tear sheets exist

---

## 🏗️ System Architecture

```
                          [ Analyst Input: e.g. "0700.HK" ]
                                        │
                                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. CROSS-BORDER DATA INGESTION & CACHING LAYER                                         │
│    • AKShare: EastMoney (HK/US statements, valuation, peers) & Sina (A-shares, prices) │
│    • yfinance (quotes, multiples, US debt & peers) · CNINFO (A-share profiles)         │
│    • Filings: SEC EDGAR, HKEXnews, CNINFO (latest annual / interim report sections)    │
│    • Normalizer: Normalizes CAS, HKFRS, and US GAAP into a unified data schema         │
│    • Local Disk Cache (SQLite): Financials cached 30 days, real-time prices cached 15m │
└───────────────────────────────────────┬────────────────────────────────────────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
┌───────────────────────────────────────┐ ┌──────────────────────────────────────────────┐
│ 2. DETERMINISTIC QUANTITATIVE ENGINE  │ │ 3. QUALITATIVE & AGENTIC LAYER (DeepSeek)    │
│    • 5-Year CAGR, margins, debt/cash  │ │    • Real-time news extraction via AKShare   │
│    • Rebased benchmark chart (Base=100│ │    • DuPont & Operating Leverage Analysis    │
│    • Dynamic peer discovery & comps   │ │    • Comps commentary vs. peer median        │
│      (calculates peer median metrics) │ │    • 3 Investment Catalysts & 2 Key Risks    │
│    • WACC + DCF / DDM value grid      │ │    • Reads latest report (MD&A, risks)       │
└───────────────────┬───────────────────┘ └──────────────────┬───────────────────────────┘
                    │                                        │
                    └───────────────────┬────────────────────┘
                                        │
                                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 4. STANFORD DSPy ASSERTION GUARDRAIL                                                   │
│    • Re-prompts model if any financial number does not exist in the deterministic data │
└───────────────────────────────────────┬────────────────────────────────────────────────┘
                                        │
                                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 5. INSTITUTIONAL TEAR SHEET COMPILER (Typst Engine)                                    │
│    • Injects structured payload into InvestSync branded template (`#1B3A8C`, fonts)   │
│    • Emits tear sheet + full report as A4 vector PDF + clean JSON API for the website  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📄 Anatomy of the 1-Page Tear Sheet

The output follows standard institutional formats (Goldman Sachs / Morgan Stanley research tear sheets):

1. **Header & Profile:**
   - Company name, ticker, primary listing exchange, and GICS/Shenwan industry sector.
   - Live share price, market capitalization, enterprise value (EV), and 52-week trading range.
2. **Rebased Benchmark Performance Chart:**
   - 1-Year, 3-Year, and 5-Year historical performance vs. market benchmark (Hang Seng Index, CSI 300, or S&P 500), normalized to 100 at period start.
3. **5-Year Historical Financial Summary:**
   - Five fiscal years of reported financials: Total Revenue, Revenue YoY Growth %, Gross Margin %, Net Profit, Net Margin %, Diluted EPS, Cash & Equivalents, Total Debt, and Net Debt / (Cash).
4. **Comparable Companies Table (Comps & Relative Valuation):**
   - Target company evaluated against 3 to 5 direct industry peers on P/E (TTM), EV/EBITDA, P/B, and Dividend Yield.
   - Automatically computes **Peer Median** and calculates the target stock's premium or discount percentage.
5. **Overall view, scorecard line & rating levels (in the header):**
   - **Overall view**: one verdict that takes every *recent* view into account — the InvestSync AI rating plus each broker's latest rating from the last 90 days (newer notes count more; older ones are left out and listed in chapter 1). Shown as a 1–5 score with the model's and the brokers' parts side by side, and flagged "views split" when they disagree. The AI rating itself is unchanged and still shown on its own.
   - Five yes/no scorecards (value, growth, past, health, dividend) and the Piotroski F-score; under the AI rating, the **buy-below / sell-above** prices at which the same rule would say Buy or Sell.
6. **What brokers say (third-party views):**
   - Rating mix and agreement, price-target range and median vs the share price, the brokers' EPS forecast range, where the **InvestSync model sits among the brokers' targets**, and the two newest broker notes with text (A-shares: the broker's own summary; HK: AAStocks' write-up of the note; US: a news article about the rating action; English one-liners once the AI step runs). Credited and linked; never presented as InvestSync's view.
7. **Intrinsic Value (DCF / DDM, illustrative):**
   - WACC built from the 10-year government bond yield, a 2-year weekly beta, Damodaran's equity risk premium, the cost of debt and the effective tax rate.
   - DCF on analyst-consensus revenue that fades to a terminal growth rate (the 3×3 / 5×5 grids are in the report); banks and insurers get a dividend discount model instead.
8. **Investment Thesis & Risk Analysis (DeepSeek CoT):**
   - High-signal qualitative bullet points synthesizing latest filings and EastMoney/Cailianpress news and the latest annual / interim report (English news for US stocks):
     - **3 Key Catalysts:** Core business growth drivers, upcoming product cycles, and margin expansion levers.
     - **2 Downside Risks:** Regulatory headwinds, foreign exchange exposure, or competitive margin pressure.
9. **Footer & Compliance:**
   - Data sources (AKShare, EastMoney, exchange disclosures), generation timestamp, and InvestSync Technology disclaimer.

---

## 📚 The Full Research Report (pages 2–14)

`--layout report` (the default) adds up to thirteen chapters after the tear sheet; `--layout tearsheet` gives page 1 only.
Chapter numbers adapt to what a company has (e.g. no broker chapter without broker coverage).
Every figure and chart is computed in code. Sections marked **AI** show a styled placeholder until the DeepSeek key is
configured, then the AI text (checked by the number guardrail).

| # | Chapter | Computed in code | AI (placeholder until a key is set) |
| :-- | :-- | :-- | :-- |
| 1 | Investment summary | **Overall view** (the AI rating and each broker's latest view from the last 90 days on one 1–5 score: inputs and weights, the broker views counted with dates, the stale views left out, Yahoo consensus as a cross-check); **AI rating** (Buy/Hold/Sell set by a fixed rule from a blended fair value; config in `config/rating.json`) with **buy-below / sell-above prices** and **rating definitions**; **since the last report** (price, rating, fair value, brokers' target and EPS vs the previous saved run; "Buy since …"); key-figure tiles (incl. forward P/E, ROE); **valuation football field**; **data audit** (up to 15 automatic checks, incl. model vs brokers and Piotroski) | Tagline, thesis, key takeaways |
| 2 | Scorecard | Five areas of yes/no checks (value, future growth, past performance, financial health, dividend), each stating the figures behind it, after Simply Wall St's published model (CC BY-NC-SA 4.0) with peers standing in for the market; **Piotroski F-score** (9 checks). Descriptive only, never feeds the rating | – |
| 3 | Company overview | Full business description, company facts, **revenue by product/segment and by region** | Company overview |
| 4 | Financial analysis | Charts: revenue & net profit, margins, cash flow, ROE/ROA/ROIC, EPS; 5-year DuPont table | Financial analysis |
| 5 | Financial statements | Income statement, balance sheet, cash flow (5 years) and ~30 ratios in 6 groups | – |
| 6 | Valuation | WACC build, DCF forecast table, **EV bridge**, **reverse DCF** (growth and FCF margin the price implies), two **5×5 sensitivity grids**, **Monte Carlo** (5,000 seeded draws), **5-year P/E band**, street consensus (targets, ratings, EPS/revenue estimates) | Valuation commentary |
| 7 | Broker research | **What brokers say, compared with each other and with our model**: rating mix and agreement, upgrades/downgrades, price-target strip (one dot per broker, the price, the brokers' median and the InvestSync model), how far apart the EPS forecasts are (low–high, spread, vs last actual, vs Yahoo consensus; per-ADS outliers left out), **estimate trend** (A-shares: last 30 days vs 31–120 days ago), a table of broker notes with links to each PDF / source, and excerpts of each broker's own summary (A-shares) or of a news write-up of each note (HK: AAStocks 《大行》; US: same-day articles about each rating action), plus target changes the write-ups show before etnet's table does | One-line English summary per report or write-up (figures checked against that text), street view (where brokers agree / differ) |
| 8 | Competitive landscape | Peer multiples with premium/discount, **operating comparison** (growth, margins, ROE), P/E-vs-ROE scatter | Competitive analysis |
| 9 | Share price & technicals | Price with 50/200-day averages, volume, RSI; MACD, volatility, beta, drawdowns, support/resistance, returns vs index (1M–5Y), rule-based signals | – |
| 10 | Catalysts, news & events | Upcoming events; **official announcements of the last 90 days** (SEC filings with 8-K items in plain English, HKEXnews, CNINFO; routine filings counted, not listed); **company news of the last 45 days spread across weeks** (Yahoo + Finnhub for US, EastMoney for HK/CN; only stories that name the company, linked to the original); **dividend history** | Catalysts, risks, events to monitor, news summary, news tags and English headlines |
| 11 | Ownership & governance | Ownership split, **major holders** (US 13F / HK disclosure of interests / A-share top 10), **insider & major-holder trades**, ISS governance scores, management | – |
| 12 | Latest company report | Excerpts from the latest annual/interim report (contents-page fragments filtered out) | Report summary |
| 13 | Methodology, sources & disclosures | Methods; **numbered citation list** (what, original publisher, how accessed — e.g. "AKShare stock_financial_hk_report_em" — retrieval time, link); data notes; disclaimer. Each chapter ends with "Sources: [n]" pointing into this list; news headlines link to the original articles | – |

Chart rules: one y-axis per chart (no dual axes), a colour-blind-checked palette in a fixed order, legends for two or
more series, and the exact values in a table on the same page. Banks and insurers get bank-appropriate charts and
ratios (no free-cash-flow or working-capital measures) and a dividend discount model.

**vs FinRobot.** Matches its report chapters (cover, thesis, company, competitive, financial analysis, valuation,
sensitivity, news, catalysts, technical, financial data, ownership & governance, disclaimer, data-caveat banner) and adds:
HK and A-share coverage, the number guardrail, reverse DCF for banks (DDM), a P/E band, revenue segments for all three
markets, HK disclosure-of-interest and A-share holder data, and latest-report excerpts. Deliberately **not** included:
trading entry/stop levels, LBO and sum-of-the-parts models. Like FinRobot V2, the **rating is set by code, not by
the AI**: the AI explains it and is checked for stating any other rating.

### Three AI modes and the learner's guide

| Mode | What runs | Time · cost (deepseek-flash, measured 8 Nov 2026) |
| :--- | :--- | :--- |
| `single` (default) | news step, broker step, one writer call, guardrail rewrites | ~30–50 s · ~¥0.02 |
| `two_step` | Concept call → Thesis call | ~50 s · ~¥0.03 |
| `deep` | analyst → bull + bear (parallel) → rebuttals → judge → writer → reviewer → revision | ~3 min · ~¥0.15 off-peak |

**Deep mode** (the "investment committee"). The analyst works through nine areas, citing numbered evidence: `S` signals
computed in code, each marked with the side its sign supports, and `E` fact lines. A bull and a bear portfolio manager
each make up to five arguments. Every argument must cite evidence and name the assumption it rests on, and code drops
arguments that cite nothing, quote figures not in the data, or rest only on the other side's evidence. Each side then
rebuts the other and states what it concedes. A judge says which side the evidence favours, with conviction, the
*swing factor* (the assumption that decides it) and *what would change the view*; it never sets the rating. The
writer builds the report on the debate and adds a variant view and a pre-mortem. A reviewer must quote the exact
words it objects to (code discards quotes that are not in the draft), and the writer then edits its own draft. The
analyst, debate, judge and reviewer use DeepSeek's thinking mode (`LLM_DEEP_EFFORT`); `LLM_DEEP_MODEL=deepseek-v4-pro`
is possible (~11 min, ~¥1.5 per report in our test, not clearly better). The report gains an **Investment debate**
chapter, and page 1 gets one line ("AI debate: bull case stronger · medium conviction").

**Learner's guide** (`layout=learner`), for first-year students. Page 1 carries orange step markers 1–8, followed by
a guide that walks through the report in the order an analyst reads it:
1. What does the company do?
2. Is it growing?
3. Is the profit real?
4. Is it safe?
5. Is it cheap?
6. What is it worth?
7. What do others think?
8. What could go wrong?

Each step shows where to look, this company's numbers, how to read them, a worked calculation with the real figures
(CAGR, DuPont, net debt, premium to peers, the fair-value blend, the overall-view average), red flags and a question
to ask. Exercises, answers, a checklist, discussion questions and a glossary close the guide. It is built in code, so
every number matches page 1. One small AI call (`learner=true`, about ¥0.01) adds "how an analyst reads it" notes,
checked like the report. Teaching approach: worked examples for novices, and a separate guide rather than notes inside
the analyst report (the expertise-reversal effect: guidance that helps beginners slows experts down).

**AI calls per report (V2-style):** (1) news sorting and English headlines, (2) broker step: English one-liners from
the brokers' own summaries plus a short street view (skipped when there is no broker coverage), (3) one writer call for
every text section (or Concept → Thesis in two-step mode). About ¥0.02 per full report with `deepseek-flash` (measured 7 Nov 2026: ¥0.20 for 11 runs; up to ~¥0.05 at peak price). Prompt rules
partly adapted from FinRobot (AI4Finance Foundation, Apache-2.0).

---

## 💻 Tech Stack & Cost Efficiency

Designed for zero maintenance and negligible operating costs (< ¥30 RMB / month):

| Component | Technology | Cost | Description |
| :--- | :--- | :--- | :--- |
| **Market Data** | `akshare` + `yfinance` | **¥0** | Open-source multi-market financial data extraction. |
| **AI Synthesis** | **DeepSeek Cloud API** (`deepseek-flash`, thinking off) | **~¥0.02 per tear-sheet commentary; ~¥0.05 per full report** (peak price, see below) | Native bilingual understanding of Chinese financial disclosures. |
| **Anti-Hallucination** | **Stanford DSPy** | **¥0** | Programmatic verification enforcing data integrity. |
| **Document Engine** | **Typst** | **¥0** | Blazing-fast Rust-based typesetting engine for vector PDFs. |
| **Backend & Caching** | **FastAPI + SQLite** | **¥0** | Asynchronous REST API with local statement caching. |
| **Production Hosting** | **Tencent Cloud Lighthouse (HK)** | **~¥25 RMB / mo** | 2 vCPU / 2GB RAM Linux VPS in Hong Kong (low-latency to campus, no ICP license needed). |
| **DNS & Gateway** | **Cloudflare (Free Tier)** | **¥0** | SSL/TLS termination, DDoS mitigation, and global edge routing. |

---

## 📦 Source data pack, peers and data sources

### Source data pack (optional)
For readers who want to dig further, a report can come with the numbers behind it: `--datapack PATH.zip` on the
CLI, the `/datapack` endpoint, or the "Include source data files" box on the test page. The ZIP holds:

| File | Contents |
| :--- | :--- |
| `<TICKER>_data.xlsx` | **README** (currency and units, fiscal-year convention, as-of dates, sources, disclaimer) · **Income statement**, **Balance sheet**, **Cash flow** (5 fiscal years, plus the latest interim period, the same period a year earlier, the latest quarter and TTM when available) · **Ratios** (margins, returns, DuPont, growth, leverage, liquidity, efficiency, payout) · **Valuation** (WACC build-up, DCF forecast, EV-to-equity bridge, DDM, sensitivity grids, reverse DCF, Monte Carlo, football field, P/E band, rating methods) · **Peers** · **Prices** (the sampled price, benchmark and P/E series the report uses) · **Brokers** (street view, broker notes, consensus) · **Sources** (citations, reports read, announcements) |
| `sources.md` | Every source, filing, announcement, broker and news link as a plain list |
| `data.json` | The full payload (same as the JSON endpoint) |
| `filings/` | Only with `--datapack-docs` / `?docs=true`: the original annual / interim reports (SEC EDGAR, HKEXnews, CNINFO), downloaded in parallel; any that fail or take longer than `FILINGS_TIMEOUT_SECONDS` are skipped and listed in `sources.md` |

Numbers are stored as numbers (amounts in millions, ratios as %), copied from the payload; the workbook models
nothing new. The only arithmetic is labelled where it appears (interim / TTM margins, after-tax cost of debt).

### Peers
Peers are found automatically: EastMoney's industry lists for HK and A-shares (largest profitable names), Yahoo Finance's industry rankings for US stocks (with a minimum size). To override for any ticker, add a curated list to `config/peers.json`:
```json
{ "0700.HK": ["9999.HK", "9988.HK", "3690.HK", "1024.HK", "9618.HK"] }
```

### Data Sources & Methodology
| Item | Hong Kong | A-shares | US |
| :--- | :--- | :--- | :--- |
| Statements | EastMoney (HKFRS/IFRS) | Sina Finance (CAS) | EastMoney (US GAAP) + Yahoo (debt) |
| Prices & benchmark | Sina (Hang Seng Index) | Sina (CSI 300) | Sina (S&P 500) |
| P/E, P/B, yield, market cap | EastMoney | EastMoney + dividend history | Yahoo Finance |
| EV/EBITDA | Yahoo Finance | EastMoney industry comparison | Yahoo Finance |
| News | EastMoney (Chinese) | EastMoney (Chinese) | Yahoo Finance + Finnhub (English; free key) |
| Official announcements | HKEXnews | CNINFO | SEC EDGAR |
| Latest report | HKEXnews (annual / interim PDF) | CNINFO (annual / semi-annual PDF) | SEC EDGAR (10-K, 10-Q) |
| Analyst consensus | Yahoo Finance | Yahoo Finance | Yahoo Finance |
| Broker research | etnet: each broker's latest rating, target, EPS forecasts; AAStocks 《大行》 news write-ups of each note (the reports themselves are not public) | EastMoney research centre: every broker report (rating, 3-year EPS, target if given, the broker's own summary, PDF) | Yahoo Finance: analyst rating actions and target changes; news articles about each action (Finnhub / Yahoo news: Benzinga, Investing.com …) |
| Risk-free rate | US 10Y (HKD peg) or China 10Y by reporting currency | China 10Y (ChinaBond via EastMoney) | US 10Y |
| Catalysts & risks | DeepSeek from news + report | DeepSeek from news + report | DeepSeek from news + report |
| Revenue segments | EastMoney F10 (product, region) | EastMoney 主营构成 | EastMoney F10 (product, region) |
| Holders | HKEX disclosure of interests (EastMoney) | Top-10 shareholders (EastMoney) | 13F institutional holders (Yahoo) |
| Insider / major-holder trades | HKEX disclosure of interests (EastMoney) | Major-shareholder trades (EastMoney) | Form 4 (Yahoo) |
| Consensus, management, dividends, governance | Yahoo Finance | Yahoo Finance | Yahoo Finance |

* **Total debt** = borrowings + bonds/notes, excluding lease liabilities. **Cash** includes short-term deposits / marketable securities. Banks and insurers show no debt or EV (not meaningful).
* **Enterprise value** = market cap + latest fiscal-year net debt (converted at spot FX).
* **DuPont** uses average balances: ROE = net margin × asset turnover × equity multiplier. **Accruals ratio** = (net profit − operating cash flow) / average assets.
* **WACC** = cost of equity (risk-free + beta × equity risk premium) and after-tax cost of debt (interest ÷ average debt), weighted by market cap and debt. Beta: 2-year weekly returns vs the benchmark, Blume-adjusted. Equity risk premium: Damodaran (January 2026) by reporting currency, editable in `config/valuation.json`.
* **DCF** (FCFF): consensus revenue for the years covered, then growth fades to the terminal rate over 5 years; free-cash-flow margin = median of the last 3 years; Gordon terminal value; equity = EV − net debt. Shown as a 3×3 grid (WACC ±1pp, terminal growth ±0.5pp). It excludes non-operating assets such as investment stakes and is **not a price target**.
* **DDM** for banks and insurers: trailing dividend grown at the terminal rate, discounted at the cost of equity.
* DCF/DDM are **withheld** when the discount rate is less than 3 percentage points above terminal growth (`min_spread` in `config/valuation.json`). Example: Moutai, where China's 1.6% 10-year yield and a measured beta of 0.40 give a 3.7% WACC. Whether to use a normalised risk-free rate or a beta floor for China is a finance-team decision.
* **EPS** is restated onto today's share basis after splits and A-share bonus issues (送转).
* **Overall view** (page 1): every view on one score — Sell 1, Underperform 2, Hold 3, Outperform 4, Buy 5 (the model's Buy / Hold / Sell = 5 / 3 / 1). Each broker counts once, with its latest rating, and only if that is at most 90 days old (full weight up to 30 days, half weight to 90). The model counts one third and the brokers two thirds; with fewer than three recent brokers their share shrinks in proportion, and a model that is not rated is left out. Model and brokers two or more steps apart → "views split". Yahoo's analyst consensus is shown as a cross-check only. All weights are in `config/rating.json` (`"overall"`). It summarises views; it is not a separate rating.
* **Broker research** is third-party material: every broker is named and linked; ratings are mapped onto Buy / Outperform / Hold / Underperform / Sell; comparisons use each broker's latest note; targets more than 5× or under 0.2× the price and EPS forecasts more than 3× from the median are left out. EastMoney's "this year" EPS column is the first fiscal year not yet reported (January–April notes usually still forecast last year). HK and US brokers sell their reports to clients, so for those markets the text is a news write-up of each note, credited to the news site and linked; write-ups are summarised but never counted in the rating mix or targets. An HK write-up is kept only if its first sentence names the company (or it covers no other stock), and a rating or target is read from it only when stated once and in Hong Kong dollars (the US-listed shares' USD target is ignored).
* **Number guardrail and Chinese text:** figures inside Chinese text (e.g. 增长3.08%, 402.67亿元, 1.64pcts) are read correctly; 亿元 amounts may be written in billions (402.67亿元 = RMB 40.27bn).
* **History:** each run saves headline figures to `data/history/<ticker>/<date>.json` (turn off with `INVESTSYNC_HISTORY=0`), used for "since the last report" and the rating's "since" date.
* **Fiscal year** label = calendar year of the period end (NVIDIA's year to Jan 2026 is FY2026).
* EastMoney's live-quote servers (push2) rate-limit bursts of requests, so the pipeline avoids them entirely. If Sina is unreachable, prices and indices fall back to Yahoo Finance.
* Report downloads from HKEXnews can take minutes from mainland networks; they run in the background, are cached for 30 days, and the sheet is produced without them if they are still downloading.

---

## 📚 References & Prior Art

- **AI4Finance Foundation:** [FinRobot GitHub](https://github.com/AI4Finance-Foundation/FinRobot)
- **Zhou, Wang, Wu, & Yang (2024):** [*FinRobot: AI Agent for Equity Research and Valuation with Large Language Models* (ICAIF 2024 Workshop)](https://arxiv.org/abs/2411.08804)
- **Kim, Muhn, & Nikolaev (2024):** [*Financial Statement Analysis with Large Language Models* (University of Chicago Booth School of Business)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4835311). Withdrawn by the authors in February 2025 for review ([arXiv notice](https://arxiv.org/abs/2407.17866v3)).
- **Stanford NLP:** [DSPy Documentation](https://dspy.ai/) · [Output refinement with `Refine` and `BestOfN`](https://dspy.ai/tutorials/output_refinement/best-of-n-and-refine/)
- **AKShare:** [Open Source Financial Data Interface](https://github.com/akfamily/akshare)
- **Typst:** [Modern Typesetting Engine](https://typst.app/)
