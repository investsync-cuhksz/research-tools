# Sector playbooks

Short notes on what an equity analyst checks for each kind of company. The matching playbook is added to
the facts the AI writer, debaters and reviewer see (`playbook_for` in `__init__.py`).

Rules for editing (finance team owns the content):
- **No numbers or thresholds** (no digits at all): the number guardrail treats every figure in the facts as
  quotable data, so a number here could end up in a report as if it were the company's. Say "compare with
  peers / its own history" instead.
- Keep each file under ~250 words: it is sent with every AI call.
- `sectors:` line = lower-case words matched against the sector / industry name (Yahoo or EastMoney).
