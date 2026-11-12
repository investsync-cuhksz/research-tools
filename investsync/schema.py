"""The TearSheetData contract.

Every layer meets here: the data adapters fill it, the quant engine derives
from it, the narrative layer reads it (and may only quote numbers found in it),
and the Typst template renders it. Change it only through a reviewed PR.

Conventions
-----------
* Monetary amounts are in full units of the stated currency (not millions).
* Ratios are decimals: 0.253 means 25.3%.
* Lists of fiscal years run oldest -> newest.
* ``None`` means "not available"; never substitute 0 for missing data.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.12"  # 1.1 full report; 1.2 AI rating, news tags; 1.3 citations; 1.4 announcements;
#                         1.5 broker research (street view), scorecard, buy-below / sell-above, since last report
#                         (1.5 also: street.writeups, news write-ups of HK / US broker notes; overall, the
#                         page-1 verdict combining the model and recent broker views; both optional)
#                         1.6 narrative.mode "deep" + narrative.deep (debate, judge, reviewer), narrative.learner,
#                         guardrail.text_issues (all optional)
#                         1.7 financials.latest (latest interim / quarter vs a year earlier), financials.ttm,
#                         fiscal_year.minority_interest, financials.cash_definition, ai_usage, DCF margin path /
#                         stub year / minorities in the EV bridge (all optional)
#                         1.8 research (sourced facts from results releases, announcements, broker reports and news,
#                         read by the AI and quote-checked in code) (optional)
#                         1.9 forecast (house forecast: AI drivers, P&L and EPS computed in code, vs consensus);
#                         ai_usage.by_step (optional)
#                         1.10 filing_facts (key items read from the company's own filings: buybacks, dividends,
#                         investment gains, commitments, guarantees; "not reported" when the filing data lacks
#                         them) (optional)
#                         1.11 research.facts[].label (a few words naming the event) and research.dropped_by (drops
#                         by reason) (both optional)
#                         1.12 analyst_questions (the questions an analyst would ask, from config/question_bank.json
#                         plus AI-added ones; deep mode also answers them) (optional)


class Market(str, Enum):
    HK = "HK"  # Hong Kong (HKEX)
    CN = "CN"  # Mainland A-shares (SSE / SZSE / BSE)
    US = "US"  # US listings


class Profile(BaseModel):
    ticker: str = Field(description="Canonical ticker, e.g. 0700.HK, 600519.SH, NVDA")
    name: str
    name_local: Optional[str] = Field(None, description="Chinese name where available")
    market: Market
    exchange: str = Field(description="HKEX, SSE, SZSE, BSE, NASDAQ, NYSE, ...")
    sector: Optional[str] = None
    sector_scheme: Optional[str] = Field(None, description="Classification source, e.g. EastMoney industry")
    trading_currency: str
    reporting_currency: str
    description: Optional[str] = None


class Quote(BaseModel):
    as_of: date
    price: float
    currency: str
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    dividend_yield: Optional[float] = None
    next_earnings_date: Optional[date] = Field(None, description="Next scheduled results, where known")
    # 1.9: what the options market prices by the first expiry after the results (at-the-money straddle / price)
    implied_move: Optional[float] = None
    implied_move_expiry: Optional[date] = None
    # 1.9: A-shares with an H-share listing: the H-share close on the same date and its premium to the A-share
    h_share: Optional[str] = Field(None, description="e.g. 3750.HK")
    h_share_price: Optional[float] = Field(None, description="HKD")
    h_premium: Optional[float] = Field(None, description="H-share price in CNY / A-share price - 1")
    fx_to_reporting: Optional[float] = Field(
        None, description="Multiply trading-currency amounts by this to get reporting currency")


class FiscalYear(BaseModel):
    fiscal_year: int
    period_end: date
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = Field(None, description="Attributable to ordinary shareholders")
    diluted_eps: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    total_debt: Optional[float] = None
    # 1.9: equity stakes outside cash (listed at fair value + unlisted at carrying value; SEC, US only)
    equity_investments: Optional[float] = None
    total_assets: Optional[float] = None
    total_equity: Optional[float] = Field(None, description="Equity attributable to shareholders")
    operating_cash_flow: Optional[float] = None
    depreciation_amortization: Optional[float] = None
    capex: Optional[float] = Field(None, description="Capital expenditure, as a positive amount")
    interest_expense: Optional[float] = Field(None, description="As a positive amount")
    pretax_income: Optional[float] = None
    income_tax: Optional[float] = None
    # Added in 1.1 for the full report (statements and ratios pages)
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    total_liabilities: Optional[float] = None
    inventory: Optional[float] = None
    receivables: Optional[float] = None
    sga_expense: Optional[float] = Field(None, description="Selling + general & administrative, positive")
    rnd_expense: Optional[float] = Field(None, description="Research & development, positive")
    dividends_paid: Optional[float] = Field(None, description="Cash dividends paid, positive")
    buybacks: Optional[float] = Field(None, description="Cash spent on share repurchases, positive")
    minority_interest: Optional[float] = Field(None, description="1.7: non-controlling interests (book value)")
    # Derived by the quant engine
    revenue_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    net_margin: Optional[float] = None
    net_debt: Optional[float] = None
    ebitda: Optional[float] = None
    free_cash_flow: Optional[float] = None


class InterimPeriod(BaseModel):
    """1.7: the latest reported period after the last fiscal year (cumulative from the start of the fiscal
    year, e.g. 9M 2026), with the same period a year earlier, the latest quarter on its own, and the balance
    sheet at the period end. Amounts in the reporting currency, like FiscalYear."""
    period_end: date
    label: str = Field(description='e.g. "9M 2026", "1H 2026", "1H FY2027"')
    months: int = Field(description="3, 6 or 9")
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    capex: Optional[float] = None
    capex_complete: bool = Field(True, description="False when the source lacks capex lines for this period")
    prior_revenue: Optional[float] = None
    prior_gross_profit: Optional[float] = None
    prior_operating_income: Optional[float] = None
    prior_net_income: Optional[float] = None
    prior_operating_cash_flow: Optional[float] = None
    prior_capex: Optional[float] = None
    # the latest quarter alone (e.g. Q3 2026 = 9M minus 1H), where it can be derived
    quarter_label: Optional[str] = None
    quarter_revenue: Optional[float] = None
    quarter_revenue_prior: Optional[float] = None
    quarter_gross_profit: Optional[float] = None
    quarter_gross_profit_prior: Optional[float] = None
    quarter_net_income: Optional[float] = None
    quarter_net_income_prior: Optional[float] = None
    # balance sheet at the period end
    cash_and_equivalents: Optional[float] = None
    total_debt: Optional[float] = None
    # 1.9: equity stakes outside cash (listed at fair value + unlisted at carrying value; SEC, US only)
    equity_investments: Optional[float] = None
    total_equity: Optional[float] = None
    minority_interest: Optional[float] = None
    # 1.10 (HK / A-shares, where the statements carry the line; cumulative like the period): cash spent on
    # buybacks, dividends paid, and investment gains (A-shares: 投资收益 + 公允价值变动收益, which sit INSIDE
    # operating profit under Chinese accounting standards)
    buybacks: Optional[float] = None
    dividends_paid: Optional[float] = None
    investment_gains: Optional[float] = None
    # derived by the quant engine
    revenue_growth: Optional[float] = None
    net_income_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    prior_gross_margin: Optional[float] = None
    free_cash_flow: Optional[float] = None
    prior_free_cash_flow: Optional[float] = None
    net_debt: Optional[float] = None
    quarter_revenue_growth: Optional[float] = None
    quarter_net_income_growth: Optional[float] = None
    quarter_gross_margin: Optional[float] = None
    quarter_gross_margin_prior: Optional[float] = None


class TTMFigures(BaseModel):
    """1.7: trailing twelve months to the latest reported period (last fiscal year + this year to date
    - the same period last year)."""
    period_end: date
    basis: str
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    capex: Optional[float] = None
    free_cash_flow: Optional[float] = None
    fcf_margin: Optional[float] = None


class Financials(BaseModel):
    currency: str
    accounting_standard: Optional[str] = Field(None, description="CAS, HKFRS/IFRS, US GAAP")
    years: list[FiscalYear]
    revenue_cagr: Optional[float] = None
    net_income_cagr: Optional[float] = None
    cagr_years: Optional[int] = None
    latest: Optional[InterimPeriod] = Field(None, description="1.7: latest interim / quarter after the last FY")
    ttm: Optional[TTMFigures] = None
    cash_definition: Optional[str] = Field(None, description="1.7: what cash_and_equivalents includes")


class DuPont(BaseModel):
    fiscal_year: int
    net_margin: Optional[float] = None
    asset_turnover: Optional[float] = None
    equity_multiplier: Optional[float] = None
    roe: Optional[float] = None


class EarningsQuality(BaseModel):
    fiscal_year: int
    cfo_to_net_income: Optional[float] = Field(None, description="Operating cash flow / net income")
    accruals_ratio: Optional[float] = Field(
        None, description="(Net income - operating cash flow) / average total assets")


class CompRow(BaseModel):
    ticker: str
    name: str
    market_cap: Optional[float] = None
    currency: Optional[str] = None
    pe_ttm: Optional[float] = None
    pe_fwd: Optional[float] = Field(None, description="1.8: price / consensus EPS of the next fiscal year (Yahoo)")
    ev_ebitda: Optional[float] = None
    pb: Optional[float] = None
    dividend_yield: Optional[float] = None
    ebitda_ttm: Optional[float] = Field(None, description="1.8: trailing-twelve-month EBITDA (Yahoo), in "
                                                          "ebitda_currency")
    ebitda_currency: Optional[str] = None
    # Operating comparison (1.1), latest reported / trailing figures from Yahoo Finance
    revenue: Optional[float] = Field(None, description="Trailing revenue, in revenue_currency")
    revenue_currency: Optional[str] = None
    revenue_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None


class Comps(BaseModel):
    method: str = Field(description="How peers were chosen")
    target: CompRow
    peers: list[CompRow]
    median: CompRow
    premium_discount: dict[str, Optional[float]] = Field(
        description="Target vs. peer median per metric: 0.15 = 15% premium, -0.10 = 10% discount")


class SeriesPoint(BaseModel):
    d: date
    v: float


class BenchmarkPeriod(BaseModel):
    period: Literal["1Y", "3Y", "5Y"]
    start: date
    stock: list[SeriesPoint] = Field(description="Rebased to 100 at period start")
    benchmark: list[SeriesPoint]
    stock_return: Optional[float] = None
    benchmark_return: Optional[float] = None


class Benchmark(BaseModel):
    name: str
    code: str
    periods: list[BenchmarkPeriod]


class NewsItem(BaseModel):
    published: Optional[datetime] = None
    title: str
    source: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    # 1.2: filled by the AI news step (None until it runs)
    headline_en: Optional[str] = Field(None, description="One-line English headline written by the AI")
    category: Optional[Literal["earnings", "product", "regulation", "market", "management", "deal", "other"]] = None
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = None
    relevant: Optional[bool] = Field(None, description="Mainly about this company")


class FilingExcerpt(BaseModel):
    """Sections pulled from the latest periodic report (annual / interim / 10-K / 10-Q)."""
    source: str = Field(description="SEC EDGAR, HKEXnews or CNINFO")
    title: str
    filed: Optional[date] = None
    url: str
    sections: dict[str, str] = Field(description="Section name -> excerpt text (original language)")


class WACC(BaseModel):
    risk_free: float
    risk_free_source: str
    beta: Optional[float] = None
    beta_method: str
    equity_risk_premium: float
    erp_source: str
    cost_of_equity: float
    pre_tax_cost_of_debt: Optional[float] = None
    tax_rate: float
    debt_weight: float
    equity_weight: float
    wacc: Optional[float] = Field(None, description="None for banks / insurers (not meaningful)")


class ForecastYear(BaseModel):
    fiscal_year: int
    revenue: float
    growth: float
    free_cash_flow: float
    basis: Literal["consensus", "fade"]
    discount_factor: Optional[float] = None
    present_value: Optional[float] = None


class ValueGrid(BaseModel):
    row_label: str                     # e.g. "WACC" or "Cost of equity"
    col_label: str                     # e.g. "Terminal growth"
    rows: list[float]
    cols: list[float]
    values: list[list[Optional[float]]]  # value per share, trading currency


class EVBridge(BaseModel):
    """From discounted cash flows to value per share (reporting currency unless stated)."""
    pv_forecast: float
    pv_terminal: float
    enterprise_value: float
    net_debt: float
    equity_value: float
    shares: float
    fx_to_reporting: float
    value_per_share: float = Field(description="Trading currency")
    terminal_share: float = Field(description="PV of terminal value / enterprise value")
    minority_interest: Optional[float] = Field(None, description="1.7: non-controlling interests deducted (book)")
    balance_sheet_date: Optional[date] = Field(None, description="1.7: date of the net debt / minorities used")
    roll_forward_years: Optional[float] = Field(None, description="1.7: value rolled forward from the balance-sheet "
                                                                    "date to the price date at WACC")
    investments: Optional[float] = Field(None, description="1.9: equity stakes added to equity value, after the "
                                                           "haircut")


class DCF(BaseModel):
    method: str
    fcf_margin: float
    terminal_growth: float
    forecast: list[ForecastYear]
    enterprise_value: float
    equity_value: float
    value_per_share: Optional[float] = None
    upside: Optional[float] = None
    grid: Optional[ValueGrid] = None
    bridge: Optional[EVBridge] = None
    terminal_value: Optional[float] = None
    margin_path: Optional[list[float]] = Field(None, description="1.7: FCF margin per forecast year (fcf_margin = last)")
    stub_years: Optional[float] = Field(None, description="1.7: fraction of the first forecast year still to come")
    stub_cash_share: Optional[float] = Field(None, description="1.8: share of the first forecast year's cash flow "
                                                               "still to come (its revenue not yet reported)")
    margin_basis: Optional[str] = Field(None, description="1.7: how the FCF margin path was set")


class DDM(BaseModel):
    method: str
    dividend_per_share: float
    growth: float
    value_per_share: Optional[float] = None
    upside: Optional[float] = None
    grid: Optional[ValueGrid] = None


class ReverseDCF(BaseModel):
    """What the share price implies, holding the other DCF / DDM inputs fixed."""
    model: Literal["DCF", "DDM"]
    horizon_years: int
    implied_growth: Optional[float] = Field(
        None, description="DCF: constant revenue growth over the explicit years; DDM: perpetual dividend growth")
    model_growth: Optional[float] = Field(None, description="Average growth the base case assumes, same basis")
    implied_fcf_margin: Optional[float] = Field(None, description="DCF only: FCF margin that justifies the price")
    model_fcf_margin: Optional[float] = None
    note: Optional[str] = None
    # run 2 (12 Nov 2026): the reverse DCF can hold the consensus years and solve only for the later ones
    hold_years: int = Field(0, description="Explicit years held at our forecast / consensus before the solved years")
    from_year: Optional[int] = Field(None, description="First fiscal year of the solved growth")
    to_year: Optional[int] = Field(None, description="Last fiscal year of the solved growth")


class MonteCarlo(BaseModel):
    """Distribution of value per share when the main inputs vary at random (seeded, reproducible)."""
    model: Literal["DCF", "DDM"]
    n_draws: int
    n_valid: int
    seed: int
    percentiles: dict[str, float] = Field(description="p5, p10, p25, p50, p75, p90, p95 (trading currency)")
    mean: float
    prob_above_price: float
    bins: list[float] = Field(description="Histogram bin edges (len = counts + 1)")
    counts: list[int]
    assumptions: dict[str, float] = Field(description="Standard deviations / ranges used for each input")


class Sensitivity(BaseModel):
    discount_growth: Optional[ValueGrid] = Field(None, description="5x5: WACC (or Ke) vs terminal growth")
    margin_growth: Optional[ValueGrid] = Field(None, description="5x5: FCF margin vs revenue growth shift (DCF)")


class Valuation(BaseModel):
    currency: str = Field(description="Currency of per-share values (the trading currency)")
    wacc: WACC
    dcf: Optional[DCF] = None
    ddm: Optional[DDM] = None
    notes: list[str] = []
    # 1.1: full-report valuation pages
    reverse: Optional[ReverseDCF] = None
    monte_carlo: Optional[MonteCarlo] = None
    sensitivity: Optional[Sensitivity] = None
    scenarios: Optional["ScenarioSet"] = Field(None, description="1.8: analyst scenarios set before writing "
                                                                 "(RATING_BASIS=scenarios)")


class Bullet(BaseModel):
    title: str
    text: str


class GuardrailReport(BaseModel):
    passed: bool
    attempts: int
    unmatched_numbers: list[str] = []
    # 1.6: wording checks in code (direction, currency, period, momentum, sector) still open after the rewrites
    text_issues: list[str] = []


# ---------------------------------------------------------------- 1.6: deep analysis (debate, judge, reviewer)
class EvidenceRef(BaseModel):
    id: str = Field(description="S.. = signal computed in code, E.. = numbered fact line")
    label: str
    value: str
    stance: Literal["bull", "bear", "neutral"] = "neutral"


class DebateFinding(BaseModel):
    area: str
    finding: str
    stance: Literal["positive", "negative", "mixed"] = "mixed"
    evidence: list[str] = []


class DebateArgument(BaseModel):
    id: str = Field(description="BULL-1 ... / BEAR-1 ...")
    claim: str
    reasoning: str
    evidence: list[str] = []
    assumption: str = ""
    breaks_if: str = ""


class DebateRebuttal(BaseModel):
    side: Literal["bull", "bear"]
    target: str = Field(description="Id of the opposing argument answered")
    response: str
    evidence: list[str] = []


class ReviewNote(BaseModel):
    section: str
    quote: str
    problem: str
    fix: str
    resolved: bool = Field(False, description="The quoted words are gone from the final text")


class Scenario(BaseModel):
    """1.8: one valuation scenario; assumptions set by the AI, value computed in code with the model's DCF."""
    name: Literal["bear", "base", "bull"]
    probability: float
    revenue_growth: list[float] = Field(description="Next three fiscal years")
    fcf_margin: float = Field(description="Reached by year three and held")
    value_per_share: float
    upside: Optional[float] = None
    drivers: str = ""


class HouseForecastYear(BaseModel):
    """1.9: one year of the house forecast (computed in code from the AI's drivers)."""
    period: str = Field(description='e.g. "FY2027E"')
    revenue: float
    revenue_growth: float
    gross_margin: Optional[float] = None
    operating_margin: float
    operating_income: float
    other_income_share: Optional[float] = Field(None, description="Pre-tax minus operating profit, share of revenue")
    net_income: float
    eps: float
    eps_growth: Optional[float] = None
    consensus_revenue: Optional[float] = None
    consensus_eps: Optional[float] = None
    consensus_eps_growth: Optional[float] = None
    revenue_vs_consensus: Optional[float] = None
    eps_vs_consensus: Optional[float] = None


class HouseForecast(BaseModel):
    """1.9: the analyst's own forecast for the next three fiscal years (reporting currency)."""
    currency: str
    years: list[HouseForecastYear]
    revenue_drivers: str = ""
    margin_drivers: str = ""
    vs_consensus: str = ""
    key_risk: str = ""
    remainder: Optional[str] = Field(None, description="What the first year implies for its unreported months")
    consensus_note: Optional[str] = Field(None, description="Set when consensus EPS is on an adjusted basis")
    note: str = ""


class ScenarioSet(BaseModel):
    scenarios: list[Scenario]
    weighted_value: float
    weighted_upside: Optional[float] = None
    currency: str
    note: str = ""


class DeepAnalysis(BaseModel):
    """Deep mode: analyst findings, a bull / bear debate checked in code, the judge's verdict and the
    reviewer's notes. The judge never sets the rating; the rule-based AI rating stays the only rating."""
    findings: list[DebateFinding] = []
    priced_in: str = ""
    key_questions: list[str] = []
    bull: list[DebateArgument] = []
    bear: list[DebateArgument] = []
    rebuttals: list[DebateRebuttal] = []
    concessions_bull: list[str] = []
    concessions_bear: list[str] = []
    dropped: list[str] = Field([], description="Arguments removed by the evidence checks, with the reason")
    scenarios: Optional[ScenarioSet] = Field(None, description="1.8: bear / base / bull values (AI assumptions, "
                                                                "code-computed DCF); never the rating")
    stronger_side: Literal["bull", "bear", "balanced"] = "balanced"
    conviction: Literal["low", "medium", "high"] = "low"
    verdict: str = ""
    swing_factor: str = ""
    change_my_mind: str = ""
    divergences: list[str] = []
    rating_alignment: Literal["agrees", "disagrees", "partly", "not rated"] = "not rated"
    variant_view: str = ""
    pre_mortem: str = ""
    review: list[ReviewNote] = []
    review_summary: str = ""
    evidence: list[EvidenceRef] = Field([], description="Every evidence item cited in the debate")
    calls: int = 0
    thinking: bool = False


class LearnerNotes(BaseModel):
    """1.6: AI notes for the learner's guide (the guide itself is built in code from the data)."""
    big_picture: str = ""
    steps: dict[str, str] = Field({}, description="Guide step key -> how an analyst reads this company's numbers")
    discussion: list[str] = []


class Narrative(BaseModel):
    status: Literal["generated", "placeholder", "flagged"]
    model: Optional[str] = None
    mode: Literal["single", "two_step", "deep"] = "single"
    dupont_commentary: str
    comps_commentary: str
    catalysts: list[Bullet]
    risks: list[Bullet]
    guardrail: Optional[GuardrailReport] = None
    # 1.1: long-form sections of the full report (empty until the AI step writes them)
    tagline: str = ""
    thesis: str = Field("", description="Investment thesis paragraph")
    key_takeaways: list[str] = []
    company_overview: str = ""
    financial_analysis: str = ""
    valuation_overview: str = ""
    competitive_analysis: str = ""
    news_summary: str = ""
    report_summary: str = Field("", description="Summary of the latest annual / interim report")
    events_to_monitor: list[Bullet] = []
    rating_rationale: str = Field("", description="Why the rule-based rating comes out as it does")
    # 1.6
    deep: Optional[DeepAnalysis] = None
    learner: Optional[LearnerNotes] = None
    # 1.10 (11 Nov 2026): the analyst brief (thesis memo) the writer worked from; a later report on the same data
    # (generate.py --data-from) reuses it, so the reports of one day argue one thesis
    brief: Optional[str] = None


# ---------------------------------------------------------------- 1.1: full-report sections
class CompanyFacts(BaseModel):
    description: Optional[str] = Field(None, description="Full business description")
    headquarters: Optional[str] = None
    incorporated_in: Optional[str] = None
    founded: Optional[str] = None
    listed: Optional[str] = None
    employees: Optional[int] = None
    website: Optional[str] = None
    chairman: Optional[str] = None
    fiscal_year_end: Optional[str] = None
    index_membership: Optional[str] = None
    sources: list[str] = []


class Officer(BaseModel):
    name: str
    title: str
    age: Optional[int] = None
    total_pay: Optional[float] = None
    currency: Optional[str] = None


class Segment(BaseModel):
    name: str
    revenue: Optional[float] = None
    share: Optional[float] = Field(None, description="Share of total revenue")
    gross_margin: Optional[float] = None


class SegmentBreakdown(BaseModel):
    kind: Literal["business", "product", "region"]
    period: str = Field(description="e.g. FY2025")
    currency: Optional[str] = None
    segments: list[Segment]
    source: str


class Holder(BaseModel):
    name: str
    kind: Optional[str] = Field(None, description="e.g. institution, fund, strategic, individual")
    shares: Optional[float] = None
    pct: Optional[float] = Field(None, description="Share of the class / company, decimal")
    change: Optional[float] = Field(None, description="Change in shares since the previous report")
    value: Optional[float] = None


class InsiderTxn(BaseModel):
    on: Optional[date] = Field(None, description="Transaction date")
    name: str
    position: Optional[str] = None
    action: str = Field(description="e.g. Sale, Purchase, Award, Option exercise")
    shares: Optional[float] = None
    value: Optional[float] = None
    price: Optional[float] = None


class Ownership(BaseModel):
    as_of: Optional[date] = None
    holders_title: str = "Major shareholders"
    holders: list[Holder] = []
    insiders_pct: Optional[float] = None
    institutions_pct: Optional[float] = None
    insider_transactions: list[InsiderTxn] = []
    governance_risk: dict[str, int] = Field(
        default_factory=dict, description="ISS QualityScore via Yahoo: 1 (low risk) - 10 (high risk)")
    # 1.9: positioning (US: exchange-reported short interest via Yahoo)
    short_pct_float: Optional[float] = None
    short_ratio: Optional[float] = Field(None, description="Days to cover at average volume")
    short_as_of: Optional[date] = None
    short_change: Optional[float] = Field(None, description="Shares short vs the prior month")
    sources: list[str] = []


class EstimateRow(BaseModel):
    period: str = Field(description="e.g. FY2026E")
    eps_avg: Optional[float] = None
    eps_90d_ago: Optional[float] = Field(None, description="1.9: consensus EPS 90 days ago (Yahoo EPS trend)")
    eps_low: Optional[float] = None
    eps_high: Optional[float] = None
    eps_growth: Optional[float] = None
    revenue_avg: Optional[float] = None
    revenue_growth: Optional[float] = None
    analysts: Optional[int] = None


class Consensus(BaseModel):
    """Third-party analyst consensus (not an InvestSync view)."""
    currency: Optional[str] = None
    target_mean: Optional[float] = None
    target_median: Optional[float] = None
    target_high: Optional[float] = None
    target_low: Optional[float] = None
    analysts: Optional[int] = None
    recommendation_mean: Optional[float] = Field(None, description="1 = strong buy ... 5 = strong sell")
    distribution: dict[str, int] = Field(default_factory=dict, description="strong_buy, buy, hold, sell, strong_sell")
    estimates: list[EstimateRow] = []
    # 1.9: the next two quarters (Yahoo 0q / +1q), for the results preview and the second-half check
    quarters: list[EstimateRow] = []
    price_90d_ago: Optional[float] = Field(None, description="1.9: close about 90 days before the price date")
    estimate_currency: Optional[str] = Field(None, description="Currency of EPS / revenue estimates")
    forward_pe: Optional[float] = None
    source: str = "Yahoo Finance"


class DividendYear(BaseModel):
    year: int
    dps: float = Field(description="Cash dividend per share paid in the calendar year, trading currency")
    payout_ratio: Optional[float] = None


class Event(BaseModel):
    on: Optional[date] = Field(None, description="Event date")
    label: str
    kind: Literal["results", "dividend", "report", "other"] = "other"


class RatioYear(BaseModel):
    fiscal_year: int
    roe: Optional[float] = None
    roa: Optional[float] = None
    roic: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    ebitda_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf_margin: Optional[float] = None
    revenue_growth: Optional[float] = None
    eps_growth: Optional[float] = None
    sga_ratio: Optional[float] = None
    rnd_ratio: Optional[float] = None
    capex_ratio: Optional[float] = None
    effective_tax: Optional[float] = None
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    liabilities_to_assets: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    interest_coverage: Optional[float] = None
    asset_turnover: Optional[float] = None
    equity_multiplier: Optional[float] = None
    receivable_days: Optional[float] = None
    inventory_days: Optional[float] = None
    cash_conversion: Optional[float] = None
    accruals_ratio: Optional[float] = None
    payout_ratio: Optional[float] = None
    total_payout_ratio: Optional[float] = Field(None, description="(dividends + buybacks) / net income")


class TechPoint(BaseModel):
    d: date
    close: float
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    volume: Optional[float] = None
    rsi: Optional[float] = None


class ReturnRow(BaseModel):
    period: str
    stock: Optional[float] = None
    benchmark: Optional[float] = None


class Signal(BaseModel):
    name: str
    reading: Literal["bullish", "bearish", "neutral"]


class Technicals(BaseModel):
    """Rule-based price indicators (descriptive, not a recommendation)."""
    as_of: date
    price: float
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    rsi14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    volume_ratio: Optional[float] = Field(None, description="Latest volume / 20-day average")
    volatility_1y: Optional[float] = Field(None, description="Annualised, daily log returns")
    big_move: Optional[float] = Field(None, description="1.9: the largest one-day close-to-close move in the last "
                                                        "30 days (research searches for its cause)")
    big_move_date: Optional[date] = None
    max_drawdown_1y: Optional[float] = None
    max_drawdown_3y: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    support: Optional[float] = Field(None, description="3-month low")
    resistance: Optional[float] = Field(None, description="3-month high")
    returns: list[ReturnRow] = []
    signals: list[Signal] = []
    overall: Literal["bullish", "bearish", "neutral"] = "neutral"
    chart: list[TechPoint] = []


class RangeBar(BaseModel):
    label: str
    low: float
    high: float
    mid: Optional[float] = None
    basis: str


class FootballField(BaseModel):
    currency: str
    price: float
    bars: list[RangeBar]


class MultipleBand(BaseModel):
    metric: str = Field(description="e.g. P/E (trailing annual EPS)")
    series: list[SeriesPoint]
    current: float
    median: float
    low: float
    high: float
    mean: float
    std: float
    percentile: float = Field(description="Share of history below the current multiple")
    note: Optional[str] = None


class RatingMethod(BaseModel):
    key: str = Field(description="dcf, ddm, peer_pe, peer_ev_ebitda, peer_pb")
    label: str
    value: float = Field(description="Value per share, trading currency")
    weight: float
    included: bool
    note: Optional[str] = None


class Rating(BaseModel):
    """Rule-based rating: the code sets it from the valuation; the AI only explains it."""
    rating: Literal["Buy", "Hold", "Sell", "Not rated"]
    fair_value: Optional[float] = Field(None, description="Weighted blend of the included methods, trading currency")
    upside: Optional[float] = None
    currency: str
    confidence: Optional[Literal["high", "medium", "low"]] = None
    methods: list[RatingMethod] = []
    buy_threshold: float
    sell_threshold: float
    reason: Optional[str] = Field(None, description="Why not rated, or what drove the confidence")
    # 1.5: the price levels at which the same rule would say Buy / Sell (Morningstar-style)
    buy_below: Optional[float] = Field(None, description="Price at or below which the rule says Buy")
    sell_above: Optional[float] = Field(None, description="Price at or above which the rule says Sell")
    # 1.9: "scenarios" = the fair value is our probability-weighted bear/base/bull value (RATING_BASIS=analyst);
    # the peer multiples and the mechanical DCF are cross-checks. "blend" = the weighted blend of methods.
    basis: Literal["blend", "scenarios"] = "blend"


# ---------------------------------------------------------------- 1.5: broker research (street view)
StdRating = Literal["Buy", "Outperform", "Hold", "Underperform", "Sell"]


class BrokerNote(BaseModel):
    """One third-party broker view: a research report (A-shares), a forecast entry (HK), a rating
    action (US) or a news write-up of a broker's note (HK / US, in StreetView.writeups). Third-party
    material: credited and linked, never an InvestSync view."""
    on: date = Field(description="Report / update / action date")
    broker: str = Field(description="English name where known")
    broker_local: Optional[str] = Field(None, description="Name as published (e.g. Chinese)")
    rating: Optional[StdRating] = Field(None, description="Rating on a common 5-step scale")
    rating_original: Optional[str] = Field(None, description="Rating wording as published")
    previous_rating: Optional[StdRating] = None
    action: Optional[Literal["initiate", "upgrade", "downgrade", "maintain"]] = None
    target: Optional[float] = Field(None, description="Price target, trading currency")
    previous_target: Optional[float] = None
    eps: dict[str, float] = Field(default_factory=dict, description="FY2026 -> EPS forecast, reporting currency")
    title: Optional[str] = Field(None, description="Report title as published (original language)")
    abstract: Optional[str] = Field(None, description="The broker's own summary (original language), trimmed")
    summary_en: Optional[str] = Field(None, description="One-line English summary written by the AI, checked")
    analysts: Optional[str] = None
    url: Optional[str] = Field(None, description="Report PDF or source page")
    source: str = Field(description="Where the entry was found, e.g. EastMoney research centre")


class EpsSpread(BaseModel):
    """How far apart the brokers' EPS forecasts for one fiscal year are."""
    period: str
    n: int
    low: float
    median: float
    high: float
    spread: Optional[float] = Field(None, description="(high - low) / |median|")
    vs_last_actual: Optional[float] = Field(None, description="Median vs the latest reported EPS")
    vs_consensus: Optional[float] = Field(None, description="Median vs the Yahoo consensus for the same year")
    excluded: int = Field(0, description="Forecasts more than 3x away from the median (e.g. quoted per ADS)")


class EpsRevision(BaseModel):
    """Median forecast for one year from recent notes vs older notes (estimate-revision trend)."""
    period: str
    recent_days: int
    recent_n: int
    recent_median: float
    earlier_n: int
    earlier_median: float
    change: float


class StreetView(BaseModel):
    """What the brokers say, compared with each other and with the InvestSync model (computed in code)."""
    source: str
    source_url: Optional[str] = None
    market: Market
    window_days: int
    currency: Optional[str] = Field(None, description="Currency of price targets (trading currency)")
    eps_currency: Optional[str] = None
    notes: list[BrokerNote] = Field(default_factory=list, description="Newest first")
    writeups: list[BrokerNote] = Field(default_factory=list,
                                       description="News write-ups of recent broker notes (HK, US), newest first; "
                                                   "shown and summarised, not counted in ratings or targets")
    reports: int = 0
    brokers: int = 0
    rating_counts: dict[str, int] = Field(default_factory=dict, description="Latest rating per broker")
    upgrades: int = 0
    downgrades: int = 0
    targets_n: int = 0
    target_low: Optional[float] = None
    target_median: Optional[float] = None
    target_high: Optional[float] = None
    target_upside: Optional[float] = Field(None, description="Median target vs the share price")
    target_values: list[float] = Field(default_factory=list, description="Latest target per broker (price-checked)")
    stale_targets: int = Field(0, description="Targets older than 90 days")
    model_fair_value: Optional[float] = None
    model_rating: Optional[str] = None
    targets_above_model: Optional[int] = None
    eps: list[EpsSpread] = []
    revision: Optional[EpsRevision] = None
    agreement: Optional[Literal["high", "medium", "low"]] = None
    agreement_reason: Optional[str] = None
    findings: list[str] = Field(default_factory=list, description="Comparisons written by code (no AI)")
    synthesis: Optional[str] = Field(None, description="AI: where brokers agree / differ (checked)")

    def texts(self) -> list[BrokerNote]:
        """Entries with text to summarise, newest first: the brokers' own summaries (A-shares) or
        the news write-ups of their notes (HK, US)."""
        return sorted([n for n in self.notes if n.abstract] + list(self.writeups), key=lambda n: n.on, reverse=True)


# ---------------------------------------------------------------- 1.5: scorecard
class ScoreCheck(BaseModel):
    name: str
    passed: Optional[bool] = Field(None, description="None = not enough data")
    detail: str


class ScoreArea(BaseModel):
    key: Literal["value", "future", "past", "health", "dividend"]
    title: str
    score: int = Field(description="Checks passed")
    available: int = Field(description="Checks with enough data")
    checks: list[ScoreCheck]
    note: Optional[str] = None


class Scorecard(BaseModel):
    """Yes/no checks in five areas, after Simply Wall St's published model (CC BY-NC-SA 4.0), adapted:
    peers stand in for the whole market. Computed in code; it does not feed the rating."""
    areas: list[ScoreArea]
    piotroski: Optional[ScoreArea] = Field(None, description="Piotroski F-score (9 checks), latest vs prior year")


class BrokerVote(BaseModel):
    """One broker's latest recent view, as counted in the overall view."""
    broker: str
    on: date
    rating: StdRating
    weight: float = Field(description="1 if recent, less if older (see OverallView)")
    target: Optional[float] = None
    source: str


class ViewInput(BaseModel):
    """One voice in the overall view."""
    source: str
    rating: Optional[str] = Field(None, description="As that source states it")
    score: Optional[float] = Field(None, description="1 = Sell ... 5 = Buy")
    weight: float = Field(0.0, description="Share of the overall score; 0 = shown for reference only")
    detail: str = ""
    as_of: Optional[date] = None


class OverallView(BaseModel):
    """Page-1 verdict, computed in code: the InvestSync model plus every broker's latest recent view
    (time-weighted; stale views left out). Not a new InvestSync rating: a summary of all views."""
    rating: StdRating
    score: float = Field(description="1 = Sell ... 5 = Buy")
    basis: str = Field(description="e.g. 'model 33% + 16 brokers 67%'")
    inputs: list[ViewInput] = []
    votes: list[BrokerVote] = []
    stale: list[str] = Field(default_factory=list, description="Brokers left out: latest view older than fresh_days")
    fresh_days: int
    full_weight_days: int
    older_weight: float
    model_share: float
    broker_share: float
    brokers_score: Optional[float] = None
    split: bool = Field(False, description="Model and brokers two or more steps apart")
    split_note: Optional[str] = None
    thin: bool = Field(False, description="Fewer recent brokers than the minimum")
    target_median: Optional[float] = Field(None, description="Median of recent targets only")
    target_upside: Optional[float] = None
    targets_n: int = 0
    oldest: Optional[date] = None
    newest: Optional[date] = None


class SinceLast(BaseModel):
    """Comparison with the previous saved report for this ticker (data/history)."""
    previous_date: date
    previous_price: Optional[float] = None
    previous_rating: Optional[str] = None
    previous_fair_value: Optional[float] = None
    previous_street_target: Optional[float] = None
    rating_since: Optional[date] = Field(None, description="First saved report with today's rating, unbroken")
    changes: list[str] = []


class Announcement(BaseModel):
    """An official company filing / exchange announcement (SEC EDGAR, HKEXnews, CNINFO)."""
    on: date
    title: str
    kind: str = Field(description="Plain-English type, e.g. '8-K: Results of operations', 'Dividend payment'")
    important: bool = Field(False, description="Results, dividends, buybacks, deals, management changes, warnings")
    url: str
    source: str


class Citation(BaseModel):
    """One numbered source in the report's citation list."""
    n: int
    topic: str = Field(description="statements, market, prices, fx, rates, consensus, peers, profile, segments, "
                                   "ownership, dividends, events, news, filings, assumptions")
    what: str = Field(description="Which data came from here")
    publisher: str = Field(description="Original publisher / data owner")
    via: str = Field(description="How it was accessed (library + function, API, download)")
    url: str
    retrieved: Optional[datetime] = Field(None, description="When the data was fetched (UTC); cached data shows "
                                                            "the original fetch time")


class AuditCheck(BaseModel):
    name: str
    status: Literal["pass", "caveat", "fail", "info"]
    detail: str


class Audit(BaseModel):
    """Automatic data checks, in the spirit of FinRobot's numeric audit."""
    status: Literal["publishable", "caveated", "review"]
    checks: list[AuditCheck]


class AIUsage(BaseModel):
    """1.7: LLM usage for one report (all AI steps, incl. peer selection). Cached repeat calls cost nothing."""
    calls: int = 0
    prompt_tokens: int = 0
    cache_hit_tokens: int = Field(0, description="Input tokens served from the provider's context cache (cheaper)")
    completion_tokens: int = Field(0, description="Output tokens, including thinking tokens")
    reasoning_tokens: int = 0
    models: list[str] = Field(default_factory=list)
    est_cost_usd: Optional[float] = Field(None, description="At peak-hour list prices; off-peak is half")
    price_note: Optional[str] = None
    by_step: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="1.8: the same per step (writer, think, check, research, peers)")
    by_phase: dict[str, dict] = Field(
        default_factory=dict, description="1.12, run 3: the same per pipeline phase (research, forecast, scenarios, "
                                          "analyst brief, debate, deep review, learner coach, ...), with the models "
                                          "used; calls outside a phase keep their step label. Feeds the cost per "
                                          "report (tools/cost_split.py)")


class ResearchFact(BaseModel):
    """1.8: one sourced fact the research desk extracted; the quote was found verbatim in the document in code."""
    id: str = Field(description="R1, R2, ... (cited in the commentary as [R#])")
    topic: str = Field(description="guidance, results, quality, policy, events, capital, competition, street, "
                                   "catalysts or other")
    text: str = Field(description="The fact in one English sentence")
    quote: str = Field(description="Verbatim words from the document that support it")
    source: str
    title: str
    url: Optional[str] = None
    published: Optional[date] = None
    event_date: Optional[date] = Field(None, description="1.12, run 4: when the event happened, if the quote states it (read in code); `published` is when the source was published. None for a news note means the source does not say when it happened")
    kind: str = Field("", description="results_release, results_commentary, periodic_report, announcement, "
                                      "ir_record, broker_report, news, transcript or call_summary")
    key: str = Field("", description="1.10: set for a key fact read from the whole latest results documents (the "
                                     "checklist item, e.g. guidance or commitments); empty for other notes")
    said_by: str = Field("", description="Run 2: who made the statement: company, broker, press, or empty if unknown "
                                         "(a company statement reported by the press is still the company's)")
    label: str = Field("", description="1.11: a few words naming the event (AI-written, no figures, names checked "
                                       "against the fact); printed next to the id where AI text cites it")


class DecidingDriver(BaseModel):
    """1.12, run 4: one driver of revenue in the deciding year (narrative/deciding.py)."""
    driver: str
    evidence: str
    effect: Literal["supports", "risks", "unclear"] = "unclear"


class DecidingYear(BaseModel):
    """1.12, run 4: the year the valuation rests on (the third forecast year) and what will decide it, by the
    judgement model, figures, ids and names checked in code."""
    period: str
    base_growth: Optional[float] = None
    drivers: list[DecidingDriver] = Field(default_factory=list)
    verdict: str = ""
    model: str = ""


class ResearchBrief(BaseModel):
    """1.8: what the research desk read and found. Facts are evidence for the commentary, never for the rating."""
    questions: list[str] = Field(default_factory=list)
    facts: list[ResearchFact] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="Topics with no sourced fact found")
    docs_read: int = 0
    chunks_read: int = 0
    facts_dropped: int = Field(0, description="Extracted facts dropped because the quote or a figure was not "
                                              "found in the document")
    dropped_by: dict[str, int] = Field(default_factory=dict, description="1.11: facts_dropped by reason (research/"
                                       "desk.py DROP_REASONS: quote, figures, name, other_company, no_source, empty)")
    funnel: dict[str, int] = Field(default_factory=dict, description="1.12, run 3: documents and excerpts at each "
                                   "filter step (research/desk.py: found, duplicates, no_text, not_on_list, documents, "
                                   "candidate_excerpts, excerpts_read, news_snippets_bundled)")
    method: str = ""


class FilingFact(BaseModel):
    """1.10: one key item from the company's own filed data (SEC XBRL for US listings; the statements loaded from
    EastMoney / Sina for Hong Kong and A-shares). ``value`` None = not reported in that data: the report must then
    say so rather than take a figure from a news story or an older period."""
    key: str = Field(description="buybacks_ytd, buyback_remaining, dividends_ytd, investment_gains_ytd, "
                                 "investment_gains_quarter, nonoperating_ytd, purchase_obligations, guarantees, "
                                 "sbc_ytd, listed_stakes, unlisted_stakes, equity_method_stakes")
    label: str
    value: Optional[float] = Field(None, description="Full units of `currency`; None = not reported")
    currency: str = ""
    period: str = Field("", description='e.g. "6 months to 26 Jul 2026" or "at 26 Jul 2026"')
    as_of: Optional[date] = None
    source: str = ""
    note: str = ""


class AnalystQuestion(BaseModel):
    """1.12: one question an analyst would ask about this company: from the team's question bank
    (config/question_bank.json, general or sector) or added by the AI from recent evidence."""
    id: str = Field(description="Bank id (e.g. cash_conversion) or new_1 .. new_3 for an AI-added question")
    theme: str = Field(description="Bank theme key: moat, industry, quality, management, growth, valuation, events")
    text: str
    source: Literal["general", "sector", "new"] = "general"
    data_key: str = Field("", description="Key of the figure computed in code (narrative/questions.py COMPUTE)")
    computed: str = Field("", description="That figure as printed when the questions were chosen")
    look: str = Field("", description="Report chapter to point the reader to (overview, financials, ...)")
    why_now: str = Field("", description="AI: one line on why it matters now, citing evidence ids ([R12], [N3])")
    evidence: list[str] = Field(default_factory=list, description="Evidence ids the question or its answer cites")
    answer: str = Field("", description="Deep mode only: a short answer citing evidence ids, checked in code; never "
                                        "printed in the standard report or the learner's guide")
    answer_status: Literal["", "answered", "open"] = ""


class AnalystQuestions(BaseModel):
    """1.12: the questions shown in every report. Chosen by the AI (method "ai") or in code (method "code": the
    data-only edition, or when the AI step failed). A later report on the same data reuses them."""
    method: Literal["ai", "code"] = "code"
    sector: str = Field("", description="Matched bank sector key ('' = general questions only)")
    sector_label: str = ""
    questions: list[AnalystQuestion] = Field(default_factory=list)
    news_refs: dict[str, str] = Field(default_factory=dict, description="N ids -> 'publisher, date' of the news "
                                                                        "items the AI saw")
    answered: bool = Field(False, description="Deep mode wrote the answers")
    log: list[str] = Field(default_factory=list, description="What the code checks dropped or struck, and why")


class TearSheetData(BaseModel):
    schema_version: str = SCHEMA_VERSION
    generated_at: datetime
    ai_usage: Optional[AIUsage] = None
    research: Optional[ResearchBrief] = None
    forecast: Optional[HouseForecast] = None
    filing_facts: list[FilingFact] = Field(default_factory=list)
    deciding_year: Optional[DecidingYear] = None  # 1.12, run 4
    analyst_questions: Optional[AnalystQuestions] = None  # 1.12
    profile: Profile
    quote: Quote
    financials: Financials
    dupont: Optional[DuPont] = None
    earnings_quality: Optional[EarningsQuality] = None
    comps: Optional[Comps] = None
    benchmark: Optional[Benchmark] = None
    news: list[NewsItem] = []
    filings: list[FilingExcerpt] = []
    valuation: Optional[Valuation] = None
    narrative: Optional[Narrative] = None
    # 1.1: full report
    company: Optional[CompanyFacts] = None
    officers: list[Officer] = []
    segments: list[SegmentBreakdown] = []
    ownership: Optional[Ownership] = None
    consensus: Optional[Consensus] = None
    dividends: list[DividendYear] = []
    events: list[Event] = []
    ratios: list[RatioYear] = []
    technicals: Optional[Technicals] = None
    football_field: Optional[FootballField] = None
    pe_band: Optional[MultipleBand] = None
    audit: Optional[Audit] = None
    rating: Optional[Rating] = None
    announcements: list[Announcement] = Field(default_factory=list, description="Official filings, last 90 days")
    announcements_routine: int = Field(0, description="Routine filings left out (e.g. daily buyback returns)")
    # 1.5
    street: Optional[StreetView] = None
    scorecard: Optional[Scorecard] = None
    since_last: Optional[SinceLast] = None
    overall: Optional[OverallView] = None
    citations: list[Citation] = []
    sources: list[str] = []
    warnings: list[str] = Field(default_factory=list, description="Data gaps the reader should know about")


# 1.8: Valuation.scenarios refers to ScenarioSet, defined after Valuation
Valuation.model_rebuild()
TearSheetData.model_rebuild()
