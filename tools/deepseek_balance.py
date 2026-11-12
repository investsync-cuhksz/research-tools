"""Print the DeepSeek account balance (never prints the key).

  python tools/deepseek_balance.py
  python tools/deepseek_balance.py --require 3.0   # exit 1 when the CNY balance is below 3.0 (run scripts use it so a
                                                   # run never starts that would run out of money halfway)

The balance updates with a delay of a minute or more after a run; wait before measuring cost.
"""
import requests

from investsync.config import Settings

s = Settings()
if not s.llm.enabled:
    raise SystemExit("No DeepSeek key configured (secrets/deepseek.txt or LLM_API_KEY).")
r = requests.get(f"{s.llm.base_url}/user/balance", headers={"Authorization": f"Bearer {s.llm.api_key}"}, timeout=20)
r.raise_for_status()
import sys

cny = 0.0
for b in r.json().get("balance_infos", []):
    print(f"{b['currency']}: {b['total_balance']} (topped up {b['topped_up_balance']}, granted {b['granted_balance']})")
    if b["currency"] == "CNY":
        cny = float(b["total_balance"])
if "--require" in sys.argv:
    need = float(sys.argv[sys.argv.index("--require") + 1])
    if cny < need:
        raise SystemExit(f"Balance CNY {cny:.2f} is below the CNY {need:.2f} this run needs: not starting.")
