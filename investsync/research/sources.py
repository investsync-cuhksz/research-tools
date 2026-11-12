"""Document collector for the research step: fetch and clean free documents, nothing else.

What an analyst reads besides the statements, from free official sources and free news:

* US         SEC EDGAR: the latest results 8-K (Item 2.02) EX-99.1 press release and EX-99.2 (often
             "CFO commentary", with the outlook), the previous quarter's too (guidance vs actual), and
             other material 8-Ks (agreements, deals, debt, impairments, management changes, other events)
* Hong Kong  HKEXnews: the newest results announcement in full + material announcements
* A-shares   CNINFO: the newest periodic report, investor-relations records (投资者关系活动记录表) and
             material announcements; EastMoney research-centre broker report PDFs (``broker_docs``)
* News       Bing News RSS (en / zh), article text fetched best effort (snippet kept when paywalled)

Every network call is a ``@cached`` function with a ``provenance.REGISTRY`` entry, so citations stay
automatic. Failed downloads return None (never cached) and are retried on the next run; one slow or
broken document never fails the whole call. Reading the documents is another module's job.
"""
from __future__ import annotations

import hashlib
import html as htmllib
import io
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Callable, Optional, Union
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import requests

from .. import provenance
from ..cache import cached
from ..config import settings
from ..data import filings as fl
from ..schema import Market
from ..tickers import Ticker, parse

log = logging.getLogger(__name__)


@dataclass
class Doc:
    id: str            # stable, short, unique: "sec-0001045810-26-000073-ex99-2", "hkex-<hash8>", "news-<hash8>"
    kind: str          # results_release | results_commentary | periodic_report | announcement | ir_record |
                       # broker_report | news
    title: str
    source: str        # "SEC EDGAR" | "HKEXnews" | "CNINFO" | "EastMoney research centre: <broker>" | "Bing News: <publisher>"
    published: date
    url: str
    lang: str          # "en" | "zh"
    text: str          # cleaned full text, capped; for news that can't be fetched, the snippet
    snippet: str = ""  # RSS description for news


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}
EM_PDF_HEADERS = {**BROWSER_HEADERS, "Referer": "https://data.eastmoney.com/"}

RESULTS_CHARS = 200_000       # results releases and periodic reports (a Q3 report is ~20k; an annual report is capped)
ANNOUNCEMENT_CHARS = 25_000
BROKER_CHARS = 30_000
NEWS_CHARS = 30_000
MAX_ANNOUNCEMENTS = 8
PREV_RESULTS_DAYS = 200       # the previous quarter's results 8-K: past guidance vs what happened
RESULTS_LOOKBACK_DAYS = 400   # newest results / periodic report when none falls inside ``days``
IR_DAYS = 200
BROKER_DAYS = 60
HK_RESULTS_PAGES = 70         # an HKEX results announcement runs 40-60 pages
FETCH_BUDGET = settings.filings_timeout + 120   # seconds per call; later documents are skipped this time
KINDS = ["results_release", "results_commentary", "periodic_report", "ir_record", "announcement",
         "broker_report", "news"]
KIND_GROUP = {"results_release": 0, "results_commentary": 0, "periodic_report": 0, "ir_record": 1,
              "announcement": 2, "broker_report": 3, "news": 4}


# ================================================================ text cleaning
_ZERO_WIDTH = re.compile(r"[​-‍⁠﻿­]")
_SPACES = re.compile(r"[ \t\r\f\v\xa0 -   　]+")
_PUA = re.compile(r"[-]")


def _tidy(text: str) -> str:
    """Collapse whitespace per line, drop empty and repeated consecutive lines (filings._clean, line-aware)."""
    text = _ZERO_WIDTH.sub("", text)
    lines: list[str] = []
    for line in text.split("\n"):
        line = _SPACES.sub(" ", line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n".join(lines)


def _cap(text: str, n: int) -> str:
    """At most ``n`` characters, cut at a line or sentence end, with a visible marker."""
    if len(text) <= n:
        return text
    cut = text[:n]
    end = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("。"))
    if end > n * 0.8:
        cut = cut[: end + 1]
    return cut.rstrip() + f"\n[… truncated: first {len(cut):,} of {len(text):,} characters]"


def _h8(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:8]


def _ws(s: Optional[str]) -> str:
    return " ".join((s or "").split())


# ---------------------------------------------------------------- HTML
_DROP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "svg",
              "button", "select", "template", "object", "title", "ix:header"}
_BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
               "section", "article", "main", "blockquote", "pre", "figcaption", "caption", "hr", "center",
               "address", "body", "td", "th"}
_HIDDEN = re.compile(r"display\s*:\s*none", re.I)
_LEFT_GLUE = {"$", "US$", "HK$", "€", "£", "¥", "(", "$(", "($"}
_RIGHT_GLUE = re.compile(r"[%)]+|\)%|pts?|bps?")


def _decode(content: bytes, content_type: str = "") -> str:
    m = re.search(r"charset=[\"']?([\w-]+)", content_type or "", re.I) or \
        re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", content[:4096], re.I)
    enc = m.group(1) if m else None
    if isinstance(enc, bytes):
        enc = enc.decode("ascii", "ignore")
    if enc and enc.lower() in ("gb2312", "gbk", "x-gbk"):
        enc = "gb18030"
    for e in (enc, "utf-8", "gb18030"):
        if not e:
            continue
        try:
            return content.decode(e)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace")


def _parse_html(raw: Union[str, bytes]):
    from lxml import html as lhtml
    if isinstance(raw, bytes):
        raw = _decode(raw)
    raw = re.sub(r"^\s*<\?xml[^>]*\?>", "", raw)  # lxml rejects str input with an encoding declaration
    raw = re.sub(r"(?is)^\s*<DOCUMENT>.*?<TEXT>", "", raw)  # EDGAR's SGML wrapper (type, sequence, filename)
    if not raw.strip():
        return None
    try:
        root = lhtml.document_fromstring(raw)
    except Exception:  # noqa: BLE001 - malformed markup only means no text
        return None
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        if tag == "form" and len(el.text_content()) > 1500:
            continue  # ASP.NET pages wrap the whole page in one <form>
        if tag in _DROP_TAGS or (tag not in ("html", "body") and _HIDDEN.search(el.get("style") or "")):
            if el.getparent() is not None:
                el.drop_tree()  # keeps the tail text
    return root


def _cells(tr) -> list[str]:
    out: list[str] = []
    pending = ""
    for td in tr.xpath("./td|./th"):
        buf: list[str] = []
        _inner(td, buf)
        c = _ws("".join(buf))
        if not c:
            continue
        if c in _LEFT_GLUE:           # "$" | "46,743"  ->  "$46,743"
            pending += c
            continue
        if out and _RIGHT_GLUE.fullmatch(c):  # "56" | "%"  ->  "56%"
            out[-1] += c
            continue
        out.append(pending + c)
        pending = ""
    if pending:
        out.append(pending)
    return out


def _table_text(table) -> str:
    rows = table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")
    return "\n".join(" | ".join(cells) for cells in map(_cells, rows) if cells)


def _walk(el, out: list[str]) -> None:
    if isinstance(el.tag, str):
        tag = el.tag.lower()
        if tag == "br":
            out.append("\n")
        elif tag == "table":
            out.append("\n" + _table_text(el) + "\n")
        else:
            block = tag in _BLOCK_TAGS
            if block:
                out.append("\n")
            _inner(el, out)
            if block:
                out.append("\n")
    if el.tail:
        out.append(el.tail)


def _inner(el, out: list[str]) -> None:
    if el.text and isinstance(el.tag, str):
        out.append(el.text)
    for ch in el:
        _walk(ch, out)


def _element_text(el) -> str:
    out: list[str] = []
    try:
        _inner(el, out)
        return _tidy("".join(out))
    except RecursionError:  # absurdly deep markup
        return _tidy(el.text_content())


def _article_text(root) -> str:
    """Main text of a news page: the largest <article>, else the page's <p> and <li> texts."""
    arts = list(root.iter("article"))
    if arts:
        text = _element_text(max(arts, key=lambda a: len(a.text_content())))
        if len(text) >= 400:
            return text
    parts: list[str] = []
    for el in root.iter("p", "li"):
        if next(el.iterancestors("p", "li"), None) is not None:
            continue  # counted with its parent
        txt = _ws(el.text_content())
        if len(txt) < 2:
            continue
        linked = sum(len(_ws(a.text_content())) for a in el.iter("a")) / len(txt)
        if (el.tag == "li" and (len(txt) < 15 or linked > 0.5)) or (el.tag == "p" and linked > 0.8):
            continue  # menus, link lists, "related stories"
        parts.append(txt)
    text = _tidy("\n".join(parts))
    return text if len(text) >= 200 else ""


def html_to_text(raw: Union[str, bytes], article: bool = False) -> str:
    """Readable text from HTML: scripts, styles, navigation, headers, footers and forms dropped; block
    elements on their own lines; table rows as ``cell | cell``. ``article=True`` (news pages) prefers the
    <article> element, else joins <p> and <li> texts; falls back to the whole body."""
    root = _parse_html(raw)
    if root is None:
        return ""
    if article:
        text = _article_text(root)
        if text:
            return text
    body = root.find("body")
    return _element_text(body if body is not None else root)


# ---------------------------------------------------------------- PDF
_PAGE_NO = re.compile(r"^(?:[-–—]\s*)?\d{1,3}(?:\s*[-–—])?$|^(?:page|p\.)\s*\d+(?:\s*(?:of|/)\s*\d+)?$|"
                      r"^第\s*\d+\s*页(?:\s*[,，/]?\s*共\s*\d+\s*页)?$|^\d{1,3}\s*/\s*\d{1,3}$", re.I)
_CJK = "㐀-䶿一-鿿"
_CJK_WIDE = _CJK + "　-〿＀-￯"
_CJK_SPACE = re.compile(f"(?<=[{_CJK_WIDE}]) +(?=[{_CJK_WIDE}])")
_WRAP_END = re.compile(f"[{_CJK}，、（“《]$")
_WRAP_START = re.compile(f"^[{_CJK}，。、；：）”》]")


def _norm_line(line: str) -> str:
    return re.sub(r"\d+", "#", _ws(line).lower())


def strip_page_furniture(pages: list[str], edge: int = 3) -> list[str]:
    """Drop page numbers and running headers / footers: lines near the top or bottom of a page that repeat
    (digits ignored) on at least 40% of the pages."""
    split = [[ln.strip() for ln in p.split("\n") if ln.strip()] for p in pages]
    n = len(split)
    counts: Counter = Counter()
    for lines in split:
        counts.update({_norm_line(ln) for ln in lines[:edge] + lines[-edge:]})
    repeated = {k for k, c in counts.items() if n >= 4 and c >= max(3, 0.4 * n) and len(k) >= 4}
    out = []
    for lines in split:
        keep = [ln for i, ln in enumerate(lines)
                if not ((i < edge or i >= len(lines) - edge) and (_PAGE_NO.match(ln) or _norm_line(ln) in repeated))]
        out.append("\n".join(keep))
    return out


_CJK_PUNCT = re.compile(r"[，。；：！？、]")


def _despace(line: str) -> str:
    """Remove spaces between Chinese characters in prose (stray kerning gaps, '第 三 季 度'); keep them in
    table and form lines, where they separate columns ('项目 本报告期 年初至报告期末')."""
    line = _ws(line)
    tokens = [tok for tok in line.split(" ") if re.search(f"[{_CJK}]", tok)]
    char_spaced = tokens and sum(map(len, tokens)) / len(tokens) <= 2.5
    return _CJK_SPACE.sub("", line) if char_spaced or _CJK_PUNCT.search(line) else line


def fix_cjk(text: str) -> str:
    """Undo PDF extraction artefacts in Chinese text: spaces inside sentences, and lines wrapped mid-
    sentence (joined when the line is close to the full line width, both sides are Chinese and the line
    is not a table row)."""
    lines = [_despace(ln) for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    widths = sorted(len(ln) for ln in lines if re.search(f"[{_CJK}]", ln))
    if not widths:
        return "\n".join(lines)
    full = widths[int(len(widths) * 0.8)]
    out: list[str] = []
    prev = ""
    for ln in lines:
        if (out and len(prev) >= 0.8 * full and _WRAP_END.search(prev) and _WRAP_START.match(ln)
                and not _CJK_SPACE.search(prev)):
            out[-1] += ln
        else:
            out.append(ln)
        prev = ln
    return "\n".join(out)


def _cjk_share(text: str) -> float:
    sample = text[:20000]
    return len(re.findall(f"[{_CJK}]", sample)) / max(1, len(sample))


def pdf_to_text(content: bytes, max_pages: int = 80, lang: Optional[str] = None) -> str:
    """Like filings.pdf_text, page-aware: page numbers and running headers removed, Chinese re-flowed."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for p in reader.pages[:max_pages]:
        try:
            pages.append(p.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page only loses that page
            pages.append("")
    text = "\n".join(strip_page_furniture(pages))
    text = _PUA.sub(lambda m: "■" if m.group() == "" else "", text)  # Wingdings ticked box in CN forms
    if lang == "zh" or (lang is None and _cjk_share(text) > 0.15):
        text = fix_cjk(text)
    return _tidy(text)


def _is_pdf(content: bytes, content_type: str = "") -> bool:
    return content[:5] == b"%PDF-" or "pdf" in (content_type or "").lower()


def response_text(content: bytes, content_type: str = "", article: bool = False, max_pages: int = 80,
                  lang: Optional[str] = None) -> str:
    """Bytes of a download -> text: PDF (by header or content type), HTML, or plain text."""
    ct = (content_type or "").lower()
    if _is_pdf(content, ct):
        return pdf_to_text(content, max_pages=max_pages, lang=lang)
    if any(x in ct for x in ("image/", "video/", "audio/", "zip", "octet-stream")):
        return ""
    if "text/plain" in ct:
        return _tidy(_decode(content, ct))
    return html_to_text(_decode(content, ct), article=article)


# ================================================================ downloads (cached; None = failed, not cached)
_SEC_GAP = 1 / 8          # SEC fair access: at most 8 requests a second from this process
_sec_lock = threading.Lock()
_sec_next = [0.0]


def _sec_get(url: str, timeout: int = 60) -> requests.Response:
    with _sec_lock:
        delay = _sec_next[0] - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _sec_next[0] = time.monotonic() + _SEC_GAP
    return fl._get(url, headers=fl.SEC_HEADERS, timeout=timeout)


def _download_text(url: str, *, headers: dict, timeout: int, tries: int = 2, max_pages: int = 80,
                   lang: Optional[str] = None, article: bool = False) -> Optional[str]:
    r = fl._get(url, tries=tries, headers=headers, timeout=timeout)
    text = response_text(r.content, r.headers.get("content-type", ""), article=article, max_pages=max_pages,
                         lang=lang)
    return text or None


@cached("financials")  # a filed document does not change
def sec_filing_index(cik: int, accession: str) -> Optional[list[dict]]:
    """Documents in one EDGAR filing (seq, description, type such as EX-99.1, url)."""
    nodash = accession.replace("-", "")
    r = _sec_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{accession}-index.htm")
    return parse_sec_index(r.text) or None


@cached("financials")
def sec_document(url: str) -> Optional[str]:
    """Full text of one EDGAR document (8-K, exhibit)."""
    r = _sec_get(url)
    text = response_text(r.content, r.headers.get("content-type", ""))
    return text or None


@cached("financials")
def hkex_document(url: str, max_pages: int = 25) -> Optional[str]:
    """Full text of one HKEXnews document (PDF or HTML). Generous timeout: slow from mainland networks."""
    return _download_text(url, headers=BROWSER_HEADERS, timeout=settings.filings_timeout, max_pages=max_pages,
                          lang="en")


@cached("financials")
def cninfo_document(url: str, max_pages: int = 25) -> Optional[str]:
    """Full text of one CNINFO announcement PDF."""
    return _download_text(url, headers=BROWSER_HEADERS, timeout=min(settings.filings_timeout, 180),
                          max_pages=max_pages, lang="zh")


@cached("news")
def cninfo_ir_records(code: str, start: str, end: str) -> Optional[list[dict]]:
    """Investor-relations activity records (投资者关系活动记录表) of an A-share, newest first."""
    import akshare as ak
    df = ak.stock_zh_a_disclosure_relation_cninfo(symbol=code, market="沪深京", start_date=start, end_date=end)
    out = []
    for _, r in df.iterrows():
        q = parse_qs(urlparse(str(r["公告链接"])).query)
        ann, day = q.get("announcementId", [None])[0], str(r["公告时间"])[:10]
        if ann:
            out.append({"date": day, "title": str(r["公告标题"]).strip(),
                        "url": f"http://static.cninfo.com.cn/finalpage/{day}/{ann}.PDF"})
    return out or None


@cached("financials")
def em_report_text(info_code: str) -> Optional[str]:
    """Full text of one broker report PDF hosted by EastMoney (disclaimer pages trimmed)."""
    text = _download_text(f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf", headers=EM_PDF_HEADERS,
                          timeout=90, max_pages=40, lang="zh")
    return trim_disclaimer(text) if text else None


@cached("news")
def bing_news_rss(query: str, sort: str = "relevance") -> Optional[list[dict]]:
    """Bing News RSS search results (title, url, description, published, source). sort: relevance | date."""
    url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"
    if sort == "date":
        url += "&qft=" + quote('sortbydate="1"')
    r = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    r.raise_for_status()
    return parse_bing_rss(r.content) or None


@cached("financials")  # an article's text rarely changes; failures are not cached
def web_text(url: str) -> Optional[str]:
    """Readable text of a web page or PDF (news articles: the article body)."""
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("sec.gov"):
        r = _sec_get(url)
    else:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=25, allow_redirects=True)
        r.raise_for_status()
    official = host.endswith(("sec.gov", "hkexnews.hk", "cninfo.com.cn", "dfcfw.com"))
    text = response_text(r.content, r.headers.get("content-type", ""), article=not official)
    return text or None


def fetch_text(url: str, max_chars: int = 60000) -> str:
    """HTML -> readable text, PDF -> text; "" on any failure (never raises)."""
    try:
        return _cap(web_text(url) or "", max_chars)
    except Exception as e:  # noqa: BLE001 - best effort by design
        log.info("fetch_text %s failed: %s", url, type(e).__name__)
        return ""


def _run(jobs: list[Callable[[], object]], budget: float = FETCH_BUDGET, workers: int = 4) -> list[Doc]:
    """Run document jobs in parallel; a failing job is logged and skipped, jobs still running after
    ``budget`` seconds are skipped this time (their downloads still land in the cache)."""
    if not jobs:
        return []

    def safe(job):
        try:
            return job()
        except Exception as e:  # noqa: BLE001 - one document never fails the call
            log.info("document skipped: %s: %s", type(e).__name__, e)
            return None

    pool = ThreadPoolExecutor(max_workers=min(workers, len(jobs)), thread_name_prefix="research-docs")
    futures = [provenance.submit(pool, safe, job) for job in jobs]
    done, pending = wait_futures(futures, timeout=budget)
    pool.shutdown(wait=False, cancel_futures=True)
    if pending:
        log.warning("%d document(s) not ready after %.0f s; skipped this time", len(pending), budget)
    out: list[Doc] = []
    for f in futures:
        if f in done:
            v = f.result()
            out.extend(v if isinstance(v, list) else [v] if v else [])
    return out


# ================================================================ US: SEC EDGAR
MATERIAL_8K = {"1.01", "1.02", "1.05", "2.01", "2.03", "2.04", "2.05", "2.06", "3.01", "4.02", "5.02",
               "7.01", "8.01"}
ITEM_NAMES = {
    "1.01": "Entry into a Material Definitive Agreement", "1.02": "Termination of a Material Definitive Agreement",
    "1.05": "Material Cybersecurity Incident", "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition", "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate a Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities", "2.06": "Material Impairments",
    "3.01": "Notice of Delisting", "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.02": "Departure / Election of Directors or Officers", "5.07": "Shareholder Vote",
    "7.01": "Regulation FD Disclosure", "8.01": "Other Events", "9.01": "Financial Statements and Exhibits",
}


def parse_sec_index(page: Union[str, bytes]) -> list[dict]:
    """Rows of the 'Document Format Files' table of an EDGAR ``-index.htm`` page."""
    from lxml import html as lhtml
    if isinstance(page, bytes):
        page = _decode(page)
    try:
        tree = lhtml.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", page))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for table in tree.xpath('//table[contains(@class, "tableFile")]'):
        if "data files" in (table.get("summary") or "").lower():
            continue  # XBRL files
        for tr in table.xpath(".//tr[td]"):
            tds = tr.xpath("./td")
            hrefs = tds[2].xpath(".//a/@href") if len(tds) >= 4 else []
            if not hrefs:
                continue
            href = hrefs[0].split("/ix?doc=")[-1]
            out.append({"seq": _ws(tds[0].text_content()), "description": _ws(tds[1].text_content()),
                        "type": _ws(tds[3].text_content()).upper(), "document": href.rsplit("/", 1)[-1],
                        "url": "https://www.sec.gov" + href if href.startswith("/") else href})
    return out


def exhibit_no(doc_type: str) -> Optional[str]:
    """'EX-99.1' / 'EX-99.01' / 'EX-99' -> '1'; 'EX-99.2' -> '2'; anything else -> None."""
    m = re.fullmatch(r"EX-99(?:\.(\d+))?[A-Z]?", (doc_type or "").strip().upper())
    return None if not m else str(int(m.group(1))) if m.group(1) else "1"


def _accession(url: str) -> Optional[str]:
    m = re.search(r"/data/\d+/(\d{18})/", url)
    n = m.group(1) if m else None
    return f"{n[:10]}-{n[10:12]}-{n[12:]}" if n else None


def _items(row: dict) -> set[str]:
    return {x.strip() for x in str(row.get("items") or "").split(",") if x.strip()}


def _headline(text: str) -> str:
    """First line that reads like a title (the press release headline, 'CFO Commentary on ...')."""
    for line in text.split("\n")[:30]:
        ln = line.strip(" |")
        if not 15 <= len(ln) <= 200 or "|" in ln:
            continue
        if re.match(r"(?i)^(exhibit|ex-)\s*99|^(for immediate release|news release|press release|"
                    r"media contact|investor contact|contacts?:)", ln):
            continue
        if sum(c.isalpha() for c in ln) >= 0.6 * len(ln):
            return ln[:160]
    return ""


def eight_k_body(text: str) -> str:
    """The items of an 8-K without the cover page (checkboxes, addresses) and the signature block."""
    m = re.search(r"(?im)^\s*item\s+\d\.\d{2}\b", text)
    if m:
        text = text[m.start():]
    s = re.search(r"(?m)^\s*SIGNATURES?\s*$", text)
    return text[: s.start()].strip() if s else text.strip()


def _sec_results_docs(cik: int, row: dict, previous: bool) -> list[Doc]:
    acc = _accession(row["url"])
    if not acc:
        return []
    out, seen = [], set()
    for ex in sec_filing_index(cik, acc) or []:
        n = exhibit_no(ex["type"])
        if n not in ("1", "2") or n in seen:
            continue
        seen.add(n)
        text = sec_document(ex["url"]) or ""
        if not text:
            continue
        what = "earnings press release" if n == "1" else "results commentary"
        when = "previous quarter, " if previous else ""
        out.append(Doc(id=f"sec-{acc}-ex99-{n}", kind="results_release" if n == "1" else "results_commentary",
                       title=f"{_headline(text) or what.capitalize()} ({when}8-K filed {row['date']}, EX-99.{n})",
                       source="SEC EDGAR", published=date.fromisoformat(row["date"]), url=ex["url"], lang="en",
                       text=_cap(text, RESULTS_CHARS)))
    return out


def _sec_event_doc(cik: int, row: dict) -> Optional[Doc]:
    acc = _accession(row["url"])
    if not acc:
        return None
    body = eight_k_body(sec_document(row["url"]) or "")
    ex1 = next((e for e in sec_filing_index(cik, acc) or [] if exhibit_no(e["type"]) == "1"), None)
    ex_text = (sec_document(ex1["url"]) or "") if ex1 else ""
    if not body and not ex_text:
        return None
    items = sorted(_items(row) - {"9.01"})
    title = f"8-K filed {row['date']}: " + "; ".join(f"Item {i} {ITEM_NAMES.get(i, '')}".strip() for i in items)
    if ex_text and _headline(ex_text):
        title += f" — {_headline(ex_text)}"
    text = body + (f"\n\nExhibit 99.1\n{ex_text}" if ex_text else "")
    return Doc(id=f"sec-{acc}-8k", kind="announcement", title=title, source="SEC EDGAR",
               published=date.fromisoformat(row["date"]), url=row["url"], lang="en",
               text=_cap(text.strip(), ANNOUNCEMENT_CHARS))


def _us_jobs(t: Ticker, today: date, days: int) -> list[Callable]:
    cik = fl.sec_cik(t.code)
    if not cik:
        return []
    rows = [r for r in fl.sec_recent_filings(cik) or []
            if r["form"] in ("8-K", "8-K/A") and r["date"] <= today.isoformat()]
    jobs: list[Callable] = []
    results = [r for r in rows if "2.02" in _items(r)]
    if results:
        jobs.append(partial(_sec_results_docs, cik, results[0], False))
    if len(results) > 1 and (today - date.fromisoformat(results[1]["date"])).days <= PREV_RESULTS_DAYS:
        jobs.append(partial(_sec_results_docs, cik, results[1], True))
    since = (today - timedelta(days=days)).isoformat()
    events = [r for r in rows if r["date"] >= since and "2.02" not in _items(r) and _items(r) & MATERIAL_8K]
    jobs += [partial(_sec_event_doc, cik, r) for r in events[:MAX_ANNOUNCEMENTS]]
    return jobs


# ================================================================ Hong Kong: HKEXnews
_HK_RESULTS_CAT = re.compile(r"\b(?:FINAL|INTERIM|QUARTERLY) RESULTS\b")
_HK_RESULTS_TITLE = re.compile(r"\bRESULTS\b|EARNINGS RELEASE")
_HK_NOT_RESULTS = re.compile(r"POLL|GENERAL MEETING|BOARD MEETING|BOOK CLOSURE|CLOSURE OF REGISTER|"
                             r"RESULTS? OF (?:THE )?(?:\w+ )?(?:OFFER|ISSUE|PLACING|SUBSCRIPTION|TENDER|EXCHANGE|"
                             r"CONSENT|ALLOTMENT|ELECTION|VOTING|MEETING|RIGHTS)")
_HK_SKIP = re.compile(
    r"NEXT DAY DISCLOSURE|MONTHLY RETURN|PROXY|LIST OF DIRECTORS|GENERAL MEETING|CIRCULAR|BOARD MEETING|"
    r"CLOSURE OF REGISTER|BOOK CLOSURE|NOTIFICATION LETTER|NOTICE OF LISTING|FORMAL NOTICE|PRICING SUPPLEMENT|"
    r"CONSTITUTIONAL|ARTICLES OF ASSOCIATION|MEMORANDUM AND ARTICLES|TERMS OF REFERENCE|ANNUAL REPORT|"
    r"INTERIM REPORT|\bESG\b|ENVIRONMENTAL, SOCIAL|SUSTAINABILITY REPORT|PRINCIPAL PLACE OF BUSINESS|"
    r"SHARE REGISTRAR|AUTHORI[SZ]ED REPRESENTATIVE|ELECTRONIC COMMUNICATION|DEBT AND STRUCTURED PRODUCTS|"
    r"FINANCIAL STATEMENTS/ESG|COMPANY INFORMATION SHEET|DOCUMENTS ON DISPLAY")
_HK_KEEP = [
    (3, re.compile(r"INSIDE INFORMATION|PROFIT WARNING|PROFIT ALERT|POSITIVE PROFIT|MAJOR TRANSACTION|"
                   r"VERY SUBSTANTIAL|DISCLOSEABLE TRANSACTION|CONNECTED TRANSACTION|ACQUISITION|DISPOSAL|TAKEOVER|"
                   r"PRIVATI[SZ]ATION|SPIN-OFF|MERGER|LITIGATION|ARBITRATION|INVESTIGATION|SUSPENSION|RESUMPTION|"
                   r"TRADING HALT|BUSINESS UPDATE|OPERATIONAL UPDATE|OPERATING DATA")),
    (2, re.compile(r"VOLUNTARY ANNOUNCEMENT|ISSUE OF|\bNOTES\b|\bBONDS?\b|DEBT SECURITIES|PLACING|SUBSCRIPTION|"
                   r"BUY-?BACK|REPURCHASE|CHANGE (?:IN|OF) (?:DIRECTOR|CHIEF|CHAIR|COMPOSITION|EXECUTIVE|SENIOR|"
                   r"MANAGEMENT|AUDITOR)|APPOINTMENT|RESIGNATION|RETIREMENT|STRATEGIC|AGREEMENT|COOPERATION|"
                   r"CONVERTIBLE|JOINT VENTURE|CAPITAL REDUCTION|FINANCIAL ASSISTANCE|GUARANTEE")),
    (1, re.compile(r"SHARE AWARD|SHARE OPTION|GRANT OF|OVERSEAS REGULATORY|ANNOUNCEMENT")),
]


def classify_hk(title: str, category: str = "") -> tuple[str, int]:
    """HKEXnews document -> ("results" | "announcement" | "skip", priority). Results: 2 when HKEX tags it
    as final / interim / quarterly results, 1 when only the title says so."""
    t = htmllib.unescape(title or "").upper()
    c = htmllib.unescape(category or "").upper()
    routine = any(x in c for x in ("NEXT DAY", "MONTHLY RETURN", "FINANCIAL STATEMENTS", "DEBT AND STRUCTURED"))
    if not routine and not _HK_NOT_RESULTS.search(t):
        if _HK_RESULTS_CAT.search(c):
            return "results", 2
        if _HK_RESULTS_TITLE.search(t):
            return "results", 1
    if _HK_SKIP.search(t) or _HK_SKIP.search(c):
        return "skip", 0
    for prio, pat in _HK_KEEP:
        if pat.search(t) or pat.search(c):
            return "announcement", prio
    return "skip", 0


def _newest(rows: list[dict], classify: Callable[[dict], tuple[str, int]], kind: str) -> Optional[dict]:
    hits = [(classify(r)[1], r["date"], r) for r in rows if classify(r)[0] == kind]
    if not hits:
        return None
    best = max(p for p, _, _ in hits)  # HKEX-tagged results before title-only matches
    return max((h for h in hits if h[0] == best), key=lambda h: h[1])[2]


def _pick_material(rows: list[dict], classify: Callable[[dict], tuple[str, int]], n: int) -> list[dict]:
    scored = [(classify(r)[1], r["date"], r) for r in rows if classify(r)[0] == "announcement"]
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return sorted((r for _, _, r in scored[:n]), key=lambda r: r["date"], reverse=True)


def _hk_doc(row: dict, kind: str, max_pages: int, cap: int) -> Optional[Doc]:
    text = hkex_document(row["url"], max_pages) or ""
    if not text:
        return None
    return Doc(id=f"hkex-{_h8(row['url'])}", kind=kind, title=htmllib.unescape(row["title"]), source="HKEXnews",
               published=date.fromisoformat(row["date"]), url=row["url"], lang="en", text=_cap(text, cap))


def _hk_jobs(t: Ticker, today: date, days: int) -> list[Callable]:
    sid = fl.hkex_stock_id(t.code)
    if not sid:
        return []
    fmt, end = "%Y%m%d", today.strftime("%Y%m%d")
    rows = fl.hkex_announcements(sid, (today - timedelta(days=days)).strftime(fmt), end) or []
    hk = lambda r: classify_hk(r["title"], r.get("category", ""))  # noqa: E731
    res = _newest(rows, hk, "results")
    if res is None:  # semi-annual reporters: the last results can be older than ``days``
        wider = fl.hkex_announcements(sid, (today - timedelta(days=RESULTS_LOOKBACK_DAYS)).strftime(fmt), end) or []
        res = _newest(wider, hk, "results")
    jobs: list[Callable] = []
    if res:
        jobs.append(partial(_hk_doc, res, "results_release", HK_RESULTS_PAGES, RESULTS_CHARS))
    jobs += [partial(_hk_doc, r, "announcement", 25, ANNOUNCEMENT_CHARS)
             for r in _pick_material(rows, hk, MAX_ANNOUNCEMENTS)]
    return jobs


# ================================================================ A-shares: CNINFO
_CN_PERIODIC = re.compile(r"(?:年度报告|半年度报告|季度报告)(?:全文)?(?:[（(][^）)]*[）)])?$")
_CN_PERIODIC_SKIP = re.compile(r"摘要|英文|更正|取消|提示性|问询|回复|说明|意见|审核|H股")
_CN_SKIP = re.compile(
    r"董事会决议|董事会会议决议|监事会|法律意见|独立董事|股东(?:大)?会(?:的)?通知|召开.{0,30}股东(?:大)?会|"
    r"股东(?:大)?会决议|核查意见|工作细则|管理办法|议事规则|制度|章程|摘要|英文|更正|取消|H股公告|翌日披露|月报表|"
    r"董事会会议召开日期|保荐|鉴证|审计报告|内部控制|社会责任|ESG|可持续发展|前十名|自主行权|注销|作废|归属结果|"
    r"上市流通|募集资金存放|资金占用|合规性|自查|^《")
_CN_KEEP = [
    (3, re.compile(r"业绩预告|业绩快报|业绩预增|业绩预减|业绩预亏|重大资产|重组|收购|出售|诉讼|仲裁|处罚|立案|调查|"
                   r"重大合同|中标|战略合作|停牌|复牌|风险提示|澄清|控制权|要约|退市|回购|增持|减持")),
    (2, re.compile(r"发行|债券|投资|合作|担保|关联|财务资助|签订|签署|合同|项目|产能|扩产|分红|"
                   r"利润分配|权益分派|辞职|离任|选举|聘任|变更|董事长|总经理|可转债|定增|向特定对象|股权激励")),
    (1, re.compile(r"进展|员工持股|激励|授予|行权|期权|^关于.*公告$")),
]
_CN_ROUTINE = re.compile(r"进展|备案")   # progress updates and routine filings rank one level lower


def classify_cn(title: str) -> tuple[str, int]:
    """CNINFO announcement title -> ("periodic" | "ir" | "announcement" | "skip", priority)."""
    t = _ws(title)
    if "投资者关系活动记录" in t:
        return "ir", 1
    if _CN_PERIODIC.search(t) and not _CN_PERIODIC_SKIP.search(t):
        return "periodic", 1
    if _CN_SKIP.search(t):
        return "skip", 0
    for prio, pat in _CN_KEEP:
        if pat.search(t):
            return "announcement", max(prio - 1, 1) if _CN_ROUTINE.search(t) else prio
    return "skip", 0


def _cn_periodic_pages(title: str) -> int:
    if "半年度报告" in title:
        return 80
    return 100 if "年度报告" in title else 40


def _cn_doc(row: dict, kind: str, max_pages: int, cap: int) -> Optional[Doc]:
    text = cninfo_document(row["url"], max_pages) or ""
    if not text:
        return None
    m = re.search(r"/(\d+)\.PDF", row["url"], re.I)
    return Doc(id=f"cninfo-{m.group(1) if m else _h8(row['url'])}", kind=kind, title=row["title"], source="CNINFO",
               published=date.fromisoformat(row["date"][:10]), url=row["url"], lang="zh", text=_cap(text, cap))


def _cn_jobs(t: Ticker, today: date, days: int) -> list[Callable]:
    fmt, end = "%Y%m%d", today.strftime("%Y%m%d")

    def listing(fn, start_days):
        try:
            return fn(t.code, (today - timedelta(days=start_days)).strftime(fmt), end) or []
        except Exception as e:  # noqa: BLE001 - one listing failing leaves the others
            log.warning("CNINFO %s unavailable for %s: %s", fn.__name__, t.code, type(e).__name__)
            return []

    rows = listing(fl.cninfo_announcements, days)
    cn = lambda r: classify_cn(r["title"])  # noqa: E731
    periodic = _newest(rows, cn, "periodic") or _newest(listing(fl.cninfo_announcements, RESULTS_LOOKBACK_DAYS),
                                                         cn, "periodic")
    ir = listing(cninfo_ir_records, max(days, IR_DAYS))
    ir_rows = {r["url"]: r for r in ir + [r for r in rows if cn(r)[0] == "ir"]}
    ir_rows = sorted(ir_rows.values(), key=lambda r: r["date"], reverse=True)[:2]
    jobs: list[Callable] = []
    if periodic:
        jobs.append(partial(_cn_doc, periodic, "periodic_report", _cn_periodic_pages(periodic["title"]), RESULTS_CHARS))
    jobs += [partial(_cn_doc, r, "ir_record", 20, ANNOUNCEMENT_CHARS) for r in ir_rows]
    jobs += [partial(_cn_doc, r, "announcement", 20, ANNOUNCEMENT_CHARS)
             for r in _pick_material(rows, cn, MAX_ANNOUNCEMENTS)]
    return jobs


# ================================================================ entry points
def _ticker(t: Union[Ticker, str]) -> Ticker:
    return parse(t) if isinstance(t, str) else t


def _order(docs: list[Doc]) -> list[Doc]:
    """Results / periodic report first, then IR records, then announcements; newest first in each group."""
    uniq = list({d.id: d for d in docs}.values())
    return sorted(uniq, key=lambda d: (KIND_GROUP.get(d.kind, 9), -d.published.toordinal(),
                                       KINDS.index(d.kind) if d.kind in KINDS else 99))


def primary_docs(t: Union[Ticker, str], today: Optional[date] = None, days: int = 120) -> list[Doc]:
    """Official documents of the last ``days``: results release / commentary or periodic report, IR records
    (A-shares) and material announcements. Never raises; missing sources give fewer documents."""
    t, today = _ticker(t), today or date.today()
    make = {Market.US: _us_jobs, Market.HK: _hk_jobs, Market.CN: _cn_jobs}[t.market]
    try:
        jobs = make(t, today, days)
    except Exception as e:  # noqa: BLE001 - listing failed: no documents this time
        log.warning("primary documents unavailable for %s: %s: %s", t.canonical, type(e).__name__, e)
        return []
    return _order(_run(jobs))


def trim_disclaimer(text: str) -> str:
    """Drop a broker report's closing disclaimer / rating-definition pages (second half only)."""
    pat = re.compile(r"(?im)^(?:[一二三四五六七八九十\d]+[、.．]\s*)?(?:免责声明|分析师声明|分析师承诺|证券分析师承诺|"
                     r"分析师(?:与研究助理)?简介|投资评级说明|评级说明|评级体系|评级定义|分析员披露|分析员声明|重要声明|法律声明|"
                     r"特别声明|一般声明|"
                     r"disclaimer|analyst certification|important disclosures)")
    m = next((m for m in pat.finditer(text) if m.start() >= len(text) * 0.5), None)
    return text[: m.start()].rstrip() if m else text


def _broker_doc(row: dict) -> Optional[Doc]:
    code = row["infoCode"]
    text = em_report_text(code) or ""
    if not text:
        return None
    broker = _ws(row.get("orgSName") or row.get("orgName") or "broker")
    return Doc(id=f"em-{code}", kind="broker_report", title=_ws(row.get("title")) or f"{broker} report",
               source=f"EastMoney research centre: {broker}",
               published=datetime.strptime(str(row["publishDate"])[:10], "%Y-%m-%d").date(),
               url=f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf", lang="zh", text=_cap(text, BROKER_CHARS))


def broker_docs(t: Union[Ticker, str], today: Optional[date] = None, limit: int = 5) -> list[Doc]:
    """Full texts of the newest ``limit`` broker reports (A-shares, EastMoney, last 60 days); [] elsewhere."""
    t, today = _ticker(t), today or date.today()
    if t.market != Market.CN:
        return []
    from ..data import sources as src
    try:
        rows = src.em_research_reports(t.code, (today - timedelta(days=BROKER_DAYS)).isoformat(),
                                       today.isoformat()) or []
    except Exception as e:  # noqa: BLE001
        log.warning("broker report list unavailable for %s: %s", t.canonical, type(e).__name__)
        return []
    rows = sorted((r for r in rows if r.get("infoCode") and r.get("publishDate")),
                  key=lambda r: str(r["publishDate"]), reverse=True)
    seen: set[str] = set()
    picked = [r for r in rows if not (r["infoCode"] in seen or seen.add(r["infoCode"]))][:limit]
    docs = _run([partial(_broker_doc, r) for r in picked], budget=240)
    return sorted(docs, key=lambda d: d.published, reverse=True)


# ================================================================ news: Bing News RSS
PAYWALLED = ("bloomberg.com", "reuters.com", "wsj.com", "ft.com", "barrons.com", "economist.com", "nikkei.com",
             "theinformation.com", "seekingalpha.com", "caixinglobal.com", "nytimes.com", "washingtonpost.com",
             "scmp.com")


def unwrap_bing_url(link: str) -> str:
    """The article URL inside Bing's ``apiclick.aspx?...&url=<encoded>`` redirect link."""
    u = (parse_qs(urlparse(link or "").query).get("url") or [""])[0]
    return u if u.startswith(("http://", "https://")) else (link or "")


def _rss_date(s: Optional[str]) -> Optional[datetime]:
    try:
        d = parsedate_to_datetime(s or "")
    except (TypeError, ValueError, IndexError):
        return None
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_bing_rss(xml: Union[str, bytes]) -> list[dict]:
    """Items of a Bing News RSS feed: title, url (unwrapped), description, published (UTC), source."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        source = next((_ws(c.text) for c in it if isinstance(c.tag, str) and c.tag.rsplit("}", 1)[-1].lower() == "source"), "")
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
        out.append({"title": _ws(htmllib.unescape(it.findtext("title") or "")),
                    "url": unwrap_bing_url((it.findtext("link") or "").strip()),
                    "description": _ws(htmllib.unescape(desc)),
                    "published": _rss_date(it.findtext("pubDate")), "source": source})
    return out


def _title_key(title: str) -> str:
    return re.sub(f"[^0-9a-z{_CJK}]", "", title.lower())


def select_news(items: list[dict], days: int, limit: int, now: Optional[datetime] = None) -> list[dict]:
    """Items within ``days``, de-duplicated by URL and normalised title (one title containing the other
    counts as the same story), the first ``limit`` in search order, returned newest first."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    keep: list[dict] = []
    urls: set[str] = set()
    keys: list[str] = []
    for it in items:
        when, url, key = it.get("published"), it.get("url") or "", _title_key(it.get("title") or "")
        if when is None or when < since or when > now + timedelta(days=1) or not url or not key:
            continue
        if url in urls or any(key == k or (min(len(key), len(k)) >= 12 and (key in k or k in key)) for k in keys):
            continue
        urls.add(url)
        keys.append(key)
        keep.append(it)
        if len(keep) >= limit:
            break
    return sorted(keep, key=lambda x: x["published"], reverse=True)


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _relevant(text: str, title: str) -> bool:
    """Fetched page is the article, not a cookie wall or a home page: shares enough words with the title."""
    head = text[:6000].lower()
    zh = re.findall(f"[{_CJK}]{{2}}", title)
    if len(zh) >= 3:
        toks = {title[i:i + 2] for i in range(len(title) - 1) if re.fullmatch(f"[{_CJK}]{{2}}", title[i:i + 2])}
    else:
        toks = {w for w in re.findall(r"[a-z0-9]{4,}", title.lower())}
    return not toks or sum(tok.lower() in head for tok in toks) >= 0.3 * len(toks)


def _news_doc(it: dict, lang: str) -> Doc:
    publisher = it.get("source") or _host(it["url"])
    return Doc(id=f"news-{_h8(it['url'])}", kind="news", title=it["title"], source=f"Bing News: {publisher}",
               published=it["published"].date(), url=it["url"], lang=lang, text=it.get("description") or "",
               snippet=it.get("description") or "")


def _fill_article(doc: Doc) -> Doc:
    if _host(doc.url).endswith(PAYWALLED):
        return doc
    text = fetch_text(doc.url, NEWS_CHARS)
    return replace(doc, text=text) if len(text) >= 300 and _relevant(text, doc.title) else doc


FEED_DAYS = 30   # the company news feed: stories this recent are read in full
FEED_MAX = 24


def feed_docs(items: list, today: date, days: int = FEED_DAYS, limit: int = FEED_MAX, fetch: bool = True) -> list[Doc]:
    """Run 3 (12 Nov 2026): the report's own news feed (finnhub / Yahoo for US listings, EastMoney for Hong Kong and
    A-shares), already limited to the approved outlets, read as full articles. Run 2 read only its Bing searches; the
    feed's stories reached the writers as headlines, so a detail given only in an article's body (the executive named
    in the CEO story) never reached the report. Newest first, within ``days``; the article text is fetched where the
    site allows it (paywalled sites keep the summary). Never raises."""
    docs: list[Doc] = []
    seen: set[str] = set()

    def day(n) -> Optional[date]:
        p = getattr(n, "published", None)
        return p.date() if isinstance(p, datetime) else p

    for n in sorted((n for n in items or [] if day(n)), key=day, reverse=True):
        url, pub = getattr(n, "url", "") or "", day(n)
        if not url or url in seen or (today - pub).days > days or pub > today:
            continue
        seen.add(url)
        summary = (getattr(n, "summary", "") or "").strip()
        title = n.title or ""
        docs.append(Doc(id=f"feed-{_h8(url)}", kind="news", title=title,
                        source=f"News feed: {getattr(n, 'source', '') or _host(url)}", published=pub, url=url,
                        lang="zh" if re.search(f"[{_CJK}]", title) else "en", text=summary or title, snippet=summary))
        if len(docs) >= limit:
            break
    if fetch and docs:
        filled = {d.id: d for d in _run([partial(_fill_article, d) for d in docs], budget=120, workers=6)}
        docs = [filled.get(d.id, d) for d in docs]
    return docs


def news_search(query: str, lang: str = "en", days: int = 90, limit: int = 8, fetch: bool = True,
                keep: Optional[Callable[[str, str], bool]] = None) -> list[Doc]:
    """Bing News search: relevance-ranked results (date-sorted results fill in), within ``days``,
    de-duplicated, newest first. ``fetch``: article text, best effort; paywalled or unreadable pages keep
    the RSS snippet as ``text``. ``keep(source, url)``: only these outlets count toward ``limit`` (the research
    desk passes the team's news list, so up to ``limit`` approved stories are read). Never raises."""
    items: list[dict] = []
    for sort in ("relevance", "date"):
        try:
            items += bing_news_rss(query, sort) or []
        except Exception as e:  # noqa: BLE001
            log.info("Bing News (%s) failed for %r: %s", sort, query, type(e).__name__)
    if keep is not None:
        items = [it for it in items if keep(it.get("source") or "", it.get("url") or "")]
    docs = [_news_doc(it, lang) for it in select_news(items, days, limit)]
    if fetch and docs:
        filled = {d.id: d for d in _run([partial(_fill_article, d) for d in docs], budget=120, workers=6)}
        docs = [filled.get(d.id, d) for d in docs]
    return docs
