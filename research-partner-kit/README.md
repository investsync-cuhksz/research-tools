# Research partner kit

Everything for the three tasks below: our latest NVIDIA reports, the files to upload to an AI, a review template and
a starting point for the watchlist sheet.

| Folder / file | What it is | Used in |
|---|---|---|
| [`our_reports/`](our_reports/) | Our three NVIDIA reports from run 4 (standard, learner's guide, deep). Read them; never upload them to an AI. | Parts 1 and 2 |
| [`upload_to_ai/`](upload_to_ai/) | The files you give the AI in part 2: `SKILL.md`, the two exercise packs and the two example pages | Part 2 |
| [`review_template.md`](review_template.md) | The review format for parts 1 and 2 (the 7 points our reviewers score) | Parts 1 and 2 |
| [`watchlist/`](watchlist/) | A template for the weekly sheet and where each number comes from | Part 3 |

---

Hi Birlik,

Parts 1 and 2 are short, and they show how a student with a free AI compares with our tool. Part 3 is your own
tool.

### 1) Make a report with free AI, from your own prompts

- Use NVIDIA, the same stock as our latest reports, so we can compare.
- Use free accounts: DeepSeek, ChatGPT, Claude, and any others you like (Gemini, Kimi, Doubao...).
- Rules: don't upload our PDFs or any of our files. You can tell the AI what you want (which sections, which charts,
  how long), but don't write any of the content yourself. Let it search the web if it can.
- Save every prompt and every answer, and note the date and whether web search was on.
- Then write a short review comparing each AI's report with ours. Score each one 1-10 on the 7 points our reviews
  use: accuracy, valuation, thesis, risk & balance, timeliness, communication, standards. List every wrong number or
  date you find: quote it, give the right figure, and say where you checked it. Finish with what it did better than
  ours and what ours did better. The format is in [`review_template.md`](review_template.md).

### 2) The same, but with our facts

- The files are in [`upload_to_ai/`](upload_to_ai/): our "exercise pack" for NVIDIA (two text files: one for the
  standard report and learner's guide, one for the deep report), `SKILL.md` (the rules our own AI writers follow) and
  two example pages. The pack has all our numbers, forecast, scenarios and rating, but none of our written text.
- Upload `SKILL.md`, the pack and one of the two example pages to each AI, and ask it to write the standard report,
  the learner's guide and the deep report. The exact prompts are in `SKILL.md` under "How to use this file".
- Don't edit the AI's answers. Compare them with our three reports (in [`our_reports/`](our_reports/)) section by
  section, in the same review format as in 1).
- This tells us how much our tool adds beyond the numbers. If a free AI with our pack writes as well as our pipeline,
  that's worth knowing too.

### 3) Your own tool: a weekly watchlist sheet

- One page each week for the club, saying what changed for the stocks we follow. For example: "3 brokers raised
  Tencent's EPS forecast in the last 30 days", "HSBC's P/E is now below its peers' median", "NVIDIA results due on
  17 Nov".
- The finance judgement is yours: which stocks go on the list, which signals matter, where the cut-offs are (e.g.
  flag a forecast change above X% in 30 days), how to rank them, and how to word each line as a fact, not advice.
- Our tool already makes most of these numbers for one stock at a time, free and with no AI:
  `python generate.py --ticker NVDA --no-ai`. Broker changes and the forecast revision trend are in
  [`investsync/quant/street.py`](../investsync/quant/street.py). The health checks, including the Piotroski score,
  are in [`investsync/quant/scorecard.py`](../investsync/quant/scorecard.py). Peer multiples are in the Peers sheet
  of our data pack. The stock list is [`covered_tickers.txt`](../covered_tickers.txt), which has 7 placeholder stocks
  for now.
- First step: make the sheet once by hand for those 7 stocks from the free reports, so we agree on what goes in.
  Then we automate it, and I can help with the code. A starting layout is in
  [`watchlist/template.md`](watchlist/template.md).

Let me know roughly how long you think each part will take.

Thanks!
Karel
