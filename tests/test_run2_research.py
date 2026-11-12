"""Run 2, WP2: the earnings call, company statements reported in the press, and company events after the results
(offline: DummyLM and fake documents; no network)."""
import json
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from dspy.utils import DummyLM

import investsync.research as research_pkg
from investsync.research import desk
from investsync.schema import Market, ResearchBrief, ResearchFact


@dataclass
class FakeDoc:
    id: str
    kind: str
    title: str
    source: str
    published: date
    url: str
    lang: str
    text: str
    snippet: str = ""


RESULTS_DAY = date(2026, 8, 26)
RELEASE = FakeDoc("rel", "results_release", "Acme Announces Financial Results for Second Quarter", "SEC EDGAR",
                  RESULTS_DAY, "https://www.sec.gov/rel.htm", "en",
                  "Acme Announces Financial Results. As of the end of the second quarter, the company had approximately "
                  "$99.0 billion remaining under its share repurchase authorization. " * 3)


def _news(i, title, day, text="x" * 900, source="Bing News: Reuters"):
    return FakeDoc(f"n{i}", "news", title, source, day, f"https://example.com/{i}", "en", text)


def _found(text, doc, order=0, figures=(), importance=1, item="", said_by="", topic="events"):
    return desk._Found(topic, text, "q", doc, order, tuple(figures), importance, item, said_by)


def _data(warnings=None, local=None):
    prof = SimpleNamespace(name="Acme Corporation", ticker="ACME", description="Makes chips.", sector="Technology",
                           industry="Semiconductors", name_local=local)
    quote = SimpleNamespace(price=100.0, currency="USD", as_of="2026-11-10")
    return SimpleNamespace(profile=prof, quote=quote, technicals=None, financials=SimpleNamespace(latest=None),
                           rating=None, warnings=[] if warnings is None else warnings)


def _fake_sources(monkeypatch, primary=(), news=(), fetch=None):
    fake = SimpleNamespace(primary_docs=lambda t, today=None: list(primary),
                           broker_docs=lambda t, today=None: [],
                           news_search=lambda q, lang="en", days=90, limit=8, **kw: list(news),
                           fetch_text=fetch or (lambda url, n=60000: ""))
    monkeypatch.setattr(research_pkg, "sources", fake, raising=False)
    store = {}
    monkeypatch.setattr(desk, "get_cache", lambda: SimpleNamespace(get=store.get,
                                                                   set=lambda k, v, ttl: store.__setitem__(k, v)))
    return store


PLAN = {"extra_questions": json.dumps([]), "queries": json.dumps([])}


# ---------------------------------------------------------------- 1. who said it
def test_said_by_is_read_safely_from_the_model():
    base = {"questions": [1], "fact": "f", "quote": "q"}
    assert desk.Extracted.model_validate(base).said_by == "other"
    assert desk.Extracted.model_validate({**base, "said_by": "Management"}).said_by == "company"
    assert desk.Extracted.model_validate({**base, "said_by": "analyst"}).said_by == "broker"
    assert desk.Extracted.model_validate({**base, "said_by": "the government"}).said_by == "other"
    assert desk.Extracted.model_validate({**base, "said_by": None}).said_by == "other"


def test_management_said_on_the_call_in_a_press_article_is_a_company_statement(monkeypatch):
    """Run 1: the CFO's outlook, known only from press articles, was labelled "press report" by our own code and
    written up as "not company guidance"."""
    article = _news(1, "Acme expects sales to grow 70% next year", date(2026, 11, 9),
                    "Acme's chief financial officer said on the call that the company expects revenue to grow about 70% "
                    "in fiscal 2028. " + "Other commentary follows here. " * 40, source="Bing News: Reuters")
    store = _fake_sources(monkeypatch, news=[article])
    facts = [{"questions": [1], "said_by": "company",
              "fact": "Acme's CFO said on the call that the company expects revenue to grow about 70% in fiscal 2028.",
              "quote": "said on the call that the company expects revenue to grow about 70% in fiscal 2028"},
             {"questions": [9], "said_by": "press", "fact": "Acme's shares fell 3% on the day.",
              "quote": "Other commentary follows here."}]                       # 3% not in the quote: dropped
    lm = DummyLM([PLAN, {"facts": json.dumps(facts)}])
    b = desk.run(_data(), SimpleNamespace(canonical="ACME", market=Market.US, code="ACME"), lm=lm, plan_lm=lm,
                 budget=5, today=date(2026, 11, 10))
    assert [f.said_by for f in b.facts] == ["company"]
    block = desk.facts_block(b)
    assert "company statement reported by Reuters: it is company guidance" in block
    assert "management said it, as reported by Reuters" in block
    assert "press report" not in block
    assert store == {}                                    # one note: a thin brief is not cached for the day


def test_press_and_company_labels_and_kinds():
    company_doc = FakeDoc("a", "announcement", "8-K", "SEC EDGAR", date(2026, 9, 3), "", "en", "")
    news = _news(2, "Story", date(2026, 9, 4))
    broker = FakeDoc("b", "broker_report", "Note", "EastMoney research centre: X", date(2026, 9, 5), "", "en", "")
    summary = FakeDoc("s", "call_summary", "Call highlights", "Earnings call, as reported by Yahoo Finance",
                      RESULTS_DAY, "", "en", "")
    assert desk._said_by(_found("t", company_doc, said_by="press")) == "company"
    assert desk._said_by(_found("t", summary)) == "company"
    assert desk._said_by(_found("t", news, said_by="company")) == "company"
    assert desk._said_by(_found("t", news, said_by="press")) == "press"
    assert desk._said_by(_found("t", news, said_by="other")) == ""
    assert desk._said_by(_found("t", broker, said_by="other")) == "broker"
    plain = ResearchFact(id="R1", topic="street", text="Shares fell.", quote="q", source="Bing News: Reuters",
                         title="t", kind="news", said_by="press")
    assert "(press report: attribute it" in desk.facts_block(ResearchBrief(facts=[plain]))


# ---------------------------------------------------------------- 2. call summaries
def test_call_summary_is_found_and_read_with_the_results():
    good = _news(1, "Acme Corp (ACME) (Q2 2027) Earnings Call Highlights: Record Revenue", date(2026, 8, 27),
                 "Acme management said ... " * 60, source="Bing News: Yahoo Finance")
    recap = _news(2, "Acme Corp. Q2 2027 Earnings: Recap of $ACME Earnings Call, Forecast", RESULTS_DAY,
                  "Acme recap " * 100)
    other = _news(3, "Widget Inc (WDGT) Q2 Earnings Call Highlights", date(2026, 8, 27), "Widget " * 200)
    old = _news(4, "Acme Corp (ACME) (Q1 2027) Earnings Call Highlights", date(2026, 5, 21), "Acme " * 300)
    late = _news(5, "Acme Corp (ACME) Earnings Call Highlights", date(2026, 9, 10), "Acme " * 300)
    teaser = _news(6, "Acme Corp (ACME) Earnings Call Takeaways", date(2026, 8, 27), "Acme short")
    found = desk.call_summaries([RELEASE, good, recap, other, old, late, teaser], "Acme", "ACME")
    assert [d.id for d in found] == ["n1", "n2"]                     # longest first; only this quarter's, this company's
    assert all(d.kind == "call_summary" for d in found)
    assert found[0].source == "Earnings call, as reported by Yahoo Finance"
    read = desk.latest_results_docs([RELEASE] + found)
    assert [d.id for d in read] == ["rel", "n1", "n2"]
    transcript = FakeDoc("t", "transcript", "Acme (ACME) Q2 2027 Earnings Call Transcript", "Bing News: Fool",
                         date(2026, 8, 27), "", "en", "y" * 6000)
    assert [d.id for d in desk.latest_results_docs([RELEASE, transcript] + found)] == ["rel", "t"]


def test_call_summary_refetch_failure_is_safe(monkeypatch):
    def boom(url, n=60000):
        raise RuntimeError("network down")
    monkeypatch.setattr(research_pkg, "sources", SimpleNamespace(fetch_text=boom), raising=False)
    art = _news(1, "Acme Corp (ACME) Earnings Call Highlights", date(2026, 8, 27), "Acme said " * 100)
    assert [d.id for d in desk.call_summaries([RELEASE, art], "Acme", "ACME")] == ["n1"]   # keeps the news text
    assert desk.call_summaries([art], "Acme", "ACME") == []                # no results document: nothing to anchor
    assert desk.call_summaries([RELEASE, art], "", "") == []               # the company must be named
    assert desk.call_summaries(None, "Acme", "ACME") == []                 # never raises


def test_the_call_summary_header_tells_the_reader_it_is_company_guidance():
    summ = desk.call_summaries([RELEASE, _news(1, "Acme Corp (ACME) Earnings Call Highlights", date(2026, 8, 27),
                                               "Management said revenue will grow 70% next year. " * 30,
                                               source="Bing News: Yahoo Finance")], "Acme", "ACME")
    lm = DummyLM([{"facts": json.dumps([{"item": "outlook", "document": 2,
                                         "fact": "Management said on the call revenue will grow 70% next year.",
                                         "quote": "Management said revenue will grow 70% next year."}])}])
    found, missing, docs = desk.read_key_facts([RELEASE] + summ, "Acme (ACME)", lm)
    prompt = json.dumps(lm.history[-1]["messages"])
    assert "Press summary of the company's earnings call held with the results of 26 Aug 2026" in prompt
    assert "statements attributed to management are company guidance given on that call" in prompt
    assert [f.item for f in found] == ["outlook"] and found[0].doc.kind == "call_summary"
    b = desk.brief(found, [("guidance", "g")], 2, 0, 0, None, missing, docs)
    assert b.facts[0].said_by == "company" and b.facts[0].kind == "call_summary"
    assert "Earnings call, as reported by Yahoo Finance" in desk.facts_block(b)


# ---------------------------------------------------------------- 3. events after the results
def _brief_with_buyback(newer):
    key = _found("As of the end of the second quarter, the company had approximately $99.0 billion remaining under "
                 "its share repurchase authorization.", RELEASE, -1, (99.0,), 0, "capital_return")
    later = _news(10, "Acme boosts share buyback by record $150 billion", date(2026, 9, 28))
    buy = _found("Acme's board authorized an additional $150 billion for share repurchases, without expiration.",
                 later, 5, (150.0,), 1, said_by="company")
    return desk.brief([key, buy] + newer, [("events", "q")], 20, 20, 0, None, None, [RELEASE])


def test_a_buyback_after_the_results_survives_twelve_newer_event_notes():
    words = ["lawsuit", "factory", "partner", "supplier", "customer", "patent", "award", "license", "office",
             "storage", "robotics", "network"]
    newer = [_found(f"Acme {w} news {w}s {w}ing item number {i}.", _news(20 + i, f"Acme {w}", date(2026, 11, 9)), i,
                    (float(i + 1),), 1, said_by="press") for i, w in enumerate(words)]
    b = _brief_with_buyback(newer)
    buy = [f for f in b.facts if "$150 billion" in f.text]
    assert len(buy) == 1 and buy[0].key == "update:capital_return" and buy[0].said_by == "company"
    assert sum(1 for f in b.facts if not f.key) == desk.PER_TOPIC    # the cap still holds for the other notes
    block = desk.facts_block(b, ids=True)
    assert "UPDATES SINCE THE LATEST RESULTS" in block
    assert f"(as of the results date; see the later update [{buy[0].id}])" in block
    assert block.index("UPDATES SINCE") < block.index("Research notes")
    assert "a company announcement listed under UPDATES below supersedes them" in block
    plain = desk.facts_block(b)
    assert "(as of the results date; see the later update under UPDATES below)" in plain


def test_newer_company_events_on_another_item_cannot_take_every_update_place():
    ceo = [_found(f"Acme said its board appointed a new CFO, item {i}, effective {i + 1} December.",
                  _news(40 + i, f"Acme names CFO {i}", date(2026, 11, 9)), i, (float(i + 1),), 1, said_by="company")
           for i in range(8)]
    b = _brief_with_buyback(ceo)
    keys = [f.key for f in b.facts if f.key.startswith("update:")]
    assert "update:capital_return" in keys and len(keys) == desk.UPDATE_MAX


def test_not_an_update_press_view_older_event_or_before_the_results():
    after = date(2026, 10, 2)
    press = _found("Acme's buyback authorization increase looks too large, says the columnist.",
                   _news(1, "View", after), said_by="press")
    retold = _found("On May 18, 2026, Acme's board approved an additional $80.0 billion to its share repurchase "
                    "authorization.", _news(2, "Recap", after), figures=(18.0, 80.0), said_by="company")
    before = _found("Acme's board approved an additional $80.0 billion to its share repurchase authorization.",
                    _news(3, "Old", date(2026, 5, 19)), figures=(80.0,), said_by="company")
    deal = _found("On September 2, 2026, Acme entered into a definitive agreement to acquire Beta Inc.",
                  FakeDoc("a", "announcement", "8-K", "SEC EDGAR", date(2026, 9, 3), "", "en", ""), figures=(2.0,))
    ups = desk.pick_updates([press, retold, before, deal], RESULTS_DAY)
    assert list(ups.values()) == ["deal"] and id(deal) in ups
    assert desk.pick_updates([deal], None) == {}
    assert desk.pick_updates([SimpleNamespace(importance=1)], RESULTS_DAY) == {}   # bad input: no update, no crash


def test_update_items_cover_each_kind_of_announcement():
    assert desk.update_item("NVIDIA Board Authorizes $150 Billion Increase to Share Repurchase Program") == \
        "capital_return"
    assert desk.update_item("The board declared a quarterly dividend of $0.25") == "capital_return"
    assert desk.update_item("The board authorized an additional $150.0 billion for share repurchases.") == \
        "capital_return"                                              # a decimal point does not end the window
    assert desk.update_item("Acme sold $2.5 billion of bonds") == "funding"
    assert desk.update_item("Acme raises full-year guidance") == "guidance"
    assert desk.update_item("Acme to acquire Beta in $2bn deal") == "deal"
    assert desk.update_item("Acme prices $5bn of senior notes due 2036") == "funding"
    assert desk.update_item("Acme CFO to step down at year end") == "people"
    assert desk.update_item("腾讯控股：回购股份") == "capital_return"
    assert desk.update_item("关于收购某公司股权的公告") == "deal"
    assert desk.update_item("Acme returned $26.0 billion to shareholders in the quarter") == ""
    assert desk.update_item("Acme revenue declined 12 percent") == ""


def test_post_results_announcements_are_read_first():
    buy = _news(1, "Acme boosts share buyback by record $150 billion", date(2026, 9, 28))
    same = _news(2, "Acme quarterly update for investors", date(2026, 9, 28))
    early = _news(3, "Acme declares dividend", date(2026, 8, 1))
    later = desk.update_docs([RELEASE, buy, same, early])
    assert later == {id(buy)}
    picked = desk.select_chunks([RELEASE, buy, same, early], [("events", "q")], 50)
    score = {c.doc.id: c.score for c in picked}
    assert score["n1"] - score["n2"] == desk.UPDATE_BONUS
    many = [_news(10 + i, f"Acme CEO investigation update {i}", date(2026, 11, 9)) for i in range(8)]
    chosen = desk.update_docs([RELEASE, buy] + many)
    assert len(chosen) == desk.UPDATE_MAX and id(buy) in chosen
    assert desk.update_docs([buy]) == set()                       # no results document: no ranking change


# ---------------------------------------------------------------- 4. dedupe
def test_a_new_buyback_amount_is_not_a_copy_of_the_older_one():
    may = FakeDoc("m", "results_commentary", "CFO commentary Q1 (previous quarter)", "SEC EDGAR", date(2026, 5, 20),
                  "", "en", "")
    sep = _news(1, "Buyback", date(2026, 9, 28))
    old = desk._Found("events", "On May 18, 2026, NVIDIA's Board of Directors approved an additional $80.0 billion to "
                      "its share repurchase authorization, without expiration.", "q", may, 0, (18.0, 80.0))
    new = desk._Found("events", "On September 28, 2026, NVIDIA's Board of Directors approved an additional $150 "
                      "billion to its share repurchase authorization, without expiration.", "q", sep, 1, (28.0, 150.0))
    assert len(desk.dedupe([old, new])) == 2
    copy = desk._Found("events", "NVIDIA's Board of Directors approved an additional $80.0 billion to its share "
                       "repurchase authorization without expiration.", "q", sep, 2, (80.0,))
    assert len(desk.dedupe([old, copy])) == 1                      # a shared figure: still a copy
    words = desk._Found("events", "NVIDIA's Board of Directors approved an additional amount for its share "
                        "repurchase authorization without expiration.", "q", sep, 3, ())
    assert len(desk.dedupe([old, words])) == 1                     # no figure: still a copy


# ---------------------------------------------------------------- 5. ratio words
R48_FACT = ("Georgia's Keisha Lance Bottoms and Ohio's Amy Acton also won governorships on pauses or conditional "
            "moratoriums, and the three states combined account for about one-third of planned capacity (about 141 GW "
            "out of a total of about 156 GW currently planned).")
R48_QUOTE = ("Combined, the three states account for about one-third of the planned capacity (about 141 GW out of a "
             "total of about 156 GW currently planned).")


def test_run1_r48_is_dropped_by_ratio_ok():
    assert not desk.ratio_ok(R48_FACT, R48_QUOTE)
    doc = _news(1, "Data centers and the election", date(2026, 11, 5), R48_QUOTE)
    x = desk.Extracted(questions=[5], fact=R48_FACT, quote=R48_QUOTE)
    kept, dropped = desk.verify([(desk._Chunk(doc, 0, R48_QUOTE, 1.0), x)], [("policy", "q")])
    assert kept == [] and dropped == 1


def test_ratio_words_must_agree_and_be_in_the_quote():
    assert desk.ratio_ok("About one-third of revenue (52 of 156 GW) came from Texas.", "52 of 156 GW, one-third")
    assert desk.ratio_ok("Revenue more than doubled to $96 billion.", "Total revenue more than doubled to $96 billion")
    assert not desk.ratio_ok("Revenue more than doubled to $96 billion.", "Total revenue rose to $96 billion")
    assert not desk.ratio_ok("Half of revenue came from cloud customers.", "Cloud customers were 50% of revenue")
    assert desk.ratio_ok("In the first half of fiscal 2026 revenue was $10 billion.", "six months: $10 billion")
    assert desk.ratio_ok("In the first half, 3 of 4 segments grew.", "In the first half, 3 of 4 segments grew")
    assert desk.ratio_ok("It voted on behalf of 3 of 10 holders.", "on behalf of 3 of 10 holders")
    assert desk.ratio_ok("Net profit doubled to RMB 18.5bn.", "归母净利润185亿元，同比翻倍")
    assert desk.ratio_ok("The majority of sales are to hyperscalers.", "Most of our sales are to hyperscalers")
    assert desk.ratio_ok("Revenue is expected to be $108.0 billion.", "")
    assert desk.ratio_ok(None, None)                               # a check that cannot run keeps the fact
    assert not desk.figures_ok(R48_FACT, R48_QUOTE)               # through the existing figure check too


# ---------------------------------------------------------------- 7. queries
def test_the_call_is_searched_by_the_results_month_and_in_chinese():
    qs = [q for q, _ in desk._default_queries(_data(), Market.US, [RELEASE])]
    assert qs[0] == "Acme (ACME) earnings call transcript" and qs[1] == "Acme earnings call outlook"
    assert "Acme earnings call August 2026" in qs
    assert not any("earnings call 20" in q or "August" in q for q in desk._default_queries(_data(), Market.US)[0])
    hk = [q for q, lang in desk._default_queries(_data(local="某某控股"), Market.HK, [RELEASE]) if lang == "zh"]
    assert "某某控股 业绩会 纪要" in hk


# ---------------------------------------------------------------- 8. safety
def test_an_empty_brief_returns_none_with_a_data_note(monkeypatch):
    store = _fake_sources(monkeypatch, news=[_news(1, "Acme story", date(2026, 11, 9), "Nothing relevant. " * 60)])
    data = _data()
    lm = DummyLM([PLAN, {"facts": json.dumps([])}])
    b = desk.run(data, SimpleNamespace(canonical="ACME", market=Market.US, code="ACME"), lm=lm, plan_lm=lm, budget=5,
                 today=date(2026, 11, 10))
    assert b is None and data.warnings == [desk.NO_RESEARCH_NOTE] and store == {}


def test_a_full_brief_is_cached_under_v10(monkeypatch):
    texts = [f"Acme item {w} grew {i + 1}% in the quarter." for i, w in enumerate(
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec "
        "romeo sierra tango uniform victor".split())]
    body = " ".join(texts) + " " + "Padding words here. " * 40
    store = _fake_sources(monkeypatch, news=[_news(1, "Acme quarterly items", date(2026, 11, 9), body)])
    facts = [{"questions": [q], "fact": t, "quote": t, "said_by": "press"}
             for q, t in zip([1, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 3, texts)]
    lm = DummyLM([PLAN, {"facts": json.dumps(facts[:8])}])
    monkeypatch.setattr(desk, "MAX_FACTS", 64)
    b = desk.run(_data(), SimpleNamespace(canonical="ACME", market=Market.US, code="ACME"), lm=lm, plan_lm=lm,
                 budget=5, today=date(2026, 11, 10))
    assert b is not None and 0 < len(b.facts) < desk.CACHE_MIN_FACTS and store == {}
    monkeypatch.setattr(desk, "CACHE_MIN_FACTS", len(b.facts))
    lm2 = DummyLM([PLAN, {"facts": json.dumps(facts[:8])}])
    desk.run(_data(), SimpleNamespace(canonical="ACME", market=Market.US, code="ACME"), lm=lm2, plan_lm=lm2,
             budget=5, today=date(2026, 11, 10))
    assert list(store) == [desk.cache_key(SimpleNamespace(canonical="ACME"), date(2026, 11, 10), 5)]


def test_research_cache_key_changes_with_the_rules_and_the_reading_settings(monkeypatch):
    """13 Nov 2026: run 4 got run 3's cached notes because the key was only ticker + day."""
    t, day = SimpleNamespace(canonical="NVDA"), date(2026, 11, 12)
    base = desk.cache_key(t, day, 70)
    assert base.startswith(f"research_brief:v{desk.RESEARCH_VERSION}:NVDA:2026-11-12") and desk.RESEARCH_VERSION >= 12
    assert desk.cache_key(t, day, 110) != base                       # RESEARCH_CHUNKS
    monkeypatch.setattr(desk, "MAX_FACTS", desk.MAX_FACTS + 26)
    assert desk.cache_key(t, day, 70) != base                        # RESEARCH_MAX_FACTS
    monkeypatch.setattr(desk, "MAX_FACTS", desk.MAX_FACTS - 26)
    monkeypatch.setattr(desk, "PER_TOPIC", desk.PER_TOPIC + 3)
    assert desk.cache_key(t, day, 70) != base                        # RESEARCH_PER_TOPIC
    monkeypatch.setattr(desk, "PER_TOPIC", desk.PER_TOPIC - 3)
    assert desk.cache_key(t, day, 70) == base and desk.cache_key(t, date(2026, 11, 13), 70) != base


def test_gap_line_allows_attributed_call_statements():
    rel = FakeDoc("p", "results_commentary", "CFO commentary", "SEC EDGAR", RESULTS_DAY, "v", "en", "")
    q3 = desk._Found("guidance", "Revenue is expected to be $108.0 billion for Q3.", "q", rel, 0, (108.0,), 0,
                     "guidance")
    b = desk.brief([q3], [("guidance", "g")], 1, 1, 0, None, ["customers"], [rel])
    gap = next(g for g in b.gaps if g.startswith("Not stated in the latest results documents"))
    assert "a press report of what management said on the results call may be used if attributed" in gap
    assert "or press reports" not in gap


def test_update_kept_when_two_documents_report_the_same_amount_without_a_company_label():
    """R2-CHECK: the reading model may label a press report of a board decision 'press'; two documents with the
    same amount after the results are enough. One document alone, or a shared day number, is not."""
    after = date(2026, 9, 28)
    txt = "Acme's board approved a $150 billion increase to its share repurchase authorization on September 28."
    a = _found(txt, _news(71, "Acme lifts buyback", after), figures=(28.0, 150.0), said_by="press")
    b = _found("Acme added $150 billion to its buyback authorization.", _news(72, "Record buyback", after),
               figures=(150.0,), said_by="press")
    c = _found("A columnist thinks a $90 billion buyback increase on September 28 would be wiser.",
               _news(73, "View", after), figures=(28.0, 90.0), said_by="press")
    assert desk.pick_updates([a, c], RESULTS_DAY, [a, b, c]) == {id(a): "capital_return"}
    assert desk.pick_updates([a, c], RESULTS_DAY, [a, c]) == {}
