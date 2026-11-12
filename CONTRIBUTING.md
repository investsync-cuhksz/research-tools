# Contributing to InvestSync Research Tools

Thanks for helping. This project is run by InvestSync Technology, the student investment club at CUHK-Shenzhen.
Club members, students and outside contributors are all welcome.

## Ways to help

| You are... | Good first contributions |
|---|---|
| A finance student | Review a report and log errors ([`research-partner-kit/review_template.md`](research-partner-kit/review_template.md)); improve a sector playbook ([`investsync/narrative/playbooks/`](investsync/narrative/playbooks/)); curate peer lists ([`config/peers.json`](config/peers.json)) |
| A developer | Fix an issue, add a test, add a data source, improve the web page ([`api/static/`](api/static/)) |
| Either | Improve the README or the FAQ, report a bug with the ticker and the command you ran |

## Set up

Follow [Getting started](README.md#getting-started) in the README. No API key is needed for the tests or for
data-only reports.

```bash
LITELLM_LOCAL_MODEL_COST_MAP=True pytest -q
```

`LITELLM_LOCAL_MODEL_COST_MAP=True` stops LiteLLM from fetching its online price list, which can hang. The suite
runs offline, needs no key and takes about 1–2 minutes.

## How to propose a change

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Create a branch from `main` (`fix/peer-median-label`, `feature/watchlist`).
3. Keep each pull request to one change, with a test where it makes sense.
4. Run the tests and make sure they pass.
5. Open a pull request that says what changed, why, and how you checked it. For a change to a report, attach a
   before/after page (PNG or PDF).

## House rules for the code

These rules are why the reports can be trusted. Please keep them.

1. **Code computes every number.** The AI never supplies a figure: it writes words around numbers that code has
   computed and formatted.
2. **Every AI sentence is checked.** New AI text must go through the existing checks (the number guardrail
   `narrative/guardrail.py`, the claim check `narrative/claimcheck.py`, the fact sweep `narrative/factcheck.py`).
3. **Rules are general, never per ticker.** Fix a class of error with a general rule and a test, never with an
   exception for one company.
4. **Sources are named.** Every figure and quote keeps its source; broker views and news are attributed.
5. **No secrets in git.** Keys live in `.env` or `secrets/` (both git-ignored). Never paste a key into code, tests,
   logs or issues.
6. **Paid AI runs need approval.** Tests must not call a paid API. A full paid run is started by a maintainer.
7. **Finance settings belong to the finance team.** `config/valuation.json`, `config/rating.json` and the sector
   playbooks change only with their review.

## Adding things

- **A sector playbook:** add `investsync/narrative/playbooks/<sector>.md` with a first line
  `sectors: word, word, 中文` and at most ~250 words. No digits: the number guardrail would treat them as data.
- **Peers for a ticker:** add `"<TICKER>": ["PEER1", "PEER2", ...]` to `config/peers.json`. Curated lists always
  win over automatic ones.
- **A news source:** add the outlet to `config/news_sources.json`. News is kept only from listed outlets.
- **A data source:** add an adapter in `investsync/data/`, record where each figure came from (`provenance.py`),
  and add an offline test with a saved fixture in `fixtures/`.

## Reporting a bug

Include the ticker, the command or web option you used, the date and time, and what you expected. If a figure is
wrong, quote it with its page and give the correct figure and where you checked it.

## Code of conduct

Be kind and specific. Critique the work, not the person. Reports are for education, never investment advice.
