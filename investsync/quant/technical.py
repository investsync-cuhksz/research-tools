"""Rule-based price indicators for the technical page.

Everything here is descriptive: standard formulas applied to daily adjusted closes, and a
simple vote across five rules. It is not a trading signal or a recommendation.

* SMA 50 / 200          simple moving averages of the close
* RSI 14                Wilder's relative strength index
* MACD 12/26/9          EMA(12) - EMA(26), signal = EMA(9) of MACD, histogram = MACD - signal
* Volatility            annualised standard deviation of daily log returns, last 252 days
* Max drawdown          largest peak-to-trough fall within the window
* Support / resistance  lowest low / highest high of the last 63 trading days (about 3 months)
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from ..schema import ReturnRow, Signal, TechPoint, Technicals

TRADING_DAYS = 252


def sma(values: list[float], n: int) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= n:
            run -= values[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def ema(values: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out, e = [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(values: list[float], n: int = 14) -> list[Optional[float]]:
    """Wilder's RSI; None until ``n`` changes are available."""
    out: list[Optional[float]] = [None] * len(values)
    if len(values) <= n:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n

    def value(g: float, l: float) -> float:
        return 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    out[n] = value(ag, al)
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out[i + 1] = value(ag, al)
    return out


def macd(values: list[float], fast: int = 12, slow: int = 26, sig: int = 9) -> tuple[float, float, float]:
    line = [a - b for a, b in zip(ema(values, fast), ema(values, slow))]
    signal = ema(line, sig)
    return line[-1], signal[-1], line[-1] - signal[-1]


def max_drawdown(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def volatility(values: list[float]) -> Optional[float]:
    rets = [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]
    if len(rets) < 20:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def _ret_since(series: dict[date, float], dates: list[date], start: date) -> Optional[float]:
    window = [d for d in dates if d >= start]
    if not window or (window[0] - start).days > 10:
        return None
    return series[dates[-1]] / series[window[0]] - 1


def period_returns(stock: dict[date, float], bench: dict[date, float]) -> list[ReturnRow]:
    s_dates, b_dates = sorted(stock), sorted(bench)
    if not s_dates:
        return []
    end = s_dates[-1]
    starts = [("1M", end - timedelta(days=30)), ("3M", end - timedelta(days=91)),
              ("6M", end - timedelta(days=182)), ("YTD", date(end.year, 1, 1) - timedelta(days=1)),
              ("1Y", end - timedelta(days=365)), ("3Y", end - timedelta(days=round(3 * 365.25))),
              ("5Y", end - timedelta(days=round(5 * 365.25)))]
    out = []
    for label, start in starts:
        if label == "YTD":  # measure from the last close of the previous year
            prev = [d for d in s_dates if d <= start]
            s = stock[end] / stock[prev[-1]] - 1 if prev else None
            bprev = [d for d in b_dates if d <= start]
            b = bench[b_dates[-1]] / bench[bprev[-1]] - 1 if bprev and b_dates else None
        else:
            s = _ret_since(stock, s_dates, start)
            b = _ret_since(bench, b_dates, start) if b_dates else None
        if s is not None:
            out.append(ReturnRow(period=label, stock=s, benchmark=b))
    return out


def _downsample(n: int, max_points: int) -> list[int]:
    if n <= max_points:
        return list(range(n))
    step = n / max_points
    idx = sorted({int(i * step) for i in range(max_points)} | {n - 1})
    return idx


def compute(prices: pd.DataFrame, bench: dict[date, float], chart_years: float = 2.0,
            max_points: int = 260) -> Optional[Technicals]:
    """Indicators from daily prices (columns date, close, high, low, optional volume)."""
    if prices is None or len(prices) < 60:
        return None
    df = prices.sort_values("date").reset_index(drop=True)
    closes = [float(x) for x in df["close"]]
    dates = list(df["date"])
    highs = [float(x) for x in df["high"]] if "high" in df else closes
    lows = [float(x) for x in df["low"]] if "low" in df else closes
    vols = [float(x) if x == x else None for x in df["volume"]] if "volume" in df else None

    s50, s200, r14 = sma(closes, 50), sma(closes, 200), rsi(closes)
    m, ms, mh = macd(closes)
    price, last = closes[-1], dates[-1]
    one_year = [c for d, c in zip(dates, closes) if d >= last - timedelta(days=365)]
    three_years = [c for d, c in zip(dates, closes) if d >= last - timedelta(days=round(3 * 365.25))]
    hi52 = max(h for d, h in zip(dates, highs) if d >= last - timedelta(days=365))
    lo52 = min(l for d, l in zip(dates, lows) if d >= last - timedelta(days=365))

    vol_ratio = None
    if vols and len(vols) >= 21 and all(v is not None for v in vols[-21:]):
        avg20 = sum(vols[-21:-1]) / 20
        vol_ratio = vols[-1] / avg20 if avg20 else None

    # Five simple rules -> bullish / bearish / neutral
    signals: list[Signal] = []
    if s200[-1] is not None:
        signals.append(Signal(name="Trend (price vs 200-day average)",
                              reading="bullish" if price > s200[-1] else "bearish"))
    if s50[-1] is not None and s200[-1] is not None:
        signals.append(Signal(name="Moving-average cross (50 vs 200-day)",
                              reading="bullish" if s50[-1] > s200[-1] else "bearish"))
    if s50[-1] is not None:
        signals.append(Signal(name="Short-term trend (price vs 50-day average)",
                              reading="bullish" if price > s50[-1] else "bearish"))
    if r14[-1] is not None:
        reading = "bearish" if r14[-1] >= 70 else "bullish" if r14[-1] <= 30 else "neutral"
        signals.append(Signal(name="RSI 14 (overbought >= 70, oversold <= 30)", reading=reading))
    signals.append(Signal(name="MACD histogram", reading="bullish" if mh > 0 else "bearish"))
    score = sum(1 if s.reading == "bullish" else -1 if s.reading == "bearish" else 0 for s in signals)
    overall = "bullish" if score >= 2 else "bearish" if score <= -2 else "neutral"

    start = last - timedelta(days=round(365.25 * chart_years))
    first = next(i for i, d in enumerate(dates) if d >= start)
    idx = _downsample(len(dates) - first, max_points)

    def bucket_volume(k: int) -> Optional[float]:
        """Average daily volume over the days a downsampled point stands for."""
        if not vols:
            return None
        lo = first + (idx[k - 1] + 1 if k else idx[0])
        vs = [v for v in vols[lo: first + idx[k] + 1] if v is not None]
        return sum(vs) / len(vs) if vs else None

    chart = [TechPoint(d=dates[first + i], close=round(closes[first + i], 4),
                       sma50=round(s50[first + i], 4) if s50[first + i] is not None else None,
                       sma200=round(s200[first + i], 4) if s200[first + i] is not None else None,
                       volume=bucket_volume(k),
                       rsi=round(r14[first + i], 2) if r14[first + i] is not None else None)
             for k, i in enumerate(idx)]

    # the largest one-day move in the last 30 days: the research desk searches for its cause (round-7 review: the
    # 5 Nov -9.3% day went unexplained)
    big, big_d = None, None
    for i in range(1, len(closes)):
        if dates[i] >= last - timedelta(days=30) and closes[i - 1]:
            r = closes[i] / closes[i - 1] - 1
            if big is None or abs(r) > abs(big):
                big, big_d = r, dates[i]
    if big is not None and abs(big) < 0.04:  # only a move worth explaining
        big, big_d = None, None
    return Technicals(
        big_move=big, big_move_date=big_d.date() if hasattr(big_d, "date") and callable(big_d.date) else big_d,
        as_of=last, price=price, sma50=s50[-1], sma200=s200[-1], rsi14=r14[-1],
        macd=m, macd_signal=ms, macd_hist=mh, volume_ratio=vol_ratio,
        volatility_1y=volatility(one_year), max_drawdown_1y=max_drawdown(one_year),
        max_drawdown_3y=max_drawdown(three_years) if len(three_years) > len(one_year) + 100 else None,
        high_52w=hi52, low_52w=lo52, support=min(lows[-63:]), resistance=max(highs[-63:]),
        returns=period_returns(dict(zip(dates, closes)), bench),
        signals=signals, overall=overall, chart=chart)
