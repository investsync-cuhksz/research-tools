<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/investsync-cuhksz/.github/main/assets/investsync-logo-dark.png">
    <img src="https://raw.githubusercontent.com/investsync-cuhksz/.github/main/assets/investsync-logo.png" alt="InvestSync" height="56">
  </picture>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/investsync-cuhksz/.github/main/assets/cuhksz-logo-dark.png">
    <img src="https://raw.githubusercontent.com/investsync-cuhksz/.github/main/assets/cuhksz-logo.png" alt="The Chinese University of Hong Kong, Shenzhen" height="56">
  </picture>
</p>

# Research Tools

**Project #3 · InvestSync Technology**

A tool that turns any ticker into a one-page company summary for analysts. An analyst enters a ticker and gets a one-page PDF tear sheet in under a minute, instead of spending hours collecting numbers by hand.

## Team

- Birlik Yessen
- Karel Hutajulu ([@karelhutajulu](https://github.com/karelhutajulu)), CTO

## Core features

- **Ticker input** for Hong Kong, mainland China and US listings (e.g. `0700.HK`), with a clear error for unknown tickers
- **Company overview:** name, exchange, sector, market cap, description, price and 52-week range
- **Price chart:** 1, 3 and 5 years against the benchmark, rebased to 100
- **Financial summary:** five fiscal years of revenue, margins, profit, EPS, debt and cash
- **Valuation vs. peers:** P/E, EV/EBITDA, P/B and dividend yield against 3 to 5 peers and the peer median
- **PDF output:** one A4 page in InvestSync style, with sources and generation date in the footer
- **Batch mode** for a whole list of tickers
- **Data and caching** via [AKShare](https://github.com/akfamily/akshare), so repeat runs take seconds

## Deliverable

An analyst can generate a correct, good-looking tear sheet for any covered company in under a minute, and Research has used it for at least one report.

## Getting started

_To be added: setup, how to run, and an example tear sheet._

## References

- [Yahoo Finance: Tencent](https://finance.yahoo.com/quote/0700.HK/) and its [key statistics](https://finance.yahoo.com/quote/0700.HK/key-statistics/)
- [AKShare](https://github.com/akfamily/akshare) · [pandas docs](https://pandas.pydata.org/docs/) · [Matplotlib docs](https://matplotlib.org/stable/)
