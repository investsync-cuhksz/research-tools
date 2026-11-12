"""Section finder for annual / interim reports (offline, synthetic text)."""
from investsync.data import filings as f
from investsync.schema import Market

PROSE = ("Demand for our data center platforms remained strong during the year as customers expanded "
         "their computing capacity, and we continued to invest in new architectures and software. ") * 12


def test_skips_table_of_contents_and_takes_body():
    toc = ("Item 1. Business 4 Item 1A. Risk Factors 12 Item 1B. Unresolved Staff Comments 32 "
           "Item 2. Properties 33 Item 3. Legal Proceedings 33 Item 7. Management's Discussion 36 ")
    text = toc + "Part I Item 1A. Risk Factors " + PROSE + " Item 1B. Unresolved Staff Comments None."
    sec = f.sections_from_text(text, Market.US)["Risk factors"]
    assert sec.startswith("Demand for our data center")
    assert "Unresolved Staff Comments" not in sec  # stops at the next heading


def test_cross_reference_is_not_a_heading():
    text = ("Item 7. Management's Discussion and Analysis The following discussion should be read with "
            "“Item 1A. Risk Factors” and Part II, Item 8 of this report. " + PROSE + " Item 7A. Market Risk.")
    sec = f.sections_from_text(text, Market.US)["Management discussion"]
    assert len(sec) > 1000 and "Market Risk" not in sec


def test_numbered_contents_page_rejected():
    toc = "\n".join(f"{20 + i} Condensed Consolidated Statement {i}" for i in range(8))
    assert f._prose_score(toc) < 0.5 < f._prose_score(PROSE)


def test_chinese_report_sections():
    text = ("目录 第三节 管理层讨论与分析 ...... 10 第四节 公司治理 ...... 20\n" + "前言" * 200
            + "第三节 管理层讨论与分析\n一、经营情况讨论与分析\n" + "公司坚持高质量发展，产品结构持续优化，渠道改革稳步推进，经营业绩保持稳健增长。" * 30
            + "\n可能面对的风险\n一是宏观经济风险；二是安全风险；三是舆情风险；四是环境保护风险。\n第四节 公司治理\n董事变动……")
    secs = f.sections_from_text(text, Market.CN)
    assert "可能面对的风险" in secs and secs["可能面对的风险"].startswith("一是宏观经济风险")
    assert "公司治理" not in secs["可能面对的风险"]
    assert "经营情况讨论与分析" in secs
