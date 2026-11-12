"""Run 3 (12 Nov 2026): news kept only from the team's list of outlets, names checked like figures, scenario drivers
checked before they are printed, and research-note ids printed with a short label."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from investsync import newssources, pipeline
from investsync.narrative import claimcheck, guardrail, scenarios
from investsync.render.report_vm import label_ids
from investsync.research import desk
from investsync.schema import (NewsItem, ResearchBrief, ResearchFact, ReviewNote, Scenario, ScenarioSet,
                               TearSheetData)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- news sources
@pytest.mark.parametrize("source,url,ok", [
    ("Reuters", "https://finance.yahoo.com/news/x", True),                 # syndicated through an aggregator
    ("TipRanks", "https://finance.yahoo.com/news/x", False),               # same aggregator, not on the list
    ("Yahoo", "https://finnhub.io/api/news?id=1", False),                  # publisher unknown
    ("Bing News: Techloy", "https://www.techloy.com/nvidia", False),       # run 2's CEO note came from here
    ("Bing News: CNBC", "https://www.cnbc.com/2026/11/11/x.html", True),
    ("", "https://www.reuters.com/markets/x", True),                       # a direct link: the website counts
    ("Some Blog", "https://reuters.com.example.io/x", False),              # not reuters.com
    ("Barrons.com", "https://www.barrons.com/x", True),
    ("The Wall Street Journal", "", True),
    ("Motley Fool", "https://www.fool.com/x", False),
    ("财联社", "https://finance.eastmoney.com/a/1.html", True),
    ("东方财富网", "https://finance.eastmoney.com/a/2.html", False),
])
def test_news_is_kept_only_from_listed_outlets(source, url, ok):
    assert newssources.allowed(source, url) is ok


def test_the_list_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(newssources, "settings", SimpleNamespace(news_allowlist=False))
    assert newssources.allowed("Bing News: Techloy", "https://www.techloy.com/x")


def test_report_news_keeps_only_listed_outlets_even_if_none_are_left():
    items = [NewsItem(title="a", source="Reuters", url="https://finance.yahoo.com/a"),
             NewsItem(title="b", source="Motley Fool", url="https://www.fool.com/b"),
             NewsItem(title="c", source="Stocktwits", url="https://stocktwits.com/c")]
    assert [n.title for n in pipeline._quality_news(items)] == ["a"]
    assert pipeline._quality_news(items[1:]) == []


def test_research_desk_does_not_read_unlisted_news():
    N = SimpleNamespace
    assert desk._low_tier(N(kind="news", source="Bing News: Techloy", url="https://www.techloy.com/x"))
    assert not desk._low_tier(N(kind="news", source="Bing News: Reuters", url="https://www.reuters.com/x"))
    assert not desk._low_tier(N(kind="results_release", source="Bing News: Techloy", url="https://techloy.com/x"))


# ---------------------------------------------------------------- names
SRC = ("Acme's board launched an investigation into allegations concerning CEO Jane Smith on Tuesday. "
       "Data-center revenue rose; the OpenAI deal was signed.")


@pytest.mark.parametrize("text,missing", [
    ("The board's probe of CEO Jane Smith began on Tuesday, November 11.", []),
    ("Data Center revenue rose at Acme Corp after the OpenAI-linked deal.", []),   # suffixes, hyphen parts
    ("Kimberly Powell, the head of healthcare, left.", ["Kimberly Powell"]),         # a name the source lacks
    ("Morgan Stanley raised its target.", ["Morgan Stanley"]),
    ("CEO Jane Smith said demand is strong.", []),
    ("CEO Mary Smith said demand is strong.", []),                                    # surname found, half the words
    ("CFO John Smithers left.", ["CFO John Smithers"]),
])
def test_a_name_must_be_in_the_source(text, missing):
    assert guardrail.names_missing(text, SRC) == missing


def test_names_are_not_checked_against_chinese_text():
    assert guardrail.names_missing("CFO Jane Smith resigned", "首席财务官辞职") == []


def test_research_facts_with_an_invented_name_are_dropped_and_reasons_counted():
    doc = SimpleNamespace(title="Acme news", published="2026-11-11", source="Bing News: Reuters", url="u", kind="news")
    chunk = SimpleNamespace(doc=doc, text="Acme's board opened an inquiry into CEO Jane Smith. Sales rose 12% to "
                                          "$5 billion in the quarter.")
    X = lambda fact, quote, **k: SimpleNamespace(fact=fact, quote=quote, questions=[1], importance=1,
                                                about_company=True, said_by="press", **k)
    found = [(chunk, X("The board opened an inquiry into CEO Jane Smith.", "board opened an inquiry into CEO Jane Smith",
                       label="Board inquiry into CEO Jane Smith")),
             (chunk, X("The board opened an inquiry into CFO John Doe.", "board opened an inquiry into CEO Jane Smith")),
             (chunk, X("Sales rose 15% in the quarter.", "Sales rose 12% to $5 billion in the quarter")),
             (chunk, X("Sales rose 12% in the quarter.", "Sales jumped 12% this quarter"))]
    reasons: dict = {}
    keep, dropped = desk.verify(found, [("guidance", "q1")], reasons)
    assert [f.text for f in keep] == ["The board opened an inquiry into CEO Jane Smith."]
    assert keep[0].label == "Board inquiry into CEO Jane Smith"
    assert dropped == 3 and reasons == {"name": 1, "figures": 1, "quote": 1}


@pytest.mark.parametrize("label,expected", [
    ("Board inquiry into CEO Jane Smith", "Board inquiry into CEO Jane Smith"),
    ("Sales up 12% in Q3", ""),                         # no figures in a label
    ("Board inquiry into CFO John Doe", ""),            # a name the fact does not have
    ("", ""),
])
def test_labels_have_no_figures_and_no_new_names(label, expected):
    assert desk._label(label, "The board opened an inquiry into CEO Jane Smith.") == expected


# ---------------------------------------------------------------- scenario drivers
def _scenario_set(bear: str) -> ScenarioSet:
    mk = lambda name, p, g, m, v, d: Scenario(name=name, probability=p, revenue_growth=g, fcf_margin=m,
                                              value_per_share=v, upside=v / 100 - 1, drivers=d)
    return ScenarioSet(currency="USD", weighted_value=101.0, weighted_upside=0.01, scenarios=[
        mk("bear", 0.25, [0.84, 0.35, -0.047], 0.34, 77.2, bear),
        mk("base", 0.55, [0.9, 0.7, 0.35], 0.40, 110.0, "Revenue follows the Q3 guide [R1]."),
        mk("bull", 0.20, [0.95, 0.85, 0.55], 0.45, 140.0, "Demand keeps accelerating [R1].")])


@pytest.fixture
def nvda() -> TearSheetData:
    return TearSheetData.model_validate(json.loads((ROOT / "fixtures" / "NVDA.json").read_text(encoding="utf-8")))


EVIDENCE = ("[R1] Management expects third-quarter revenue of $108.0 billion.\n"
            "[R2] The board opened an investigation into allegations concerning CEO Jane Smith.")


def test_driver_sentences_with_invented_figures_ids_or_names_are_deleted(nvda):
    s = _scenario_set("Growth fades after the Q3 guide of $108.0 billion [R1] and the board's investigation into "
                      "CEO Jane Smith [R2] adds disruption. Revenue falls 12% next year [R1]. Margins drop on the "
                      "new rules [R9]. Kimberly Powell leaves [R2]. Probability: 25%, raised by the investigation "
                      "[R2] and held down by the guide [R1].")
    lines = scenarios.check_drivers(nvda, s, EVIDENCE)
    bear = s.scenarios[0].drivers
    assert bear.startswith("Growth fades after the Q3 guide of $108.0 billion [R1]")
    assert "Probability: 25%" in bear                      # 25% is the scenario's own probability
    assert "12%" not in bear and "[R9]" not in bear and "Kimberly" not in bear
    assert len(lines) == 3 and all(x.startswith("[struck] scenario drivers (bear)") for x in lines)
    assert s.scenarios[1].drivers == "Revenue follows the Q3 guide [R1]."


def test_a_driver_may_quote_its_own_final_assumptions(nvda):
    s = _scenario_set("Growth slows to 35.0% and then -4.7%, with a 34% margin [R1].")
    assert scenarios.check_drivers(nvda, s, EVIDENCE) == []


def test_claim_check_removes_contradicted_drivers_and_keeps_unsupported_hypotheses(nvda, monkeypatch):
    s = _scenario_set("The investigation into CEO Jane Smith [R2] ends in charges. "
                      "Probability: 25% because management cut the Q3 guide [R1].")
    sec = scenarios.CLAIM_SECTION.format("bear")
    notes = [ReviewNote(section=sec, quote="Probability: 25% because management cut the Q3 guide [R1].",
                        problem='wrong (check 1): the guide was not cut. Evidence: "expects"', fix="x"),
             ReviewNote(section=sec, quote="The investigation into CEO Jane Smith [R2] ends in charges.",
                        problem="unsupported (check 2): no source says so", fix="x")]
    monkeypatch.setattr(claimcheck, "check", lambda parts, sources, company, lm, adapter: (notes, {}))
    lines = scenarios.check_drivers(nvda, s, EVIDENCE, lm=object(), adapter=None)
    assert s.scenarios[0].drivers == "The investigation into CEO Jane Smith [R2] ends in charges."
    assert lines[0].startswith("[struck] scenario drivers (bear), claim check: wrong")
    assert lines[1].startswith("[scenario] bear drivers, claim check (kept, a hypothesis): unsupported")


# ---------------------------------------------------------------- id labels in the report
def test_cited_research_ids_get_a_label_the_first_time():
    rb = ResearchBrief(facts=[
        ResearchFact(id="R1", topic="guidance", text="Management expects Q3 revenue of $108.0 billion, plus or minus 2%.",
                     quote="q", source="s", title="t"),
        ResearchFact(id="R2", topic="events", text="The board opened an investigation into CEO Jane Smith.", quote="q",
                     source="s", title="t", label="Board probe of CEO Jane Smith")])
    out = label_ids("Disruption from the probe [R2] and the guide [R1, E4]; still [R2].", rb)
    assert out == ("Disruption from the probe [R2: Board probe of CEO Jane Smith] and the guide "
                   "[R1; E4]; still [R2].")                       # R1 has no label of its own: the id alone
    assert label_ids("No research [R1].", None) == "No research [R1]."


# ---------------------------------------------------------------- run-2 review fixes
def test_news_feed_items_are_read_as_documents_newest_first():
    from datetime import date, datetime, timezone
    from investsync.research import sources as rs
    items = [NewsItem(title="Old story", source="Reuters", url="https://finance.yahoo.com/old",
                      published=datetime(2026, 9, 1, tzinfo=timezone.utc), summary="old"),
             NewsItem(title="Board probes CEO", source="Yahoo Finance", url="https://finance.yahoo.com/a",
                      published=datetime(2026, 11, 9, tzinfo=timezone.utc), summary="The board opened a probe."),
             NewsItem(title="Shares fall", source="Reuters", url="https://finance.yahoo.com/b",
                      published=datetime(2026, 11, 10, tzinfo=timezone.utc), summary="")]
    docs = rs.feed_docs(items, date(2026, 11, 12), fetch=False)
    assert [d.title for d in docs] == ["Shares fall", "Board probes CEO"]          # 30 days, newest first
    assert docs[1].source == "News feed: Yahoo Finance" and docs[1].kind == "news" and docs[1].id.startswith("feed-")
    assert docs[0].text == "Shares fall"                                          # no summary: the title
    assert not desk._low_tier(docs[1])                                            # an approved outlet


def test_the_newer_price_file_is_used(monkeypatch):
    import pandas as pd
    from datetime import date
    from investsync.data import sources as src
    sina = pd.DataFrame({"date": [date(2026, 11, 9), date(2026, 11, 10)], "close": [178.67, 168.89]})
    yahoo = pd.DataFrame({"date": [date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)],
                          "close": [178.67, 168.89, 173.73]})
    monkeypatch.setattr(src, "_yf_history", lambda symbol: yahoo.copy())
    out = src._newest_of(sina, "US", "NVDA")
    assert out["date"].iloc[-1] == date(2026, 11, 11) and out.attrs["source"].startswith("yahoo")
    monkeypatch.setattr(src, "_yf_history", lambda symbol: sina.iloc[:1].copy())
    assert src._newest_of(sina, "US", "NVDA") is sina                             # Sina is newer or equal: kept


@pytest.mark.parametrize("sentence,wrong", [
    ("Net cash of 23.2bn still exceeds total debt of 33.4bn.", True),
    ("Cash and securities of $56.6bn exceed debt of $33.4bn.", False),
    ("It trades at 24.6x, below the 20.4x peer median.", True),
    ("It trades at 10.6x forward earnings, well below the 20.4x peer median.", False),
    ("Revenue rose 35% to more than $100bn.", False),                                 # different kinds
    ("Growth of 20% is more than twice the 9% of peers.", False),                     # a multiplier
    ("Buy at or below USD 173.93 and Sell at or above USD 222.24.", False),           # two subjects
])
def test_a_comparison_word_must_agree_with_its_figures(sentence, wrong):
    from investsync.narrative import factcheck
    assert bool(factcheck._comparisons([sentence], None)) is wrong


def test_the_flip_probability_is_rounded_up_so_the_sentence_is_true(monkeypatch):
    s = _scenario_set("x")
    data = SimpleNamespace(valuation=SimpleNamespace(scenarios=s))
    monkeypatch.setattr(scenarios, "flip_points", lambda d, buy=0.15, sell=-0.10: {"now": "Buy", "bear_for_hold": 0.2947})
    assert "rose from 25% to 30%" in scenarios.flip_text(data)                      # at 29% it is still Buy


def test_the_current_year_forecast_keeps_reported_profit():
    from datetime import date
    from investsync.narrative import forecast
    fy = SimpleNamespace(period_end=date(2026, 1, 25))
    lt = SimpleNamespace(period_end=date(2026, 7, 26), months=6, revenue=177_837e6, net_income=118_010e6)
    data = SimpleNamespace(financials=SimpleNamespace(years=[fy], latest=lt))
    ni = forecast._reported_basis(data, 411_794e6, 0.65, 0.005, 0.15, 1.0, ni=224_213e6)
    rest = 411_794e6 - 177_837e6
    assert ni == pytest.approx(118_010e6 + rest * 0.655 * 0.85)
    lt.months = 12                                                                 # not a partly reported year
    assert forecast._reported_basis(data, 411_794e6, 0.65, 0.005, 0.15, 1.0, ni=1.0) == 1.0


def test_us_prices_come_from_yahoo_first_with_sina_as_backup(monkeypatch):
    import pandas as pd
    from datetime import date
    from investsync.data import sources as src
    yahoo = pd.DataFrame({"date": [date(2026, 11, 10), date(2026, 11, 11)], "close": [168.89, 173.73]})
    sina = pd.DataFrame({"date": ["2026-11-10"], "close": [168.89], "open": [1.0], "high": [1.0], "low": [1.0],
                         "volume": [1]})
    monkeypatch.setattr(src, "_yf_history", lambda symbol: yahoo.copy())
    monkeypatch.setattr(src, "_ak", lambda: SimpleNamespace(stock_us_daily=lambda symbol, adjust: sina.copy()))
    out = src.price_history.__wrapped__("US", "NVDA")
    assert out.attrs["source"] == "yahoo" and out["date"].iloc[-1] == date(2026, 11, 11)

    def down(symbol):
        raise LookupError("no Yahoo")
    monkeypatch.setattr(src, "_yf_history", down)
    out = src.price_history.__wrapped__("US", "NVDA")
    assert out.attrs["source"] == "sina (Yahoo unreachable)" and out["close"].iloc[-1] == 168.89
