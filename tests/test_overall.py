"""Page-1 overall view: the model plus recent broker views, time-weighted. Offline."""
from datetime import timedelta

from investsync.quant import overall, street
from investsync.render import report_vm, viewmodel
from investsync.render.render import render_pdf
from investsync.schema import BrokerNote, Consensus, Rating

from tests.test_street import TODAY, _note, _pages, _text, tencent

CFG = dict(overall.DEFAULTS)


def _rated(d, rating="Buy"):
    p = d.quote.price
    d.rating = Rating(rating=rating, fair_value=p * (1.3 if rating == "Buy" else 0.6 if rating == "Sell" else 1.0),
                      upside=0.3 if rating == "Buy" else -0.4 if rating == "Sell" else 0.0, currency="HKD",
                      buy_threshold=0.15, sell_threshold=-0.1)
    return d


def _with(d, notes, writeups=()):
    d.street = street.build(d, notes, today=TODAY, writeups=list(writeups))
    d.overall = overall.build(d, today=TODAY, cfg=CFG)
    return d


def test_only_recent_views_count_and_newer_ones_weigh_more():
    d = _rated(tencent(), "Buy")
    p = d.quote.price
    ov = _with(d, [_note("A", 5, "Buy", p * 1.5), _note("B", 60, "Hold", p * 1.1),
                   _note("C", 200, "Sell", p * 0.5), _note("A", 100, "Sell")]).overall
    assert [v.broker for v in ov.votes] == ["A", "B"]           # C is stale; A's older note is replaced
    assert ov.stale and ov.stale[0].startswith("C (")
    assert ov.brokers_score == round((5 * 1 + 3 * 0.5) / 1.5, 2)  # 30-90 days count half
    assert ov.targets_n == 2                                       # the stale target is not used


def test_model_counts_one_third_and_few_brokers_count_less():
    d = _rated(tencent(), "Sell")
    many = _with(d, [_note(f"B{i}", 3, "Buy") for i in range(5)]).overall
    assert round(many.model_share, 2) == 0.33 and many.score == round(1 / 3 + 5 * 2 / 3, 2)
    assert many.split and many.rating == "Outperform" and "two or more steps apart" in many.split_note
    one = _with(_rated(tencent(), "Sell"), [_note("X", 3, "Buy")]).overall
    assert one.thin and round(one.broker_share, 2) == round(2 / 3 / 3, 2)   # one broker of the three needed


def test_not_rated_model_leaves_the_brokers_alone():
    d = _rated(tencent(), "Buy")
    d.rating = d.rating.model_copy(update={"rating": "Not rated", "fair_value": None})
    ov = _with(d, [_note("A", 3, "Hold"), _note("B", 3, "Outperform"), _note("C", 3, "Outperform")]).overall
    assert ov.model_share == 0 and ov.broker_share == 1 and ov.rating == "Outperform"
    assert "model not rated" in ov.basis


def test_newer_hk_write_up_updates_that_brokers_view():
    d = _rated(tencent(), "Buy")
    p = d.quote.price
    table = [_note("CLSA", 20, "Buy", p * 1.6), _note("Citi", 5, "Buy", p * 1.5), _note("UBS", 5, "Buy", p * 1.5)]
    w = BrokerNote(on=TODAY, broker="CLSA", rating="Hold", target=p * 1.05, title="t", abstract="a", source="AAStocks")
    ov = _with(d, table, [w]).overall
    clsa = next(v for v in ov.votes if v.broker == "CLSA")
    assert clsa.rating == "Hold" and clsa.on == TODAY and clsa.source == "AAStocks"


def test_yahoo_consensus_is_a_cross_check_only():
    d = _rated(tencent(), "Buy")
    d.consensus = (d.consensus or Consensus()).model_copy(update={"recommendation_mean": 1.4, "analysts": 41})
    ov = _with(d, [_note("A", 3, "Buy"), _note("B", 3, "Buy"), _note("C", 3, "Buy")]).overall
    y = next(i for i in ov.inputs if i.source.startswith("Yahoo"))
    assert y.weight == 0 and y.score == 4.6 and y.rating == "Buy"
    assert abs(sum(i.weight for i in ov.inputs) - 1) < 1e-9


def test_overall_view_leads_page_one_and_chapter_one():
    d = _rated(tencent(), "Sell")
    p = d.quote.price
    _with(d, [_note(f"B{i}", 3, "Buy", p * 1.5) for i in range(4)])
    vm = viewmodel.overall(d)
    assert vm["rating"] == "Outperform" and vm["split"] == "views split"
    assert [r["label"] for r in vm["rows"]] == ["AI rating", "Brokers"]
    assert _pages(render_pdf(d, layout="tearsheet")) == 1
    text = _text(render_pdf(d))
    assert "OVERALL VIEW" in text.upper() and "Left out" not in text      # nothing stale here
    assert report_vm._overall(d)["rows"][0][0].startswith("InvestSync model")


def test_commentary_may_name_the_overall_view_but_not_another_rating():
    from investsync.narrative.commentary import _rating_conflicts
    text = "The overall view is Hold, while the model's SELL rating reflects a lower fair value."
    assert _rating_conflicts(text, "Sell", ("Hold",)) == []
    assert _rating_conflicts("We would BUY the shares.", "Sell", ("Hold",)) == ["Buy"]
    assert _rating_conflicts("We give it a Buy rating.", "Sell", ("Hold",)) == ["Buy"]   # mixed case too
    assert _rating_conflicts("Investors may buy or sell the shares.", "Hold") == []


def test_history_reports_a_change_in_the_overall_view(tmp_path, monkeypatch):
    from investsync import history
    monkeypatch.setenv("INVESTSYNC_HISTORY", "1")
    monkeypatch.setenv("INVESTSYNC_HISTORY_DIR", str(tmp_path))
    d = _rated(tencent(), "Buy")
    _with(d, [_note("A", 3, "Hold"), _note("B", 3, "Hold"), _note("C", 3, "Hold")])
    d.quote.as_of = TODAY - timedelta(days=2)
    history.save(d)
    d.quote.as_of = TODAY
    _with(d, [_note("A", 1, "Buy"), _note("B", 1, "Buy"), _note("C", 1, "Buy")])
    s = history.compare(d)
    assert any(c.startswith("Overall view changed: Outperform") and "→ Buy" in c for c in s.changes)


def test_a_broker_rating_quoted_from_the_news_is_not_a_conflict():
    from investsync.narrative.commentary import _rating_conflicts
    quote = "Industrial Securities maintained a Buy rating, noting third-quarter pretax profit beat forecasts."
    assert _rating_conflicts(quote, "Sell", ("Hold",)) == []
    assert _rating_conflicts("The AI rating is Sell, while Citi has a BUY call.", "Sell", (), ("Citi",)) == []
    assert _rating_conflicts("J.P. Morgan reiterated its Buy rating.", "Sell") == []
    # our own rating misstated is still caught, even next to a broker
    assert _rating_conflicts("The AI rating is Buy, in line with brokers.", "Sell") == ["Buy"]
    assert _rating_conflicts("We keep a Buy rating.", "Sell") == ["Buy"]
