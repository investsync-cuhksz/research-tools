"""Research desk: quotes and figures are checked in code; only verified facts reach the brief (offline, DummyLM)."""
import json
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from dspy.utils import DummyLM

import investsync.research as research_pkg
from investsync.research import desk
from investsync.schema import Market


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


RELEASE = ("NVIDIA Announces Financial Results for Second Quarter Fiscal 2027. Outlook: NVIDIA's outlook for the "
           "third quarter of fiscal 2027 is as follows: Revenue is expected to be $108.0 billion, plus or minus "
           "2%.\nGAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points.")


def test_quote_must_be_verbatim_and_figures_in_the_quote():
    text = desk._norm("Revenue is expected to be\n$108.0  billion, plus or minus 2%.")
    assert desk.quote_found("Revenue is expected to be $108.0 billion", text)       # whitespace / line breaks ok
    assert not desk.quote_found("Revenue is forecast to be $108.0 billion", text)   # paraphrase rejected
    assert not desk.quote_found("short", text)                                     # too short to prove anything
    assert desk.figures_ok("Q3 FY27 revenue is guided at $108.0bn, plus or minus 2%.",
                           "Revenue is expected to be $108.0 billion, plus or minus 2%.")
    assert not desk.figures_ok("Q3 revenue is guided at $110.0bn.", "Revenue is expected to be $108.0 billion")
    # Chinese amounts are converted in code, so the English fact may use the bn value
    assert desk.figures_ok("Q3 net profit was RMB 18.5bn.", "第三季度归母净利润185亿元")


def test_chunks_cover_the_text_with_overlap():
    text = ("Sentence number one about revenue. " * 600).strip()
    parts = desk.chunks(text, "en")
    assert len(parts) > 2 and all(len(p) <= desk.CHUNK_CHARS["en"] for p in parts)
    assert parts[0][-50:] in text and parts[-1][-20:] == text[-20:]


def _data():
    prof = SimpleNamespace(name="NVIDIA Corporation", ticker="NVDA", description="Designs GPUs.",
                           sector="Technology", industry="Semiconductors", name_local=None)
    quote = SimpleNamespace(price=186.64, currency="USD", as_of="2026-11-06")
    fin = SimpleNamespace(latest=None)
    return SimpleNamespace(profile=prof, quote=quote, technicals=None, financials=fin, rating=None)


def test_run_keeps_only_verified_facts(monkeypatch):
    docs = [FakeDoc("sec-1", "results_release", "Q2 FY27 press release", "SEC EDGAR", date(2026, 8, 26),
                    "https://www.sec.gov/x.htm", "en", RELEASE)]
    fake = SimpleNamespace(primary_docs=lambda t, today=None: docs, broker_docs=lambda t, today=None: [],
                           news_search=lambda q, lang="en", days=90, limit=8, **kw: [])
    monkeypatch.setattr(research_pkg, "sources", fake, raising=False)
    store = {}
    monkeypatch.setattr(desk, "get_cache", lambda: SimpleNamespace(get=store.get,
                                                                   set=lambda k, v, ttl: store.__setitem__(k, v)))
    monkeypatch.setattr(desk, "CACHE_MIN_FACTS", 1)  # run 2 caches only a full brief (20+ notes); see test_run2_research
    plan = {"extra_questions": json.dumps(["How exposed is NVIDIA to customer financing?"]),
            "queries": json.dumps([{"query": "Nvidia guidance", "lang": "en"}])}
    facts = [
        {"questions": [1], "fact": "Management expects Q3 FY27 revenue of $108.0 billion, plus or minus 2%.",
         "quote": "Revenue is expected to be $108.0 billion, plus or minus 2%."},                    # kept
        {"questions": [1], "fact": "Gross margin is expected to be 74.0%.",
         "quote": "gross margins are expected to be 74.0%"},                                        # kept
        {"questions": [2], "fact": "Data center revenue rose 120%.",
         "quote": "Data center revenue rose 120% on Blackwell demand"},                             # quote invented
        {"questions": [1], "fact": "Revenue is expected to be $112.0 billion.",
         "quote": "Revenue is expected to be $108.0 billion"},                                      # wrong figure
    ]
    lm = DummyLM([plan, {"facts": json.dumps(facts)}])
    b = desk.run(_data(), SimpleNamespace(canonical="NVDA", market=Market.US), lm=lm, plan_lm=lm, budget=5,
                 today=date(2026, 11, 8))
    assert [f.text for f in b.facts] == ["Management expects Q3 FY27 revenue of $108.0 billion, plus or minus 2%.",
                                         "Gross margin is expected to be 74.0%."]
    assert b.facts_dropped == 2 and b.facts[0].id == "R1" and b.facts[0].topic == "guidance"
    assert b.facts[0].source == "SEC EDGAR" and b.facts[0].published == date(2026, 8, 26)
    assert "How exposed is NVIDIA to customer financing?" in b.questions
    assert any(g.startswith("Which government policies") for g in b.gaps)
    block = desk.facts_block(b)
    assert "Guidance (2026-08-26, SEC EDGAR): Management expects Q3 FY27 revenue of $108.0 billion" in block
    assert "Not found in the documents read" in block
    # cached for the day: a second run makes no AI call
    again = desk.run(_data(), SimpleNamespace(canonical="NVDA", market=Market.US), lm=DummyLM([]), budget=5,
                     today=date(2026, 11, 8))
    assert [f.text for f in again.facts] == [f.text for f in b.facts]


def test_dedupe_prefers_primary_source():
    news = FakeDoc("n", "news", "Press story", "Bing News: Reuters", date(2026, 8, 27), "u", "en", "")
    prim = FakeDoc("p", "results_commentary", "CFO commentary", "SEC EDGAR", date(2026, 8, 26), "v", "en", "")
    a = desk._Found("guidance", "Nvidia guided revenue of $108.0 billion for the third quarter.", "q", news, 0, (108.0,))
    b = desk._Found("guidance", "Revenue is expected to be $108.0 billion.", "q", prim, 1, (108.0,))
    kept = desk.dedupe([a, b])
    assert len(kept) == 1 and kept[0].doc is prim


def test_source_labels_are_english():
    assert desk.source_en("EastMoney research centre: 国信证券") == "Guosen Securities (via EastMoney)"
    assert desk.source_en("Bing News: 搜狐", "https://www.sohu.com/a/1") == "Bing News: Sohu"
    assert desk.source_en("Bing News: 某某网", "https://www.abc.cn/x") == "Bing News: abc.cn"
    assert desk.source_en("SEC EDGAR") == "SEC EDGAR"


def test_segment_labels_translated_in_place():
    from investsync.schema import Segment, SegmentBreakdown
    data = _data()
    data.segments = [SegmentBreakdown(kind="product", period="FY2026", segments=[
        Segment(name="数据中心产品"), Segment(name="代工生产"), Segment(name="Gaming")], source="EastMoney")]
    lm = DummyLM([{"english": json.dumps([{"original": "数据中心产品", "english": "Data Center"},
                                          {"original": "代工生产", "english": "OEM and Other"}])}])
    assert desk.english_labels(data, lm) == 2
    assert [s.name for s in data.segments[0].segments] == ["Data Center", "OEM and Other", "Gaming"]


def test_low_tier_news_sites_are_not_read():
    from types import SimpleNamespace as N
    from investsync.research import desk
    farm = N(kind="news", source="Bing News: Ad Hoc News", url="https://www.ad-hoc-news.de/x", id="1", text="t", snippet="")
    wire = N(kind="news", source="Bing News: Reuters", url="https://www.reuters.com/x", id="2", text="t", snippet="")
    filing = N(kind="filing", source="SEC EDGAR: ainvest mention", url="https://sec.gov/x", id="3", text="t", snippet="")
    assert desk._low_tier(farm) and not desk._low_tier(wire) and not desk._low_tier(filing)


def test_facts_about_other_companies_are_dropped():
    # round-6 review: a news page about Synaptics gave "guidance" facts in NVIDIA's notes
    doc = FakeDoc("n1", "news", "Synaptics Reports First Quarter Results", "Bing News: Markets Insider",
                  date(2026, 11, 6), "u", "en", "Synaptics will not host a quarterly earnings conference call.")
    chunk = desk._Chunk(doc, 0, doc.text, 1.0)
    ours = desk.Extracted(questions=[1], fact="Synaptics will not host a call.",
                          quote="Synaptics will not host a quarterly earnings conference call.", about_company=False)
    kept, dropped = desk.verify([(chunk, ours)], [("guidance", "q")])
    assert kept == [] and dropped == 1


def test_missing_next_year_outlook_is_reported_as_a_gap():
    rel = FakeDoc("p", "results_commentary", "CFO commentary", "SEC EDGAR", date(2026, 8, 26), "v", "en", "")
    q3 = desk._Found("guidance", "Revenue is expected to be $108.0 billion for Q3 FY27.", "q", rel, 0, (108.0,))
    qs = [("guidance", "g")]
    b = desk.brief([q3], qs, 1, 1, 0, next_year=2028)
    assert any(g.startswith("Management's outlook for fiscal 2028") for g in b.gaps)
    fy28 = desk._Found("guidance", "Management expects fiscal 2028 revenue growth of approximately 70%.", "q", rel,
                       1, (70.0,))
    b2 = desk.brief([q3, fy28], qs, 1, 1, 0, next_year=2028)
    assert not any("fiscal 2028" in g for g in b2.gaps)


def test_fixed_searches_ask_for_next_year_outlook_first():
    d = _data()
    qs = desk._default_queries(d, Market.US)
    nxt = desk.next_fiscal_year(d)
    assert qs[0][0].endswith("earnings call transcript") and qs[1][0].endswith("earnings call outlook")
    if nxt:
        assert any(f"fiscal {nxt} outlook" in q for q, _ in qs)


def test_biggest_recent_move_gets_a_search():
    d = _data()
    d.technicals = SimpleNamespace(big_move=-0.093, big_move_date=date(2026, 11, 5))
    qs = [q for q, _ in desk._default_queries(d, Market.US)]
    assert "NVIDIA stock falls November 5" in qs and "NVIDIA gross margin guidance" in qs


def test_key_facts_are_kept_beyond_the_topic_caps_and_missing_items_listed():
    """Round 8: the quarter's commitments and half-year gains were lost to per-topic caps. Key facts read from the
    whole latest results documents are always kept, and checklist items not found become gaps."""
    doc = FakeDoc("d1", "results_commentary", "CFO commentary Q2", "SEC EDGAR", date(2026, 8, 26), "", "en", RELEASE)
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo",
             "lima", "mike", "november", "oscar"]
    found = [desk._Found("guidance", f"{w.title()} {w}s {w}ing {w}ed.", "q", doc, i, (float(i),), 1)
             for i, w in enumerate(words[:desk.PER_TOPIC + 3])]
    key = desk._Found("guidance", "Management expects Q3 revenue of $108.0 billion.", "q", doc, -1, (108.0,), 0,
                      "guidance")
    b = desk.brief([key] + found, [("guidance", "Q")], 1, 1, 0, None, ["customers", "commitments"], [doc])
    texts = [f.text for f in b.facts]
    assert texts[0].startswith("Management expects Q3") and b.facts[0].key == "guidance"
    assert sum(1 for f in b.facts if not f.key) == desk.PER_TOPIC   # the cap still applies to the other notes
    assert any("Not stated in the latest results documents" in g and "customer concentration" in g for g in b.gaps)
    block = desk.facts_block(b)
    assert block.startswith("KEY FACTS from the latest results documents")


def test_latest_results_docs_skip_the_previous_quarter():
    new = FakeDoc("a", "results_release", "Q2 release", "SEC", date(2026, 8, 26), "", "en", "x" * 50)
    com = FakeDoc("b", "results_commentary", "Q2 commentary", "SEC", date(2026, 8, 26), "", "en", "y" * 50)
    old = FakeDoc("c", "results_commentary", "Q1 commentary (previous quarter, 8-K)", "SEC", date(2026, 5, 27), "",
                  "en", "z" * 50)
    assert [d.id for d in desk.latest_results_docs([old, com, new])] == ["a", "b"]


def test_the_quarters_call_transcript_is_read_with_the_results():
    """Rounds 6 and 8: the next-year outlook was said on the call, not in the release. A transcript published within
    two weeks of the results joins the key-facts read; an older quarter's does not."""
    rel = FakeDoc("a", "results_release", "Q2 release", "SEC", date(2026, 8, 26), "", "en", "x" * 50)
    call = FakeDoc("t", "transcript", "NVIDIA (NVDA) Q2 2027 Earnings Call Transcript", "Bing News: The Motley Fool",
                   date(2026, 8, 31), "", "en", "y" * 6000)
    old = FakeDoc("o", "transcript", "NVIDIA (NVDA) Q1 2027 Earnings Call Transcript", "Bing News: The Motley Fool",
                  date(2026, 5, 30), "", "en", "z" * 6000)
    assert [d.id for d in desk.latest_results_docs([rel, old, call])] == ["a", "t"]


def test_next_year_outlook_said_on_the_call_counts_for_the_next_fiscal_year():
    from investsync.narrative import forecast as fc
    from investsync.schema import ResearchBrief, ResearchFact
    d = _data()
    d.financials = SimpleNamespace(latest=None, years=[SimpleNamespace(fiscal_year=2026)])
    nxt = 2028
    d.research = ResearchBrief(facts=[ResearchFact(id="R1", topic="guidance", text="Management expects revenue to "
                                                   "grow about 70% next year.", quote="next year", source="x",
                                                   title="call", kind="transcript", key="outlook")])
    assert fc._outlook_ids(d, nxt) == ["R1"] and fc._outlook_ids(d, nxt - 1) == []


def test_transcript_dated_by_the_call_not_the_write_up():
    """Round 9: the call was dated by the article (31 Aug) instead of the day it was held (26 Aug)."""
    from datetime import date
    from investsync.research import desk
    head = "Call participants ... DATE Wednesday, Aug. 26, 2026 at 5:00 p.m. ET ... posted Aug 31, 2026"
    assert desk.call_date(head, date(2026, 8, 31)) == date(2026, 8, 26)
    assert desk.call_date("业绩说明会于2026年8月20日召开", date(2026, 8, 25)) == date(2026, 8, 20)
    assert desk.call_date("held 3 March 2026", date(2026, 8, 25)) is None   # too old: not this call
    assert desk.call_date("no date here", date(2026, 8, 25)) is None
