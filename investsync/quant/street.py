"""What the brokers say, compared with each other and with the InvestSync model.

Code only, no AI: rating mix, upgrades / downgrades, price-target range, how far apart the EPS
forecasts are, whether recent forecasts moved up or down (revision trend), and where the
InvestSync model's fair value sits among the brokers' targets. The ``findings`` are plain
sentences built from those numbers; the AI step may quote them but never changes them.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Optional

from ..data.brokers import SCALE, SOURCE, WINDOW_DAYS
from ..render.viewmodel import ccy, num, pct
from ..schema import BrokerNote, EpsRevision, EpsSpread, Market, StreetView, TearSheetData

STALE_DAYS = 90
RECENT_DAYS = 30        # revision trend: notes from the last 30 days ...
EARLIER_DAYS = 120      # ... vs notes 31-120 days old
MAX_NOTES = 40          # kept in the payload (newest first)


def _latest_per_broker(notes: list[BrokerNote], keep=lambda n: True) -> dict[str, BrokerNote]:
    out: dict[str, BrokerNote] = {}
    for n in sorted(notes, key=lambda x: x.on, reverse=True):
        if keep(n) and n.broker not in out:
            out[n.broker] = n
    return out


def _last_actual(data: TearSheetData) -> tuple[Optional[int], Optional[float]]:
    for y in reversed(data.financials.years):
        if y.diluted_eps:
            return y.fiscal_year, y.diluted_eps
    ys = data.financials.years
    return (ys[-1].fiscal_year if ys else None), None


def _eps_spreads(notes: list[BrokerNote], data: TearSheetData, today: date) -> list[EpsSpread]:
    last_fy, last_eps = _last_actual(data)
    if last_fy is None:
        return []
    latest = _latest_per_broker(notes, keep=lambda n: bool(n.eps))
    cons = {}
    c = data.consensus
    if c and c.estimates and (c.estimate_currency in (None, data.financials.currency)):
        for e in c.estimates:
            fy = "".join(ch for ch in e.period if ch.isdigit())
            if fy and e.eps_avg:
                cons[f"FY{fy}"] = e.eps_avg
    out = []
    for fy in (last_fy + 1, last_fy + 2):
        key = f"FY{fy}"
        raw = [n.eps[key] for n in latest.values() if key in n.eps]
        if len(raw) < 2:
            continue
        m0 = median(raw)
        vals = [v for v in raw if m0 > 0 and m0 / 3 <= v <= m0 * 3] if m0 > 0 else raw  # per-ADS or unit slips
        if len(vals) < 2:
            continue
        md = median(vals)
        if last_eps and not (0.25 <= md / last_eps <= 4):  # units differ (e.g. per-ADR or other currency)
            continue
        out.append(EpsSpread(
            period=key, n=len(vals), low=min(vals), median=md, high=max(vals),
            spread=(max(vals) - min(vals)) / abs(md) if md else None,
            vs_last_actual=(md / last_eps - 1) if last_eps and fy == last_fy + 1 and last_eps > 0 else None,
            vs_consensus=(md / cons[key] - 1) if key in cons and cons[key] > 0 else None,
            excluded=len(raw) - len(vals)))
    return out


def _revision(notes: list[BrokerNote], period: str, today: date) -> Optional[EpsRevision]:
    recent_cut, earlier_cut = today - timedelta(days=RECENT_DAYS), today - timedelta(days=EARLIER_DAYS)
    rec = _latest_per_broker(notes, keep=lambda n: period in n.eps and n.on > recent_cut)
    old = _latest_per_broker(notes, keep=lambda n: period in n.eps and earlier_cut <= n.on <= recent_cut)
    if len(rec) < 2 or len(old) < 2:
        return None
    a, b = median(n.eps[period] for n in rec.values()), median(n.eps[period] for n in old.values())
    if not b:
        return None
    return EpsRevision(period=period, recent_days=RECENT_DAYS, recent_n=len(rec), recent_median=a,
                       earlier_n=len(old), earlier_median=b, change=a / b - 1)


def build(data: TearSheetData, notes: list[BrokerNote], today: Optional[date] = None,
          writeups: Optional[list[BrokerNote]] = None) -> Optional[StreetView]:
    if not notes:
        return None
    today = today or data.quote.as_of
    m = data.profile.market
    q = data.quote
    price = q.price
    name, url = SOURCE[m]
    code = data.profile.ticker.split(".")[0] if m != Market.US else data.profile.ticker
    sv = StreetView(source=name, source_url=url.format(code=code.lstrip("0") if m == Market.HK else code),
                    market=m, window_days=WINDOW_DAYS if m != Market.HK else 365,
                    currency=q.currency, eps_currency=data.financials.currency,
                    notes=sorted(notes, key=lambda n: n.on, reverse=True)[:MAX_NOTES],
                    writeups=sorted(writeups or [], key=lambda n: n.on, reverse=True))
    latest = _latest_per_broker(notes)
    sv.reports, sv.brokers = len(notes), len(latest)
    rated = [n.rating for n in latest.values() if n.rating]
    sv.rating_counts = {r: rated.count(r) for r in reversed(SCALE) if rated.count(r)}
    sv.upgrades = sum(1 for n in notes if n.action == "upgrade")
    sv.downgrades = sum(1 for n in notes if n.action == "downgrade")

    # price targets: latest per broker, sanity-checked against the price
    tg = {b: n for b, n in _latest_per_broker(notes, keep=lambda n: n.target is not None).items()
          if price and 0.2 <= n.target / price <= 5}
    targets = [n.target for n in tg.values()]
    if targets:
        sv.targets_n = len(targets)
        sv.target_low, sv.target_median, sv.target_high = min(targets), median(targets), max(targets)
        sv.target_upside = sv.target_median / price - 1 if price else None
        sv.stale_targets = sum(1 for n in tg.values() if (today - n.on).days > STALE_DAYS)
    sv.target_values = targets
    _set_model(sv, data)

    sv.eps = _eps_spreads(notes, data, today)
    if sv.eps and m == Market.CN:  # only A-share notes carry dated forecast history
        sv.revision = _revision(notes, sv.eps[0].period, today)

    # agreement: one-sided ratings and a tight target range
    pos = sum(sv.rating_counts.get(r, 0) for r in ("Buy", "Outperform"))
    neg = sum(sv.rating_counts.get(r, 0) for r in ("Underperform", "Sell"))
    share = max(pos, neg) / len(rated) if rated else None
    disp = (sv.target_high - sv.target_low) / sv.target_median if targets and len(targets) >= 3 else None
    if share is not None:
        if share >= 0.8 and (disp is None or disp <= 0.35):
            sv.agreement = "high"
        elif share >= 0.8 or (share >= 0.6 and (disp is None or disp <= 0.7)):
            sv.agreement = "medium"   # same direction, different conviction
        else:
            sv.agreement = "low"
        sv.agreement_reason = (f"{max(pos, neg)} of {len(rated)} ratings on one side"
                               + (f"; targets spread {pct(disp, 0)} of the median" if disp is not None else ""))
    sv.findings = findings(sv, data, notes)
    return sv


def _set_model(sv: StreetView, data: TearSheetData) -> None:
    rt = data.rating
    sv.model_fair_value = sv.model_rating = sv.targets_above_model = None
    if rt and rt.fair_value:
        sv.model_fair_value, sv.model_rating = rt.fair_value, rt.rating
        if sv.target_values:
            sv.targets_above_model = sum(1 for t in sv.target_values if t > rt.fair_value)


_MODEL_LINE = "The InvestSync model's fair value"


def _model_line(sv: StreetView) -> Optional[str]:
    if not (sv.model_fair_value and sv.targets_above_model is not None and sv.targets_n):
        return None
    cur = ccy(sv.currency)
    fv = f"{cur} {num(sv.model_fair_value, 2)}"
    n, k = sv.targets_n, sv.targets_above_model
    if k == n:
        side = f"below all {n} broker targets: the model is more cautious than the brokers" if n > 1 else \
               "below the broker's target"
    elif k == 0:
        side = f"above all {n} broker targets: the model is more optimistic than the brokers" if n > 1 else \
               "above the broker's target"
    else:
        side = f"inside the brokers' range ({k} of {n} targets are higher)"
    return f"{_MODEL_LINE} ({fv}) is {side}."


def _drop_old_value(text: str, old: str) -> Optional[str]:
    """The AI's street-view paragraph without the sentences that quote the superseded model value (round 13, run 4:
    the deep report's broker digest was written before the debate set the scenarios and printed "the USD 281.76
    InvestSync fair value" next to a USD 196.26 rating). None when nothing is left."""
    import re
    kept = [s for s in re.split(r"(?<=[.!?])\s+", text) if old not in s]
    return " ".join(kept).strip() or None


def refresh_model(data: TearSheetData) -> None:
    """After the rating is recomputed (RATING_BASIS=scenarios), point the street view at the new fair value, so the
    broker comparison never shows a second, superseded model value (round-4 review, 9 Nov 2026)."""
    sv = data.street
    if sv is None:
        return
    old = sv.model_fair_value
    _set_model(sv, data)
    if sv.synthesis and old and sv.model_fair_value and num(old, 2) != num(sv.model_fair_value, 2):
        sv.synthesis = _drop_old_value(sv.synthesis, num(old, 2))
    line = _model_line(sv)
    kept = [f for f in sv.findings if not f.startswith(_MODEL_LINE)]
    if line:
        i = next((j for j, f in enumerate(sv.findings) if f.startswith(_MODEL_LINE)), len(kept))
        kept.insert(min(i, len(kept)), line)
    sv.findings = kept


def findings(sv: StreetView, data: TearSheetData, notes: Optional[list[BrokerNote]] = None) -> list[str]:
    """Plain-English comparisons, formatted exactly as the report prints the figures."""
    cur, ecur = ccy(sv.currency), ccy(sv.eps_currency)
    out: list[str] = []
    if sv.market == Market.CN:
        out.append(f"{sv.brokers} brokers published {sv.reports} research reports in the last {sv.window_days} days.")
    elif sv.market == Market.HK:
        out.append(f"{sv.brokers} brokers have a current rating or forecast on file at etnet.")
    else:
        out.append(f"{sv.brokers} brokers acted on the stock in the last {sv.window_days} days "
                   f"({sv.reports} rating or target actions).")
    if sv.rating_counts:
        rated = sum(sv.rating_counts.values())
        pos = sum(sv.rating_counts.get(r, 0) for r in ("Buy", "Outperform"))
        mix = ", ".join(f"{v} {k}" for k, v in sv.rating_counts.items())
        out.append(f"Latest ratings: {mix} ({pct(pos / rated, 0)} positive).")
    if sv.market != Market.HK and (sv.upgrades or sv.downgrades):
        out.append(f"Rating changes in the window: {sv.upgrades} upgrade{'s' * (sv.upgrades != 1)} and "
                   f"{sv.downgrades} downgrade{'s' * (sv.downgrades != 1)}.")
    if sv.targets_n:
        stale = f" ({sv.stale_targets} older than {STALE_DAYS} days)" if sv.stale_targets else ""
        if sv.targets_n == 1:
            out.append(f"One broker gives a price target: {cur} {num(sv.target_median, 2)} "
                       f"({pct(sv.target_upside, 1, signed=True)} vs the share price){stale}.")
        else:
            out.append(f"Price targets from {sv.targets_n} brokers range {cur} {num(sv.target_low, 2)}–"
                       f"{num(sv.target_high, 2)}; the median {cur} {num(sv.target_median, 2)} is "
                       f"{pct(sv.target_upside, 1, signed=True)} vs the share price{stale}.")
    elif sv.market == Market.CN:
        out.append("Most mainland brokers publish ratings and EPS forecasts without a price target.")
    line = _model_line(sv)
    if line:
        out.append(line)
    price = data.quote.price
    tg = [n for n in _latest_per_broker(notes or sv.notes, keep=lambda n: n.target is not None).values()
          if price and 0.2 <= n.target / price <= 5]
    if len(tg) >= 3:
        hi, lo = max(tg, key=lambda n: n.target), min(tg, key=lambda n: n.target)
        out.append(f"Most bullish target: {hi.broker} ({cur} {num(hi.target, 2)}); most cautious: "
                   f"{lo.broker} ({cur} {num(lo.target, 2)}).")
    last_fy, last_eps = _last_actual(data)
    for e in sv.eps[:1]:
        vs = (f" ({pct(e.vs_last_actual, 1, signed=True)} vs FY{last_fy} actual {ecur} {num(last_eps, 2)})"
              if e.vs_last_actual is not None else "")
        level = "wide" if (e.spread or 0) > 0.3 else "moderate" if (e.spread or 0) > 0.1 else "narrow"
        dropped = (f" ({e.excluded} forecast{'s' * (e.excluded != 1)} more than 3× from the median left out, "
                   f"e.g. quoted per ADS)" if e.excluded else "")
        out.append(f"{e.period} EPS forecasts from {e.n} brokers: {ecur} {num(e.low, 2)}–{num(e.high, 2)}, "
                   f"median {ecur} {num(e.median, 2)}{vs}; {level} disagreement (spread {pct(e.spread, 0)}){dropped}.")
        if e.vs_consensus is not None:
            gap = (" A gap this size usually means the two use different EPS definitions (e.g. adjusted vs "
                   "reported)." if abs(e.vs_consensus) > 0.08 else "")
            out.append(f"The brokers' median {e.period} EPS is {pct(e.vs_consensus, 1, signed=True)} vs the "
                       f"Yahoo Finance consensus.{gap}")
    r = sv.revision
    if r:
        word = "higher than" if r.change > 0.005 else "lower than" if r.change < -0.005 else "in line with"
        out.append(f"Estimate trend: {r.period} EPS forecasts from the last {r.recent_days} days (median "
                   f"{ecur} {num(r.recent_median, 2)}, {r.recent_n} brokers) are {pct(abs(r.change), 1)} {word} "
                   f"those from 31–{EARLIER_DAYS} days ago ({ecur} {num(r.earlier_median, 2)}, {r.earlier_n} brokers)."
                   if word != "in line with" else
                   f"Estimate trend: {r.period} EPS forecasts from the last {r.recent_days} days are in line with "
                   f"those from 31–{EARLIER_DAYS} days ago (median {ecur} {num(r.recent_median, 2)}).")
    out += _newer_than_table(sv, data)
    return out


def _newer_than_table(sv: StreetView, data: TearSheetData, limit: int = 3) -> list[str]:
    """HK: target changes in news write-ups that etnet's table does not show yet (it updates later)."""
    if sv.market != Market.HK or not sv.writeups:
        return []
    cur, price = ccy(sv.currency), data.quote.price
    table = _latest_per_broker(sv.notes)
    out, seen = [], set()
    for w in sv.writeups:  # newest first
        row = table.get(w.broker)
        if (w.target is None or w.broker in seen or not row or row.target is None or w.on <= row.on
                or abs(w.target - row.target) < 0.005 or not (price and 0.2 <= w.target / price <= 5)):
            continue
        seen.add(w.broker)
        out.append(f"Newer than etnet's table: {w.broker} moved its target to {cur} {num(w.target, 2)} on "
                   f"{w.on.strftime('%-d %b')} (etnet still shows {cur} {num(row.target, 2)}, "
                   f"{row.on.strftime('%-d %b')}; source: {w.source}).")
        if len(out) >= limit:
            break
    return out
