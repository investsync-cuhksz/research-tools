"""Research desk: the reading an analyst does before writing, done by a cheap model and checked in code.

Why: the blind reviews of 8 Nov 2026 marked the DeepSeek reports down mainly for missing current information
(guidance, policy changes, major events, the causes of the latest results) that the Opus analysts found by reading
results releases, announcements and news. This step does that reading with free sources and DeepSeek flash:

1. Plan (one call): the fixed analyst checklist (TOPICS) plus up to five company-specific questions and up to six
   news searches (perspective-guided question asking, as in Stanford's STORM).
2. Collect (code, ``research.sources``): results releases and commentary, announcements, the latest periodic
   report, investor-relations records, broker reports (A-shares) and news search results.
3. Read (one cheap call per excerpt, in parallel): excerpts ranked by keyword relevance to the questions; the
   model returns facts, each with a verbatim quote.
4. Verify (code): the quote must be found in the excerpt and every figure in the fact must appear in the quote
   (Chinese 亿/万 amounts are converted in code first). Anything else is dropped (grounding in the spirit of
   Chain-of-Verification: check each claim on its own against its source).
5. Brief (code): de-duplicated, grouped by topic, primary sources and newest first, ids R1..Rn, gaps listed.

The facts are evidence for the commentary. They never feed the rating, which stays rule-based.
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Literal, Optional

import dspy
from pydantic import BaseModel, Field, field_validator

from .. import provenance
from ..cache import get_cache
from ..config import settings
from ..narrative import guardrail
from ..schema import Market, ResearchBrief, ResearchFact, TearSheetData
from ..tickers import Ticker

log = logging.getLogger(__name__)

# topic -> (question, keywords used to rank excerpts; English and Chinese)
TOPICS: dict[str, tuple[str, list[str]]] = {
    # round-4/5 reviews: the notes quoted the previous quarter's opex guide as current and missed the company's
    # multi-year outlook (NVIDIA: ~70% growth next fiscal year) and a 28 Sep buyback increase; ask for them
    "guidance": ("What is management's LATEST guidance for the next quarter (revenue, gross margin, operating "
                 "expenses) and its outlook for the next fiscal year and beyond, with the date each was given; how "
                 "did earlier guidance compare with what was reported?",
                 ["outlook", "guidance", "expect", "forecast", "target", "anticipate", "next quarter", "full year",
                  "next fiscal", "operating expenses", "gross margin", "tax rate", "trough", "bottom", "low point",
                  "展望", "预计", "指引", "目标", "计划", "预期", "毛利率"]),
    "results": ("What drove the latest reported results (segments, price, volume, mix, costs), and how did they "
                "compare with expectations?",
                ["revenue", "segment", "increase", "decrease", "driven", "due to", "primarily", "compared",
                 "year-on-year", "quarter", "营业收入", "同比", "增长", "下降", "主要", "原因", "毛利率", "变动"]),
    # round-5 review, "what a top-tier note would contain": a demand build (order book, customers' capex, revenue per
    # unit of capacity) and credit work on customer financing (guarantees, vendor financing, concentration)
    "demand": ("What do management and the largest customers say about future demand: order book, backlog or "
               "bookings, supply constraints, customers' capex plans, revenue per unit of capacity, customer "
               "concentration, and any financing, guarantees or investments the company provides to its customers?",
               ["backlog", "order book", "bookings", "orders", "supply-constrained", "supply constrained",
                "visibility", "capex", "gigawatt", "per unit", "customer concentration", "largest customer",
                "financing", "guarantee", "commitment", "在手订单", "订单", "积压", "需求", "产能", "客户集中",
                "前五大客户", "融资", "担保"]),
    "quality": ("Are earnings flattered or depressed by one-offs: investment gains, impairments, non-GAAP or "
                "non-IFRS adjustments, working-capital swings?",
                ["non-gaap", "non-ifrs", "one-off", "impairment", "gain", "fair value", "adjusted", "working capital",
                 "receivable", "inventor", "非经常性", "减值", "公允价值", "投资收益", "应收", "存货"]),
    "policy": ("Which government policies, taxes, subsidies, export controls or regulations changed recently, "
               "and how do they affect the company?",
               ["policy", "tax", "tariff", "export", "regulat", "ban", "licen", "subsid", "rebate", "antitrust",
                "政策", "消费税", "退税", "关税", "出口", "监管", "补贴", "管制"]),
    "events": ("What major corporate events happened in the last four months (acquisitions, bond issues, "
               "guarantees, buyback authorisations and how much remains, dividends, management changes, "
               "investigations, lawsuits)?",
               ["acqui", "notes due", "bond", "guarant", "repurchase", "buy-back", "buyback", "authoriz", "authoris",
                "dividend", "appoint", "resign", "investigat", "probe", "litigation", "收购", "债券", "担保", "回购",
                "分红", "任命", "辞职", "调查", "诉讼", "发行"]),
    "capital": ("What are the capex and investment plans, and how are they funded?",
                ["capital expenditure", "capex", "investment", "capacity", "funding", "purchase commitment",
                 "资本开支", "资本支出", "投资", "产能", "融资", "扩产"]),
    "competition": ("What is changing in competition, market share, pricing and customers?",
                    ["competit", "market share", "pricing", "price", "customer", "demand", "竞争", "份额",
                     "市占率", "价格", "客户", "需求"]),
    "street": ("Why has the share price moved recently, and what are brokers and the press debating?",
               ["shares", "stock", "analyst", "rating", "price target", "downgrade", "upgrade", "investors",
                "股价", "评级", "目标价", "下调", "上调", "投资者"]),
    "catalysts": ("Which dated events are coming up (results dates, product launches, policy dates, meetings)?",
                  ["will", "upcoming", "scheduled", "launch", "expected to", "effective", "from 1", "将于", "发布",
                   "推出", "召开", "起实施", "生效"]),
}
TOPIC_ORDER = list(TOPICS)
PRIMARY = {"results_release", "results_commentary", "periodic_report", "announcement", "ir_record", "transcript"}
RESULTS_KINDS = ("results_release", "results_commentary", "periodic_report")
CALL_KINDS = ("transcript", "call_summary")
COMPANY_KINDS = PRIMARY | {"call_summary"}  # documents whose statements are the company's own
KIND_BONUS = {"results_commentary": 4.0, "results_release": 4.0, "periodic_report": 2.5, "ir_record": 3.0,
              "broker_report": 2.5, "announcement": 1.5, "news": 1.0}
PER_DOC_CHUNKS = {"results_commentary": 8, "results_release": 8, "periodic_report": 5, "ir_record": 4,
                  "broker_report": 3, "announcement": 2, "news": 1}
CHUNK_CHARS = {"en": 7000, "zh": 3600}  # ~2k tokens either way
MAX_FACTS = int(__import__('os').getenv('RESEARCH_MAX_FACTS', '64'))  # run 4: RESEARCH_MAX_FACTS=90
PER_TOPIC = int(__import__('os').getenv('RESEARCH_PER_TOPIC', '9'))
_CJK = re.compile(r"[\u4e00-\u9fff]")


# ---------------------------------------------------------------- AI signatures
class SearchQuery(BaseModel):
    query: str = Field(description="A short keyword query, as typed into a news search")
    lang: str = Field(description="en or zh")


class PlanResearch(dspy.Signature):
    """You are the research lead preparing an equity analyst's reading list for the company below.

    The standard checklist is always covered. Add up to 5 extra questions specific to this company right now:
    what a buy-side portfolio manager, a credit analyst, an industry specialist and a sceptical accountant would
    each ask (for example a new tax on its main product, a large customer's financing, a pending acquisition, a
    product transition). Then write up to 6 news search queries, short keywords as a professional would type
    them: in English, and also in Chinese for companies listed in Hong Kong or mainland China. Use the company's
    common name; cover guidance and results reaction, policy, major deals and the main debate. Do not write
    figures or dates you are not given."""
    company: str = dspy.InputField()
    business: str = dspy.InputField()
    situation: str = dspy.InputField(desc="Key facts: price move, latest results, valuation context")
    checklist: str = dspy.InputField()
    documents: str = dspy.InputField(desc="Documents already collected (titles)")
    extra_questions: list[str] = dspy.OutputField()
    queries: list[SearchQuery] = dspy.OutputField()


class Extracted(BaseModel):
    questions: list[int] = Field(description="Numbers of the questions this fact answers")
    importance: int = Field(2, description="1 = an investor must know it (guidance, a policy hitting profit, the "
                                           "cause of a results change, a major deal); 2 = useful; 3 = minor detail "
                                           "or boilerplate")
    about_company: bool = Field(True, description="True only if the fact is about the company named in `company` "
                                                  "(or directly about its customers, competitors or policies in "
                                                  "relation to it); false for news about another company")
    fact: str = Field(description="One specific English sentence with the period and figures as written")
    quote: str = Field(description="The exact words from the excerpt that support the fact, copied verbatim")
    label: str = Field("", description="3 to 8 words that name the specific event or item for a reader, using the names the "
                                   "text gives and no figures (e.g. \"Board probe of CEO Jane Smith\", "
                                   "\"Next-quarter revenue guidance\")")
    # run 2: press notes of what management said on the results call were called "not company guidance" (run 1)
    said_by: Literal["company", "broker", "press", "other"] = Field(
        "other", description="Who made the statement. company = a statement, guidance or forecast made by the company "
                             "or its management (in a filing, a release or on a call), or an action the company "
                             "announced, even when the excerpt is a press article that reports it; broker = an "
                             "analyst's or broker's view; press = the journalist's own reporting or analysis; other = "
                             "anyone else")

    @field_validator("said_by", mode="before")
    @classmethod
    def _said_by(cls, v):
        """A reply outside the four values must not lose the excerpt's facts: map it, else 'other'."""
        s = str(v or "").strip().lower()
        if s in ("company", "management", "the company", "issuer", "executive", "executives", "ceo", "cfo"):
            return "company"
        if s in ("broker", "analyst", "analysts", "brokers", "bank"):
            return "broker"
        if s in ("press", "media", "journalist", "news", "reporter"):
            return "press"
        return "other"


class ExtractFacts(dspy.Signature):
    """You are an equity research associate reading one excerpt of a document about the company. Extract the
    facts that answer any of the numbered questions.

    Rules:
    - Only what the excerpt says. Never add outside knowledge and never infer a cause the text does not state.
    - fact: one English sentence, specific, with the period or date and the figures exactly as written in the
      excerpt (same units and currency). Amounts written in 亿 or 万 are followed by their conversion in
      brackets: use the bracketed bn / mn value. Say whose view or forecast it is ("management expects ...",
      "Citi says ...", "the company attributes ... to ..."). Translate Chinese into English.
    - Be specific about who and what: name the people (with their role), companies, products, regulators and
      places exactly as the excerpt names them ("CFO Jane Smith resigned", not "an executive left"; "the Commerce
      Department's new export rule", not "new rules"). Never add a name the excerpt does not give.
    - Keep the subject: say whose prices, costs or plans a statement is about (prices the company pays for memory
      are a cost to it, not its own pricing).
    - A rule, ban or situation that the excerpt describes as already in place is background, not news: write it
      as "Existing ... rules bar ...", never as something announced now. Give an event's date only if the excerpt
      states when it happened.
    - label: 3 to 8 words naming the event or item for a reader, with the same names and no figures.
    - quote: copy the supporting words from the excerpt exactly, character for character, one contiguous
      passage of at most 300 characters (you may join two passages with "..."). Never paraphrase the quote.
    - questions: the question numbers the fact answers.
    - Skip boilerplate (forward-looking-statement disclaimers, accounting policies, legal notices), anything
      not about the company, its industry or policies affecting it, and facts older than the document's
      main period unless they are guidance or a comparison.
    - News pages often carry stories about other companies: a fact about another company's own results, guidance
      or deals is not about this company (about_company = false) unless the excerpt ties it to this company.
    - Management's outlook for the NEXT fiscal year (preliminary or long-range guidance, often given on the
      earnings call) is importance 1. Give each guided item as its own fact: revenue, gross margin (including an
      expected low point or range later this year or next year), operating expenses, other income and the tax
      rate. If the excerpt says when or where management gave it (e.g. on the results call of a given date),
      state that date rather than the article's.
    - importance: 1 only for what would change an investor's view; procedural details (approval votes, validity
      periods, shareholder-relationship disclaimers) are 3 and usually not worth extracting.
    - said_by: company = a statement, guidance or forecast made by the company or its management (in a filing, a
      release or on a call), even when the excerpt is a press article that reports it ("the CFO said on the call",
      "the board authorised", "the company announced"); broker = an analyst's or broker's view; press = the
      journalist's own reporting or analysis; other = anyone else (governments, customers, competitors).
    - At most 8 facts, the most decision-relevant first. Return an empty list if nothing is relevant."""
    company: str = dspy.InputField()
    questions: str = dspy.InputField()
    document: str = dspy.InputField(desc="Title, source and date of the document")
    excerpt: str = dspy.InputField()
    facts: list[Extracted] = dspy.OutputField()


# ---------------------------------------------------------------- key facts (whole latest results documents)
# Round-8 review (9 Nov 2026): reading the results documents excerpt by excerpt lost the quarter's key items (the
# commitments table, the half-year investment gains, the next-year outlook) to per-topic caps and chunk ranking, and
# an older quarter's figure was quoted as current. DeepSeek reads 1M tokens, so one cheap call now reads the latest
# results documents whole against a fixed checklist; what it finds is kept ahead of every other note, and what it
# does not find is listed as "not stated" so the writers say so instead of guessing.
KEY_ITEMS: dict[str, tuple[str, str]] = {  # key -> (checklist line, research topic)
    "guidance": ("Management's guidance for the next quarter: each guided line as its own fact (revenue, gross "
                 "margin, operating expenses, other income, tax rate) with its range", "guidance"),
    "outlook": ("Management's outlook for the full current fiscal year and for the next fiscal year or beyond "
                "(growth, margins, capex), with when and where it was given", "guidance"),
    "segments": ("Revenue of each reported segment, platform or market in the latest quarter, with its "
                 "year-on-year and quarter-on-quarter change", "results"),
    "drivers": ("What management says drove the latest quarter's revenue and margin changes", "results"),
    "customers": ("Customer concentration: the share of revenue or receivables from the largest customers", "demand"),
    "commitments": ("Purchase, supply or capacity commitments, guarantees and other obligations not on the balance "
                    "sheet at the latest period end, with the previous period's figure where given", "demand"),
    "investment_gains": ("Gains or losses on investments and fair-value changes in the latest quarter and in the year "
                         "to date", "quality"),
    "capital_return": ("Share buybacks and dividends in the latest quarter and year to date, the buyback "
                       "authorisation remaining, and any change to the dividend", "events"),
    "accounting": ("Changes to accounting policies, segment definitions or the non-GAAP / adjusted measures, and "
                   "restatements of earlier periods", "quality"),
    "funding": ("Debt issued or repaid in the period; cash and investments at the period end", "capital"),
    "one_offs": ("Impairments, write-downs, legal, tax or other one-off items in the period", "quality"),
}
KEY_CHARS = {"en": 420_000, "zh": 260_000}  # ~100-170k tokens in total, about CNY 0.1-0.2 at flash prices


class KeyFact(BaseModel):
    item: str = Field(description="The checklist key this fact answers, e.g. guidance or commitments")
    fact: str = Field(description="One specific English sentence with the period or date and the figures exactly as "
                                  "written (same units and currency)")
    quote: str = Field(description="The exact supporting words from the document, copied verbatim (at most 300 "
                                   "characters; two passages may be joined with ...)")
    document: int = Field(description="The number of the document the quote comes from")
    label: str = Field("", description="3 to 8 words that name the specific event or item for a reader, using the names the "
                                   "text gives and no figures (e.g. \"Board probe of CEO Jane Smith\", "
                                   "\"Next-quarter revenue guidance\")")


class ReadResults(dspy.Signature):
    """You are an equity research associate reading the company's latest results documents in full (the results
    release, the management or CFO commentary, or the periodic report, and the earnings call: a transcript or a press
    summary of the call). Go through the checklist and extract every fact the documents state for each item.

    Rules:
    - Only what the documents say; never add outside knowledge or infer a figure. If the documents do not state an
      item, give no fact for it. Never use a figure from an earlier period as the current one: when a document gives
      the current and an earlier figure (e.g. commitments now and a quarter ago), state both with their dates.
    - Give each guided or reported line as its own fact (e.g. revenue guidance, gross-margin guidance and the tax-rate
      guidance are three facts). Say whose statement it is ("management expects ...") and the period it covers.
    - Amounts written in 亿 or 万 are followed by their conversion in brackets: use the bracketed bn / mn value.
      Translate Chinese into English.
    - quote: copied character for character from the document, one passage of at most 300 characters (two passages
      may be joined with "..."). Never paraphrase it.
    - A press summary of the earnings call: what it attributes to management (the CEO, the CFO, "the company") is
      company guidance given on that call; state it as "management said on the call ...". Skip the article's own
      comments and analysts' views.
    - At most 40 facts, the most decision-relevant first within each item."""
    company: str = dspy.InputField()
    checklist: str = dspy.InputField()
    documents: str = dspy.InputField(desc="Numbered documents: [n] title | source | date, then the full text")
    facts: list[KeyFact] = dspy.OutputField()


def latest_results_date(docs: list) -> Optional[date]:
    """Date of the newest results document (release, commentary or periodic report; not the previous quarter's)."""
    ds = [d.published for d in docs or [] if getattr(d, "kind", "") in RESULTS_KINDS and getattr(d, "published", None)
          and "previous quarter" not in (getattr(d, "title", "") or "")]
    return max(ds) if ds else None


def latest_results_docs(docs: list) -> list:
    """The newest round of results documents (release + commentary, or the periodic report), not the previous
    quarter's, plus that quarter's earnings-call transcript when one was found, else up to two press summaries of
    the call."""
    cands = [d for d in docs if d.kind in RESULTS_KINDS and "previous quarter" not in (d.title or "") and (d.text or "")]
    if not cands:
        return []
    newest = max((d.published or date.min) for d in cands)
    same = [d for d in cands if (d.published or date.min) >= newest - timedelta(days=7)]
    same.sort(key=lambda d: RESULTS_KINDS.index(d.kind))
    calls = [d for d in docs if d.kind == "transcript" and d.published and
             newest - timedelta(days=3) <= d.published <= newest + timedelta(days=14)]
    calls.sort(key=lambda d: -len(d.text or ""))
    summaries = [d for d in docs if d.kind == "call_summary" and d.published and (d.text or "") and
                 newest - timedelta(days=1) <= d.published <= newest + timedelta(days=CALL_SUMMARY_DAYS)]
    summaries.sort(key=lambda d: -len(d.text or ""))
    return same[:3] + (calls[:1] or summaries[:2])


# Rounds 6 and 8: management's outlook for the next fiscal year was given on the earnings call (not in the release)
# and the notes missed it both times. Transcripts published as news articles (e.g. The Motley Fool's, syndicated by
# Yahoo Finance and Nasdaq) are found by the "earnings call transcript" search and read whole with the results.
TRANSCRIPT = re.compile(r"earnings call transcript|conference call transcript|call transcript|业绩会实录|电话会实录|"
                        r"业绩说明会", re.I)
TRANSCRIPT_CHARS = 160_000


def _fool_urls(title: str, day: Optional[date]) -> list[str]:
    """The Motley Fool publishes transcripts as "<Name> (<TICKER>) Q2 2027 Earnings Call Transcript" and syndicates
    them (Yahoo Finance, AOL, Nasdaq, The Globe and Mail) under the same title, often cut to a teaser; the original's
    address follows from the title and the date."""
    if not day:
        return []
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
                  ).strip("-")
    return [f"https://www.fool.com/earnings/call-transcripts/{day + timedelta(days=k):%Y/%m/%d}/{slug}/"
            for k in (0, -1, 1)]


_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_PATTERNS = [
    (re.compile(r"\b" + _MON + r"\s+(\d{1,2}),?\s+(20\d\d)\b", re.I),
     lambda m: (int(m[3]), _month(m[1]), int(m[2]))),
    (re.compile(r"\b(\d{1,2})\s+" + _MON + r",?\s+(20\d\d)\b", re.I),
     lambda m: (int(m[3]), _month(m[2]), int(m[1]))),
    (re.compile(r"(20\d\d)年(\d{1,2})月(\d{1,2})日"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
]


def _month(abbr: str) -> int:
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(abbr.lower()) + 1


def call_date(text: str, published: Optional[date]) -> Optional[date]:
    """The date the call was held, from the transcript's header: the first date in the opening text that falls in
    the two weeks up to the article's publication. Round 9: the call was dated by its write-up (31 Aug) instead of
    the day it was held (26 Aug). None when no such date is found."""
    if not text or not published:
        return None
    head = text[:10000]
    found = []
    for rx, conv in _DATE_PATTERNS:
        for m in rx.finditer(head):
            try:
                d = date(*conv(m))
            except (ValueError, KeyError):
                continue
            if published - timedelta(days=14) <= d <= published:
                found.append((m.start(), d))
    return min(found)[1] if found else None


def transcripts(docs: list, name: str = "", ticker: str = "") -> list:
    """News results that are this company's earnings-call transcripts, fetched in full (news text is capped) as kind
    "transcript". Never raises."""
    from dataclasses import replace as _replace
    from . import sources as rs
    keys = [k.lower() for k in (name, f"({ticker})" if ticker else "") if k]
    out, seen = [], set()
    for d in docs:
        title = d.title or ""
        if d.kind != "news" or not TRANSCRIPT.search(title) or (keys and not any(k in title.lower() for k in keys)):
            continue
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        best = d.text or ""
        for url in _fool_urls(title, d.published) + ([d.url] if d.url else []):
            try:
                text = rs.fetch_text(url, TRANSCRIPT_CHARS) or ""
            except Exception:  # noqa: BLE001
                text = ""
            if len(text) > len(best) and (not keys or any(k.strip("()") in text.lower() for k in keys)):
                best = text
            if len(best) >= 20000:
                break
        if len(best) >= 5000:  # a paywall or a teaser is not a transcript
            held = call_date(best, d.published)
            out.append(_replace(d, kind="transcript", text=best, published=held or d.published,
                                title=d.title if not held or held == d.published else
                                f"{d.title} (call held {held.strftime('%-d %b %Y')})"))
        if len(out) >= 2:
            break
    return out


# Run 1 (11 Nov 2026): no transcript could be fetched (the Motley Fool address returned nothing), so management's
# next-year outlook reached the notes only through press articles, which our own label then called "press reports".
# Press summaries of the call ("Earnings Call Highlights", "Recap of ... Earnings Call") are read whole with the
# results, labelled as the company's statements on the call.
CALL_SUMMARY = re.compile(r"(?:earnings|conference|results) call\W{0,3}(?:key\s+)?(?:highlights|recap|summary|"
                          r"takeaways)|recap of .{0,80}(?:earnings|conference) call|业绩会(?:纪要|要点|速递)|"
                          r"业绩说明会(?:纪要|要点)|电话会(?:议)?(?:纪要|要点)", re.I)
CALL_SUMMARY_DAYS = 7         # published within a week after the latest results document
CALL_SUMMARY_CHARS = 60_000
CALL_SUMMARY_MIN = 800        # shorter is a teaser or a snippet, not a summary


def _publisher(d) -> str:
    src = source_en(getattr(d, "source", "") or "", getattr(d, "url", "") or "")
    return src.split(": ", 1)[1] if ": " in src else src


def call_summaries(docs: list, name: str = "", ticker: str = "", local: str = "") -> list:
    """News articles that summarise this company's latest earnings call (title names the company and matches
    CALL_SUMMARY; published within CALL_SUMMARY_DAYS after the latest results document), refetched in full, as kind
    "call_summary" with the source "Earnings call, as reported by <publisher>". Longest first. Never raises."""
    try:
        from . import sources as rs
        cut = latest_results_date(docs)
        keys = [k.lower() for k in (name, f"({ticker})" if ticker else "", f"${ticker}" if ticker else "", local) if k]
        if not cut or not keys:
            return []
        out, seen = [], set()
        for d in docs:
            title = getattr(d, "title", "") or ""
            pub = getattr(d, "published", None)
            if (getattr(d, "kind", "") != "news" or not CALL_SUMMARY.search(title) or title.lower() in seen
                    or not any(k in title.lower() for k in keys) or not pub
                    or not cut - timedelta(days=1) <= pub <= cut + timedelta(days=CALL_SUMMARY_DAYS)):
                continue
            seen.add(title.lower())
            best = d.text or ""
            if d.url:
                try:
                    text = rs.fetch_text(d.url, CALL_SUMMARY_CHARS) or ""
                except Exception:  # noqa: BLE001
                    text = ""
                if len(text) > len(best) and any(k.strip("()$") in text.lower() for k in keys):
                    best = text
            if len(best) < CALL_SUMMARY_MIN:
                continue
            held = call_date(best, pub)
            held = held if held and held >= cut - timedelta(days=1) else None
            out.append(replace(d, kind="call_summary", text=best, published=held or pub,
                               source=f"Earnings call, as reported by {_publisher(d)}",
                               title=title if not held or held == pub else
                               f"{title} (call held {held.strftime('%-d %b %Y')})"))
            if len(out) >= 3:
                break
        out.sort(key=lambda d: -len(d.text or ""))
        return out
    except Exception as e:  # noqa: BLE001 - the results are still read without the call
        log.warning("call summaries failed: %s", type(e).__name__)
        return []


def _call_note(d, cut: Optional[date]) -> str:
    """The ReadResults header line for a press summary of the call."""
    if getattr(d, "kind", "") != "call_summary":
        return ""
    held = (f"held {d.published.strftime('%-d %b %Y')}" if "(call held " in (d.title or "") and d.published else
            f"held with the results of {cut.strftime('%-d %b %Y')}" if cut else "on the latest results")
    return (f"\nPress summary of the company's earnings call {held}: statements attributed to management are company "
            f"guidance given on that call.")


def read_key_facts(docs: list, company: str, lm: dspy.LM) -> tuple[list[_Found], list[str], list]:
    """(facts found, checklist keys with nothing found, documents read). Facts have importance 0: kept ahead of every
    other note and never pushed out by the per-topic caps."""
    picked = latest_results_docs(docs)
    if not picked:
        return [], [], []
    lang = "zh" if any(d.lang == "zh" for d in picked) else "en"
    room, texts, parts = KEY_CHARS[lang], [], []
    cut = latest_results_date(picked)
    # the call (transcript or press summary) keeps its room even after a long periodic report
    reserve = sum(min(len(d.text or ""), 80_000) for d in picked if d.kind in CALL_KINDS)
    for i, d in enumerate(picked, 1):
        t = guardrail.annotate_cn_amounts(d.text) if d.lang == "zh" else d.text
        t = t[: max(0, room if d.kind in CALL_KINDS else room - reserve)]
        room -= len(t)
        texts.append(t)
        parts.append(f"[{i}] {d.title} | {d.source} | {d.published or 'undated'}{_call_note(d, cut)}\n{t}")
    checklist = "\n".join(f"- {k}: {q}" for k, (q, _) in KEY_ITEMS.items())
    try:
        with dspy.context(lm=lm, adapter=_adapter()):
            out = dspy.Predict(ReadResults)(company=company, checklist=checklist, documents="\n\n".join(parts))
        raw = list(out.facts or [])[:40]
    except Exception as e:  # noqa: BLE001 - the excerpt reading still runs
        log.warning("key-facts read failed: %s", type(e).__name__)
        return [], [], picked
    norms = [_norm(t) for t in texts]
    found: list[_Found] = []
    for n, x in enumerate(raw):
        item = (x.item or "").strip().lower()
        k = (x.document or 1) - 1
        if item not in KEY_ITEMS or not (0 <= k < len(picked)):
            continue
        d = picked[k]
        fact, quote = (x.fact or "").strip(), (x.quote or "").strip()
        header = f"{d.title} {d.published or ''}"
        if not fact or not quote_found(quote, norms[k]) or not figures_ok(fact, quote, header):
            continue
        if guardrail.names_missing(fact, f"{texts[k]} {header}"):
            continue
        figs = tuple(sorted({round(f.value, 3) for f in guardrail.extract(fact)}))
        found.append(_Found(KEY_ITEMS[item][1], fact, quote, d, -1000 + n, figs, 0, item,
                            label=_label(getattr(x, "label", ""), fact)))
    have = {f.item for f in found}
    missing = [k for k in KEY_ITEMS if k not in have and k not in ("drivers", "one_offs")]
    return found, missing, picked


# ---------------------------------------------------------------- text helpers
_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-", " ": " "})


def _norm(s: str) -> str:
    """Comparison form: NFKC, plain quotes and dashes, no whitespace (PDF text breaks words and lines
    unpredictably), lower case."""
    s = unicodedata.normalize("NFKC", s or "").translate(_QUOTES)
    return re.sub(r"\s+", "", s).lower()


def quote_found(quote: str, text_norm: str) -> bool:
    """Every part of the quote (split at ellipses) of 8+ characters is in the text, verbatim."""
    parts = [p for p in re.split(r"\.\.\.|…", quote or "") if len(_norm(p)) >= 8]
    return bool(parts) and all(_norm(p) in text_norm for p in parts)


def figures_ok(fact: str, quote: str, header: str = "") -> bool:
    """Every figure in the fact is in the quote (or the document header, e.g. its date), and its ratio words agree
    with its figures and its quote (``ratio_ok``)."""
    allowed = guardrail.build_allowed(guardrail.annotate_cn_amounts(quote), header)
    return not guardrail.unmatched(fact, allowed) and ratio_ok(fact, quote)


# Run 1: a note said "about one-third of planned capacity (about 141 GW out of a total of about 156 GW)", as its
# source article did; the reviewers marked it as an error. Same regexes as final_v9/accept.py.
FRACTION = {"one-third": 1 / 3, "one third": 1 / 3, "a third": 1 / 3, "two-thirds": 2 / 3, "two thirds": 2 / 3,
            "half": 0.5, "one-half": 0.5, "a quarter": 0.25, "one-quarter": 0.25, "one quarter": 0.25,
            "three-quarters": 0.75, "three quarters": 0.75, "one-fifth": 0.2, "a fifth": 0.2, "one-tenth": 0.1}
# (with word boundaries here: "behalf" holds no "half")
FRACTION_RX = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in sorted(FRACTION, key=len, reverse=True)) + r")\b",
                         re.I)
X_OF_Y = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?[A-Za-z$%]{0,8}\s+(?:out\s+)?of\s+(?:a\s+)?(?:total\s+)?(?:of\s+)?"
                    r"(?:about\s+|around\s+|roughly\s+|approximately\s+|~)?[A-Z$]{0,4}\s?(\d[\d,]*(?:\.\d+)?)")
# a ratio or multiple word in a fact must be backed by the quote (English or Chinese); "a quarter" is left out (it is
# also a period), and "first half" / "half-year" are periods, not ratios
_RATIO_WORDS = [
    (re.compile(r"\b(?:one|a)[- ]third\b", re.I), re.compile(r"\b(?:one|a)[- ]third\b|三分之一", re.I)),
    (re.compile(r"\btwo[- ]thirds\b", re.I), re.compile(r"\btwo[- ]thirds\b|三分之二", re.I)),
    (re.compile(r"\bthree[- ]quarters\b", re.I), re.compile(r"\bthree[- ]quarters\b|四分之三", re.I)),
    (re.compile(r"\b(?:one|a)[- ]fifth\b", re.I), re.compile(r"\b(?:one|a)[- ]fifth\b|五分之一", re.I)),
    (re.compile(r"\bone[- ]tenth\b", re.I), re.compile(r"\bone[- ]tenth\b|十分之一", re.I)),
    (re.compile(r"\bhalf\b|\bhalved\b", re.I), re.compile(r"\bhalf\b|\bhalved\b|\bhalving\b|一半|半数|过半|减半", re.I)),
    (re.compile(r"\bdoubl\w*|\btwice\b|\btwo-?fold\b", re.I),
     re.compile(r"\bdoubl\w*|\btwice\b|\btwo-?fold\b|翻倍|翻番|翻一番|两倍", re.I)),
    (re.compile(r"\btripl\w*|\bthree-?fold\b", re.I), re.compile(r"\btripl\w*|\bthree-?fold\b|三倍", re.I)),
    (re.compile(r"\bmajority\b", re.I), re.compile(r"\bmajority\b|\bmost\b|大部分|大多数|多数|过半", re.I)),
]
_HALF_PERIOD = re.compile(r"\b(?:first|second|1st|2nd|latter|back|front)[- ]half\b|\bhalf[- ]year\w*", re.I)


def ratio_ok(fact: str, quote: str = "") -> bool:
    """A fraction word next to "X of Y" agrees with X / Y (within 12 points), and every ratio or multiple word in the
    fact (one-third, half, double, twice, majority ...) is also in the quote. True when a check cannot run."""
    try:
        text = _HALF_PERIOD.sub(" ", fact or "")  # "first half", "half-year": periods, not ratios
        for f in FRACTION_RX.finditer(text):
            for m in X_OF_Y.finditer(text):
                if abs(m.start() - f.start()) > 160:
                    continue
                try:
                    x, y = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
                except ValueError:
                    continue
                if y > 0 and 0 < x <= y and abs(x / y - FRACTION[f.group(0).lower()]) > 0.12:
                    return False
        if quote:
            for in_fact, in_quote in _RATIO_WORDS:
                if in_fact.search(text) and not in_quote.search(quote):
                    return False
        return True
    except Exception:  # noqa: BLE001 - a check that cannot run keeps the old behaviour
        return True


def chunks(text: str, lang: str) -> list[str]:
    size = CHUNK_CHARS.get(lang, 6000)
    text = text or ""
    if len(text) <= size:
        return [text] if text.strip() else []
    out, i, overlap = [], 0, size // 12
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):  # end at a sentence or line break when one is near
            k = max(text.rfind("\n", i + size // 2, j), text.rfind("。", i + size // 2, j),
                    text.rfind(". ", i + size // 2, j))
            j = k + 1 if k > 0 else j
        out.append(text[i:j])
        if j >= len(text):
            break
        i = max(j - overlap, i + 1)
    return out


def _score(chunk: str, keywords: list[str]) -> float:
    low = chunk.lower()
    hits = sum(min(low.count(k), 6) for k in keywords)
    figures = len(re.findall(r"\d", chunk)) / max(1, len(chunk))
    return hits / max(1.0, len(chunk) / 2000) + 8 * min(figures, 0.08)


@dataclass
class _Chunk:
    doc: object
    n: int
    text: str
    score: float = 0.0


@dataclass
class _Found:
    topic: str
    text: str
    quote: str
    doc: object
    order: int = 0
    figures: tuple = field(default_factory=tuple)
    importance: int = 2  # 0 = key fact from the whole latest results documents, or a later update (never capped)
    item: str = ""       # key facts: the KEY_ITEMS checklist key; updates: "update:<UPDATE_RX item>"
    said_by: str = ""    # the reading model's label: company, broker, press or other
    label: str = ""      # run 3: a few words naming the event, printed next to the note's id


# ---------------------------------------------------------------- steps
def _situation(data: TearSheetData) -> str:
    q, lines = data.quote, []
    lines.append(f"Price {q.price} {q.currency} on {q.as_of}." if getattr(q, "as_of", None) else f"Price {q.price} {q.currency}.")
    t = data.technicals
    if t is not None and getattr(t, "return_1y", None) is not None:
        lines.append(f"One-year share price change {t.return_1y:+.0%}.")
    lt = data.financials.latest
    if lt is not None:
        g = f"{lt.revenue_growth:+.1%}" if lt.revenue_growth is not None else "n/a"
        lines.append(f"Latest reported period: {lt.label} (to {lt.period_end}), revenue growth {g} year on year.")
    if data.rating is not None:
        lines.append(f"Rule-based model rating: {data.rating.rating}.")
    if getattr(data.profile, "sector", None):
        lines.append(f"Sector: {data.profile.sector}; industry: {getattr(data.profile, 'industry', None) or 'n/a'}.")
    return " ".join(lines)


def _checklist(extra: list[str]) -> tuple[str, list[tuple[str, str]]]:
    qs = [(k, TOPICS[k][0]) for k in TOPIC_ORDER] + [("other", x.strip()) for x in extra if x and x.strip()]
    return "\n".join(f"{i}. {q}" for i, (_, q) in enumerate(qs, 1)), qs


def next_fiscal_year(data: TearSheetData) -> Optional[int]:
    """The fiscal year after the current one (latest reported FY + 2): the year whose outlook management gives on
    its calls and that our forecast's second year covers."""
    ys = getattr(getattr(data, "financials", None), "years", None) or []
    return ys[-1].fiscal_year + 2 if ys else None


def _default_queries(data: TearSheetData, market: Market, docs: Optional[list] = None) -> list[tuple[str, str]]:
    """``docs``: documents already collected; the latest results document's month dates the earnings-call search."""
    p = data.profile
    name = re.sub(r"\b(Inc|Corp|Corporation|Co|Ltd|Limited|Holdings?|Group|plc|Company)\b\.?,?", "", p.name).strip(" ,.")
    nxt = next_fiscal_year(data)
    # round-6 review: the notes had the next-quarter guide but missed management's outlook for the next fiscal year,
    # given on the earnings call, and the forecast contradicted it
    tick = f" ({p.ticker})" if market == Market.US and getattr(p, "ticker", None) else ""
    out = [(f"{name}{tick} earnings call transcript", "en"), (f"{name} earnings call outlook", "en")]
    try:  # run 2: press summaries of the call ("Earnings Call Highlights") when no transcript can be fetched
        cut = latest_results_date(docs or [])
    except Exception:  # noqa: BLE001
        cut = None
    if cut:
        out.append((f"{name} earnings call {cut:%B %Y}", "en"))
    out.append((f"{name} gross margin guidance", "en"))
    if nxt:
        out.append((f"{name} fiscal {nxt} outlook", "en"))
    t = getattr(data, "technicals", None)
    if t is not None and getattr(t, "big_move", None) and getattr(t, "big_move_date", None):
        # why the shares moved on their biggest day of the last month (round-7 review: a -9.3% day unexplained)
        out.append((f"{name} stock {'falls' if t.big_move < 0 else 'jumps'} {t.big_move_date:%B} "
                    f"{t.big_move_date.day}", "en"))
    # capital returns: rounds 6 and 9, a 28 Sep buyback increase (to USD 235bn) never reached the notes; "<name>
    # buyback dividend" returned no news at all (checked 10 Nov 2026), "<name> share repurchase authorization" returned
    # the announcement and its coverage first
    out += [(f"{name} shares", "en"), (f"{name} outlook", "en"), (f"{name} share repurchase authorization", "en"),
            (f"{name} dividend", "en")]
    # round-8 review: the competitors' latest results and industry policy news were missed (peer results, permit
    # halts); search the two largest peers' results and the industry's news
    comps = getattr(data, "comps", None)
    peers = [c for c in (getattr(comps, "peers", None) or []) if getattr(c, "name", None)]
    peers.sort(key=lambda c: -(getattr(c, "market_cap", None) or 0))
    for c in peers[:2]:
        pn = re.sub(r"\b(Inc|Corp|Corporation|Co|Ltd|Limited|Holdings?|Group|plc|Company)\b\.?,?", "", c.name).strip(" ,.")
        if pn and pn.lower() != name.lower():
            out.append((f"{pn} quarterly results", "en"))
    ind = getattr(p, "industry", None)
    if ind:
        out.append((f"{ind} industry news policy", "en"))
    local = getattr(p, "name_local", None)
    if market in (Market.HK, Market.CN) and local:
        out += [(f"{local}", "zh"), (f"{local} 业绩", "zh"), (f"{local} 业绩会 纪要", "zh"), (f"{local} 回购", "zh")]
        if nxt:
            out.append((f"{local} {nxt}年 展望", "zh"))
    return out


def plan(data: TearSheetData, docs: list, lm: dspy.LM, market: Market) -> tuple[list[str], list[tuple[str, str]]]:
    checklist, _ = _checklist([])
    titles = "\n".join(f"- {d.published} | {d.kind} | {d.title[:110]}" for d in docs[:40]) or "(none)"
    try:
        with dspy.context(lm=lm, adapter=_adapter()):
            out = dspy.Predict(PlanResearch)(
                company=f"{data.profile.name} ({data.profile.ticker})",
                business=(data.profile.description or "")[:1200], situation=_situation(data),
                checklist=checklist, documents=titles)
        extra = [str(x) for x in (out.extra_questions or [])][:5]
        queries = [(q.query.strip(), (q.lang or "en").strip().lower()[:2]) for q in (out.queries or [])
                   if q.query and q.query.strip()][:6]
    except Exception as e:
        log.warning("research plan failed: %s", e)
        extra, queries = [], []
    seen, merged = set(), []
    for q, lang in _default_queries(data, market, docs) + queries:  # the fixed checklist searches first: never cut off
        key = q.lower()
        if key not in seen:
            seen.add(key)
            merged.append((q, "zh" if lang == "zh" else "en"))
    return extra, merged[:20]  # 10-16 fixed searches + up to 6 from the plan (some overlap); reading stays capped by RESEARCH_CHUNKS


def _adapter():
    from ..narrative.commentary import ADAPTER
    return ADAPTER


# Content farms and auto-generated sites that round-3 reviewers called "low-tier sources" (their figures were
# often second-hand or wrong). News from them is not read; company documents and broker reports are unaffected.
LOW_TIER = re.compile(r"ainvest|ad[- ]?hoc[- ]?news|biggo|tradingkey|stocktwits|boerse-global|stocktitan|ibtimes|"
                      r"marketbeat|insidermonkey|247wallst|24/7 wall|simplywall|simply wall|gurufocus|benzinga\.com/pressreleases|"
                      r"finanzen\.net|wallstreet-online|aktiencheck|investorsobserver|coincentral|techstock|"
                      r"timothy sykes|kalkine|stockstory|zacks|beincrypto|prediction markets|kucoin|nai500|binance|coinmarketcap|"
                      r"coindesk|cointelegraph", re.I)


def _low_tier(d) -> bool:
    """News that is not read: a content farm, or (run 3, 12 Nov 2026) an outlet that is not on the team's list in
    config/news_sources.json. Company documents and broker reports are never filtered."""
    if d.kind != "news":
        return False
    from .. import newssources
    return bool(LOW_TIER.search(f"{d.source} {d.url or ''}")) or not newssources.allowed(d.source or "", d.url or "")


def collect(t: Ticker, queries: list[tuple[str, str]], today: date, feed: Optional[list] = None,
            stats: Optional[dict] = None) -> list:
    """Company documents, broker reports, the report's own news feed read in full (``feed``: data.news, run 3) and
    news searches; de-duplicated by URL; news only from the approved outlets. ``stats`` (run 3) receives the counts
    at each filter: found, duplicates, no_text, not_on_list, documents."""
    from .. import newssources
    from . import sources as rs
    docs: list = []
    for fn, args in ((rs.primary_docs, (t, today)), (rs.broker_docs, (t, today))):
        try:
            docs += fn(*args) or []
        except Exception as e:
            log.warning("research %s failed for %s: %s", fn.__name__, t.canonical, e)
    if feed:
        try:
            docs += rs.feed_docs(feed, today) or []
        except Exception as e:  # noqa: BLE001 - the searches below still run
            log.warning("research news feed failed for %s: %s", t.canonical, e)
    for q, lang in queries:
        try:
            docs += rs.news_search(q, lang=lang, days=90, limit=8, keep=newssources.allowed) or []
        except Exception as e:
            log.warning("news search %r failed: %s", q, e)
    seen, out = set(), []
    n = {"found": len(docs), "duplicates": 0, "no_text": 0, "not_on_list": 0}
    for d in docs:
        key = d.url or d.id
        if key in seen:
            n["duplicates"] += 1
            continue
        if not (d.text or d.snippet):
            n["no_text"] += 1
            continue
        if _low_tier(d):
            n["not_on_list"] += 1
            continue
        seen.add(key)
        out.append(d)
    if stats is not None:
        stats.update(n, documents=len(out))
    return out


# ---------------------------------------------------------------- company events after the latest results
# Rounds 6 and 9 and run 1: a buyback increase announced a month after the results (USD 150bn) never reached the
# report: the "remaining" figure from the results release was given as current. Company announcements dated after the
# latest results document are read first and kept outside the per-topic caps, and the writers are told that they
# supersede the key fact on the same item. (item -> regex on a title or a fact; English and Chinese)
_W = r"(?:[^.;]|\.(?=\d))"  # a window inside one sentence (a decimal point does not end it)
_CAP_WORDS = (r"(?:authori[sz]\w*|increas\w*|program(?:me)?s?|declar\w*|additional|boost\w*|rais\w*|approv\w*|new|"
              r"adds?|added|expan\w*)")
_PEOPLE = r"(?:CEO|CFO|chief executive|chief financial officer|chair(?:man|woman|person)?)"
_PEOPLE_ACT = (r"(?:appoint\w*|resign\w*|step(?:s|ped|ping)? down|retir\w*|investigat\w*|prob(?:e|es|ed|ing)|"
               r"named|depart\w*|successor|succession|replac\w*|oust\w*|allegation\w*|alleged\w*|scandal\w*|"
               r"misconduct|fired|dismiss\w*|remov\w*|leave of absence)")
_GUIDE_ACT = r"(?:rais\w*|cuts?|cutting|lowered|lowers|updat\w*|withdr\w*)"
UPDATE_RX: dict[str, re.Pattern] = {
    "capital_return": re.compile(
        rf"\b(?:repurchase\w*|buy-?backs?|dividends?)\b{_W}{{0,80}}\b{_CAP_WORDS}\b|"
        rf"\b{_CAP_WORDS}\b{_W}{{0,80}}\b(?:repurchase\w*|buy-?backs?|dividends?)\b|回购|分红|派息|股息", re.I),
    "guidance": re.compile(
        rf"\b(?:guidance|outlook|forecasts?)\b{_W}{{0,60}}\b{_GUIDE_ACT}\b|"
        rf"\b{_GUIDE_ACT}\b{_W}{{0,40}}\b(?:guidance|outlook|forecasts?)\b|profit warning|"
        r"(?:上调|下调|更新|撤回|调整).{0,8}(?:指引|预期|展望|目标)|业绩预告|盈利预警", re.I),
    "deal": re.compile(r"\bacqui(?:re[sd]?|ring|sitions?)\b|\bmergers?\b|definitive agreement|\bstake\b|收购|并购|"
                       r"重组", re.I),
    "funding": re.compile(
        r"\b(?:senior|unsecured|convertible|exchangeable|green)\s+notes\b|\bnotes\s+due\b|\bnotes?\s+offering|"
        rf"offering of {_W}{{0,40}}\bnotes\b|\bbonds?\b{_W}{{0,30}}\b(?:offering|issu\w*|sale|priced)\b|"
        rf"\b(?:issu\w*|priced|sold)\b{_W}{{0,30}}\bbonds?\b|credit facilit\w*|revolving credit|term loan|"
        r"发行(?!人)|债券|配售|供股", re.I),
    "people": re.compile(
        rf"\b{_PEOPLE}\b{_W}{{0,80}}\b{_PEOPLE_ACT}\b|\b{_PEOPLE_ACT}\b{_W}{{0,80}}\b{_PEOPLE}\b|"
        r"辞职|辞任|离任|任命|聘任|调查|立案", re.I),
}
UPDATE_MAX = 6
UPDATE_BONUS = 10.0
# the key-fact items a later update on that item supersedes
UPDATE_SUPERSEDES = {"capital_return": ("capital_return",), "funding": ("funding",), "guidance": ("guidance", "outlook")}


def update_item(text: str) -> str:
    """The UPDATE_RX item a title or a fact is about ("" when none); the first match in UPDATE_RX's order."""
    for item, rx in UPDATE_RX.items():
        if rx.search(text or ""):
            return item
    return ""


def _round_robin(groups: dict[str, list], limit: int) -> list[tuple[str, object]]:
    """Up to ``limit`` (item, x), one item at a time, so one busy item (a week of news on one event) cannot take
    every place."""
    queues = {k: list(v) for k, v in groups.items() if v}
    out: list[tuple[str, object]] = []
    while len(out) < limit and any(queues.values()):
        for k, q in queues.items():
            if q and len(out) < limit:
                out.append((k, q.pop(0)))
    return out


def update_docs(docs: list) -> set[int]:
    """ids of the documents (at most UPDATE_MAX) whose title is a company event dated after the latest results
    document: company documents first, then the newest. Never raises."""
    try:
        cut = latest_results_date(docs)
        if not cut:
            return set()
        groups: dict[str, list] = {k: [] for k in UPDATE_RX}
        for d in docs:
            pub = getattr(d, "published", None)
            if not pub or pub <= cut or d.kind in RESULTS_KINDS or (d.kind == "news" and len(d.text or "") <= 600):
                continue  # snippet-only news is read in the bundle anyway
            item = update_item(d.title or "")
            if item:
                groups[item].append(d)
        for v in groups.values():
            v.sort(key=lambda d: (0 if d.kind in COMPANY_KINDS else 1, -d.published.toordinal()))
        return {id(d) for _, d in _round_robin(groups, UPDATE_MAX)}
    except Exception as e:  # noqa: BLE001 - reading order only
        log.info("update ranking skipped: %s", type(e).__name__)
        return set()


def select_chunks(docs: list, questions: list[tuple[str, str]], budget: int,
                  stats: Optional[dict] = None) -> list[_Chunk]:
    """Split each document into excerpts, score them (topic keywords and figures per length, plus a bonus by kind
    of document and for company events after the latest results), keep the best few per document, then read the
    ``budget`` best overall; news snippets go in one bundle. ``stats`` (run 3): candidate_excerpts, excerpts_read,
    news_snippets_bundled."""
    keywords = [k for key in TOPIC_ORDER for k in TOPICS[key][1]]
    extra_words = [w.lower() for _, q in questions if _ == "other" for w in re.findall(r"[A-Za-z]{5,}", q)]
    keywords += extra_words
    cands: list[_Chunk] = []
    news = [d for d in docs if d.kind == "news"]
    later = update_docs(docs)
    for d in docs:
        if d.kind == "news":
            continue
        text = guardrail.annotate_cn_amounts(d.text) if d.lang == "zh" else d.text
        bonus = KIND_BONUS.get(d.kind, 1.0) + (UPDATE_BONUS if id(d) in later else 0.0)
        scored = [_Chunk(d, i, c, _score(c, keywords) + bonus) for i, c in enumerate(chunks(text, d.lang))]
        scored.sort(key=lambda c: -c.score)
        cands += scored[:PER_DOC_CHUNKS.get(d.kind, 2)]
    # news: full articles are read one by one; snippet-only items are bundled
    snippets = []
    for d in news:
        body = d.text if len(d.text or "") > 600 else ""
        if body:
            text = guardrail.annotate_cn_amounts(body) if d.lang == "zh" else body
            c = chunks(text, d.lang)[0]
            bonus = KIND_BONUS["news"] + (UPDATE_BONUS if id(d) in later else 0.0)
            cands.append(_Chunk(d, 0, c, _score(c, keywords) + bonus))
        else:
            snippets.append(d)
    cands.sort(key=lambda c: -c.score)
    picked = cands[:max(0, budget - (1 if snippets else 0))]
    if snippets:
        lines = [f"[{d.published}] {d.source}: {d.title}. {d.snippet or d.text}" for d in snippets[:30]]
        bundle = guardrail.annotate_cn_amounts("\n".join(lines))
        picked.append(_Chunk(_Bundle(snippets[:30]), 0, bundle, 0.0))
    if stats is not None:
        stats.update(candidate_excerpts=len(cands) + (1 if snippets else 0), excerpts_read=len(picked),
                     news_snippets_bundled=min(len(snippets), 30))
    return picked


@dataclass
class _Bundle:
    """News snippets read together; the source of each fact is the item its quote comes from."""
    items: list
    kind: str = "news"
    title: str = "News search results"
    source: str = "Bing News"
    published: Optional[date] = None
    url: str = ""
    lang: str = "en"


def _read(chunk: _Chunk, company: str, questions_text: str, lm: dspy.LM) -> list[Extracted]:
    d = chunk.doc
    header = f"{d.title} | {d.source} | {d.published or 'various dates'}"
    try:
        with dspy.context(lm=lm, adapter=_adapter()):
            out = dspy.Predict(ExtractFacts)(company=company, questions=questions_text, document=header,
                                             excerpt=chunk.text)
        return list(out.facts or [])[:8]
    except Exception as e:
        log.info("research read failed (%s #%d): %s", getattr(d, "title", "?")[:60], chunk.n, type(e).__name__)
        return []


def _topic(nums: list[int], qs: list[tuple[str, str]]) -> str:
    for n in nums or []:
        if 1 <= n <= len(qs):
            return qs[n - 1][0]
    return "other"


def _source_of(chunk: _Chunk, quote: str):
    d = chunk.doc
    if isinstance(d, _Bundle):
        for item in d.items:
            if quote_found(quote, _norm(guardrail.annotate_cn_amounts(f"{item.title}. {item.snippet or item.text}"))):
                return item
        return None
    return d


DROP_REASONS = {
    "empty": "no fact or no quote",
    "quote": "quote not found word for word in the document",
    "figures": "a figure or ratio word in the fact is not in its quote",
    "name": "a name in the fact is not in the document",
    "other_company": "about another company",
    "no_source": "quote not traced to one news item",
}


def verify(found: list[tuple[_Chunk, Extracted]], qs: list[tuple[str, str]],
           reasons: Optional[dict[str, int]] = None) -> tuple[list[_Found], int]:
    """Keep a fact only if its quote is in the excerpt, every figure in it is in the quote, every name in it is in the
    excerpt, and it is about this company. ``reasons`` (if given) counts each drop by its DROP_REASONS key (run 3:
    the count alone could not say whether the model misquoted or the checks were too strict)."""
    keep, dropped = [], 0

    def drop(why: str) -> None:
        nonlocal dropped
        dropped += 1
        if reasons is not None:
            reasons[why] = reasons.get(why, 0) + 1

    for i, (c, x) in enumerate(found):
        fact, quote = (x.fact or "").strip(), (x.quote or "").strip()
        header = f"{c.doc.title} {getattr(c.doc, 'published', '') or ''}"
        if not fact or not quote:
            drop("empty")
            continue
        if not quote_found(quote, _norm(c.text)):
            drop("quote")
            continue
        if not figures_ok(fact, quote, header):
            drop("figures")
            continue
        if guardrail.names_missing(fact, f"{c.text} {header}"):  # run 3: the reader is asked to name people
            drop("name")
            continue
        if getattr(x, "about_company", True) is False:  # round-6 review: Synaptics / Stratum facts in NVIDIA's notes
            drop("other_company")
            continue
        doc = _source_of(c, quote)
        if doc is None:
            drop("no_source")
            continue
        figs = tuple(sorted({round(f.value, 3) for f in guardrail.extract(fact)}))
        imp = x.importance if x.importance in (1, 2, 3) else 2
        keep.append(_Found(_topic(x.questions, qs), fact, quote, doc, i, figs, imp,
                           said_by=str(getattr(x, "said_by", "") or ""),
                           label=_label(getattr(x, "label", ""), fact)))
    return keep, dropped


def _label(label: str, fact: str) -> str:
    """The reading model's short label, kept only if it has no figures and no name the fact does not have; else ""
    (the report then shows the start of the fact)."""
    t = re.sub(r"\s+", " ", str(label or "")).strip().strip(".")
    if not t or len(t.split()) > 10 or re.search(r"\d", t) or guardrail.names_missing(t, fact):
        return ""
    return t


def _rank(f: _Found) -> tuple:
    d = f.doc
    tier = 0 if d.kind in PRIMARY else 1 if d.kind == "broker_report" else 2
    return (f.importance, tier, -(d.published or date.min).toordinal(), f.order)


def dedupe(found: list[_Found]) -> list[_Found]:
    out: list[_Found] = []
    for f in sorted(found, key=_rank):
        words = set(re.findall(r"[a-z]{4,}", f.text.lower()))
        dup = False
        for g in out:
            fs, gs = set(f.figures), set(g.figures)
            other = set(re.findall(r"[a-z]{4,}", g.text.lower()))
            jw = len(words & other) / len(words | other) if words and other else 0.0
            if fs and gs and (fs == gs or (len(fs & gs) / len(fs | gs) >= 0.6 and jw >= 0.25)):
                dup = True  # the same figures (e.g. guidance repeated in the release, the commentary and the press)
            elif jw >= 0.5 and (not fs or not gs or fs & gs):
                # the same words: a copy only when the figures do not differ (run 1: the September "additional $150
                # billion" buyback was dropped as a copy of May's "additional $80.0 billion")
                dup = True
            if dup:
                break
        if not dup:
            out.append(f)
    return out


_PUBLISHERS = {"搜狐": "Sohu", "凤凰网": "ifeng.com", "腾讯网": "QQ News", "新浪": "Sina Finance", "虎嗅": "Huxiu",
               "中华网": "China.com", "东方财富": "EastMoney", "财联社": "Cailian Press", "证券时报": "Securities Times",
               "第一财经": "Yicai", "界面": "Jiemian", "澎湃": "The Paper", "华尔街见闻": "Wallstreetcn",
               "经济观察": "Economic Observer", "21世纪": "21st Century Business Herald", "每日经济": "NBD",
               "中国证券报": "China Securities Journal", "上海证券报": "Shanghai Securities News", "财新": "Caixin"}


def source_en(source: str, url: str = "") -> str:
    """English source labels: broker names translated, Chinese publishers named in English (or by web host)."""
    from urllib.parse import urlparse
    head, sep, name = (source or "").partition(": ")
    if not sep or not _CJK.search(name):
        return source
    if head.startswith("EastMoney research centre"):
        from ..data.brokers import broker_en
        en = broker_en(name)
        return f"{en} (via EastMoney)" if not _CJK.search(en) else f"EastMoney research centre"
    for k, v in _PUBLISHERS.items():
        if k in name:
            return f"{head}: {v}"
    host = urlparse(url or "").netloc.removeprefix("www.")
    return f"{head}: {host}" if host else head


def has_outlook(texts: list[str], year: Optional[int]) -> bool:
    """Does any guidance fact speak about the next fiscal year?"""
    if not year:
        return True
    pat = re.compile(rf"\b(fiscal(?: year)? {year}|FY ?{year}|FY ?{year % 100}\b|{year}\b|next (?:fiscal )?year|"
                     rf"{year}年|明年)", re.I)
    return any(pat.search(t or "") for t in texts)


# whole month names or their abbreviations only ("decreased 12" is not 12 December)
_MON_WORD = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
             r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
_MONTH_YEAR = re.compile(r"\b" + _MON_WORD + r",?\s+(20\d\d)\b", re.I)
_MONTH_DAY = re.compile(r"\b" + _MON_WORD + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*%)(?!,?\s+20\d\d)", re.I)


def _dates_in(text: str, published: Optional[date]) -> list[date]:
    """Explicit dates in a fact: full dates; "May 2026" as that month's last day; "September 28" in the year that puts
    it on or before ``published``."""
    out: list[date] = []
    for rx, conv in _DATE_PATTERNS:
        for m in rx.finditer(text or ""):
            try:
                out.append(date(*conv(m)))
            except (ValueError, KeyError):
                continue
    for m in _MONTH_YEAR.finditer(text or ""):
        try:
            mo, yr = _month(m[1][:3]), int(m[2])
            out.append(date(yr + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1))
        except (ValueError, KeyError):
            continue
    if published:
        for m in _MONTH_DAY.finditer(text or ""):
            try:
                d = date(published.year, _month(m[1][:3]), int(m[2]))
                out.append(d if d <= published else date(published.year - 1, d.month, d.day))
            except (ValueError, KeyError):
                continue
    return out


def _said_by(f: _Found) -> str:
    """ResearchFact.said_by: company documents (results, announcements, IR records, the call) are the company's;
    otherwise the reading model's label ('other' -> ''); a broker report's own view is the broker's."""
    kind = getattr(f.doc, "kind", "")
    if kind in COMPANY_KINDS or f.said_by == "company":
        return "company"
    if kind == "broker_report":
        return "broker"
    return f.said_by if f.said_by in ("broker", "press") else ""


_AMOUNT_FIG = re.compile(r"(?:\$|USD|HKD|RMB|CNY|EUR|€|£)\s?(\d[\d,]*(?:\.\d+)?)|"
                         r"(\d[\d,]*(?:\.\d+)?)\s?(?:billion|bn|million|mn|trillion|tn|亿|万)", re.I)
CORROBORATED_ITEMS = ("capital_return", "funding", "deal")  # hard corporate events; views on guidance or people are not


def _amounts(text: str) -> set[float]:
    """Money amounts in a note (not days or years), for matching the same event across documents."""
    out = set()
    for m in _AMOUNT_FIG.finditer(text or ""):
        try:
            out.add(float((m.group(1) or m.group(2)).replace(",", "")))
        except ValueError:
            pass
    return out


def pick_updates(found: list[_Found], cut: Optional[date], pool: Optional[list[_Found]] = None) -> dict[int, str]:
    """{id(fact): item} for at most UPDATE_MAX verified facts about a company event (UPDATE_RX) dated after the latest
    results document ``cut`` and stated by the company (a company document, or a press note the reading model marked
    as the company's statement). Not one that only retells an event dated on or before ``cut``. One item at a time,
    newest first within an item. Never raises."""
    try:
        if not cut:
            return {}
        groups: dict[str, list[_Found]] = {k: [] for k in UPDATE_RX}
        # R2-CHECK (12 Nov 2026): the mark must not hang on the reading model's said_by label alone. An event after
        # the results that two or more different documents report with the same figure is kept as well (``pool``:
        # the notes before de-duplication, which removes exactly those repeats).
        seen_in: dict[tuple[str, float], set] = {}
        for g in (pool or []):
            gp = getattr(g.doc, "published", None)
            gi = update_item(g.text) if gp and gp > cut else ""
            if gi in CORROBORATED_ITEMS and g.said_by != "broker":
                for x in _amounts(g.text):
                    seen_in.setdefault((gi, x), set()).add(getattr(g.doc, "url", None) or getattr(g.doc, "title", ""))
        for f in found:
            d = f.doc
            pub = getattr(d, "published", None)
            if f.importance == 0 or not pub or pub <= cut:
                continue
            if _said_by(f) != "company":
                it = update_item(f.text)
                if not it or not any(len(seen_in.get((it, x), ())) >= 2 for x in _amounts(f.text)):
                    continue
            item = update_item(f.text) or (update_item(f.quote) if _CJK.search(f.quote or "") else "")
            ds = _dates_in(f.text, pub)
            if not item or (ds and max(ds) <= cut):
                continue
            groups[item].append(f)
        for v in groups.values():
            v.sort(key=lambda f: (-f.doc.published.toordinal(), 0 if f.doc.kind in COMPANY_KINDS else 1, f.order))
        return {id(f): item for item, f in _round_robin(groups, UPDATE_MAX)}
    except Exception as e:  # noqa: BLE001 - the notes are still kept, only without the update mark
        log.warning("update selection failed: %s", type(e).__name__)
        return {}


def brief(found: list[_Found], qs: list[tuple[str, str]], docs: int, chunks_read: int, dropped: int,
          next_year: Optional[int] = None, key_missing: Optional[list[str]] = None,
          key_docs: Optional[list] = None, results_cut: Optional[date] = None,
          dropped_by: Optional[dict[str, int]] = None, funnel: Optional[dict[str, int]] = None) -> ResearchBrief:
    """``results_cut``: the latest results document's date (default: from ``key_docs``, else from the facts' own
    documents); verified company events dated after it are kept as updates ("update:<item>")."""
    by_topic: dict[str, list[_Found]] = {}
    chosen: dict[str, list[_Found]] = {t: [] for t in TOPIC_ORDER + ["other"]}
    deduped = dedupe(found)
    cut = results_cut or latest_results_date(key_docs or []) or latest_results_date([f.doc for f in found])
    ups = pick_updates(deduped, cut, found)
    for f in deduped:
        if id(f) in ups:  # a company event after the results: kept outside the caps, like a key fact
            f = replace(f, importance=0, item=f"update:{ups[id(f)]}")
        if f.importance == 0:  # key facts from the whole latest results documents: always kept, outside the caps
            chosen.setdefault(f.topic, []).append(f)
            by_topic.setdefault(f.topic, [])
        elif f.importance < 3:  # minor details and boilerplate are left out of the brief
            by_topic.setdefault(f.topic, []).append(f)
    # round robin over the topics (most important first within each), so every topic gets its share
    keyn = {t: len(v) for t, v in chosen.items()}
    queues = {t: list(v) for t, v in by_topic.items()}
    total = 0
    while total < MAX_FACTS and any(queues.values()):
        for t in TOPIC_ORDER + ["other"]:
            q = queues.get(t)
            if q and len(chosen[t]) - keyn.get(t, 0) < PER_TOPIC and total < MAX_FACTS:
                chosen[t].append(q.pop(0))
                total += 1
        if all(not q or len(chosen[t]) - keyn.get(t, 0) >= PER_TOPIC for t, q in queues.items()):
            break
    facts: list[ResearchFact] = []
    for topic in TOPIC_ORDER + ["other"]:
        for f in chosen.get(topic, []):
            d = f.doc
            facts.append(ResearchFact(id=f"R{len(facts) + 1}", topic=topic, text=f.text, quote=f.quote[:400],
                                      source=source_en(d.source, d.url), title=d.title[:200], url=d.url or None,
                                      published=d.published, kind=d.kind, key=f.item if f.importance == 0 else "",
                                      said_by=_said_by(f), label=f.label,
                                      event_date=event_date(f.quote, d.published, d.kind)))
    gaps = [TOPICS[k][0] for k in TOPIC_ORDER if k not in by_topic]
    if key_missing and key_docs:
        names = "; ".join(f"{d.title[:80]} ({d.published})" for d in key_docs)
        gaps.append("Not stated in the latest results documents (" + names + "): "
                    + ", ".join(KEY_ITEMS[k][0].split(":")[0].split(" (")[0].lower() for k in key_missing)
                    + ". Say these were not found in the documents read, or leave them out: never write that the "
                      "company did not disclose them (you have not read every document), and never fill them from "
                      "older periods; a press report of what management said on the results call may be used if "
                      "attributed")
    if next_year and "guidance" in by_topic and not has_outlook(
            [f"{f.text} {f.quote}" for f in by_topic["guidance"]], next_year):
        gaps.append(f"Management's outlook for fiscal {next_year} (the next fiscal year): not found in the documents "
                    f"read; do not assume or invent it, and say a forecast for that year has no guidance to anchor on")
    share_event_dates(facts)
    return ResearchBrief(
        questions=[q for _, q in qs], facts=facts, gaps=gaps, docs_read=docs, chunks_read=chunks_read,
        facts_dropped=dropped, dropped_by=dict(dropped_by or {}), funnel=dict(funnel or {}),
        method=("Research desk: the AI read the latest results releases, announcements, periodic report, "
                "the earnings call (a transcript or a press summary of the call), investor-relations records, broker "
                "reports (A-shares) and news search results and extracted facts with verbatim quotes; code kept a "
                "fact only if its quote was found in the document, every figure and ratio word in it appears in "
                "the quote and every name in it appears in the document. Company announcements dated after the latest results are kept as updates. Facts are "
                "evidence for the commentary and never feed the rating."))


def run(data: TearSheetData, t: Ticker, lm: Optional[dspy.LM] = None, plan_lm: Optional[dspy.LM] = None,
        budget: Optional[int] = None, today: Optional[date] = None,
        key_lm: Optional[dspy.LM] = None) -> Optional[ResearchBrief]:
    """Plan -> collect -> read -> verify -> brief. Cached per ticker per day (the simple, deep and learner
    runs of one day share one reading) when it holds at least CACHE_MIN_FACTS notes. None when no note was kept (a
    data note says so)."""
    today = today or date.today()
    budget = budget or settings.research_chunks
    key = cache_key(t, today, budget)
    cache = get_cache()
    if not settings.no_cache:
        hit = cache.get(key)
        if hit:
            return ResearchBrief.model_validate(hit)
    if lm is None:
        if not settings.llm.enabled:
            return None
        from ..narrative.commentary import make_lm
        lm = make_lm(settings.llm, max_tokens=3000, thinking="disabled", step="research")
        plan_lm = plan_lm or make_lm(settings.llm, max_tokens=6000, thinking="enabled", step="research")
        key_lm = key_lm or make_lm(settings.llm, max_tokens=12000, thinking="disabled", step="research")
    plan_lm = plan_lm or lm

    from . import sources as rs
    try:
        first = rs.primary_docs(t, today) or []
    except Exception as e:
        log.warning("research primary docs failed for %s: %s", t.canonical, e)
        first = []
    extra, queries = plan(data, first, plan_lm, t.market)
    funnel: dict[str, int] = {}
    docs = collect(t, queries, today, getattr(data, "news", None), stats=funnel)
    questions_text, qs = _checklist(extra)
    picked = select_chunks(docs, qs, budget, stats=funnel)
    company = f"{data.profile.name} ({data.profile.ticker})"
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [(c, provenance.submit(pool, _read, c, company, questions_text, lm)) for c in picked]
        found = [(c, x) for c, fut in futures for x in fut.result()]
    reasons: dict[str, int] = {}
    kept, dropped = verify(found, qs, reasons)
    short = re.sub(r"\b(Inc|Corp|Corporation|Co|Ltd|Limited|Holdings?|Group|plc|Company)\b\.?,?", "",
                   data.profile.name).strip(" ,.")
    us_code = getattr(t, "code", "") if getattr(t, "market", None) == Market.US else ""
    calls = transcripts(docs, short, us_code)
    summaries = [] if calls else call_summaries(docs, short, us_code,
                                                getattr(data.profile, "name_local", None) or "")
    key_found, key_missing, key_docs = read_key_facts(docs + calls + summaries, company, key_lm or lm)
    b = brief(key_found + kept, qs, len(docs), len(picked), dropped, next_fiscal_year(data), key_missing, key_docs,
              latest_results_date(docs), dropped_by=reasons,
              funnel=dict(funnel, facts_written=len(found), facts_dropped=dropped, key_facts=len(key_found)))
    b.funnel["facts_kept"] = len(b.facts)  # after duplicates and the per-topic caps
    log.info("research %s: %d docs, %d excerpts, %d facts kept, %d dropped (%s), call: %d transcript(s), "
             "%d summary(ies)", t.canonical, len(docs), len(picked), len(b.facts), dropped,
             ", ".join(f"{k} {v}" for k, v in reasons.items()) or "none", len(calls), len(summaries))
    if not b.facts:  # audit item 3c: an empty brief is not returned (or cached) as if it were research
        _data_note(data, NO_RESEARCH_NOTE)
        return None
    if len(b.facts) >= CACHE_MIN_FACTS:  # a thin brief (a source down) is not reused for the rest of the day
        cache.set(key, b.model_dump(mode="json"), 12 * 3600)
    return b


CACHE_MIN_FACTS = 20
NO_RESEARCH_NOTE = "Research notes not available this time."

# Bump when the reader's prompt or the verify rules change, so a cached reading made under the old rules is not reused.
# v9 call summaries, who said it; v10 labels, names check, drop reasons; v11 funnel; v12 (13 Nov 2026) event dates and
# run 4's reader rules, and the key now holds the reading settings too.
RESEARCH_VERSION = 12


def cache_key(t, today: date, budget: int) -> str:
    """The research cache key: one reading per ticker, day, rule version and reading settings. Why (13 Nov 2026): v11
    keyed on ticker and day only, so run 4 (the same day as run 3, with new reader rules and RESEARCH_CHUNKS 110 instead
    of 70) got run 3's 97 notes back unchanged: no event dates, 70 excerpts read. The three reports of one set still
    share one reading, because they run with the same settings."""
    return (f"research_brief:v{RESEARCH_VERSION}:{t.canonical}:{today.isoformat()}"
            f":chunks{budget}:facts{MAX_FACTS}:topic{PER_TOPIC}:allow{int(settings.news_allowlist)}")


def _data_note(data, note: str) -> None:
    try:
        w = getattr(data, "warnings", None)
        if isinstance(w, list) and note not in w:
            w.append(note)
    except Exception:  # noqa: BLE001
        pass


def facts_block(b: Optional[ResearchBrief], today: Optional[date] = None, ids: bool = False) -> str:
    """The research notes as a facts section for the writers (each line becomes citable evidence). ``today``: the
    price date. ``ids``: prefix each note with its id ([R12]) for the steps that must cite notes (forecast,
    scenarios); the R ids are printed in the report's research-notes table."""
    if not b or not b.facts:
        return ""
    label = {"guidance": "Guidance", "results": "Results driver", "quality": "Earnings quality", "policy": "Policy",
             "events": "Event", "capital": "Capex / investment", "competition": "Competition",
             "street": "Street / share price", "catalysts": "Upcoming", "demand": "Demand / customers",
             "other": "Other"}
    from ..narrative.facts import after_close
    lines: list[str] = []
    upd = [f for f in b.facts if (getattr(f, "key", "") or "").startswith("update:")]
    keyf = [f for f in b.facts if getattr(f, "key", "") and not f.key.startswith("update:")]
    later: dict[str, list[str]] = {}  # key-fact item -> ids of the later updates on that item
    for u in upd:
        for k in UPDATE_SUPERSEDES.get(u.key.split(":", 1)[1], ()):
            later.setdefault(k, []).append(u.id)

    def line(f, tail: str = "") -> str:
        when = (f.published.isoformat() if f.published else "undated") + after_close(f.published, today)
        if getattr(f, "kind", "") == "news":  # run 4: a news note's date is when it was reported
            ev = getattr(f, "event_date", None)
            when = f"reported {when}; " + (f"happened {ev.isoformat()}" if ev else "when it happened is not stated")
        return (f"- {'[' + f.id + '] ' if ids else ''}{label.get(f.topic, 'Other')} ({when}, "
                f"{source_en(f.source, f.url or '')}{_who(f)}): {f.text}{tail}")

    if keyf:
        d0 = keyf[0]
        lines.append(f"KEY FACTS from the latest results documents (read in full; e.g. {d0.title[:90]}, "
                     f"{d0.published}). They are the current figures as of the results date: they override any older "
                     f"note, press report or earlier quarter on the same item"
                     + ("; a company announcement listed under UPDATES below supersedes them on its item" if upd else "")
                     + "; date management's statements by these documents; notes sourced 'Earnings call, as reported "
                       "by ...' are management's statements on the call (company guidance):")
        for f in keyf:
            refs = later.get(f.key)
            tail = (" (as of the results date; see the later update "
                    + (", ".join(f"[{i}]" for i in refs) if ids else "under UPDATES below") + ")") if refs else ""
            lines.append(line(f, tail))
        lines.append("")
    if upd:
        lines.append("UPDATES SINCE THE LATEST RESULTS (company announcements dated after the key facts; on the same "
                     "item they supersede the key fact: give the newer figure and date both):")
        lines += [line(f) for f in upd]
        lines.append("")
    lines.append("Research notes (dated facts read from results releases, announcements, broker reports and news; "
                 "each has a verbatim source quote; attribute views and forecasts to whoever made them):")
    for f in b.facts:
        if getattr(f, "key", ""):
            continue
        lines.append(line(f))
    if b.gaps:
        lines.append("Not found in the documents read (say so rather than guess): " + "; ".join(
            g.split(" (")[0].split(",")[0].rstrip("?") for g in b.gaps) + ".")
    return "\n".join(lines)


def event_date(quote: str, published: Optional[date], kind: str = "news") -> Optional[date]:
    """Run 4 (round-12 reviews: a buyback dated by the day an article ran, a board statement of 8 Nov dated 12 Nov):
    the one calendar date a news quote gives for its event, on or before the article's own date and at most 120
    days earlier; None when the quote gives none or several. Company documents are dated by their own filing date."""
    if kind != "news" or not quote or published is None:
        return None
    from ..narrative.factcheck import _dates
    days = {d for _, _, d in _dates(quote, published.year)
            if published - timedelta(days=120) <= d <= published}
    return days.pop() if len(days) == 1 else None


def share_event_dates(facts: list) -> None:
    """Run 4: a news note without its own event date takes the earliest stated date of another note on the same
    topic that gives the same amount (two articles on one buyback: one says "On Sept. 28", the other only ran on
    1 Oct). In place; never raises."""
    try:
        dated = [g for g in facts if getattr(g, "event_date", None)]
        for f in facts:
            if getattr(f, "kind", "") != "news" or f.event_date:
                continue
            amts = _amounts(f.text)
            item = update_item(f.text)
            hits = [g.event_date for g in dated if g is not f and amts and amts & _amounts(g.text)
                    and (g.topic == f.topic or (item and update_item(g.text) == item))]
            if hits:
                f.event_date = min(hits)
    except Exception as e:  # noqa: BLE001
        log.info("event dates not shared: %s", type(e).__name__)


def _who(f) -> str:
    """The provenance label of a press note. Run 1: every news note was labelled a press report, so management's
    guidance reported from the results call was written up as "press reports, not company guidance"."""
    if getattr(f, "kind", "") != "news":
        return ""
    if getattr(f, "said_by", "") == "company":
        pub = _publisher(f)
        how = pub if "." not in pub else "that publisher"  # a dot would end the instruction early for readers
        return (f" (company statement reported by {pub}: it is company guidance; write that management said it, "
                f"as reported by {how})")
    return " (press report: attribute it, and prefer company figures where they differ)"


def doc_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:8]


# ---------------------------------------------------------------- English labels for segment names
class Label(BaseModel):
    original: str
    english: str = Field(description="The company's own English term if you know it, else a plain translation")


class TranslateLabels(dspy.Signature):
    """Translate the company's Chinese segment and product labels into English, using the segment name the company
    itself uses in its English annual report when you know it, rather than a literal translation of the Chinese.
    Keep it short (1-5 words). No figures."""
    company: str = dspy.InputField()
    labels: list[str] = dspy.InputField()
    english: list[Label] = dspy.OutputField()


_CJK = re.compile(r"[一-鿿]")


def english_labels(data: TearSheetData, lm: Optional[dspy.LM] = None) -> int:
    """Replace Chinese segment names with English ones in place (one cheap call); returns how many."""
    names = sorted({s.name for b in data.segments for s in b.segments if _CJK.search(s.name or "")})
    if not names:
        return 0
    if lm is None:
        if not settings.llm.enabled:
            return 0
        from ..narrative.commentary import make_lm
        lm = make_lm(settings.llm, max_tokens=1500, thinking="disabled", step="research")
    try:
        with dspy.context(lm=lm, adapter=_adapter()):
            out = dspy.Predict(TranslateLabels)(company=f"{data.profile.name} ({data.profile.ticker})", labels=names)
        mapping = {x.original.strip(): x.english.strip() for x in (out.english or [])
                   if x.english and not _CJK.search(x.english) and len(x.english) <= 60}
    except Exception as e:
        log.warning("segment label translation failed: %s", e)
        return 0
    n = 0
    for b in data.segments:
        for s in b.segments:
            if s.name in mapping:
                s.name, n = mapping[s.name], n + 1
    return n
