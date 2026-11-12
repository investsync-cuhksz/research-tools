"""News write-ups of HK / US broker notes: parsing, matching, display and the AI step. Offline."""
import json
from datetime import date, datetime, timedelta

import pandas as pd
from dspy.utils.dummies import DummyLM

from investsync.data import brokers
from investsync.quant import street
from investsync.render import report_vm, viewmodel
from investsync.render.render import render_pdf
from investsync.schema import BrokerNote, TearSheetData
from investsync.tickers import parse

from tests.test_street import TODAY, _pages, _text, tencent

CLSA = ("里昂发表研究报告指，腾讯控股(00700.HK) 正加快推进AI应用，WorkBuddy有望成为新增长动力。\n"
        "该行预计腾讯第三季总收入按年升9.4%至2,110亿元人民币(下同)。该行下调2026/27年经调整净利润预测3%/7%，"
        "并把目标价由740港元降至685港元，评级维持「高确信跑赢大市」。")
NOMURA = ("野村发表研究报告指，腾讯(00700.HK) 上月举办全球数字生态大会，WorkBuddy成为焦点。\n"
          "野村认为字节跳动与阿里(09988.HK) 将主导中国AI MaaS市场，维持阿里「买入」评级。")
CLSA_BABA = ("里昂发表研究报告指，阿里-W(09988.HK) 次财季业绩料表现强劲。\n"
             "该行维持阿里(BABA.US) ADR「跑赢大市」评级及目标价190美元不变。")


# ---------------------------------------------------------------- Hong Kong (AAStocks)
def test_broker_and_company_are_read_from_the_headline():
    assert brokers._hk_broker("《大行》里昂降腾讯目标价至685元 AI应用加速推进")[0] == "里昂"
    assert brokers._hk_broker("《大行》 花旗：腾讯稳步确立领先地位")[0] == "花旗"
    assert brokers._hk_broker("《大行》Minimax跌4.5%  遭花旗劈目标价至533元")[0] == "花旗"
    assert brokers.broker_en("摩通") == "J.P. Morgan" and brokers.broker_en("里昂") == "CLSA"
    assert {"腾讯控股", "腾讯"} <= brokers._aliases("00700", "腾讯控股")
    assert {"阿里巴巴", "阿里"} <= brokers._aliases("09988", "阿里巴巴-W")
    assert "汇控" in brokers._aliases("00005", "汇丰控股")


def test_rating_and_target_come_from_the_write_up_text():
    rating, target, prev = brokers._parse_call(CLSA, "00700", {"腾讯", "腾讯控股"})
    assert (rating, target, prev) == ("高确信跑赢大市", 685.0, 740.0)
    assert brokers.std_rating(rating) == "Outperform"
    assert brokers.wording_en(rating) == "High-conviction outperform"
    # the US-listed shares' target in US dollars is not an HKD target
    assert brokers._parse_call(CLSA_BABA, "09988", {"阿里", "阿里巴巴"})[1] is None
    # a note led by another company: its rating for Alibaba is read only where Alibaba alone is named
    assert brokers._parse_call(NOMURA, "00700", {"腾讯"})[0] is None


def test_a_note_led_by_another_company_is_not_attributed():
    assert brokers._about(CLSA, "里昂降腾讯目标价", "00700", {"腾讯"})
    assert not brokers._about(NOMURA, "野村：腾讯加速… 料字节跳动与阿里主导", "09988", {"阿里", "阿里巴巴"})
    assert brokers._about(CLSA_BABA, "里昂：阿里盈利料反弹", "09988", {"阿里", "阿里巴巴"})


def test_hk_write_ups_load_from_aastocks(monkeypatch):
    feed = [{"id": "N1", "time": "2026/11/06 10:00", "headline": "《大行》里昂降腾讯目标价至685元 AI应用加速推进", "src": "AAFN"},
            {"id": "N2", "time": "2026/11/05 10:00", "headline": "港股通腾讯净流入", "src": "AAFN"},
            {"id": "N3", "time": "2026/11/04 10:00", "headline": "《大行》东吴证券列出南向资金十大净买入名单(表)", "src": "AAFN"},
            {"id": "N4", "time": "2026/11/03 10:00", "headline": "《大行》大摩：美团外卖份额回升", "src": "AAFN"},
            {"id": "N5", "time": "2026/01/03 10:00", "headline": "《大行》花旗：腾讯旧报告", "src": "AAFN"}]
    monkeypatch.setattr(brokers.src, "aastocks_news_list", lambda code, pages=8, keyword="": feed if not keyword else [])
    monkeypatch.setattr(brokers.src, "aastocks_article", lambda code, nid, f="AAFN": CLSA)
    out = brokers.writeups(parse("0700.HK"), [], "Tencent", "腾讯控股", "0700.HK", today=TODAY)
    assert len(out) == 1                       # not news, a table, another company, or older than 120 days
    w = out[0]
    assert (w.broker, w.broker_local, w.source, w.on) == ("CLSA", "里昂", "AAStocks", date(2026, 11, 6))
    assert (w.rating, w.target, w.previous_target) == ("Outperform", 685.0, 740.0)
    assert w.url.endswith("/00700/AAFN/N1/hk-stock-news") and w.abstract.startswith("里昂发表研究报告指")


# ---------------------------------------------------------------- US (news about each rating action)
def _fh(when: str, headline: str, summary: str, source="Yahoo", url=None):
    ts = int(datetime.strptime(when, "%Y-%m-%d %H:%M").timestamp())
    return {"datetime": ts, "headline": headline, "summary": summary, "source": source, "url": url or headline}


def test_us_write_ups_match_the_action_and_skip_templates(monkeypatch):
    notes = [BrokerNote(on=date(2026, 10, 20), broker="Loop Capital", rating="Hold", previous_rating="Buy",
                        action="downgrade", target=330, previous_target=370, source="Yahoo Finance"),
             BrokerNote(on=date(2026, 11, 3), broker="JP Morgan", rating="Outperform", target=355,
                        previous_target=360, source="Yahoo Finance")]
    news = {"2026-10-20": [
        _fh("2026-10-20 09:00", "Loop Capital Downgrades Apple to Hold, Lowers Price Target to $330",
            "Loop Capital  analyst Ananda Baruah   downgrades Apple (NASDAQ:AAPL) from Buy to Hold and lowers the "
            "price target from $370 to $330.", source="Benzinga"),
        _fh("2026-10-20 11:00", "Loop Capital downgrades Apple, sees no recovery of cut iPhone shipments",
            "Investing.com -- Loop Capital cut its rating for Apple to Hold from Buy and lowered the price target to "
            "$330 from $370, citing iPhone shipment cuts that it does not expect to be recovered.")],
        "2026-11-03": [_fh("2026-11-03 12:00", "JPMorgan Nasdaq Equity Prem. Income (JEPQ) Buys $18.9 Million More AAPL",
                           "The fund added $211.8 million across all 82 of its positions.")]}
    monkeypatch.setattr(brokers.src, "finnhub_news", lambda sym, a, b: news.get(a, []))
    monkeypatch.setattr(brokers.src, "yf_news", lambda sym: [])
    out = brokers.writeups(parse("AAPL"), notes, "Apple Inc.", None, "AAPL", today=TODAY)
    assert len(out) == 1                       # the template line and the fund article are not write-ups
    w = out[0]
    assert w.broker == "Loop Capital" and w.action == "downgrade" and w.target == 330
    assert w.source == "Investing.com" and w.abstract.startswith("Loop Capital cut its rating")


def test_firm_names_match_common_spellings():
    keys = brokers._firm_keys("JP Morgan")
    assert any(k.search("jpmorgan lifts target") for k in keys)
    assert any(k.search("j.p. morgan says") for k in keys)
    assert any(k.search("bofa reiterates buy") for k in brokers._firm_keys("B of A Securities"))
    assert not any(k.search("david davidson's fund") for k in brokers._firm_keys("UBS"))


# ---------------------------------------------------------------- comparison, display, AI step
def _hk_street(d: TearSheetData) -> TearSheetData:
    p = d.quote.price
    table = [BrokerNote(on=TODAY - timedelta(days=20), broker="CLSA", broker_local="里昂", rating="Outperform",
                        target=740.0, source="etnet (经济通)"),
             BrokerNote(on=TODAY - timedelta(days=10), broker="Citi", broker_local="花旗", rating="Buy",
                        target=p * 1.5, source="etnet (经济通)")]
    ups = [BrokerNote(on=TODAY, broker="CLSA", broker_local="里昂", rating="Outperform", target=685.0,
                      previous_target=740.0, title="里昂降腾讯目标价至685元 AI应用加速推进", abstract=CLSA,
                      url="https://www.aastocks.com/x", source="AAStocks")]
    d.street = street.build(d, table, today=TODAY, writeups=ups)
    return d


def test_write_ups_are_shown_but_not_counted():
    d = _hk_street(tencent())
    st = d.street
    assert st.brokers == 2 and st.targets_n == 2 and 740.0 in (st.target_low, st.target_high)
    assert st.texts() == st.writeups
    assert any(f.startswith("Newer than etnet's table: CLSA moved its target to HKD 685.00") for f in st.findings)
    vm = viewmodel.street(d)
    assert vm["source"] == "etnet + AAStocks" and vm["notes"][0]["broker"] == "CLSA"
    rv = report_vm._street(d)
    assert rv["summaries"][0]["via"] == "AAStocks" and rv["summaries"][0]["link"] == "article"
    assert rv["summaries"][0]["target"] == "TP 740 → 685" and "not public" in rv["credit"]


def test_broker_step_summarises_write_ups_against_their_own_text():
    from investsync.narrative import commentary
    d = _hk_street(tencent())
    out = {"summaries": json.dumps([{"index": 1, "summary_en": "CLSA cut its target to HKD 685 from 740, expecting "
                                                               "Q3 revenue up 9.4% to RMB 211bn as AI spending weighs."}]),
           "street_view": "Both brokers are positive."}
    assert commentary.digest_brokers(d, DummyLM([out])) is True
    assert d.street.writeups[0].summary_en.startswith("CLSA cut its target to HKD 685")


def test_report_renders_write_ups_with_credit():
    d = _hk_street(tencent())
    assert _pages(render_pdf(d, layout="tearsheet")) == 1
    text = _text(render_pdf(d))
    assert "WHAT THE LATEST NOTES ARGUE" in text.upper() and "write-up: AAStocks" in text
    assert "Newer than etnet" in text
