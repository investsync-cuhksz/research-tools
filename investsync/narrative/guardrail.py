"""Anti-hallucination guardrail: every number in the commentary must come from the data.

Each figure in the generated text is extracted with its unit and accepted only if it
equals, after normal rounding, a value the model was given:

* ``25.3%`` / ``+2.1pp``  -> a ratio in the data (x100) or a percentage shown on the sheet
* ``18.4x``               -> a multiple in the data
* ``660.3bn`` / ``812mn`` -> an amount in the data, scaled to that unit
* ``660,257`` (no unit)   -> a value in the data, as-is or in millions / billions

Used as the reward function for ``dspy.Refine`` and as the final publish gate.
"""
from __future__ import annotations

import bisect
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

# Boundaries are ASCII-only on purpose: Chinese characters count as "word" characters in Python, so
# "增长3.08%" would otherwise hide the figure. Chinese units: 亿 = 1e8, 万 = 1e4; "pcts" and 个百分点 = percentage points.
_NUM = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<sign>[+\-−–])?\(?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\)?"
    r"\s?(?P<unit>%|pcts|pct|pp|个百分点|百分点|bps|x|×|tn|trillion|bn|billion|mn|million|m|k|亿|万)?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
# Tokens that look numeric but are labels: FY2024, Q3, 1H25, 3Y, 5-year, 52-week, 1st
_LABEL = re.compile(
    r"\b(?:FY|CY|Q|H)\d{1,4}\b|\b\d{1,2}[HQ]\d{2,4}\b|\b\d{1,2}Y\b"
    r"|\b\d{1,2}-(?:year|month|week|day|quarter)s?\b|\b\d{1,2}(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)
# "200-400bn" / "200–400亿" / "5-10%": the unit written once after a range applies to both ends, so the first
# number is checked as an amount too (a bare "200" would otherwise match the raw 200 in "200-400亿").
_RANGE = re.compile(r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)(\s?[-–~至到]\s?)(\d[\d,]*(?:\.\d+)?)\s?"
                    r"(%|pcts|pct|pp|个百分点|百分点|bps|x|×|tn|trillion|bn|billion|mn|million|亿|万)(?![A-Za-z])", re.IGNORECASE)
_SCALE = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9,
          "tn": 1e12, "trillion": 1e12, "亿": 1e8, "万": 1e4}
_PCT = {"%", "pp"}


@dataclass(frozen=True)
class Figure:
    token: str
    value: float      # absolute value as written
    decimals: int
    unit: str         # "", "%", "pp", "bps", "x", or a scale unit


def extract(text: str) -> list[Figure]:
    """Numbers in ``text`` that need checking. Labels, years and small counts are skipped."""
    masked = _LABEL.sub(lambda m: " " * len(m.group(0)), text)
    masked = _RANGE.sub(lambda m: f"{m.group(1)}{m.group(4)}{m.group(2)}{m.group(3)}{m.group(4)}", masked)
    out = []
    for m in _NUM.finditer(masked):
        raw = m.group("num")
        unit = (m.group("unit") or "").lower().replace("×", "x")
        if unit in ("pcts", "pct", "个百分点", "百分点"):
            unit = "pp"
        value = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if not unit and decimals == 0:
            if len(raw) == 4 and 1990 <= value <= 2040:
                continue  # a year
            if value <= 10:
                continue  # a count, e.g. "3 catalysts"
        out.append(Figure(m.group(0).strip(), value, decimals, unit))
    return out


class _Pool:
    def __init__(self) -> None:
        self._v: list[float] = []

    def add(self, v: float) -> None:
        if v is not None and not math.isnan(v) and not math.isinf(v):
            self._v.append(abs(v))

    def freeze(self) -> None:
        self._v = sorted(set(round(v, 9) for v in self._v))

    def near(self, x: float, tol: float) -> bool:
        i = bisect.bisect_left(self._v, x - tol)
        return i < len(self._v) and self._v[i] <= x + tol


class Allowed:
    """The numbers the commentary may use, indexed by how they can be written."""

    def __init__(self, raw_values: Iterable[float], shown: Iterable[Figure] = ()):
        self.pct, self.mult, self.plain = _Pool(), _Pool(), _Pool()
        self.amount: dict[str, _Pool] = {u: _Pool() for u in set(_SCALE)}
        for v in raw_values:
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            v = float(v)
            self.pct.add(v * 100)
            self.mult.add(v)
            self.plain.add(v)
            self.plain.add(v / 1e6)
            self.plain.add(v / 1e9)
            for u, s in _SCALE.items():
                self.amount[u].add(v / s)
        for f in shown:  # figures exactly as displayed on the sheet / in the facts
            if f.unit in _PCT:
                self.pct.add(f.value)
            elif f.unit == "x":
                self.mult.add(f.value)
            elif f.unit in _SCALE:
                for u, s in _SCALE.items():
                    self.amount[u].add(f.value * _SCALE[f.unit] / s)
            else:
                self.plain.add(f.value)
        for p in (self.pct, self.mult, self.plain, *self.amount.values()):
            p.freeze()

    def matches(self, f: Figure) -> bool:
        tol = 0.5 * 10 ** (-f.decimals) * 1.0001 + 1e-9  # a correct rounding of the source
        if f.unit in _PCT:
            return self.pct.near(f.value, tol)
        if f.unit == "bps":
            return self.pct.near(f.value / 100, tol / 100)
        if f.unit == "x":
            return self.mult.near(f.value, tol)
        if f.unit in _SCALE:
            return self.amount[f.unit].near(f.value, tol)
        return self.plain.near(f.value, tol)


def numbers_in(obj: Any) -> tuple[list[float], list[Figure]]:
    """Raw numbers and displayed figures inside a nested dict/list/str structure."""
    raw: list[float] = []
    shown: list[Figure] = []

    def walk(o: Any) -> None:
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            raw.append(float(o))
        elif isinstance(o, str):
            shown.extend(extract(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(obj)
    return raw, shown


def build_allowed(*sources: Any) -> Allowed:
    raw: list[float] = []
    shown: list[Figure] = []
    for s in sources:
        r, sh = numbers_in(s)
        raw += r
        shown += sh
    return Allowed(raw, shown)


def unmatched(text: str, allowed: Allowed) -> list[str]:
    return [f.token for f in extract(text) if not allowed.matches(f)]


_CN_AMOUNT = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)(?:\s*[-–~至到]\s*(\d[\d,]*(?:\.\d+)?))?\s*(亿|万)"
                        r"(港元|美元|元|股)?(?!港元|美元|元|股|\s*\()")
_CN_CCY = {"元": "RMB ", "港元": "HKD ", "美元": "USD "}


def annotate_cn_amounts(text: str) -> str:
    """Add the English amount after every Chinese 亿 / 万 amount, computed in code, so the model copies it
    instead of converting: "回购53.6亿元" -> "回购53.6亿元 (RMB 5.36bn)", "200-400亿元" -> "(RMB 20-40bn)"."""
    def fmt(raw: str, scale: float) -> str:
        v = float(raw.replace(",", "")) * scale
        if v >= 1e9:
            return f"{v / 1e9:,.2f}".rstrip("0").rstrip(".") + "bn"
        return f"{v / 1e6:,.2f}".rstrip("0").rstrip(".") + "mn"

    def rep(m: re.Match) -> str:
        a, b, unit, cur = m.groups()
        scale = 1e8 if unit == "亿" else 1e4
        conv = fmt(a, scale) + (f"-{fmt(b, scale)}" if b else "")
        if cur == "股":
            return f"{m.group(0)} ({conv} shares)"
        return f"{m.group(0)} ({_CN_CCY.get(cur or '', '')}{conv})"
    return _CN_AMOUNT.sub(rep, text) if text else text


# ---------------------------------------------------------------- names
# Run 3 (12 Nov 2026): the AI is asked to name the people, companies and products in an event ("CFO Jane Smith",
# not "an executive"). A name it writes must come from its source text, like a figure. Capitalised runs of two or
# more words are names; each word is looked up on its own, anywhere in the source, ignoring case, so a name that is
# reordered, abbreviated or split across a line still passes. Titles, company suffixes, months and weekdays are not
# name words.
_NAME_RUN = re.compile(r"\b[A-Z][A-Za-z'’.\-]*(?:\s+[A-Z][A-Za-z'’.\-]*)+")
_NAME_SKIP = frozenset("""
the and for with from into onto upon over under after before about between its our their this that these those
inc corp corporation ltd limited group holdings holding company plc llc sa ag nv
chief executive officer financial operating technology president chairman chairwoman chair vice head director
board management ceo cfo coo cto senior general manager founder co-founder deputy acting interim
fiscal year quarter half first second third fourth full annual interim results report
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday
usd rmb hkd cny eur gbp jpy
""".split())
_CJK = re.compile(r"[㐀-鿿]")


def names_missing(text: str, source: str) -> list[str]:
    """Names in ``text`` (capitalised runs of 2+ words) that ``source`` does not contain: their last word or more
    than half of their words are not found. [] when all are found, or when ``source`` is Chinese (an English name
    is then a translation and cannot be looked up)."""
    src = unicodedata.normalize("NFKC", source or "").lower().replace("’", "'")
    if not text or _CJK.search(src):
        return []
    out = []
    for m in _NAME_RUN.finditer(unicodedata.normalize("NFKC", text).replace("’", "'")):
        # "OpenAI-linked" or "Blackwell/Rubin": only the capitalised parts are name words
        parts = [p for w in m.group(0).split() for p in re.split(r"[-/]", w) if p[:1].isupper()]
        words = [w for w in (re.sub(r"'s$", "", p).strip(".'").lower() for p in parts)
                 if len(w) >= 3 and w not in _NAME_SKIP]
        found = [w in src for w in words]
        # the last word (a surname, a product's model name) must be there, and at least half of the words:
        # "Jensen Huang" passes where the source says "Huang"; an invented "Jane Doe" does not
        if words and not (found[-1] and 2 * sum(found) >= len(words)):
            out.append(m.group(0))
    return out
