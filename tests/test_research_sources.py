"""Document collector for the research step (offline: inline samples, network functions patched)."""
import pickle
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime

from investsync.data import filings as fl
from investsync.research import sources as rs

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------- news: Bing RSS
def _rss(items: list[tuple]) -> str:
    """items: (title, article url or None, description, pubDate or None, source or None)."""
    from urllib.parse import quote
    out = []
    for title, url, desc, when, source in items:
        link = ("http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=abc&amp;url="
                + quote(url, safe="") + "&amp;c=123&amp;mkt=en-sg") if url else ""
        out.append(f"<item><title>{title}</title><link>{link}</link><description>{desc}</description>"
                   + (f"<pubDate>{when}</pubDate>" if when else "")
                   + (f"<News:Source>{source}</News:Source>" if source else "") + "</item>")
    return ('<?xml version="1.0" encoding="utf-8" ?><rss version="2.0" '
            'xmlns:News="https://www.bing.com/news/search?q=CATL&amp;format=rss"><channel><title>CATL - BingNews'
            "</title>" + "".join(out) + "</channel></rss>")


SAMPLE = _rss([
    ("CATL shares fall over 10% in Hong Kong as tax changes add to profit pressure",
     "https://cnevpost.com/2026/10/21/catl-shares-fall-profit-pressure/",
     "CATL&#39;s Hong Kong shares fell to their lowest since July 2025.", "Tue, 20 Oct 2026 23:28:00 GMT", "CnEVPost"),
    ("Battery makers weigh new consumption tax", "https://www.example-news.com/story?id=7&src=rss",
     "A 2% tax on batteries took effect in September.", "Sun, 25 Oct 2026 08:00:00 GMT", None),
    ("CATL Shares Fall Over 10% in Hong Kong as Tax Changes Add to Profit Pressure!",
     "https://other.example.com/copy", "Syndicated copy.", "Wed, 21 Oct 2026 01:00:00 GMT", "Copycat"),
    ("CATL opens Hungary plant", "https://cnevpost.com/2026/05/01/hungary/", "Old story.",
     "Fri, 01 May 2026 08:00:00 GMT", "CnEVPost"),
    ("No date on this one", "https://cnevpost.com/no-date/", "x", None, "CnEVPost"),
])


def test_parse_bing_rss_unwraps_links_and_reads_source():
    items = rs.parse_bing_rss(SAMPLE)
    assert len(items) == 5
    a, b = items[0], items[1]
    assert a["url"] == "https://cnevpost.com/2026/10/21/catl-shares-fall-profit-pressure/"
    assert a["source"] == "CnEVPost" and a["description"].startswith("CATL's Hong Kong")
    assert a["published"] == datetime(2026, 10, 20, 23, 28, tzinfo=timezone.utc)
    assert b["url"] == "https://www.example-news.com/story?id=7&src=rss" and b["source"] == ""
    assert items[4]["published"] is None
    assert rs.unwrap_bing_url("https://example.com/plain") == "https://example.com/plain"
    assert rs.parse_bing_rss("<not xml") == []


def test_select_news_filters_dates_dedupes_and_sorts_newest_first():
    picked = rs.select_news(rs.parse_bing_rss(SAMPLE), days=90, limit=8, now=NOW)
    titles = [p["title"] for p in picked]
    assert titles == ["Battery makers weigh new consumption tax",
                      "CATL shares fall over 10% in Hong Kong as tax changes add to profit pressure"]
    # limit applies in search (relevance) order, before sorting by date
    assert [p["title"] for p in rs.select_news(rs.parse_bing_rss(SAMPLE), 90, 1, NOW)] == [titles[1]]


def test_news_search_builds_docs_and_keeps_snippet_for_paywalls(monkeypatch):
    now = datetime.now(timezone.utc)
    feed = rs.parse_bing_rss(_rss([
        ("宁德时代三季报出炉：净利增14.5%，电池消费税影响逐步显现", "https://finance.example.cn/a.html", "摘要一",
         format_datetime(now - timedelta(days=3)), "新浪财经"),
        ("CATL profit slows on battery tax", "https://www.reuters.com/business/catl", "Reuters snippet.",
         format_datetime(now - timedelta(days=2)), "Reuters"),
        ("Battery tax hits margins", "https://www.example-news.com/b", "Snippet b.",
         format_datetime(now - timedelta(days=1)), None),
    ]))
    monkeypatch.setattr(rs, "bing_news_rss", lambda q, sort="relevance": feed if sort == "relevance" else None)
    docs = rs.news_search("宁德时代 消费税", lang="zh", fetch=False)
    assert [d.published for d in docs] == sorted((d.published for d in docs), reverse=True)
    assert all(d.kind == "news" and d.lang == "zh" and d.text == d.snippet for d in docs)
    assert docs[0].source == "Bing News: example-news.com" and docs[2].source == "Bing News: 新浪财经"
    assert docs[0].id.startswith("news-") and len(docs[0].id) == 13

    article = "宁德时代三季报显示电池消费税影响逐步显现，净利增速放缓。" * 30
    monkeypatch.setattr(rs, "fetch_text", lambda url, n=60000: article if "example.cn" in url else "cookie wall " * 50)
    docs = {d.url: d for d in rs.news_search("宁德时代 消费税", lang="zh", fetch=True)}
    assert docs["https://finance.example.cn/a.html"].text == article           # fetched, relevant
    assert docs["https://www.reuters.com/business/catl"].text == "Reuters snippet."   # paywalled: never fetched
    assert docs["https://www.example-news.com/b"].text == "Snippet b."          # fetched page is not the article


# ---------------------------------------------------------------- HTML -> text
PAGE = """<?xml version="1.0" encoding="utf-8"?>
<html><head><title>Site title</title><script>var x = 1;</script><style>p {color: red}</style></head>
<body><nav><ul><li><a href="/">Home</a></li><li><a href="/m">Markets</a></li></ul></nav>
<header>Breaking banner</header>
<div style="display:none"><ix:header>hidden xbrl facts</ix:header></div>
<div><font>CFO Commentary on Second Quarter Fiscal 2027 Results</font></div>
<p>Revenue was <b>$96.2 billion</b>,<br>up 106% from a year ago.</p>
<table><tr><td>($ in millions)</td><td>Q2 FY27</td><td>Q2 FY26</td><td>Y/Y</td></tr>
<tr><td>Revenue</td><td>$</td><td>96,221</td><td>$</td><td>46,743</td><td>106</td><td>%</td></tr>
<tr><td>Net loss</td><td>(</td><td>1,234</td><td>)</td><td></td></tr></table>
<form><input name="q"><button>Search</button></form>
<footer>Copyright 2026</footer></body></html>"""


def test_html_to_text_drops_boilerplate_and_flattens_tables():
    text = rs.html_to_text(PAGE)
    lines = text.split("\n")
    assert lines[0] == "CFO Commentary on Second Quarter Fiscal 2027 Results"
    assert "Revenue was $96.2 billion," in lines and "up 106% from a year ago." in lines
    assert "Revenue | $96,221 | $46,743 | 106%" in lines
    assert "Net loss | (1,234)" in lines
    for junk in ("var x", "color: red", "Home", "Breaking banner", "hidden xbrl", "Search", "Copyright", "Site title"):
        assert junk not in text


def test_article_mode_prefers_article_then_paragraphs():
    body = "Battery makers face a new consumption tax that took effect in September. " * 8
    with_article = (f"<html><body><div>Sidebar text that is not the story</div><article><h1>Tax bites</h1>"
                    f"<p>{body}</p></article></body></html>")
    assert rs.html_to_text(with_article, article=True).startswith("Tax bites\nBattery makers")
    paragraphs = (f"<html><body><div class='menu'><ul><li><a href='/a'>Markets</a></li><li><a href='/b'>Autos and "
                  f"electric vehicles today</a></li></ul></div><div id='content'><p>{body}</p>"
                  f"<li>CATL said it is negotiating with customers to share the tax.</li></div></body></html>")
    text = rs.html_to_text(paragraphs, article=True)
    assert text.startswith("Battery makers") and "negotiating with customers" in text
    assert "Markets" not in text and "Autos and electric" not in text  # link lists dropped


def test_page_wrapped_in_one_form_keeps_its_text():
    story = "<p>" + "Goldman Sachs cut its target price for CATL H shares to HK$777. " * 30 + "</p>"
    page = f"<html><body><form id='aspnetForm'><div>{story}</div></form></body></html>"
    assert "Goldman Sachs cut" in rs.html_to_text(page, article=True)


def test_pdf_detection():
    assert rs._is_pdf(b"%PDF-1.7 ...", "") and rs._is_pdf(b"", "application/pdf")
    assert not rs._is_pdf(b"<html>", "text/html; charset=utf-8")
    assert rs.response_text(b"\x89PNG", "image/png") == ""


# ---------------------------------------------------------------- PDF cleaning
def test_strip_page_furniture_removes_running_headers_and_page_numbers():
    pages = [f"宁德时代新能源科技股份有限公司 2026 年第三季度报告\n{i}\n{c}公司的业务内容。\n{c}项目进展顺利。\n{i}"
             for i, c in enumerate("甲乙丙丁戊己", 1)]
    out = rs.strip_page_furniture(pages)
    assert out[0] == "甲公司的业务内容。\n甲项目进展顺利。"
    assert all("季度报告" not in p for p in out)
    assert rs.strip_page_furniture(["Page 3 of 9\nRevenue rose.", "- 4 -\nCosts fell."]) == ["Revenue rose.",
                                                                                           "Costs fell."]


def test_fix_cjk_joins_wrapped_lines_and_keeps_table_columns():
    text = ("第 三 季 度 ， 公司 动 力 和 储 能 电池 销量 合计 超过 260GWh。\n"
            "公司布局换电生态多年，已初步形成较完善的换电生态，已经看到越来越多车企和合作伙伴认可换\n"
            "电模式的价值。\n"
            "项目 本报告期 本报告期比上年同期增减 年初至报告期末\n"
            "营业收入（千元） 165,220,844 58.58% 442,137,424")
    out = rs.fix_cjk(text).split("\n")
    assert out[0] == "第三季度，公司动力和储能电池销量合计超过 260GWh。"
    assert out[1].endswith("认可换电模式的价值。")              # wrapped line joined
    assert out[2] == "项目 本报告期 本报告期比上年同期增减 年初至报告期末"  # column gaps kept, not joined
    assert out[3].startswith("营业收入")


def test_trim_disclaimer_only_in_second_half():
    body = "公司三季度出货量快速增长，盈利能力承压。\n" * 20
    text = "请务必阅读正文之后的免责声明\n" + body + "免责声明\n本报告仅供参考。\n评级说明\n买入：……"
    out = rs.trim_disclaimer(text)
    assert out.startswith("请务必阅读") and out.endswith("盈利能力承压。") and "本报告仅供参考" not in out


def test_cap_marks_truncation():
    text = "\n".join(f"Line {i} of the filing." for i in range(1000))
    capped = rs._cap(text, 500)
    assert len(capped) < 600 and capped.endswith("characters]") and "truncated" in capped
    assert rs._cap("short", 500) == "short"


# ---------------------------------------------------------------- title filters
def test_classify_hk_keep_and_skip():
    res = [("ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND SIX MONTHS ENDED 30 JUNE 2026",
            "Announcements and Notices - [Interim Results]", 2),
           ("ANNUAL RESULTS ANNOUNCEMENT FOR THE YEAR ENDED 31 DECEMBER 2025", "", 1),
           ("UNAUDITED THIRD QUARTER 2026 RESULTS", "Announcements and Notices - [Quarterly Results]", 2),
           ("3Q 2026 EARNINGS RELEASE", "", 1)]
    for title, cat, prio in res:
        assert rs.classify_hk(title, cat) == ("results", prio), title
    skip = [("Next Day Disclosure Return", "Next Day Disclosure Returns - [Share Buyback]"),
            ("Monthly Return of Equity Issuer on Movements in Securities for the month ended 31 October 2026",
             "Monthly Returns"),
            ("FORM OF PROXY FOR THE ANNUAL GENERAL MEETING", "Proxy Forms"),
            ("NOTICE OF ANNUAL GENERAL MEETING", "Announcements and Notices - [Notice of AGM]"),
            ("LIST OF DIRECTORS AND THEIR ROLES AND FUNCTIONS", "Announcements and Notices - [List of Directors]"),
            ("POLL RESULTS OF THE ANNUAL GENERAL MEETING HELD ON 14 MAY 2026", "Announcements and Notices - [Results of AGM]"),
            ("DATE OF BOARD MEETING", "Announcements and Notices - [Date of Board Meeting]"),
            ("INTERIM REPORT 2026", "Financial Statements&#x2f;ESG Information - [Interim&#x2f;Half-Year Report]"),
            ("NOTICE OF LISTING ON THE STOCK EXCHANGE OF HONG KONG LIMITED - US$1,300,000,000 6.10% SENIOR NOTES",
             "Debt and Structured Products - [Formal Notice - Debt Securities]"),
            ("CIRCULAR - PROPOSED RE-ELECTION OF DIRECTORS", "Circulars - [General Mandate]")]
    for title, cat in skip:
        assert rs.classify_hk(title, cat)[0] == "skip", title
    keep = [("INSIDE INFORMATION - PROFIT WARNING", "", 3),
            ("DISCLOSEABLE TRANSACTION - ACQUISITION OF EQUITY INTEREST", "", 3),
            ("CONNECTED TRANSACTION", "Announcements and Notices - [Connected Transaction]", 3),
            ("COMPLETION OF US$1.8 BILLION AND CNY26 BILLION ISSUE OF NOTES UNDER THE GLOBAL MEDIUM TERM NOTE "
             "PROGRAMME", "Announcements and Notices - [Issue of Debt Securities]", 2),
            ("VOLUNTARY ANNOUNCEMENT - SHARE BUY-BACK PROGRAMME", "", 2),
            ("CHANGE OF CHIEF EXECUTIVE OFFICER", "", 2),
            ("GRANT OF AWARDS PURSUANT TO SHARE AWARD SCHEME", "Announcements and Notices - [Share Scheme]", 1)]
    for title, cat, prio in keep:
        assert rs.classify_hk(title, cat) == ("announcement", prio), title


def test_classify_cn_keep_and_skip():
    for title in ("2026年三季度报告", "2026年第三季度报告", "2025年年度报告", "2026年半年度报告", "2026年第一季度报告"):
        assert rs.classify_cn(title)[0] == "periodic", title
    assert rs.classify_cn("2026年10月20日投资者关系活动记录表")[0] == "ir"
    skip = ["2026年半年度报告摘要", "2025年年度报告（英文版）", "关于2026年第三季度报告的更正公告",
            "关于2026年半年度募集资金存放与使用情况的专项报告", "第四届董事会第二十一次会议决议公告", "第四届监事会第九次会议决议公告",
            "上海市通力律师事务所关于宁德时代2026年第二次临时股东会的法律意见书", "独立董事关于第四届董事会相关事项的独立意见",
            "关于召开2026年第二次临时股东会的通知", "2026年第二次临时股东会决议公告", "H股公告（翌日披露报表）",
            "《2026年A股第二期员工持股计划（草案）》", "关于回购股份事项前十名股东和前十名无限售条件股东持股情况的公告"]
    for title in skip:
        assert rs.classify_cn(title)[0] == "skip", title
    keep = {"2026年度业绩预告": 3, "关于回购公司股份方案的公告暨回购股份报告书": 3, "关于持股5%以上股东减持股份的预披露公告": 3,
            "关于回购公司A股股份的进展公告": 2, "关于2026年度第八期绿色科技创新债券发行完成的公告": 2,
            "关于接受关联方担保的公告": 2, "关于参与投资的基金完成私募投资基金备案的公告": 1,
            "关于授予2026年A股第二期员工持股计划预留份额的公告": 1}
    for title, prio in keep.items():
        assert rs.classify_cn(title) == ("announcement", prio), title


def test_pick_material_prefers_priority_then_recency():
    rows = [{"date": "2026-10-01", "title": "关于接受关联方担保的公告"},
            {"date": "2026-11-03", "title": "关于授予员工持股计划预留份额的公告"},
            {"date": "2026-09-01", "title": "2026年度业绩预告"},
            {"date": "2026-10-20", "title": "第四届董事会第二十一次会议决议公告"}]
    picked = rs._pick_material(rows, lambda r: rs.classify_cn(r["title"]), 2)
    assert [r["date"] for r in picked] == ["2026-10-01", "2026-09-01"]  # top-2 by priority, newest first


# ---------------------------------------------------------------- SEC
INDEX = """<html><body><div class="formDiv">
<table class="tableFile" summary="Document Format Files">
<tr><th scope="col">Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td scope="row">1</td><td scope="row">8-K</td><td scope="row"><a href="/ix?doc=/Archives/edgar/data/1045810/000104581026000073/nvda-20260826.htm">nvda-20260826.htm</a> &nbsp;<span>iXBRL</span></td><td scope="row">8-K</td><td>26457</td></tr>
<tr class="evenRow"><td scope="row">2</td><td scope="row">EX-99.1</td><td scope="row"><a href="/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm">q2fy27pr.htm</a></td><td scope="row">EX-99.1</td><td>341113</td></tr>
<tr><td scope="row">3</td><td scope="row">EX-99.2</td><td scope="row"><a href="/Archives/edgar/data/1045810/000104581026000073/q2fy27cfocommentary.htm">q2fy27cfocommentary.htm</a></td><td scope="row">EX-99.2</td><td>256881</td></tr>
<tr><td scope="row">7</td><td scope="row">NVDA LOGO</td><td scope="row"><a href="/Archives/edgar/data/1045810/000104581026000073/nvdalogoa19.jpg">nvdalogoa19.jpg</a></td><td scope="row">GRAPHIC</td><td>13441</td></tr>
</table></div>
<div class="formDiv"><table class="tableFile" summary="Data Files">
<tr><td scope="row">4</td><td scope="row">XBRL SCHEMA</td><td scope="row"><a href="/Archives/edgar/data/1045810/000104581026000073/nvda-20260826.xsd">nvda-20260826.xsd</a></td><td scope="row">EX-101.SCH</td><td>2125</td></tr>
</table></div></body></html>"""


def test_parse_sec_index_finds_exhibits():
    docs = rs.parse_sec_index(INDEX)
    assert [d["type"] for d in docs] == ["8-K", "EX-99.1", "EX-99.2", "GRAPHIC"]  # data files excluded
    assert docs[0]["url"] == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/nvda-20260826.htm"
    assert docs[2]["document"] == "q2fy27cfocommentary.htm"
    nos = {t: rs.exhibit_no(t) for t in ("EX-99.1", "EX-99.01", "EX-99", "EX-99.2", "EX-10.1", "8-K", "")}
    assert nos == {"EX-99.1": "1", "EX-99.01": "1", "EX-99": "1", "EX-99.2": "2", "EX-10.1": None, "8-K": None,
                   "": None}


def test_eight_k_body_drops_cover_and_signatures():
    text = ("UNITED STATES SECURITIES AND EXCHANGE COMMISSION\nFORM 8-K\n☐ Written communications pursuant to Rule 425\n"
            "Item 8.01. Other Events.\nOn September 2, 2026, NVIDIA entered into an agreement.\n"
            "Item 9.01. Financial Statements and Exhibits.\nSIGNATURE\nPursuant to the requirements ...")
    body = rs.eight_k_body(text)
    assert body.startswith("Item 8.01.") and "Rule 425" not in body and "Pursuant" not in body


def test_us_primary_docs_offline(monkeypatch):
    base = "https://www.sec.gov/Archives/edgar/data/1045810"

    def row(form, day, items, acc):
        return {"form": form, "date": day, "items": items, "description": form, "url": f"{base}/{acc}/doc-{acc}.htm"}

    rows = [row("8-K", "2026-09-03", "8.01", "000104581026000078"),
            row("10-Q", "2026-08-26", "", "000104581026000075"),
            row("8-K", "2026-08-26", "2.02,9.01", "000104581026000073"),
            row("8-K", "2026-08-20", "5.07", "000104581026000070"),
            row("8-K", "2026-05-20", "2.02,9.01", "000104581026000051"),
            row("8-K", "2026-02-25", "2.02,9.01", "000104581026000020"),
            row("8-K", "2026-06-01", "1.01", "000104581026000055")]  # older than 120 days
    monkeypatch.setattr(fl, "sec_cik", lambda code: 1045810)
    monkeypatch.setattr(fl, "sec_recent_filings", lambda cik: rows)

    def index(cik, acc):
        nodash = acc.replace("-", "")
        return [{"type": "8-K", "url": f"{base}/{nodash}/doc-{nodash}.htm"},
                {"type": "EX-99.1", "url": f"{base}/{nodash}/pr.htm"},
                {"type": "EX-99.2", "url": f"{base}/{nodash}/cfo.htm"}]

    def document(url):
        if url.endswith("pr.htm"):
            return "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027\nRevenue was $96.2 billion."
        if url.endswith("cfo.htm"):
            return "CFO Commentary on Second Quarter Fiscal 2027 Results\nRevenue is expected to be $108.0 billion."
        return "FORM 8-K\nItem 8.01. Other Events.\nNVIDIA agreed to acquire a company.\nSIGNATURE\nx"

    monkeypatch.setattr(rs, "sec_filing_index", index)
    monkeypatch.setattr(rs, "sec_document", document)
    docs = rs.primary_docs("NVDA", today=date(2026, 11, 8))
    assert [(d.kind, d.published.isoformat()) for d in docs] == [
        ("results_release", "2026-08-26"), ("results_commentary", "2026-08-26"),
        ("results_release", "2026-05-20"), ("results_commentary", "2026-05-20"),
        ("announcement", "2026-09-03")]
    assert docs[1].id == "sec-0001045810-26-000073-ex99-2" and "$108.0 billion" in docs[1].text
    assert docs[1].title.startswith("CFO Commentary on Second Quarter") and "previous quarter" in docs[2].title
    assert docs[4].title.startswith("8-K filed 2026-09-03: Item 8.01 Other Events")
    assert docs[4].text.startswith("Item 8.01.") and "Exhibit 99.1" in docs[4].text
    assert all(d.source == "SEC EDGAR" and d.lang == "en" for d in docs)


def test_hk_primary_docs_offline(monkeypatch):
    rows = [{"date": "2026-11-05", "title": "Monthly Return of Equity Issuer", "category": "Monthly Returns",
             "url": "https://www1.hkexnews.hk/a.pdf"},
            {"date": "2026-10-22", "title": "COMPLETION OF ISSUE OF NOTES", "url": "https://www1.hkexnews.hk/b.pdf",
             "category": "Announcements and Notices - [Issue of Debt Securities]"},
            {"date": "2026-09-24", "title": "DATE OF BOARD MEETING", "url": "https://www1.hkexnews.hk/c.pdf",
             "category": "Announcements and Notices - [Date of Board Meeting]"},
            {"date": "2026-08-12", "title": "ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND SIX MONTHS ENDED 30 JUNE 2026",
             "category": "Announcements and Notices - [Interim Results]", "url": "https://www1.hkexnews.hk/d.pdf"}]
    monkeypatch.setattr(fl, "hkex_stock_id", lambda code: 7609)
    monkeypatch.setattr(fl, "hkex_announcements", lambda sid, a, b: rows)

    def document(url, pages=25):
        if url.endswith("b.pdf"):
            raise TimeoutError("slow HKEX download")  # one failing document does not fail the call
        return f"text of {url} ({pages} pages)"

    monkeypatch.setattr(rs, "hkex_document", document)
    docs = rs.primary_docs("0700.HK", today=date(2026, 11, 8))
    assert [(d.kind, d.url[-5:]) for d in docs] == [("results_release", "d.pdf")]
    assert docs[0].text.endswith("(70 pages)") and docs[0].id.startswith("hkex-") and docs[0].source == "HKEXnews"


def test_cn_primary_docs_offline(monkeypatch):
    def r(day, title, n):
        return {"date": day, "title": title, "url": f"http://static.cninfo.com.cn/finalpage/{day}/{n}.PDF"}

    rows = [r("2026-11-02", "关于回购公司A股股份的进展公告", 1), r("2026-10-21", "第四届董事会第二十一次会议决议公告", 2),
            r("2026-10-21", "2026年三季度报告", 3), r("2026-10-01", "关于接受关联方担保的公告", 4),
            r("2026-07-25", "2026年半年度报告", 5), r("2026-07-25", "2026年半年度报告摘要", 6)]
    ir = [r("2026-10-21", "2026年10月20日投资者关系活动记录表", 7), r("2026-07-26", "2026年7月24日投资者关系活动记录表", 8),
          r("2026-04-16", "2026年4月15日投资者关系活动记录表", 9)]
    monkeypatch.setattr(fl, "cninfo_announcements", lambda code, a, b: rows)
    monkeypatch.setattr(rs, "cninfo_ir_records", lambda code, a, b: ir)
    monkeypatch.setattr(rs, "cninfo_document", lambda url, pages=25: f"正文 {url}")
    docs = rs.primary_docs("300750.SZ", today=date(2026, 11, 8))
    assert [(d.kind, d.title) for d in docs] == [
        ("periodic_report", "2026年三季度报告"),
        ("ir_record", "2026年10月20日投资者关系活动记录表"), ("ir_record", "2026年7月24日投资者关系活动记录表"),
        ("announcement", "关于回购公司A股股份的进展公告"), ("announcement", "关于接受关联方担保的公告")]
    assert docs[0].id == "cninfo-3" and docs[0].lang == "zh" and docs[0].source == "CNINFO"


# ---------------------------------------------------------------- plumbing
def test_broker_docs_only_for_a_shares():
    assert rs.broker_docs("NVDA") == [] and rs.broker_docs("0700.HK") == []


def test_doc_pickles_for_the_cache():
    d = rs.Doc(id="news-12345678", kind="news", title="t", source="Bing News: x", published=date(2026, 11, 1),
               url="https://x", lang="en", text="body", snippet="s")
    assert pickle.loads(pickle.dumps(d)) == d


def test_every_cached_research_function_has_a_citation_entry():
    import inspect
    from investsync import provenance
    cached_fns = [f for _, f in inspect.getmembers(rs, inspect.isfunction)
                  if hasattr(f, "__wrapped__") and f.__module__ == rs.__name__]
    assert len(cached_fns) >= 8
    missing = [f.__qualname__ for f in cached_fns if f.__qualname__ not in provenance.REGISTRY]
    assert not missing, f"add these to provenance.REGISTRY: {missing}"
    for name in ("sec_document", "hkex_document", "bing_news_rss", "em_report_text"):
        topic, what, publisher, via, url = provenance.REGISTRY[name]
        assert publisher and via and url(("https://example.com/doc", 25)).startswith("http")
