"""The data-only edition (Karel, 12 Nov 2026: "the no AI option on the web which basically just aggregates data for the
reader to write its own conclusions").

``strip`` returns a copy of a report's data with everything an AI model wrote and every verdict taken out: no
commentary, research notes, forecast or scenarios, no news tags or broker summaries, no rating, overall view or
"since the last report" box, no model fair value in the broker comparison, and no AI-chosen or AI-added analyst
questions (the code's choice from the question bank replaces them, with figures computed in code). What stays is the
data and the
calculations made in code (statements, ratios, DCF, sensitivities, peer multiples, technicals, filings, news headlines
as published, sources). The pipeline uses it for a data-only build (``build_tearsheet(data_only=True)``, which also
never calls an AI model), and the renderer uses it for the "data" layout, so any saved JSON can be printed as a
data-only edition.
"""
from __future__ import annotations

import logging
import re

from ..schema import AuditCheck, TearSheetData

log = logging.getLogger(__name__)

# data notes that only make sense next to AI text (left out of the data-only edition), and ones reworded for it
_AI_WARNINGS = ("Commentary step failed", "Research step failed")
_REWORD = {"Latest report is still downloading; commentary uses news only this time.":
           "The latest annual / interim report was still downloading, so its excerpts are not in this edition."}


def _peer_method(method: str) -> str:
    """The peer method without the per-peer reasons an AI step wrote ("Why each: ..."); the code's screens stay."""
    head, sep, rest = (method or "").partition(" Why each: ")
    if not sep:
        return method or ""
    left = ""
    if "Left out by the code's screens:" in rest:
        names = re.findall(r"(?:^|; )\s*([A-Z0-9][A-Z0-9.]*) \(", rest.split("Left out by the code's screens:", 1)[1])
        if names:
            left = f" Left out by the code's screens: {', '.join(names)}."
    return head + left


def _audit(d: TearSheetData) -> None:
    """The data audit without its AI rows (rating, commentary, wording checks, fact sweep, debate)."""
    from ..quant import audit
    try:
        a = audit.run(d)
    except Exception as e:  # keep the saved audit rather than lose the chapter
        log.warning("data-only audit failed: %s", e)
        a = d.audit
    if a is None:
        return
    checks: list[AuditCheck] = [c for c in a.checks if not c.name.startswith("AI ")]
    statuses = {c.status for c in checks}
    a.checks = checks
    a.status = "review" if "fail" in statuses else "caveated" if "caveat" in statuses else "publishable"
    d.audit = a


def strip(data: TearSheetData) -> TearSheetData:
    """A deep copy of ``data`` as the data-only edition prints it (see the module note). Never raises on a missing
    part: every step works on whatever the data has."""
    d = data.model_copy(deep=True)
    d.narrative = d.research = d.forecast = d.ai_usage = None
    if d.valuation is not None:
        d.valuation.scenarios = None  # AI-set bear / base / bull assumptions
    d.rating = d.overall = d.since_last = None  # no verdict: no Buy / Hold / Sell, no fair value, no rating history
    for n in d.news:  # headlines as published, without the AI step's translation, tag and sentiment
        n.headline_en = n.category = n.sentiment = n.relevant = None
    st = d.street
    if st is not None:
        st.synthesis = None
        for n in [*st.notes, *st.writeups]:
            n.summary_en = None
        try:
            from ..quant import street
            street.refresh_model(d)  # no model fair value beside the brokers' targets
        except Exception as e:
            log.warning("data-only street view: %s", e)
            st.model_fair_value = st.model_rating = st.targets_above_model = None
    if d.comps is not None and d.comps.method:
        d.comps.method = _peer_method(d.comps.method)
    try:
        from ..quant import scorecard
        d.scorecard = scorecard.build(d)  # its value checks no longer compare with a model fair value
    except Exception as e:
        log.warning("data-only scorecard: %s", e)
    d.warnings = [_REWORD.get(w, w) for w in d.warnings if not w.startswith(_AI_WARNINGS)]
    try:  # the reader's homework: bank questions chosen in code (no AI-added question, no answer)
        from ..narrative import questions
        d.analyst_questions = questions.code_select(d)
    except Exception as e:
        log.warning("data-only analyst questions: %s", e)
        d.analyst_questions = None
    _audit(d)
    return d
