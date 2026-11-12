# InvestSync weekly watchlist: week of <date>

Prices as of <date> close. Facts only, no buy / sell advice. Sources: InvestSync data-only reports
(`python generate.py --ticker <TICKER> --no-ai`).

## This week in one line per stock

| Stock | Price, 1-week move | What changed this week (most important first) | Next date to watch |
|---|---|---|---|
| Tencent (0700.HK) | | | |
| Alibaba (9988.HK) | | | |
| HSBC (0005.HK) | | | |
| ... | | | |

## Signals (cut-offs are Birlik's call; fill them in once agreed)

| Signal | Where the number is in a data-only report | Flag when |
|---|---|---|
| Analysts' EPS forecast revised up / down | "What the brokers say" (revision trend, 7 to 90 days) | moved more than __% in 30 days |
| Broker rating changes | Broker notes (upgrades / downgrades, last 30 days) | any upgrade or downgrade |
| Price target range moved | Broker notes (price-target range) | median target moved more than __% |
| Valuation vs peers | Peers table (P/E, EV/EBITDA vs peer median) | crossed the peer median, or more than __% from it |
| Financial health | Scorecard (checks passed, Piotroski F-score) | F-score changed, or a check flipped |
| Price move | Share price performance (1 week, 1 month vs benchmark) | moved more than __% vs the benchmark |
| Upcoming results | Market data ("Next scheduled results") | within 14 days |

## Ranking

How to order the stocks each week (e.g. most flags first, then the biggest price move). To be decided.

## Wording rules

- State what happened and who said it ("3 brokers raised ..."), never what to do.
- Every figure with its date and source.
- Broker views are opinions: attribute them.
