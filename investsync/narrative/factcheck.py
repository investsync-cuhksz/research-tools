"""Fact sweep (run 2): code checks on every AI-written sentence, against the report's own data.

Why: the blind reviewers of run 1 (10 Nov 2026) verified errors that every earlier check let through, because each
figure in the sentence was real and only its date, label or wording was wrong: a share-price move dated on a Sunday,
today's P/E called the five-year median, "one-third" for 141 of 156, company guidance called "a press report, not
company guidance", a scenario weight that was not the scenario's, and an older "remaining buyback" figure after a
later authorisation. Each check below reads the report's own data (price chart, P/E history, peers, scenarios,
research notes), never a list of facts about one company.

- ``find(text, data)`` lists the issues in a text. It never raises: each check runs in its own ``try``.
- ``sweep(narrative, data)`` deletes each offending sentence from every AI-written field of the narrative and
  returns one line per deletion ("[struck] <check>: <sentence>"). A field that would be emptied gets a fallback (see
  ``sweep``); nothing here can make a report "flagged".
- ``writer_notes(data)`` gives the writers the facts that prevent these errors at the source (daily closes, the net
  cash bridge, the P/E labels), built in code.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property
from typing import Optional

from pydantic import BaseModel

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Issue:
    check: str
    sentence: str
    message: str


# ---------------------------------------------------------------- sentences
_BREAK = re.compile(r"([.!?][\"'”’)\]]*)(\s+)(?=[A-Z0-9\"'“‘(\[$€£¥+\-−])")
_ABBREV = {"u.s", "u.k", "e.g", "i.e", "vs", "inc", "corp", "co", "ltd", "no", "nos", "mr", "mrs", "ms", "dr", "st",
           "approx", "est", "fig", "cf", "jr", "sr", "p.a", "a.m", "p.m"}
_MONTH_ABBR = {"jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
_LEAD = re.compile(r"\s*(?:[-•*]\s+)?")


def _spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence in ``text``; a sentence never crosses a line break, and a leading bullet
    marker is not part of it."""
    out, pos = [], 0
    for line in (text or "").split("\n"):
        base, pos = pos, pos + len(line) + 1
        i = _LEAD.match(line).end()
        start = i
        for m in _BREAK.finditer(line, i):
            tok = re.search(r"(\S+)$", line[start:m.start()])
            word = (tok.group(1) if tok else "").lower().strip("(\"'")
            nxt = line[m.end():m.end() + 1]
            if word in _ABBREV or re.fullmatch(r"[a-z]", word) or (word in _MONTH_ABBR and nxt.isdigit()):
                continue
            out.append((base + start, base + m.end(1)))
            start = m.end()
        if line[start:].strip():
            end = len(line.rstrip())
            out.append((base + start, base + end))
    return [(a, b) for a, b in out if b > a]


def sentences(text: str) -> list[str]:
    return [text[a:b] for a, b in _spans(text)]


# ---------------------------------------------------------------- report data, read once per check run
_PCT = re.compile(r"([+\-−–]?\d+(?:\.\d+)?)\s?%")
_MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
        r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?(?![a-z])")
_DATE_DM = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"(?:,?\s+((?:19|20)\d\d)\b)?", re.I)
_DATE_MD = re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*%|\.\d|,\d{3})(?:,?\s+((?:19|20)\d\d)\b)?",
                      re.I)
_DATE_ISO = re.compile(r"\b((?:19|20)\d\d)-(\d\d)-(\d\d)\b")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _dates(s: str, year: int) -> list[tuple[int, int, date]]:
    """(start, end, date) of every calendar date in a sentence; the year defaults to ``year``."""
    found: dict[int, tuple[int, int, date]] = {}
    for rx, (gd, gm, gy) in ((_DATE_DM, (1, 2, 3)), (_DATE_MD, (2, 1, 3))):
        for m in rx.finditer(s):
            try:
                d = date(int(m.group(gy) or year), _MONTHS.index(m.group(gm)[:3].lower()) + 1, int(m.group(gd)))
            except ValueError:
                continue
            if not any(a <= m.start() < b for a, b, _ in found.values()):
                found[m.start()] = (m.start(), m.end(), d)
    for m in _DATE_ISO.finditer(s):
        try:
            found.setdefault(m.start(), (m.start(), m.end(), date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
        except ValueError:
            continue
    return [found[k] for k in sorted(found)]


def _weekdays_between(a: date, b: date) -> int:
    """Weekdays strictly between two dates."""
    n, d = 0, a + timedelta(days=1)
    while d < b:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def _fmt_day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


class _Ctx:
    """What the checks read from the report, computed lazily (a failure stays inside the check that needs it)."""

    def __init__(self, data):
        self.data = data

    # ---- prices
    @cached_property
    def as_of(self) -> date:
        return self.data.quote.as_of

    @cached_property
    def closes(self) -> dict[date, float]:
        t = self.data.technicals
        return {p.d: p.close for p in (t.chart if t else []) if p.close and p.d <= self.as_of}

    @cached_property
    def days(self) -> list[date]:
        return sorted(self.closes)

    def _dense(self, d: date) -> bool:
        """The chart lists every session around ``d`` (it is downsampled over long periods): within three weeks
        either side, at most one weekday is missing outside the gap that contains ``d``."""
        days = self.days
        near = [x for x in days if abs((x - d).days) <= 21]
        if len([x for x in near if x < d]) < 5 or len([x for x in near if x > d]) < 5:
            return False
        skipped = sum(_weekdays_between(a, b) for a, b in zip(near, near[1:]) if not (a < d < b))
        return skipped <= 1

    def is_session(self, d: date) -> Optional[bool]:
        """True / False when known; None when the chart cannot tell (a weekday the downsampled chart skips)."""
        if d in self.closes:
            return True
        if d.weekday() >= 5:
            return False
        return False if self._dense(d) else None

    def change(self, d: date) -> Optional[float]:
        """Close-to-close change on session ``d``, when the previous session is known."""
        t = self.data.technicals
        if t is not None and t.big_move_date == d and t.big_move is not None:
            return t.big_move
        if d not in self.closes:
            return None
        i = self.days.index(d)
        if i == 0:
            return None
        prev = self.days[i - 1]
        if _weekdays_between(prev, d) and not self._dense(d):
            return None
        return self.closes[d] / self.closes[prev] - 1

    def next_sessions(self, d: date, n: int = 2) -> str:
        out = []
        for x in [x for x in self.days if x > d][:n]:
            c = self.change(x)
            out.append(f"{x.day} {x:%b} {c:+.1%}" if c is not None else f"{x.day} {x:%b} closed at {self.closes[x]:,.2f}")
        return ", ".join(out)

    # ---- the move regex (company name as a subject only directly before a move verb)
    @cached_property
    def move_rx(self) -> re.Pattern:
        p = self.data.profile
        names = {w for w in [(p.name or "").split()[0] if p.name else "", p.ticker.split(".")[0]]
                 if len(w) >= 3 and not w.isdigit() and w.lower() not in ("the", "and")}
        name = ("|\\b(?:" + "|".join(re.escape(w) for w in sorted(names)) + r")(?:'s)?\s+(?:shares\s+|stock\s+)?"
                + _VERB + r"\b") if names else ""
        return re.compile(_SUBJECT + r"[^.;]{0,60}?\b" + _VERB + r"\b|\bclosed (?:down|up|lower|higher)\b" + name, re.I)

    # ---- statistics with their labels (value, unit, class, label, metric)
    @cached_property
    def stats(self) -> list[tuple[float, str, str, str, str]]:
        d, out = self.data, []
        b = d.pe_band
        if b is not None:
            yrs = 5
            if b.series:
                yrs = max(1, round((b.series[-1].d - b.series[0].d).days / 365.25))
            out += [(b.current, "x", "current", "today's P/E on last fiscal year's EPS", "pe_hist"),
                    (b.median, "x", "hist_median", f"the {yrs}-year median P/E", "pe_hist"),
                    (b.mean, "x", "hist_mean", f"the {yrs}-year mean P/E", "pe_hist")]
        q = d.quote
        if q.pe_ttm:
            out.append((q.pe_ttm, "x", "own", "the company's own trailing P/E", "pe_ttm"))
        c = d.comps
        fwd = (c.target.pe_fwd if c else None) or (d.consensus.forward_pe if d.consensus else None)
        if fwd:
            out.append((fwd, "x", "own", "the company's own forward P/E", "pe_fwd"))
        if c is not None:
            for k, unit, lab in (("pe_ttm", "x", "trailing P/E"), ("pe_fwd", "x", "forward P/E"),
                                 ("ev_ebitda", "x", "EV/EBITDA"), ("pb", "x", "P/B"),
                                 ("revenue_growth", "%", "revenue growth"), ("gross_margin", "%", "gross margin"),
                                 ("operating_margin", "%", "operating margin"), ("net_margin", "%", "net margin"),
                                 ("roe", "%", "ROE")):
                own, med = getattr(c.target, k, None), getattr(c.median, k, None)
                f = 100 if unit == "%" else 1
                if own is not None and k not in ("pe_ttm", "pe_fwd"):
                    out.append((own * f, unit, "own", f"the company's own {lab}", k))
                if med is not None:
                    out.append((med * f, unit, "peer_median", f"the peer median {lab}", k))
        v = d.valuation
        rv = v.reverse if v else None
        if rv is not None:
            for x, lab in ((rv.model_growth, "the growth of the model's mechanical DCF"),
                           (rv.implied_growth, "the growth the price implies (reverse DCF)"),
                           (rv.model_fcf_margin, "the FCF margin of the model's mechanical DCF"),
                           (rv.implied_fcf_margin, "the FCF margin the price implies (reverse DCF)")):
                if x is not None:
                    out.append((x * 100, "%", "mech", lab, "growth"))
        sc = v.scenarios if v else None
        base = next((x for x in (sc.scenarios if sc else []) if x.name == "base"), None)
        if base is not None:
            out += [(g * 100, "%", "base", "a year of our base scenario's growth", "growth") for g in base.revenue_growth]
            out.append((base.fcf_margin * 100, "%", "base", "our base scenario's FCF margin", "growth"))
            cagr = self.base_cagr
            if cagr is not None:
                out.append((cagr * 100, "%", "base", "our base scenario's growth", "growth"))
        return [x for x in out if x[0] is not None]

    @cached_property
    def base_cagr(self) -> Optional[float]:
        try:
            from .facts import base_scenario_cagr
            got = base_scenario_cagr(self.data)
            return got[0] if got else None
        except Exception:  # noqa: BLE001 - optional
            return None

    @cached_property
    def scenario_weights(self) -> dict[str, float]:
        v = self.data.valuation
        sc = v.scenarios if v else None
        return {x.name: x.probability * 100 for x in (sc.scenarios if sc else [])}


# ---------------------------------------------------------------- 1. dated share-price moves
_SUBJECT = (r"\b(?:shares|share price|stock price|stock)\b(?![- ](?:based|options?|compensation|awards?|split|market|"
            r"exchange|count|outstanding|in issue|repurchases?|buybacks?|of\b))")
_VERB = (r"(?:closed|fell|falls?|falling|dropped|drops?|slid|slides?|slumped|plunged|tumbled|lost|rose|rises?|gained|"
         r"jumped|surged|rallied|sank|declined|climbed|soared|down|up)")
_SAME_DAY = re.compile(r"\bthat day\b|\bon the day\b|\bthe same day\b", re.I)
_CLOSED_PCT = re.compile(r"\bclosed\s+(?:down|up|lower|higher)\s+(?:by\s+)?([+\-−–]?\d+(?:\.\d+)?)\s?%", re.I)
_ON = re.compile(r"(?:^|[^\w])(?:on|On)\s+(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?(?:the\s+)?$", re.I)
_NOT_MOVE_ON = re.compile(r"\b(?:ended|ending|end|due|held|scheduled|expiring|expires?|filed|reported|published|"
                          r"dated|announced|released|sent|signed)\s+on\s+(?:\w+day,?\s+)?(?:the\s+)?$", re.I)
_CLAUSE = re.compile(r";|\s[—–]\s|\s-\s")


def _clauses(s: str) -> list[tuple[int, int]]:
    cuts = [0] + [m.end() for m in _CLAUSE.finditer(s)] + [len(s) + 1]
    return list(zip(cuts, cuts[1:]))


def _num(x: str) -> float:
    return abs(float(x.replace("−", "-").replace("–", "-")))


def _move_dates(sents: list[str], ctx: _Ctx) -> list[Issue]:
    """A share-price move tied to a calendar date ("fell 5.5% on 8 November", "...on 8 November; the shares closed
    down 5.5% that day"): the date must be a trading session, and a move said to have happened that day must be
    within 1.0 point of that session's close-to-close change."""
    if len(ctx.closes) < 30:
        return []
    first, as_of = ctx.days[0], ctx.as_of
    out = []
    for s in sents:
        if not _PCT.search(s):
            continue
        moves = list(ctx.move_rx.finditer(s))
        dates = _dates(s, as_of.year) if moves else []
        if not dates:
            continue
        flagged = set()
        for cs, ce in _clauses(s):
            clause = s[cs:ce]
            mv = [m for m in moves if cs <= m.start() < ce]
            if not mv or not _PCT.search(clause):
                continue
            on = [x for x in dates if cs <= x[0] < ce and _ON.search(s[max(0, x[0] - 40):x[0]])
                  and not _NOT_MOVE_ON.search(s[max(0, x[0] - 60):x[0]])]
            same = _SAME_DAY.search(clause)
            targets = []
            for m in mv:
                if on:  # "fell 5.5% on 10 Nov" (a date after the move) first, else "On 8 Nov, the shares fell"
                    after = [x for x in on if x[0] >= m.end() and x[0] - m.end() <= 80]
                    before = [x for x in on if x[1] <= m.start() and m.start() - x[1] <= 80]
                    if after or before:
                        targets.append(after[0][2] if after else before[-1][2])
                elif same:
                    prior = [x for x in dates if x[1] <= cs + same.start()]
                    if prior:
                        targets.append(prior[-1][2])
            for d in dict.fromkeys(targets):
                if not (first < d <= as_of) or d in flagged:
                    continue
                sess = ctx.is_session(d)
                if sess is False:
                    flagged.add(d)
                    what = f"was a {d:%A}" if d.weekday() >= 5 else "was not a trading day (market holiday)"
                    nxt = ctx.next_sessions(d)
                    out.append(Issue("move_dates", s, f"{_fmt_day(d)} {what}; a move is dated by its session"
                                     + (f" (next: {nxt})" if nxt else "")))
                    continue
                if not sess:
                    continue
                chg = ctx.change(d)
                if chg is None:
                    continue
                stated = ([_num(x) for x in _PCT.findall(clause)] if same else
                          [_num(x) for x in _CLOSED_PCT.findall(clause)])
                if stated and min(abs(abs(chg) * 100 - x) for x in stated) > 1.0:
                    flagged.add(d)
                    out.append(Issue("move_dates", s, f"on {_fmt_day(d)} the shares closed {chg:+.1%} "
                                     f"(close to close), not {stated[0]:.1f}%"))
    return out


# ---------------------------------------------------------------- 2. statistic labels
_V = r"(?<![\d.,])(\d{1,4}(?:\.\d+)?)\s?(x|%|times)(?![\w/])"
_QUAL = (r"(?:(?:\w+|\d+)[- ]year|historical|long-run|long-term|own|its own|peer|peers'?|sector|industry|group)")
_CENTRAL_1 = re.compile(_V + r"\s+(?:(" + _QUAL + r")\s+)?(?:P/E\s+)?(median|average|mean)\b", re.I)
_CENTRAL_2 = re.compile(r"\b(?:(" + _QUAL + r")\s+)?(median|average|mean)\s+(?:P/E\s+|multiple\s+|EV/EBITDA\s+|P/B\s+|"
                        r"ratio\s+)?(?:of\s+|is\s+|was\s+|at\s+|stands at\s+|sits at\s+)?(?:about\s+|around\s+|"
                        r"roughly\s+|~)?" + _V, re.I)
_BASE = r"base(?:[- ]case|\s+scenario)"
_BASE_1 = re.compile(_V + r"\s+(?:a year\s+|annual\s+|revenue\s+)?(?:growth\s+)?(?:in|for|under)\s+(?:the|our)\s+"
                     + _BASE + r"\b", re.I)
_BASE_2 = re.compile(_V + r"\s+" + _BASE + r"\b", re.I)
_BASE_3 = re.compile(r"\b" + _BASE + r"(?:'s)?\s+(?:revenue\s+)?(?:growth|CAGR)\s+(?:of\s+|is\s+|at\s+)?(?:about\s+)?"
                     + _V, re.I)


def _same(text_value: str, stat: float) -> bool:
    nd = len(text_value.split(".")[1]) if "." in text_value else 0
    return abs(round(stat, nd) - float(text_value)) < 10 ** -nd / 2 + 1e-9


def _qual_class(q: Optional[str]) -> str:
    q = (q or "").lower()
    if not q:
        return "any"
    return "peer" if any(w in q for w in ("peer", "sector", "industry", "group")) else "hist"


def _stat_labels(sents: list[str], ctx: _Ctx) -> list[Issue]:
    """"versus a 34.5x five-year median" when 34.5x is today's P/E and the median is 64.0x: a median / average /
    mean label put directly on a value that is another statistic; "peer median" on the company's own multiple; and
    "base case" on the model DCF's growth."""
    stats = ctx.stats
    if not stats:
        return []
    out = []
    for s in sents:
        found = []
        for m in _CENTRAL_1.finditer(s):
            found.append((m.group(1), m.group(2), m.group(3), m.group(4)))
        for m in _CENTRAL_2.finditer(s):
            found.append((m.group(3), m.group(4), m.group(1), m.group(2)))
        for val, unit, qual, lab in found:
            u = "%" if unit == "%" else "x"
            hits = [x for x in stats if x[1] == u and _same(val, x[0])]
            if not hits:
                continue
            qc = _qual_class(qual)
            ok_cls = {"peer": {"peer_median"}, "hist": {"hist_median", "hist_mean"},
                      "any": {"peer_median", "hist_median", "hist_mean"}}[qc]
            if any(x[2] in ok_cls for x in hits):
                continue
            wrong = [x for x in hits if x[2] in ("current", "own")
                     or (qc == "peer" and x[2] in ("hist_median", "hist_mean"))
                     or (qc == "hist" and x[2] == "peer_median")]
            if not wrong:
                continue
            w = wrong[0]
            if qc == "peer" or (qc == "any" and w[2] == "own"):
                right = [x for x in stats if x[2] == "peer_median" and x[4] == w[4]]
            else:
                right = [x for x in stats if x[2] == ("hist_mean" if lab.lower() in ("average", "mean") else "hist_median")]
            msg = f"{val}{u} is {w[3]}" + (f"; {right[0][3]} is {_show(right[0])}" if right else "")
            out.append(Issue("stat_labels", s, msg))
            break
        else:
            if ctx.base_cagr is None:
                continue
            for rx in (_BASE_1, _BASE_2, _BASE_3):
                m = rx.search(s)
                if not m or m.group(2) != "%":
                    continue
                hits = [x for x in stats if x[1] == "%" and _same(m.group(1), x[0])]
                if any(x[2] == "base" for x in hits):
                    continue
                mech = [x for x in hits if x[2] == "mech"]
                if mech:
                    out.append(Issue("stat_labels", s, f"{m.group(1)}% is {mech[0][3]}; our base scenario's growth is "
                                                      f"{ctx.base_cagr:.1%}"))
                    break
    return out


def _show(x) -> str:
    return f"{x[0]:.1f}{x[1]}"


# ---------------------------------------------------------------- 3. fraction words
FRACTION = {"one-third": 1 / 3, "one third": 1 / 3, "a third": 1 / 3, "two-thirds": 2 / 3, "two thirds": 2 / 3,
            "half": 0.5, "one-half": 0.5, "a quarter": 0.25, "one-quarter": 0.25, "one quarter": 0.25,
            "three-quarters": 0.75, "three quarters": 0.75, "one-fifth": 0.2, "a fifth": 0.2, "one-tenth": 0.1}
_FRACTION_RX = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in sorted(FRACTION, key=len, reverse=True)) + r")\b",
                          re.I)
_X_OF_Y = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?([A-Za-z$%]{0,8})\s+(?:out\s+)?of\s+(?:a\s+)?(?:total\s+)?(?:of\s+)?"
                     r"(?:about\s+|around\s+|roughly\s+|approximately\s+|~)?([A-Z$]{0,4})\s?(\d[\d,]*(?:\.\d+)?)")
_NOT_HALF = re.compile(r"(?:first|second|1st|2nd|latest|prior|previous|same|this|that|last|each|other|back|front)\s+"
                       r"$", re.I)
_HALF_YEAR = re.compile(r"^[- ]?(?:year|yearly|annual|time)\b|^\s+of\s+(?:the\s+)?(?:fiscal\s+)?(?:year|20\d\d|FY)", re.I)
_MORE = re.compile(r"(?:more than|over|above|at least|upwards of|in excess of|well over)\s+$", re.I)
_LESS = re.compile(r"(?:less than|under|below|fewer than|at most|well under)\s+$", re.I)


def _fractions(sents: list[str], ctx: _Ctx) -> list[Issue]:
    """"about one-third of planned capacity (141 GW out of 156 GW)": a fraction word within 160 characters of
    "X of Y" must be within 12 points of X / Y ("more than" / "less than" a fraction only one way)."""
    out = []
    for s in sents:
        for f in _FRACTION_RX.finditer(s):
            word = f.group(0).lower()
            if word == "half" and (_NOT_HALF.search(s[max(0, f.start() - 12):f.start()])
                                   or _HALF_YEAR.search(s[f.end():f.end() + 24])
                                   or re.search(r"and a\s+$", s[max(0, f.start() - 8):f.start()])):
                continue
            frac = FRACTION[word]
            before = s[max(0, f.start() - 16):f.start()]
            bad = None
            for m in _X_OF_Y.finditer(s):
                if abs(m.start() - f.start()) > 160 or m.group(2) == "%" or s[m.end(1):m.end(1) + 1] == "%":
                    continue
                ys = m.group(4)
                if re.fullmatch(r"(?:19|20)\d\d", ys) or m.group(3) in ("FY", "Q", "H"):
                    continue
                try:
                    x, y = float(m.group(1).replace(",", "")), float(ys.replace(",", ""))
                except ValueError:
                    continue
                if not (y > 0 and 0 < x <= y):
                    continue
                r = x / y
                if _MORE.search(before):
                    wrong = r < frac - 0.02
                elif _LESS.search(before):
                    wrong = r > frac + 0.02
                else:
                    wrong = abs(r - frac) > 0.12
                if wrong:
                    bad = f"\"{f.group(0)}\" does not match {m.group(1)} of {m.group(4)} ({r:.0%})"
                    break
            if bad:
                out.append(Issue("fractions", s, bad))
                break
    return out


# ---------------------------------------------------------------- 4. assertions of absence
NEG_PROVENANCE = re.compile(
    r"not\s+(?:a\s+)?(?:company|management|official|company-filed)\s+(?:guidance|figure|forecast|number)|"
    r"press reports?,?\s+not\b|not\s+(?:in|part of)\s+(?:the\s+)?(?:company's\s+)?(?:filed|filings?|official)\b|"
    r"(?:neither|no such) figure appears in the filed|only (?:in|from) (?:a |the )?press reports?", re.I)


def _provenance(sents: list[str], ctx: _Ctx) -> list[Issue]:
    """"press reports, not company guidance", "not in the filed documents": the pipeline has not read every company
    document (earnings calls are not filed), so it can never prove that a figure is absent from them."""
    return [Issue("provenance", s, "asserts that a figure is absent from the company's own statements, which the "
                                   "sources cannot prove; attribute it instead (\"management said ..., reported by "
                                   "<source>\")") for s in sents if NEG_PROVENANCE.search(s)]


# ---------------------------------------------------------------- 5. scenario weights
_W = r"(\d{1,2}(?:\.\d)?)%"
_SC = r"(bear|base|bull)"
_NOT_WEIGHT = (r"(?![- ]?(?:case\s+)?(?:downside|upside|fall|drop|decline|loss|gain|discount|premium|haircut|below|"
               r"above|lower|higher|return|growth|margin|cut|FCF|revenue|EPS|CAGR|path|value|price|target))")
_WEIGHT_RXS = [
    # "a 28% bear case": whole-number weights only, and not a growth or margin figure of the report (below)
    (re.compile(r"(?<![\d.])(\d{1,2})%\s+(?:weight(?:ing)?\s+(?:on|to|for)\s+(?:the\s+)?|probability\s+(?:on|of|for)\s+"
                r"(?:the\s+)?|chance\s+(?:of|for)\s+(?:the\s+)?)?" + _SC + r"\b(?:[- ]case)?" + _NOT_WEIGHT, re.I), 1, 2),
    (re.compile(r"\b" + _SC + r"(?:[- ]case)?\s+(?:[A-Z]{3}\s?|\$)?\d[\d,]*(?:\.\d+)?\s*(?:\(" + _W + r"\)|,?\s*"
                r"(?:weighted\s+)?at\s+" + _W + r"(?!\s*(?:upside|downside|above|below|up|down)))", re.I), None, 1),
    (re.compile(r"\b" + _SC + r"(?:[- ]case)?\s+(?:at|with|carries|gets|weighted at|has)\s+(?:a\s+)?(?:weight(?:ing)?\s+"
                r"of\s+|probability\s+of\s+)?" + _W + r"(?!\s*(?:upside|downside|above|below|lower|higher|discount|"
                r"premium|fall|drop|decline|loss|gain|return|growth|margin|of\b|a year|per|revenue|FCF))", re.I), 2, 1),
    (re.compile(r"\b" + _SC + r"(?:[- ]case)?\s+(?:weight(?:ing)?|probability)\s+(?:of\s+|is\s+|at\s+)?" + _W, re.I), 2, 1),
]


def _scenario_weights(sents: list[str], ctx: _Ctx) -> list[Issue]:
    """"a 28% bear case" when the bear scenario's probability is 25%."""
    w = ctx.scenario_weights
    if not w:
        return []
    out = []
    for s in sents:
        for rx, gw, gs in _WEIGHT_RXS:
            hit = None
            for m in rx.finditer(s):
                if gw is None:  # bear USD 77.97 (25%) / at 25%
                    nn = m.group(2) or m.group(3)
                else:
                    nn = m.group(gw)
                name = m.group(gs).lower()
                if nn is None or name not in w:
                    continue
                if gw == 1 and any(x[1] == "%" and _same(nn, x[0]) for x in ctx.stats):
                    continue  # "our 42% base case" is the base case's growth, not its weight
                if abs(float(nn) - w[name]) >= 0.6:
                    hit = f"the {name} scenario's probability is {w[name]:.0f}%, not {nn}%"
                    break
            if hit:
                out.append(Issue("scenario_weights", s, hit))
                break
    return out


# ---------------------------------------------------------------- 6. a stale "remaining" buyback figure
_BUYBACK = re.compile(r"repurchas\w*|buy-?backs?", re.I)
_AUTH_NEW = re.compile(r"authori[sz]\w*(?:[^.]|\.\d){0,80}\b(increase|additional|new|rais\w+|boost\w*|expan\w+)\b|"
                       r"\b(increase|additional|new|rais\w+|boost\w*|expan\w+)\b(?:[^.]|\.\d){0,80}authori[sz]", re.I)
_REMAINING = re.compile(r"\b(remain\w*|left)\b", re.I)
_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(tn|trillion|bn|billion|mn|million|亿)\b", re.I)
_SCALE = {"tn": 1000, "trillion": 1000, "bn": 1, "billion": 1, "mn": 0.001, "million": 0.001, "亿": 0.1}


def _amounts_bn(text: str) -> list[float]:
    out = []
    for m in _MONEY.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")) * _SCALE[m.group(2).lower()])
        except (ValueError, KeyError):
            continue
    return [x for x in out if x > 0]


def _stale_remaining(sents: list[str], ctx: _Ctx) -> list[Issue]:
    """If the research notes hold a buyback authorisation dated after the latest results documents, a sentence that
    gives a "remaining" / "left" buyback figure must also name the later amount."""
    facts = (ctx.data.research.facts if ctx.data.research else []) or []
    later = [f for f in facts if (f.key or "") == "update:capital_return" and _BUYBACK.search(f.text or "")]
    if not later:
        results = [f.published for f in facts if f.kind in ("results_release", "results_commentary", "periodic_report")
                   and f.published]
        cut = max(results) if results else None
        later = [f for f in facts if _BUYBACK.search(f.text or "") and _AUTH_NEW.search(f.text or "")
                 and f.published and (cut is None or f.published > cut)]
    amounts = sorted({round(a, 3) for f in later for a in _amounts_bn(f.text)})
    if not amounts:
        return []
    out = []
    for s in sents:
        b, r = _BUYBACK.search(s), _REMAINING.search(s)
        if not (b and r) or not any(abs(x.start() - y.start()) <= 60 for x in _BUYBACK.finditer(s)
                                    for y in _REMAINING.finditer(s)):
            continue
        said = _amounts_bn(s)
        if any(abs(a - x) <= max(0.01 * a, 0.05) for a in amounts for x in said):
            continue
        f = max(later, key=lambda x: x.published or date.min)
        out.append(Issue("stale_remaining", s, f"a note dated {f.published or 'after the results'} reports a later "
                                               f"buyback authorisation ({', '.join(f'{a:g}bn' for a in amounts)}): "
                                               "give the newer figure and its date with any remaining amount"))
    return out


def context(data) -> _Ctx:
    """The report data the checks read, built once for several ``find`` calls on one report."""
    return _Ctx(data)


# ---------------------------------------------------------------- 7. comparison direction (run 3)
# Run 2 review: "Net cash of 23.2bn still exceeds total debt of 33.4bn" (deep report, a rebuttal). Both figures were
# real, so the number check passed; the comparison word pointed the wrong way. Two figures of the same kind (amounts,
# percentages, multiples) joined by a comparison word within one clause must agree with it.
_FIG = (r"(?<![A-Za-z\d.])(?P<{n}cur>[$€£¥]|USD|HKD|RMB|CNY)?\s?(?P<{n}v>\d[\d,]*(?:\.\d+)?)\s?"
        r"(?P<{n}u>tn|trillion|bn|billion|mn|million|%|x|×)?(?![A-Za-z\d])")
_UP_WORDS = r"exceeds?|exceeded|exceeding|surpass(?:es|ed|ing)?|outweighs?|more than|greater than|larger than|higher than|above"
_DOWN_WORDS = r"less than|lower than|smaller than|below|short of"
_CMP = re.compile(_FIG.format(n="a") + r"(?P<mid>[^.;:!?\d]{0,60}?)\b(?P<w>" + _UP_WORDS + "|" + _DOWN_WORDS + r")\b"
                  r"(?P<mid2>[^.;:!?\d]{0,40}?)" + _FIG.format(n="b"), re.I)
_UNIT_SCALE = {"tn": 1e12, "trillion": 1e12, "bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6}


def _fig_kind(cur: Optional[str], v: str, u: Optional[str]) -> tuple[Optional[str], float]:
    x = float(v.replace(",", ""))
    u = (u or "").lower()
    if u in ("x", "×"):
        return "multiple", x
    if u == "%":
        return "percent", x
    if u in _UNIT_SCALE or cur:
        return "amount", x * _UNIT_SCALE.get(u, 1.0)
    return ("plain" if "." in v else None), x


def _comparisons(sents: list[str], ctx: _Ctx) -> list[Issue]:
    """"A exceeds B" with A < B, or "A is below B" with A > B, for two figures of the same kind in one clause. A
    multiplier or "twice" between them, or a mix of kinds, is left alone."""
    out = []
    for s in sents:
        for m in _CMP.finditer(s):
            ka, a = _fig_kind(m.group("acur"), m.group("av"), m.group("au"))
            kb, b = _fig_kind(m.group("bcur"), m.group("bv"), m.group("bu"))
            if ka is None or ka != kb or a == b:
                continue
            between = f"{m.group('mid')} {m.group('mid2')}".lower()
            if re.search(r"\b(?:times|twice|double|triple|half|ratio|multiple of|per\b|each)\b", between):
                continue
            # "Buy at or below 173.93 and Sell at or above 222.24": the word belongs to another subject
            if re.search(r"\b(?:and|while|but|whereas|versus|vs|against)\b", m.group("mid")):
                continue
            up = re.fullmatch(_UP_WORDS, m.group("w"), re.I) is not None
            if (up and a < b) or (not up and a > b):
                out.append(Issue("comparisons", s, f"\"{m.group(0).strip()}\": {m.group('av')} is "
                                                   f"{'smaller' if a < b else 'larger'} than {m.group('bv')}"))
                break
    return out


# ---------------------------------------------------------------- 8. event dates (run 4)
# Round 12: "On 1 Oct 2026 it added USD 150bn to its buyback" (announced 28 Sep; 1 Oct is when an article ran), the
# board's statement of 8 Nov dated 12 Nov, an explainer of 10 Nov read as a ban on 10 Nov. A sentence that pins an
# event to the day a news note was published, when that note does not say the event happened that day, is deleted
# (unless the sentence says "reported").
_REPORTED = re.compile(r"\breport(?:ed|s|ing)?\b|\baccording to\b|\bwrote\b|\bsaid on\b", re.I)
_WORDS = re.compile(r"[A-Za-z][A-Za-z'’-]{4,}")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_COMMON = {"nvidia", "company", "shares", "billion", "million", "which", "their", "would", "about", "after",
           "before", "there", "these", "those", "while", "since", "first", "quarter", "fiscal", "board", "close",
           "january", "february", "march", "april", "june", "july", "august", "september", "october", "november",
           "december"}
_PRICE_MOVE = re.compile(r"\b(?:shares?|stock|share price)\b[^.;]{0,60}?\b(?:fell|rose|closed|dropped|gained|slid|"
                         r"jumped|climbed|declined|lost|added|tumbled|surged|sank|rallied)\b", re.I)
_PRICE_DATE = re.compile(r"\bclos(?:e|ing)\b|\bas of\b", re.I)
_BROKER_ACT = re.compile(r"\b(?:upgrad|downgrad|initiat|reiterat)\w*|\b(?:raised|cut|lowered|lifted|trimmed)\s+"
                         r"(?:its|the|their)\s+(?:price\s+)?target", re.I)


def _content(text: str) -> tuple[set, set]:
    words = {w.lower() for w in _WORDS.findall(text or "")} - _COMMON
    nums = {float(x) for x in _NUM.findall(text or "") if float(x) >= 10 and not 1900 <= float(x) <= 2100}
    return words, nums


def _event_dates(sents: list[str], ctx: "_Ctx") -> list[Issue]:
    notes = [f for f in (getattr(getattr(ctx.data, "research", None), "facts", None) or [])
             if getattr(f, "kind", "") == "news" and f.published]
    if not notes:
        return []
    year = ctx.as_of.year
    out = []
    for s in sents:
        if _REPORTED.search(s) or _PRICE_MOVE.search(s):  # a price move is checked against the closes (move_dates)
            continue
        sw, sn = _content(s)
        for a, b, d in _dates(s, year):
            if _PRICE_DATE.search(s[max(0, a - 12):b + 14]):  # "the 11 November close", "as of 10 Nov": our price date
                continue
            for f in notes:
                if f.published != d or f.event_date == d or _BROKER_ACT.search(f.text or ""):
                    continue
                fw, fn = _content(f"{f.text} {f.quote}")
                if (sn & fn) or len(sw & fw) >= 3:
                    when = f.event_date.isoformat() if f.event_date else "not stated"
                    out.append(Issue("event_date", s, f"{d.isoformat()} is when {f.id} was reported; when it "
                                     f"happened: {when}"))
                    break
    return out


_NONDISC = re.compile(r"\b(?:not|never)\s+(?:been\s+)?disclosed\s+in\b|\b(?:does|did|has)\s+not\s+disclos|"
                      r"\bwas\s+not\s+disclosed\b|\bis\s+not\s+disclosed\b|\bare\s+not\s+disclosed\b", re.I)


def _non_disclosure(sents: list[str], ctx: "_Ctx") -> list[Issue]:
    """Round 12: "purchase obligations are not disclosed in the latest filing" (the 10-Q gave USD 279bn). We read a
    part of the documents; a claim that a company did not disclose something is never ours to make."""
    return [Issue("non_disclosure", s, "a claim of non-disclosure") for s in sents if _NONDISC.search(s)]


_LAST_YEAR = re.compile(r"(\d+(?:\.\d+)?)\s?[x×]\s+(?:the\s+)?last (?:fiscal )?year['’]s "
                        r"(?:profit|earnings|net profit|EPS)\b", re.I)


def _pe_label(sents: list[str], ctx: "_Ctx") -> list[Issue]:
    """Round 12 (learner's guide): "22.0x last year's profit" where 22.0x is the trailing four-quarter P/E."""
    pe = getattr(getattr(ctx.data, "quote", None), "pe_ttm", None)
    if not pe:
        return []
    out = []
    for s in sents:
        if any(abs(float(m) - pe) < 0.06 for m in _LAST_YEAR.findall(s)):
            out.append(Issue("pe_label", s, "the trailing (last four quarters) P/E called last year's"))
    return out


CHECKS = {"move_dates": _move_dates, "stat_labels": _stat_labels, "fractions": _fractions,
          "provenance": _provenance, "scenario_weights": _scenario_weights, "stale_remaining": _stale_remaining,
          "comparisons": _comparisons, "event_dates": _event_dates, "non_disclosure": _non_disclosure,
          "pe_label": _pe_label}


def find(text: str, data, ctx: Optional[_Ctx] = None) -> list[Issue]:
    """Every issue in ``text`` (one per sentence and check). Never raises: a check that fails is skipped."""
    if not text or data is None:
        return []
    try:
        sents = sentences(text)
    except Exception as e:  # noqa: BLE001
        log.warning("fact check: sentence split failed: %s", type(e).__name__)
        return []
    ctx = ctx or _Ctx(data)
    out: list[Issue] = []
    for name, fn in CHECKS.items():
        try:
            out += fn(sents, ctx)
        except Exception as e:  # noqa: BLE001 - a broken check never blocks the report
            log.warning("fact check %s skipped: %s: %s", name, type(e).__name__, e)
    seen, uniq = set(), []
    for i in out:
        if (i.check, i.sentence) not in seen:
            seen.add((i.check, i.sentence))
            uniq.append(i)
    return uniq


# ---------------------------------------------------------------- the sweep
MIN_LEFT = 25
SKIP = {"quote", "url", "source", "title", "id", "evidence", "model", "status", "mode", "guardrail"}
DROPPABLE = {"key_takeaways", "catalysts", "risks", "events_to_monitor", "findings", "key_questions", "bull", "bear",
             "rebuttals", "concessions_bull", "concessions_bear", "dropped", "divergences", "discussion"}
_LABEL_ONLY = re.compile(r"^\s*(?:[-•*]\s*)?(?:[A-Z][\w ,'/()-]{0,50}:)?\s*$")


def _remove(text: str, kill: set[str]) -> str:
    """``text`` without the sentences in ``kill``; line breaks kept; a bullet line whose first sentence goes is
    dropped whole, and so is a line left empty or holding only its label."""
    lines, pos, out = text.split("\n"), 0, []
    spans = _spans(text)
    for line in lines:
        a, b = pos, pos + len(line)
        pos = b + 1
        mine = [(x, y) for x, y in spans if a <= x < b + 1 and text[x:y] in kill]
        if not mine:
            out.append(line)
            continue
        first = next(((x, y) for x, y in spans if a <= x < b + 1), None)
        if line.lstrip().startswith(("- ", "• ", "* ")) and first in mine:
            continue
        new = line
        for x, y in sorted(mine, reverse=True):
            new = new[:x - a] + new[y - a:]
        new = re.sub(r"[ \t]{2,}", " ", new).rstrip()
        new = re.sub(r"^(\s*(?:[-•*]\s+)?)\s+", r"\1", new)
        if new.strip() and not _LABEL_ONLY.fullmatch(new):
            out.append(new)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


class _Sweep:
    def __init__(self, data):
        self.data, self.ctx, self.lines, self.opens = data, _Ctx(data), [], 0

    def strike(self, text: str, where: str) -> tuple[str, list[Issue], bool]:
        """(new text, issues, emptied): emptied = deleting would leave fewer than MIN_LEFT characters, in which case
        the text is returned unchanged."""
        issues = find(text, self.data, self.ctx)
        if not issues:
            return text, [], False
        new = _remove(text, {i.sentence for i in issues})
        if len(new.strip()) < MIN_LEFT:
            return text, issues, True
        return new, issues, False

    def log(self, kind: str, issues: list[Issue], where: str, note: str = "") -> None:
        self.opens += kind == "open"
        for i in issues:
            self.lines.append(f"[{kind}] {i.check}: {i.sentence}" + (f" [{note}]" if note else ""))
            log.info("fact sweep %s %s in %s: %s (%s)", kind, i.check, where, i.sentence[:160], i.message)

    def text_field(self, text: str, where: str, fallback=None) -> str:
        new, issues, emptied = self.strike(text, where)
        if not issues:
            return text
        if not emptied:
            self.log("struck", issues, where)
            return new
        alt = fallback() if fallback else None
        if alt:
            self.log("struck", issues, where, "replaced by the code-built line")
            return alt
        self.log("open", issues, where)
        return text

    def model(self, obj: BaseModel, path: str) -> None:
        for name in type(obj).model_fields:
            if name in SKIP:
                continue
            val, p = getattr(obj, name), f"{path}.{name}" if path else name
            if isinstance(val, str):
                if len(val) >= 20:
                    fb = self.tagline if p == "tagline" else None
                    new = self.text_field(val, p, fb)
                    if new is not val:
                        setattr(obj, name, new)
            elif isinstance(val, BaseModel):
                self.model(val, p)
            elif isinstance(val, list):
                self.items(val, p)
            elif isinstance(val, dict):
                for k, v in list(val.items()):
                    if isinstance(v, str) and len(v) >= 20:
                        val[k] = self.text_field(v, f"{p}[{k}]")

    def items(self, items: list, path: str) -> None:
        """A list item that would be emptied is dropped while the list keeps two items (narrative lists only, never
        the scenarios); a review-log note whose fix would be emptied is dropped."""
        drop, droppable = [], path.rsplit(".", 1)[-1] in DROPPABLE
        for i, x in enumerate(items):
            p = f"{path}[{i}]"
            room = droppable and len(items) - len(drop) > 2
            if isinstance(x, str):
                if len(x) < 20:
                    continue
                new, issues, emptied = self.strike(x, p)
                if not issues:
                    continue
                if not emptied:
                    items[i] = new
                    self.log("struck", issues, p)
                elif room:
                    drop.append(i)
                    self.log("struck", issues, p, "item dropped")
                else:
                    self.log("open", issues, p)
            elif isinstance(x, BaseModel):
                if "fix" in type(x).model_fields and "problem" in type(x).model_fields:  # a review-log note
                    new, issues, emptied = self.strike(getattr(x, "fix") or "", f"{p}.fix")
                    if issues and emptied:
                        drop.append(i)
                        self.log("struck", issues, f"{p}.fix", "review note dropped")
                        continue
                    if issues:
                        x.fix = new
                        self.log("struck", issues, f"{p}.fix")
                    for name in type(x).model_fields:
                        v = getattr(x, name)
                        if name not in SKIP and name != "fix" and isinstance(v, str) and len(v) >= 20:
                            nv = self.text_field(v, f"{p}.{name}")
                            if nv is not v:
                                setattr(x, name, nv)
                    continue
                before, opens = len(self.lines), self.opens
                self.model(x, p)
                if self.opens > opens and room:  # one of its texts would be emptied: drop the whole item
                    drop.append(i)
                    self.lines[before:] = [(ln.replace("[open]", "[struck]", 1) + " [item dropped]")
                                          if ln.startswith("[open]") else ln for ln in self.lines[before:]]
                    self.opens = opens
        for i in reversed(drop):
            items.pop(i)

    def tagline(self) -> Optional[str]:
        r = self.data.rating
        if r is None or r.rating == "Not rated" or not r.fair_value:
            return None
        from ..render.viewmodel import ccy
        up = f" ({r.upside:+.1%} vs the price)" if r.upside is not None else ""
        return f"{r.rating}: fair value {ccy(r.currency)} {r.fair_value:,.2f}{up}"


def sweep(narrative, data) -> list[str]:
    """Delete every sentence ``find`` flags from the narrative's AI-written fields (the deep analysis, the brief and
    the learner notes included; source quotes, ids, titles and the guardrail log are not walked), when at least 25
    characters of the field remain. Fallbacks: an emptied tagline becomes the code-built line "<Rating>: fair value
    <ccy> <value> (<upside> vs the price)"; a review-log note whose fix would be emptied is dropped; an item of a
    narrative list (takeaways, catalysts, risks, debate arguments, rebuttals ...) that would be emptied is dropped
    while the list keeps two items; any other field is left as it is and logged "[open]".
    Returns one line per deletion ("[struck] <check>: <sentence>"). Never raises."""
    if narrative is None or data is None:
        return []
    sw = _Sweep(data)
    try:
        sw.model(narrative, "")
    except Exception as e:  # noqa: BLE001
        log.warning("fact sweep stopped: %s: %s", type(e).__name__, e)
    return sw.lines


def strike_text(text: str, data) -> tuple[str, list[str]]:
    """The sweep for one plain text (the analyst brief before the writer reads it): (new text, log lines). Never
    raises; an emptied text is left as it is and logged "[open]"."""
    if not text or data is None:
        return text, []
    sw = _Sweep(data)
    try:
        return sw.text_field(text, "brief"), sw.lines
    except Exception as e:  # noqa: BLE001
        log.warning("fact sweep (text) stopped: %s: %s", type(e).__name__, e)
        return text, []


# ---------------------------------------------------------------- facts for the writers
def _closes_note(data) -> str:
    ctx = _Ctx(data)
    days = ctx.days[-10:]
    if len(ctx.days) < 11:
        return ""
    chg = {d: ctx.change(d) for d in days}
    daily = all(c is not None for c in chg.values())
    head = ("Daily closes, last 10 sessions (code; close-to-close change):" if daily else
            "Closes on recent sessions (code; the price chart skips some sessions, so a close-to-close change is "
            "given only where the previous session is known):")
    items = "; ".join(f"{d.day} {d:%b %Y} ({d:%a}) {ctx.closes[d]:,.2f}" + (f" {chg[d]:+.1%}" if chg[d] is not None
                                                                            else "") for d in days)
    return (f"{head} {items}. Date a share-price move by its session; a weekend or holiday announcement moved the "
            "price on the next session.")


def _mn(v: float, signed: bool = False) -> str:
    m = v / 1e6
    dp = 0 if abs(m) >= 100 else 1
    return f"{m:+,.{dp}f}mn" if signed else (f"{m:,.{dp}f}mn" if m >= 0 else f"({abs(m):,.{dp}f}mn)")


def _net_cash_note(data) -> str:
    f = data.financials
    fy, lt = (f.years[-1] if f.years else None), f.latest
    if fy is None or lt is None or lt.period_end <= fy.period_end:
        return ""
    vals = (fy.cash_and_equivalents, fy.total_debt, lt.cash_and_equivalents, lt.total_debt)
    if any(v is None for v in vals):
        return ""
    c0, d0, c1, d1 = vals
    for nd, c, d in ((fy.net_debt, c0, d0), (lt.net_debt, c1, d1)):  # another definition of net cash: say nothing
        if nd is not None and abs(nd - (d - c)) > 0.01 * max(abs(c), abs(d), 1):
            return ""
    ccy = f.currency
    return (f"Net cash bridge (code, {ccy}): net cash (cash and investments minus debt) went from {_mn(c0 - d0)} "
            f"({fy.period_end.day} {fy.period_end:%b %Y}) to {_mn(c1 - d1)} ({lt.period_end.day} "
            f"{lt.period_end:%b %Y}): cash and investments changed by {_mn(c1 - c0, True)}, debt by "
            f"{_mn(d1 - d0, True)}. Give the change in net cash with these two components; never name another cause "
            "unless a note states it.")


def _label_note(data) -> str:
    b = data.pe_band
    if b is None or not b.current or not b.median:
        return ""
    return (f"Statistic labels (code): today's P/E on last fiscal year's EPS is {b.current:.1f}x; the 5-year median "
            f"is {b.median:.1f}x. Never swap them.")


def writer_notes(data) -> str:
    """Facts for the writers, the brief and the debate, built in code. Never raises."""
    out = []
    for fn in (_closes_note, _net_cash_note, _label_note):
        try:
            t = fn(data)
        except Exception as e:  # noqa: BLE001
            log.warning("writer note %s skipped: %s", fn.__name__, type(e).__name__)
            continue
        if t:
            out.append(t)
    return "\n".join(out)
