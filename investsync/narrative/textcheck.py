"""Code checks on the AI's wording, run on every draft (adapted from FinRobot V2's audit operators).

The number guardrail (guardrail.py) proves every figure exists in the data. These checks catch the
mistakes it cannot see:

* direction  a "rose / fell" verb that contradicts the figures it describes ("climbed from 47.3% to
             32.1%"), or a "fell" next to a "+" figure; an amount said to be below / above the
             share price when it is not ("HKD 457.31, below today's price" of HKD 419.80)     -> hard
* currency   a statement amount or per-share price quoted in the wrong currency            -> hard
* period     a fiscal year the data does not cover                                         -> hard
* momentum   a Buy into a stock down >15% over a year (Sell into one up >30%) without the
             thesis saying why the model disagrees with the market (FinRobot's
             narrative_divergence)                                                         -> soft
* sector     EV/EBITDA, FCF or gross margin for a bank or insurer; a P/E for a loss-maker
             (FinRobot's sector_sign)                                                      -> soft

Hard issues are sent back for a rewrite and flag the narrative if they survive; soft issues are
sent back once and otherwise listed in the data audit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from ..schema import TearSheetData


@dataclass(frozen=True)
class Issue:
    check: Literal["direction", "currency", "period", "momentum", "sector", "debate", "units", "leverage"]
    severity: Literal["hard", "soft"]
    section: str
    quote: str
    message: str

    def feedback(self) -> str:
        return f"[{self.check}] In `{self.section}`: {self.message}"


_UP = (r"rose|rise[sn]?|rising|increas(?:e|ed|es|ing)|climb(?:ed|s|ing)?|grew|grow(?:s|ing)|expand(?:ed|s|ing)?|"
       r"jump(?:ed|s)?|surg(?:e|ed|es)|gain(?:ed|s)?|rebound(?:ed|s)?|recover(?:ed|s)?|accelerat(?:ed|es|ing)|"
       r"doubl(?:ed|es)|soar(?:ed|s)?|rall(?:ied|ies)|advanc(?:ed|es)|lift(?:ed|s)?|swell(?:ed|s)?|ballooned|"
       r"went up|moved up|rais(?:ed|es|ing)|hik(?:ed|es|ing)|lifted")
_DOWN = (r"fell|fall(?:s|ing|en)?|declin(?:e|ed|es|ing)|drop(?:ped|s)?|decreas(?:e|ed|es|ing)|contract(?:ed|s|ing)|"
         r"shrank|shrunk|shrink(?:s|ing)?|slid|slip(?:ped|s)?|dipp?(?:ed|s)?|slow(?:ed|s|ing)|compress(?:ed|es)|"
         r"halv(?:ed|es)|eas(?:ed|es|ing)|collaps(?:ed|es)|plung(?:ed|es)|plummet(?:ed|s)?|tumbl(?:ed|es)|sank|"
         r"slump(?:ed|s)?|erod(?:ed|es)|retreat(?:ed|s)?|went down|moved down|cut(?:s|ting)?|reduc(?:ed|es|ing)|"
         r"lower(?:ed|s|ing)|trimm(?:ed|ing)|scal(?:ed|es) back")
_VERB = re.compile(rf"\b(?:(?P<up>{_UP})|(?P<down>{_DOWN}))\b", re.IGNORECASE)
_N = r"[+\-−–]?\d[\d,]*(?:\.\d+)?"
_U = r"\s?(%|pp|x|bn|mn|tn)?"
_FROM_TO = re.compile(rf"\bfrom\s+(?:[A-Z]{{3}}\s)?(?P<a>{_N}){_U}\s+to\s+(?:[A-Z]{{3}}\s)?(?P<b>{_N})(?P<ub>{_U})")
_TO_FROM = re.compile(rf"\bto\s+(?:[A-Z]{{3}}\s)?(?P<b>{_N})(?P<ub>{_U})\s+from\s+(?:[A-Z]{{3}}\s)?(?P<a>{_N}){_U}")
_SIGNED = re.compile(rf"\b(?:(?P<up>{_UP})|(?P<down>{_DOWN}))\b(?:\s+(?:by|of|a|an|about|some))?\s+(?P<s>[+\-−–])\d",
                     re.IGNORECASE)
_SENT = re.compile(r"(?<=[^\d][.!?;])\s+|\n+")
# a verb does not reach past a contrast ("margin expanded ..., yet operating margin collapsed ...")
_CONTRAST = re.compile(r"\b(?:yet|but|while|whereas|although|though|however|despite|offset)\b", re.IGNORECASE)
_CCY = {"USD": "USD", "US$": "USD", "HKD": "HKD", "HK$": "HKD", "RMB": "CNY", "CNY": "CNY", "EUR": "EUR",
        "GBP": "GBP", "JPY": "JPY"}
_AMOUNT = re.compile(r"(?<![A-Za-z])(?P<c>USD|US\$|HKD|HK\$|RMB|CNY|EUR|GBP|JPY)\s?(?P<n>\d[\d,]*(?:\.\d+)?)"
                     r"\s?(?P<s>tn|trillion|bn|billion|mn|million)?\b")
_SCALE = {"tn": 1e12, "trillion": 1e12, "bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6}
_FY = re.compile(r"\bFY(\d{4})E?\b")


def _f(s: str) -> float:
    return float(s.replace(",", "").replace("−", "-").replace("–", "-"))


def _quote(text: str, a: int, b: int) -> str:
    return " ".join(text[max(0, a):min(len(text), b)].split())[:140]


def _direction(section: str, text: str) -> list[Issue]:
    out = []
    for sent in _SENT.split(text):
        pairs = [(m.start(), m.group("a"), m.group("b")) for m in _FROM_TO.finditer(sent)]
        pairs += [(m.start(), m.group("a"), m.group("b")) for m in _TO_FROM.finditer(sent)]
        for start, a, b in sorted(pairs):
            verbs = [v for v in _VERB.finditer(sent[:start])
                     if start - v.end() <= 100 and not _CONTRAST.search(sent[v.end():start])]
            if not verbs:
                continue
            v = verbs[-1]
            try:
                x, y = _f(a), _f(b)
            except ValueError:
                continue
            up = v.group("up") is not None
            if (up and y < x) or (not up and y > x):
                word = v.group(0)
                out.append(Issue("direction", "hard", section, _quote(sent, v.start(), start + 40),
                                 f'"{word}" does not match the figures that follow ({a} to {b} is a '
                                 f'{"fall" if y < x else "rise"}). Use the right verb for each figure.'))
        for m in _SIGNED.finditer(sent):
            up, sign = m.group("up") is not None, m.group("s")
            if (up and sign in "-−–") or (not up and sign == "+"):
                out.append(Issue("direction", "hard", section, _quote(sent, m.start(), m.end() + 12),
                                 f'"{m.group(0).strip()}" pairs a {"rise" if up else "fall"} verb with a '
                                 f'{"negative" if up else "positive"} figure. Fix the verb or the sign.'))
    return out


_VS_PRICE = re.compile(
    r"(?<![A-Za-z])(?P<c>USD|US\$|HKD|HK\$|RMB|CNY|EUR)\s?(?P<n>\d[\d,]*(?:\.\d+)?)(?!\s?(?:%|x|bn|mn|tn|pp))"
    r"[^.;:!?]{0,45}?\b(?P<d>below|under|beneath|lower than|above|over|higher than)\s+"
    r"(?:today's|the current|the latest|the last|current|the)\s+(?:share\s+|stock\s+)?price", re.IGNORECASE)


def _vs_price(section: str, text: str, data: TearSheetData) -> list[Issue]:
    """An amount in the trading currency said to be below / above the share price must actually be."""
    price, cur = data.quote.price, data.quote.currency
    out = []
    for m in _VS_PRICE.finditer(text):
        if _CCY.get(m.group("c").upper(), m.group("c").upper()) != cur or not price:
            continue
        gap = text[m.end("n"):m.start("d")]
        if re.search(r"\d", gap):
            continue  # another figure sits in between ("HKD 73.44, with only 24% of draws above the price")
        n = _f(m.group("n"))
        below = m.group("d").lower() in ("below", "under", "beneath", "lower than")
        wrong = n > price * 1.005 if below else n < price * 0.995
        if wrong:
            out.append(Issue("direction", "hard", section, _quote(text, m.start(), m.end()),
                             f"{m.group('c')} {m.group('n')} is {'above' if n > price else 'below'} the share price "
                             f"({cur} {price:,.2f}), not {m.group('d').lower()} it. Fix the comparison."))
    return out


def _known_amounts(data: TearSheetData) -> tuple[set, set]:
    """Statement amounts (reporting currency) and per-share prices (trading currency), rounded as quoted."""
    stmt, prices = set(), set()
    keys = ("revenue", "gross_profit", "operating_income", "net_income", "ebitda", "free_cash_flow",
            "operating_cash_flow", "cash_and_equivalents", "total_debt", "total_assets", "total_equity", "net_debt")
    for y in data.financials.years:
        for k in keys:
            v = getattr(y, k, None)
            if v:
                v = abs(v)
                stmt |= {round(v / 1e6), round(v / 1e9, 1), round(v / 1e9, 2), round(v / 1e12, 2)}
    q = data.quote
    for v in (q.price, q.week52_high if hasattr(q, "week52_high") else None,
              data.rating.fair_value if data.rating else None,
              data.rating.buy_below if data.rating else None, data.rating.sell_above if data.rating else None,
              data.street.target_median if data.street else None,
              data.overall.target_median if data.overall else None,
              data.valuation.dcf.value_per_share if data.valuation and data.valuation.dcf else None,
              data.valuation.ddm.value_per_share if data.valuation and data.valuation.ddm else None):
        if v:
            prices |= {round(v, 2), round(v, 1)}
    return stmt - {0, 0.0}, prices


def _currency(section: str, text: str, data: TearSheetData) -> list[Issue]:
    rep, trd = data.financials.currency, data.quote.currency
    stmt, prices = _known_amounts(data)
    out = []
    for m in _AMOUNT.finditer(text):
        c = _CCY[m.group("c")]
        try:
            v = _f(m.group("n"))
        except ValueError:
            continue
        scale = m.group("s")
        digits = len(re.sub(r"\D", "", m.group("n")).lstrip("0"))
        if digits < 3:
            continue  # "US$1.8 billion" could be anything (a bond issue in the news); too vague to check
        if scale:
            dp = len(m.group("n").split(".")[1]) if "." in m.group("n") else 0
            unit = {"tn": 1e12, "trillion": 1e12, "bn": 1e9, "billion": 1e9}.get(scale, 1e6)
            key = round(v, dp) if unit != 1e6 else round(v)
            if unit == 1e6:
                hit = key in stmt
            else:
                hit = any(abs(key - s) < 10 ** -max(dp, 1) / 2 + 1e-9 for s in stmt if isinstance(s, float))
            # a market cap / EV in the trading currency is fine; only statement figures must use `rep`
            if hit and c != rep and c != trd:
                out.append(Issue("currency", "hard", section, _quote(text, m.start(), m.end()),
                                 f"{m.group(0)} is a financial-statement figure, which is in {rep}, not {c}."))
            elif hit and c == trd != rep and unit == 1e6:
                out.append(Issue("currency", "hard", section, _quote(text, m.start(), m.end()),
                                 f"{m.group(0)} is a financial-statement figure, which is in {rep}, not {c}."))
        elif round(v, 2) in prices and c != trd and c != rep:
            out.append(Issue("currency", "hard", section, _quote(text, m.start(), m.end()),
                             f"{m.group(0)} is a per-share price, which is in {trd}, not {c}."))
    return out


def _periods(section: str, text: str, data: TearSheetData) -> list[Issue]:
    years = {y.fiscal_year for y in data.financials.years}
    years |= {int(e.period[2:6]) for e in (data.consensus.estimates if data.consensus else [])
              if e.period[:2] == "FY" and e.period[2:6].isdigit()}
    if data.valuation and data.valuation.dcf:
        years |= {f.fiscal_year for f in data.valuation.dcf.forecast}
    if years:
        years |= set(range(min(years), max(years) + 1)) | {data.quote.as_of.year, data.quote.as_of.year + 1}
    out = []
    for m in _FY.finditer(text):
        y = int(m.group(1))
        if years and y not in years:
            out.append(Issue("period", "hard", section, _quote(text, m.start() - 30, m.end() + 30),
                             f"{m.group(0)} is not covered by the data (years available: FY{min(years)}-FY{max(years)})."
                             " Remove it or use a year that is listed."))
    return out


_MOMENTUM_WORDS = re.compile(r"share price|shares (?:have )?(?:fallen|dropped|slumped|rallied|risen|surged)|"
                             r"momentum|over the past year|1Y|one-year|12-month|drawdown|technical|sell-off|"
                             r"de-rat|priced in|market (?:is|has)", re.IGNORECASE)


def _one_year(data: TearSheetData) -> Optional[float]:
    p = next((p for p in (data.benchmark.periods if data.benchmark else []) if p.period == "1Y"), None)
    return p.stock_return if p else None


def momentum_note(data: TearSheetData) -> str:
    """Told to the writer up front when the rating goes against the share price (then checked)."""
    rt, r1 = data.rating, _one_year(data)
    if not rt or r1 is None or not ((rt.rating == "Buy" and r1 < -0.15) or (rt.rating == "Sell" and r1 > 0.30)):
        return ""
    from ..render.viewmodel import pct
    move = "down" if r1 < 0 else "up"
    return (f"Momentum check (code): the AI rating is {rt.rating} while the shares are {move} "
            f"{pct(abs(r1), 1)} over one year. The thesis must say why the model disagrees with the market's "
            f"recent verdict, without changing the rating.")


def _momentum(parts: dict[str, str], data: TearSheetData) -> list[Issue]:
    rt, r1 = data.rating, _one_year(data)
    if not rt or r1 is None:
        return []
    if not ((rt.rating == "Buy" and r1 < -0.15) or (rt.rating == "Sell" and r1 > 0.30)):
        return []
    text = " ".join(parts.get(k, "") for k in ("thesis", "rating_rationale", "valuation_overview"))
    if _MOMENTUM_WORDS.search(text):
        return []
    from ..render.viewmodel import pct
    move = "fallen" if r1 < 0 else "risen"
    return [Issue("momentum", "soft", "thesis", "",
                  f"The AI rating is {rt.rating} although the shares have {move} {pct(abs(r1), 1)} over "
                  f"one year. Say in the thesis why the model disagrees with the market's recent verdict "
                  f"(for example what the price already discounts).")]


_BANK_WORDS = re.compile(r"EV/EBITDA|enterprise value|free cash flow|FCF margin|gross margin|EBITDA", re.IGNORECASE)
_PE_NUM = re.compile(r"\b\d+(?:\.\d+)?x\s+(?:TTM\s+)?P/E\b|\bP/E\s+(?:\(TTM\)\s+)?(?:of\s+)?\d+(?:\.\d+)?x", re.IGNORECASE)


# "ROE flattered by leverage / a small equity base" when the equity multiplier is low (a wrong lesson the
# reviewers found twice in learner guides, 8 Nov 2026)
_LEVERAGE_CLAIM = re.compile(r"\b(?:flatter\w*|inflat\w*|boost\w*|amplif\w*|driven|propped)\b[^.]{0,40}"
                             r"\b(?:leverage|borrowing|debt|small equity base|thin equity|equity multiplier)\b",
                             re.IGNORECASE)


def _leverage(parts: dict[str, str], data: TearSheetData) -> list[Issue]:
    du = data.dupont
    em = du.equity_multiplier if du else None
    if em is None or em >= 2.0:
        return []
    out = []
    for sec, text in parts.items():
        m = _LEVERAGE_CLAIM.search(text or "")
        if m and re.search(r"\bROE\b|return on equity", text[max(0, m.start() - 120):m.end()], re.IGNORECASE):
            out.append(Issue("leverage", "hard", sec, _quote(text, m.start(), m.end()),
                             f"The equity multiplier is only {em:.2f}x, which is low: ROE is not driven by leverage. "
                             f"Say what does drive it (margin or asset turnover)."))
    return out


def _sector(parts: dict[str, str], data: TearSheetData) -> list[Issue]:
    from ..quant.valuation import is_financial
    out = []
    if is_financial(data):
        for sec, text in parts.items():
            m = _BANK_WORDS.search(text)
            if m:
                out.append(Issue("sector", "soft", sec, _quote(text, m.start() - 40, m.end() + 40),
                                 f'"{m.group(0)}" is not meaningful for a bank or insurer; use P/B, ROE, '
                                 f"dividends and the DDM instead."))
    ys = data.financials.years
    if ys and ys[-1].net_income is not None and ys[-1].net_income <= 0:
        for sec, text in parts.items():
            m = _PE_NUM.search(text)
            if m:
                out.append(Issue("sector", "soft", sec, _quote(text, m.start() - 30, m.end() + 30),
                                 "The company made a loss, so a P/E is not meaningful (NM); value it on sales, "
                                 "book value or cash flow instead."))
    return out


# A large amount written without its unit ("revenue of 177,837"): readers cannot tell mn from bn. Only amounts
# that follow a financial noun are checked (counts such as "2,520 stations" are fine).
_BARE = re.compile(r"(?<![\w.$¥€£])(\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?!\s?(?:mn|bn|tn|m\b|k\b|million|billion|"
                   r"trillion|thousand|%|x\b|×|pp|bps|shares|GWh|MWh|kWh|TWh|GW|MW|tonnes?|units|vehicles|[\u4e00-\u9fff])|[\d,]|"
                   r"\.\d)", re.IGNORECASE)
_MONEY_NOUN = re.compile(r"\b(revenue|sales|profit|income|earnings|cash|debt|ebitda|capex|capital expenditure|"
                         r"assets|equity|liabilit\w*|expenses?|costs?|loss(?:es)?|dividends?|buyback|payables?|"
                         r"receivables?|inventor\w*|value)\b[^.;]{0,40}$", re.IGNORECASE)
_PRICE = re.compile(r"(?:USD|US\$|RMB|CNY|HKD|HK\$|\$|¥)\s?$", re.IGNORECASE)


def _units(section: str, text: str) -> list[Issue]:
    out = []
    for m in _BARE.finditer(text):
        before = text[max(0, m.start() - 60):m.start()]
        if not _MONEY_NOUN.search(before):
            continue
        if _PRICE.search(before[-6:]) and "." in m.group(1):  # a price such as USD 1,453.00
            continue
        out.append(Issue("units", "soft", section, _quote(text, m.start(), m.end()),
                         f"\"{m.group(1)}\" has no unit. Write it with its currency and unit as in the facts, "
                         f"e.g. \"USD {m.group(1)}mn\" or the bn figure if one is listed."))
    return out[:3]


def run(parts: dict[str, str], data: TearSheetData) -> list[Issue]:
    """All wording checks on a draft. ``parts``: section name -> text (lists joined)."""
    out: list[Issue] = []
    for sec, text in parts.items():
        if not text:
            continue
        out += _direction(sec, text)
        out += _vs_price(sec, text, data)
        out += _currency(sec, text, data)
        out += _periods(sec, text, data)
        out += _units(sec, text)
    out += _momentum(parts, data)
    out += _sector(parts, data)
    out += _leverage(parts, data)
    seen, uniq = set(), []
    for i in out:
        k = (i.check, i.section, i.quote)
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return uniq
