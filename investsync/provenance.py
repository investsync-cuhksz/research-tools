"""Where every figure came from: records each data call made while building a report and turns
them into a numbered citation list (publisher, how it was accessed, link, when it was retrieved).

How it works
* ``start()`` opens a recording for one report build (a context variable, so concurrent API
  requests do not mix).
* The ``@cached`` decorator calls ``record()`` for every source function, whether the value came
  from the network or from the local cache; for cached values the retrieval time is the time the
  value was originally fetched.
* ``submit()`` / ``run_in_context()`` carry the recording into worker threads.
* ``citations()`` maps the recorded calls through ``REGISTRY`` (one entry per source function),
  adds the report excerpts (SEC EDGAR / HKEXnews / CNINFO) and the equity risk premium, and
  numbers them.

Rule for maintainers: every new external call must be a ``@cached`` function in data/sources.py
(or filings.py) with an entry in REGISTRY; tests fail if a recorded call has no entry.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import quote_plus

_records: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar("investsync_provenance", default=None)


@dataclass
class Record:
    fn: str
    args: tuple
    fetched_at: datetime
    from_cache: bool
    stale: bool = False  # the live call failed and an older copy was used (cache.py backup rule)


def start() -> list:
    rec: list = []
    _records.set(rec)
    return rec


def record(fn: str, args: tuple, fetched_at: float, from_cache: bool, stale: bool = False) -> None:
    rec = _records.get()
    if rec is not None:
        rec.append(Record(fn, args, datetime.fromtimestamp(fetched_at, tz=timezone.utc), from_cache, stale))


def stale_notes(records: list[Record]) -> list[str]:
    """Data notes for sources whose live call failed and whose older copy was used: one line per fetch day, so an
    outage of every source stays readable (each item's exact fetch time is in its citation)."""
    oldest: dict[str, datetime] = {}
    for r in records:
        if r.stale and (r.fn not in oldest or r.fetched_at < oldest[r.fn]):
            oldest[r.fn] = r.fetched_at
    by_day: dict = {}
    for fn, when in sorted(oldest.items(), key=lambda kv: kv[1]):
        by_day.setdefault(when.date(), []).append((REGISTRY[fn][1] if fn in REGISTRY else fn, when))
    out = []
    for day, items in by_day.items():
        if len(items) == 1:
            what, when = items[0]
            out.append(f"Live data unavailable: {what}. Used the copy fetched on {when:%-d %b %Y %H:%M} UTC.")
        else:
            out.append(f"Live data unavailable: {'; '.join(w for w, _ in items)}. Used the copies fetched on "
                       f"{day:%-d %b %Y} (times in the citations).")
    return out


def submit(pool, fn: Callable, *args, **kwargs):
    """``pool.submit`` that keeps the current recording (each task gets its own context copy)."""
    return pool.submit(contextvars.copy_context().run, fn, *args, **kwargs)


def wrap(fn: Callable) -> Callable:
    """Bind ``fn`` to a copy of the current context (for Thread targets / executor.map)."""
    ctx = contextvars.copy_context()
    return lambda *a, **k: ctx.copy().run(fn, *a, **k)


# ---------------------------------------------------------------- registry
EM_HK_F10 = "https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/index.html?code={code}&type=web&color=w"
EM_US_F10 = "https://emweb.securities.eastmoney.com/PC_USF10/pages/index.html?code={code}&type=web&color=w"
EM_CN_F10 = "https://emweb.securities.eastmoney.com/PC_HSF10/pages/index.html?type=web&code={em}&color=b"
YF = "https://finance.yahoo.com/quote/{sym}"


def _a(args: tuple, i: int, default: str = "") -> str:
    return str(args[i]) if len(args) > i else default


def _yf_url(args: tuple, page: str = "") -> str:
    return YF.format(sym=_a(args, 0)) + page


# fn qualname -> (topic, what, publisher, via, url(args))
REGISTRY: dict[str, tuple[str, str, Any, Any, Callable[[tuple], str]]] = {
    "price_history": ("prices", "Daily share prices and volume", None, None, None),
    "ah_names": ("prices", "Companies with A- and H-share listings", "EastMoney (东方财富) via AKShare",
                 "AKShare stock_zh_ah_name", lambda a: "https://quote.eastmoney.com/center/gridlist.html#ah_comparison"),
    "traded_range_1y": ("prices", "52-week high / low as traded (unadjusted daily prices)", "Sina Finance (新浪财经)",
                        "AKShare stock_hk_daily / stock_zh_a_daily, unadjusted", lambda a: "https://finance.sina.com.cn/"),
    "index_history": ("prices", "Benchmark index levels",
                      "Yahoo Finance (US) / Sina Finance (新浪财经; HK, A-shares), each the other's backup",
                      "AKShare stock_hk_index_daily_sina / stock_zh_index_daily / index_us_stock_sina",
                      lambda a: "https://finance.sina.com.cn/"),
    "fx_table": ("fx", "FX central parity rates", "State Administration of Foreign Exchange (SAFE) via Bank of China",
                 "AKShare currency_boc_safe", lambda a: "https://www.safe.gov.cn/"),
    "_yf_fx": ("fx", "Spot FX rate", "Yahoo Finance", "yfinance Ticker.fast_info",
               lambda a: YF.format(sym=_a(a, 0))),
    "_yf_fx_on": ("fx", "FX rate at the price date's close", "Yahoo Finance", "yfinance Ticker.history",
                  lambda a: YF.format(sym=_a(a, 0))),
    "yahoo_last_close": ("prices", "Peers' last finished close (their multiples are stated at it)", "Yahoo Finance",
                         "yfinance Ticker.history", lambda a: _yf_url(a, "/history")),
    "yf_info": ("market", "Quote, multiples, profile, management, ownership split, analyst targets",
                "Yahoo Finance", "yfinance Ticker.info", lambda a: _yf_url(a)),
    "yf_balance_sheet": ("statements", "Debt (US balance sheets)", "Yahoo Finance (from SEC filings)",
                         "yfinance Ticker.balance_sheet", lambda a: _yf_url(a, "/balance-sheet")),
    "yf_industry_top": ("peers", "Largest companies in the industry (peer candidates)", "Yahoo Finance",
                        "yfinance Industry.top_companies",
                        lambda a: f"https://finance.yahoo.com/sectors/ (industry {_a(a, 0)})"),
    "hk_statement": ("statements", "Annual income statement, balance sheet, cash flow (HKFRS/IFRS)",
                     "EastMoney (东方财富) F10, from company annual reports",
                     "AKShare stock_financial_hk_report_em", lambda a: EM_HK_F10.format(code=_a(a, 0))),
    "hk_indicators": ("statements", "Annual key indicators (revenue, profit, EPS)",
                      "EastMoney (东方财富) F10, from company annual reports",
                      "AKShare stock_financial_hk_analysis_indicator_em", lambda a: EM_HK_F10.format(code=_a(a, 0))),
    "hk_statement_periods": ("statements", "Interim / quarterly statements (HKFRS/IFRS)",
                             "EastMoney (东方财富) F10, from company interim and quarterly reports",
                             "AKShare stock_financial_hk_report_em (报告期)", lambda a: EM_HK_F10.format(code=_a(a, 0))),
    "hk_indicators_periods": ("statements", "Interim / quarterly key indicators (revenue, profit)",
                              "EastMoney (东方财富) F10, from company interim and quarterly reports",
                              "AKShare stock_financial_hk_analysis_indicator_em (报告期)",
                              lambda a: EM_HK_F10.format(code=_a(a, 0))),
    "hk_valuation": ("market", "Market cap, P/E, P/B, dividend yield (HK)", "EastMoney (东方财富)",
                     "AKShare stock_hk_financial_indicator_em", lambda a: EM_HK_F10.format(code=_a(a, 0))),
    "hk_company": ("profile", "Company profile (incorporation, founding date, chairman, employees)",
                   "EastMoney (东方财富) F10", "AKShare stock_hk_company_profile_em",
                   lambda a: EM_HK_F10.format(code=_a(a, 0))),
    "hk_industry_valuation": ("peers", "Industry P/E and P/B of HK peers", "EastMoney (东方财富) data centre",
                              "datacenter report RPT_PCF10_INDUSTRY_HKCVALUE",
                              lambda a: "https://datacenter.eastmoney.com/"),
    "hk_industry_scale": ("peers", "Industry members and market caps (HK)", "EastMoney (东方财富) data centre",
                          "datacenter report RPT_PCF10_INDUSTRY_SCALE", lambda a: "https://datacenter.eastmoney.com/"),
    "cn_statement": ("statements", "Annual income statement, balance sheet, cash flow (CAS)",
                     "Sina Finance (新浪财经), from company annual reports", "AKShare stock_financial_report_sina",
                     lambda a: f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/"
                               f"{_a(a, 0)[2:]}.phtml"),
    "cn_cashflow_em": ("statements", "Depreciation and amortisation (A-share cash flow statements)",
                       "EastMoney (东方财富), from company annual reports", "AKShare stock_cash_flow_sheet_by_yearly_em",
                       lambda a: f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?code={_a(a, 0)}"),
    "cn_valuation": ("market", "Market cap, P/E (TTM), P/B (A-shares)", "EastMoney (东方财富)",
                     "AKShare stock_value_em", lambda a: f"https://data.eastmoney.com/gzfx/detail/{_a(a, 0)}.html"),
    "cn_profile": ("profile", "Company profile (listing date, website, index membership)", "CNINFO (巨潮资讯)",
                   "AKShare stock_profile_cninfo",
                   lambda a: f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={_a(a, 0)}"),
    "cn_dividends": ("dividends", "Dividends and bonus issues (A-shares)", "EastMoney (东方财富)",
                     "AKShare stock_fhps_detail_em",
                     lambda a: f"https://data.eastmoney.com/yjfp/detail/{_a(a, 0)}.html"),
    "cn_peer_comparison": ("peers", "Industry valuation comparison (A-shares)", "EastMoney (东方财富) F10",
                           "AKShare stock_zh_valuation_comparison_em", lambda a: EM_CN_F10.format(em=_a(a, 0))),
    "us_statement": ("statements", "Annual income statement, balance sheet, cash flow (US GAAP)",
                     "EastMoney (东方财富) F10, from SEC filings", "AKShare stock_financial_us_report_em",
                     lambda a: EM_US_F10.format(code=_a(a, 0))),
    "us_statement_ytd": ("statements", "Year-to-date quarterly statements (US GAAP)",
                         "EastMoney (东方财富) F10, from SEC 10-Q filings", "AKShare stock_financial_us_report_em (累计季报)",
                         lambda a: EM_US_F10.format(code=_a(a, 0))),
    "us_indicators_quarterly": ("statements", "Quarterly key indicators (US)", "EastMoney (东方财富) F10, from SEC 10-Q filings",
                                "AKShare stock_financial_us_analysis_indicator_em (quarterly)",
                                lambda a: EM_US_F10.format(code=_a(a, 0))),
    "yf_quarterly_balance_sheet": ("statements", "Debt at the latest quarter end (US)", "Yahoo Finance (from SEC filings)",
                                   "yfinance Ticker.quarterly_balance_sheet", lambda a: _yf_url(a, "/balance-sheet")),
    "us_indicators": ("statements", "Annual key indicators (US)", "EastMoney (东方财富) F10, from SEC filings",
                      "AKShare stock_financial_us_analysis_indicator_em", lambda a: EM_US_F10.format(code=_a(a, 0))),
    "bond_yields": ("rates", "10-year government bond yields (China, US)",
                    "ChinaBond (中债) and US Treasury, compiled by EastMoney", "AKShare bond_zh_us_rate",
                    lambda a: "https://data.eastmoney.com/cjsj/zmgzsyl.html"),
    "us10y_yahoo": ("rates", "US 10-year Treasury yield (backup when EastMoney lacks it)",
                    "Cboe 10-year Treasury yield index (^TNX), via Yahoo Finance", "yfinance Ticker.history",
                    lambda a: YF.format(sym="%5ETNX")),
    "yf_revenue_estimates": ("consensus", "Analyst consensus revenue", "Yahoo Finance (analyst estimates)",
                             "yfinance Ticker.revenue_estimate", lambda a: _yf_url(a, "/analysis")),
    "yf_earnings_estimate": ("consensus", "Analyst consensus EPS", "Yahoo Finance (analyst estimates)",
                             "yfinance Ticker.earnings_estimate", lambda a: _yf_url(a, "/analysis")),
    "yf_eps_trend": ("consensus", "Consensus EPS now and 7-90 days ago", "Yahoo Finance (analyst estimates)",
                     "yfinance Ticker.eps_trend", lambda a: _yf_url(a, "/analysis")),
    "yf_option_straddle": ("market", "At-the-money option prices for the first expiry after results",
                           "Yahoo Finance (US listed options)", "yfinance Ticker.option_chain",
                           lambda a: _yf_url(a, "/options")),
    "yf_recommendations": ("consensus", "Analyst rating counts", "Yahoo Finance (analyst estimates)",
                           "yfinance Ticker.recommendations", lambda a: _yf_url(a, "/analysis")),
    "yf_dividends": ("dividends", "Dividend history (per share, by ex-date)", "Yahoo Finance",
                     "yfinance Ticker.dividends", lambda a: _yf_url(a, "/history")),
    "yf_next_earnings": ("events", "Next results date", "Yahoo Finance", "yfinance Ticker.calendar",
                         lambda a: _yf_url(a)),
    "yf_news": ("news", "English news headlines", "Yahoo Finance (publishers named per item)",
                "yfinance Ticker.get_news", lambda a: _yf_url(a, "/news")),
    "news": ("news", "Chinese news headlines", "EastMoney (东方财富) news search (publishers named per item)",
             "AKShare stock_news_em", lambda a: f"https://so.eastmoney.com/news/s?keyword={_a(a, 0)}"),
    "em_segments": ("segments", "Revenue by product / business and region", "EastMoney (东方财富) F10, from annual reports",
                    "AKShare stock_zygc_em / datacenter RPT_*_INFO_*STRUCTURE",
                    lambda a: "https://emweb.securities.eastmoney.com/"),
    "hk_holders": ("ownership", "Directors' and substantial shareholders' interests",
                   "HKEX Disclosure of Interests, compiled by EastMoney", "datacenter report RPT_HKF10_EQUITYCHG_HOLDER",
                   lambda a: "https://di.hkex.com.hk/"),
    "hk_interest_changes": ("ownership", "Disclosure-of-interest notices (changes)",
                            "HKEX Disclosure of Interests, compiled by EastMoney", "datacenter report RPT_HKF10_SH_EQUITYCHG",
                            lambda a: "https://di.hkex.com.hk/"),
    "cn_top_holders": ("ownership", "Top-10 shareholders", "Company periodic reports, compiled by EastMoney",
                       "AKShare stock_gdfx_top_10_em", lambda a: "https://data.eastmoney.com/gdfx/"),
    "cn_holder_trades": ("ownership", "Major-shareholder increases and decreases",
                         "Company announcements, compiled by EastMoney", "datacenter report RPT_SHARE_HOLDER_INCREASE",
                         lambda a: "https://data.eastmoney.com/executive/gdzjc.html"),
    "yf_holders": ("ownership", "Institutional holders (13F) and insider transactions (Form 4)",
                   "Yahoo Finance, from SEC filings", "yfinance Ticker.institutional_holders / insider_transactions",
                   lambda a: _yf_url(a, "/holders")),
    "finnhub_news": ("news", "English company news, fetched week by week",
                     "Finnhub (aggregating Yahoo, Seeking Alpha, Benzinga, CNBC and others; publisher named per item)",
                     "Finnhub API /company-news", lambda a: f"https://finnhub.io/docs/api/company-news (symbol {_a(a, 0)})"),
    "sec_recent_filings": ("announcements", "Official filings (8-K, 10-Q, 10-K, proxy, ownership)", "SEC EDGAR",
                           "submissions API (data.sec.gov)",
                           lambda a: f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={_a(a, 0)}"),
    "hkex_announcements": ("announcements", "Exchange announcements and notices", "HKEXnews (HKEX)",
                           "title search API", lambda a: "https://www1.hkexnews.hk/search/titlesearch.xhtml"),
    "cninfo_announcements": ("announcements", "Company announcements (公告)", "CNINFO (巨潮资讯)",
                             "AKShare stock_zh_a_disclosure_report_cninfo",
                             lambda a: f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={_a(a, 0)}"),
    "em_research_reports": ("research", "Broker research reports: rating, EPS forecasts, price targets",
                            "Brokers named per report, listed by EastMoney (东方财富) research centre",
                            "reportapi.eastmoney.com/report/list",
                            lambda a: f"https://data.eastmoney.com/report/singlestock.jshtml?stockcode={_a(a, 0)}"),
    "em_report_abstract": ("research", "Broker report summaries (each broker's own abstract) and PDF links",
                           "Brokers named per report, hosted by EastMoney (东方财富)", "report page (data.eastmoney.com)",
                           lambda a: f"https://data.eastmoney.com/report/info/{_a(a, 0)}.html"),
    "etnet_hk_forecasts": ("research", "HK broker ratings, price targets and profit forecasts",
                           "Brokers named per row, compiled by etnet (经济通)", "quote_profit page, parsed with pandas.read_html",
                           lambda a: f"https://www.etnet.com.hk/www/sc/stocks/realtime/quote_profit.php?code={_a(a, 0).lstrip('0')}"),
    "aastocks_news_list": ("research", "Broker-note headlines (《大行》) tagged to the stock",
                           "AAStocks (阿斯达克)", "stock news feed (getmorenews)",
                           lambda a: f"https://www.aastocks.com/sc/stocks/analysis/stock-aafn/{_a(a, 0)}/0/hk-stock-news/1"),
    "aastocks_article": ("research", "News write-ups of broker notes (argument, forecast changes, target)",
                         "Brokers named per article, written up by AAStocks (阿斯达克)", "article page",
                         lambda a: f"https://www.aastocks.com/sc/stocks/analysis/stock-aafn-con/{_a(a, 0)}/"
                                   f"{_a(a, 2) or 'AAFN'}/{_a(a, 1)}/hk-stock-news"),
    "yf_analyst_actions": ("research", "Analyst rating actions and price-target changes",
                           "Brokers named per action, compiled by Yahoo Finance", "yfinance Ticker.upgrades_downgrades",
                           lambda a: _yf_url(a, "/analysis")),
    "_sec_cik_map": ("filings", "SEC company index", "SEC EDGAR", "company_tickers.json",
                     lambda a: "https://www.sec.gov/files/company_tickers.json"),
    "company_facts": ("statements", "Balance-sheet cash, marketable securities and debt (XBRL company facts)",
                      "SEC EDGAR, from the company's 10-K / 10-Q", "companyfacts API",
                      lambda a: f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(_a(a, 0) or 0):010d}.json"),
    "us_statement_facts": ("statements", "Annual income statement, balance sheet, cash flow (US GAAP; backup when "
                           "EastMoney is unavailable)", "SEC EDGAR, from the company's 10-K filings", "companyfacts API",
                           lambda a: f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(_a(a, 0) or 0):010d}.json"),
    "us_filing_concepts": ("statements", "Buybacks, dividends, investment gains, commitments and guarantees as filed "
                           "(XBRL company facts)", "SEC EDGAR, from the company's 10-K / 10-Q", "companyfacts API",
                           lambda a: f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(_a(a, 0) or 0):010d}.json"),
    "_hkex_stock_id": ("filings", "HKEXnews stock id", "HKEXnews", "title search API",
                       lambda a: "https://www1.hkexnews.hk/search/titlesearch.xhtml"),
    "latest_filings": ("filings", "Latest annual / interim report (section excerpts)", None, None, None),
    # research/sources.py: full-text documents for the research step
    "sec_filing_index": ("announcements", "Filing indexes (which exhibit is the earnings release / commentary)",
                         "SEC EDGAR", "EDGAR Archives filing index",
                         lambda a: f"https://www.sec.gov/Archives/edgar/data/{_a(a, 0)}/{_a(a, 1).replace('-', '')}/"
                                   f"{_a(a, 1)}-index.htm"),
    "sec_document": ("announcements", "Earnings releases, CFO commentary and material 8-Ks (full text)", "SEC EDGAR",
                     "EDGAR Archives (direct download)", lambda a: _a(a, 0)),
    "hkex_document": ("announcements", "Results announcement and material announcements (full text)",
                      "HKEXnews (HKEX)", "direct download", lambda a: _a(a, 0)),
    "cninfo_document": ("announcements", "Periodic report, investor-relations records and material announcements "
                        "(full text)", "CNINFO (巨潮资讯)", "direct PDF download", lambda a: _a(a, 0)),
    "cninfo_ir_records": ("announcements", "Investor-relations activity records (投资者关系活动记录表)", "CNINFO (巨潮资讯)",
                          "AKShare stock_zh_a_disclosure_relation_cninfo",
                          lambda a: f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={_a(a, 0)}"),
    "em_report_text": ("research", "Broker research reports (full text)",
                       "Brokers named per report, hosted by EastMoney (东方财富)", "PDF download (pdf.dfcfw.com)",
                       lambda a: f"https://pdf.dfcfw.com/pdf/H3_{_a(a, 0)}_1.pdf"),
    "bing_news_rss": ("news", "News search results (headline, publisher, date, summary)",
                      "Bing News (publishers named per item)", "Bing News RSS search",
                      lambda a: f"https://www.bing.com/news/search?q={quote_plus(_a(a, 0))}"),
    "web_text": ("news", "News articles and web pages (full text)", "Publishers named per article",
                 "direct download", lambda a: _a(a, 0)),
}

TOPIC_ORDER = ["statements", "market", "prices", "fx", "rates", "consensus", "peers", "profile", "segments",
               "ownership", "dividends", "events", "announcements", "research", "news", "filings", "assumptions"]


def _price_like(fn: str, args: tuple, attrs_source: Optional[str]) -> tuple[str, str, str]:
    market, code = _a(args, 0), _a(args, 1)
    if fn == "price_history":
        afn = {"HK": "stock_hk_daily", "CN": "stock_zh_a_daily", "US": "stock_us_daily"}.get(market, "")
        us = market not in ("HK", "CN")
        if attrs_source == "yahoo":  # US: Yahoo first since 12 Nov 2026; HK / A-shares: Sina failed
            return ("Yahoo Finance" if us else "Yahoo Finance (Sina unreachable)"), "yfinance Ticker.history", \
                YF.format(sym=code)
        if attrs_source and attrs_source.startswith("yahoo"):  # run 3: Sina's file was a session behind
            return "Yahoo Finance (newer than Sina's file)", "yfinance Ticker.history", YF.format(sym=code)
        return (("Sina Finance (新浪财经; Yahoo unreachable)" if us else "Sina Finance (新浪财经)"),
                f"AKShare {afn} (forward-adjusted)", "https://finance.sina.com.cn/")
    return "", "", ""


INDEX_VIA = {"HK": "AKShare stock_hk_index_daily_sina (Hang Seng Index)",
             "CN": "AKShare stock_zh_index_daily (CSI 300)", "US": "AKShare index_us_stock_sina (S&P 500)"}


def citations(records: list[Record], data, price_sources: Optional[dict[str, str]] = None) -> list:
    """Numbered citations for one report, one per (topic, publisher, access method).

    The link points at this company's own page where one exists; calls for peer companies are
    counted in the description. ``price_sources``: {"price_history": "sina"|"yahoo", ...}.
    """
    from .schema import Citation

    p = data.profile
    tokens = {p.ticker, p.ticker.split(".")[0], p.ticker.split(".")[0].zfill(5), p.ticker.replace(".SH", ".SS")}
    groups: dict[tuple, dict] = {}

    def add(topic, what, publisher, via, url, when):
        g = groups.setdefault((topic, publisher, via), {"what": what, "urls": [], "when": None})
        if url not in g["urls"]:
            g["urls"].append(url)
        if when and (g["when"] is None or when < g["when"]):
            g["when"] = when  # oldest retrieval within the group

    for r in records:
        if r.fn not in REGISTRY or r.fn == "latest_filings":
            continue  # filings are cited per document below
        topic, what, pub, via, url = REGISTRY[r.fn]
        if r.fn == "price_history":
            pub, via, url = _price_like(r.fn, r.args, (price_sources or {}).get("price_history"))
        elif r.fn == "index_history":
            us = _a(r.args, 0) not in ("HK", "CN")
            if (price_sources or {}).get("index_history") == "yahoo":
                pub, via = ("Yahoo Finance" if us else "Yahoo Finance (Sina unreachable)"), "yfinance Ticker.history"
                url = "https://finance.yahoo.com/quote/%5EGSPC/history" if us else "https://finance.yahoo.com/"
            else:
                pub, via = "Sina Finance (新浪财经)", INDEX_VIA.get(_a(r.args, 0), via)
                url = "https://finance.sina.com.cn/"
        else:
            url = url(r.args)
        add(topic, what, pub, via, url, r.fetched_at)

    for f in getattr(data, "filings", []) or []:
        add("filings", f"{f.title} (excerpts: {', '.join(f.sections)})", f.source,
            "direct download, sections located by heading", f.url, None)
    if getattr(data, "valuation", None):
        v = data.valuation
        add("assumptions", f"Equity risk premium {v.wacc.equity_risk_premium:.2%} ({v.wacc.erp_source})",
            "Aswath Damodaran, NYU Stern (country risk premiums)", "house valuation settings (finance team)",
            "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ctryprem.html", None)

    out = []
    for (topic, publisher, via), g in groups.items():
        urls = g["urls"]
        own = [u for u in urls if any(t and t in u for t in tokens)]
        url = (own or urls)[0]
        others = len(urls) - 1
        what = g["what"] + (f" (also for {others} peer {'company' if others == 1 else 'companies'})"
                            if others and topic in ("market", "profile", "dividends", "peers") else "")
        out.append(Citation(n=0, topic=topic, what=what, publisher=publisher, via=via, url=url, retrieved=g["when"]))
    out.sort(key=lambda c: (TOPIC_ORDER.index(c.topic) if c.topic in TOPIC_ORDER else 99, c.publisher))
    for i, c in enumerate(out, 1):
        c.n = i
    return out


def unregistered(records: list[Record]) -> list[str]:
    return sorted({r.fn for r in records if r.fn not in REGISTRY})
