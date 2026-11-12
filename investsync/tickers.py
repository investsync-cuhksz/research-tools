"""Ticker parsing: turn user input into a market, exchange and source codes."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Market


@dataclass(frozen=True)
class Ticker:
    canonical: str       # 0700.HK, 600519.SH, NVDA
    market: Market
    exchange: str        # HKEX, SSE, SZSE, BSE, US (resolved later to NASDAQ/NYSE)
    code: str            # 00700, 600519, NVDA

    @property
    def em_prefixed(self) -> str:
        """EastMoney-style code for statements, e.g. SH600519 / SZ000858."""
        prefix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(self.exchange, "")
        return f"{prefix}{self.code}"


BENCHMARKS = {
    Market.HK: ("Hang Seng Index", "HSI"),
    Market.CN: ("CSI 300", "000300"),
    Market.US: ("S&P 500", ".INX"),
}

CURRENCY = {Market.HK: "HKD", Market.CN: "CNY", Market.US: "USD"}


def parse(raw: str) -> Ticker:
    s = raw.strip().upper()

    m = re.fullmatch(r"(\d{1,5})\.HK", s) or re.fullmatch(r"HK\.?(\d{1,5})", s)
    if m:
        code = m.group(1).zfill(5)
        return Ticker(f"{code[-4:] if code.startswith('0') else code}.HK", Market.HK, "HKEX", code)

    m = re.fullmatch(r"(\d{6})\.(SH|SS|SZ|BJ)", s) or re.fullmatch(r"(SH|SZ|BJ)(\d{6})", s)
    if m:
        code, sfx = (m.group(1), m.group(2)) if m.group(1).isdigit() else (m.group(2), m.group(1))
        sfx = "SH" if sfx == "SS" else sfx
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[sfx]
        return Ticker(f"{code}.{sfx}", Market.CN, exchange, code)

    m = re.fullmatch(r"(\d{6})", s)
    if m:  # bare A-share code: infer exchange from the leading digit
        code = m.group(1)
        sfx = "SH" if code[0] in "69" else ("BJ" if code[0] in "48" else "SZ")
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[sfx]
        return Ticker(f"{code}.{sfx}", Market.CN, exchange, code)

    m = re.fullmatch(r"([A-Z][A-Z\-]{0,6}(?:\.[A-Z])?)(?:\.US)?", s)
    if m:
        code = m.group(1)
        return Ticker(code, Market.US, "US", code)

    raise ValueError(f"Unrecognised ticker: {raw!r}. Try 0700.HK, 600519.SH or NVDA.")
