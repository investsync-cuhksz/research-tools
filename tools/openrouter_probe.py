"""Probe OpenRouter models with one tiny request each (never prints the key).

    .venv/bin/python tools/openrouter_probe.py --key-status
    .venv/bin/python tools/openrouter_probe.py deepseek/deepseek-v4.1-flash-1017@deepinfra/fp8 anthropic/claude-sonnet-5.5
    .venv/bin/python tools/openrouter_probe.py --reasoning none deepseek/deepseek-v4.1-flash-1017@deepinfra/fp8

A model may carry a pinned provider and quantisation: <model>@<provider>[/<quantisation>]. For each model it prints
the HTTP status, the provider that served it, tokens, the billed cost (OpenRouter's usage accounting) or the error
(403 = blocked for this account / region, 402 = credit, 404 = model or provider not available). Each probe costs a
fraction of a cent. The key is read from OPENROUTER_API_KEY or secrets/openrouter.txt (git-ignored).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://openrouter.ai/api/v1"


def key() -> str:
    k = os.getenv("OPENROUTER_API_KEY")
    if not k:
        f = ROOT / "secrets" / "openrouter.txt"
        k = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    if not k:
        sys.exit("no OpenRouter key: save it to secrets/openrouter.txt (one line)")
    return k


def key_status(k: str) -> None:
    r = None
    for attempt in range(4):  # mainland networks drop connections to openrouter.ai at peak hours
        try:
            r = requests.get(f"{BASE}/key", headers={"Authorization": f"Bearer {k}"}, timeout=30)
            break
        except requests.RequestException as e:
            print(f"key status: network error ({type(e).__name__}), attempt {attempt + 1} of 4")
    if r is None:
        return
    if r.status_code != 200:
        print(f"key status: HTTP {r.status_code} {r.text[:200]}")
        return
    d = r.json().get("data", {})
    print(f"key status: usage USD {d.get('usage')} · limit {d.get('limit')} · remaining {d.get('limit_remaining')} "
          f"· free tier {d.get('is_free_tier')}")


def probe(k: str, spec: str, reasoning: str = "") -> None:
    model, _, prov = spec.partition("@")
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 16 if not reasoning or reasoning == "none" else 600, "usage": {"include": True}}
    if reasoning:
        body["reasoning"] = {"effort": reasoning}
    if prov:
        name, _, quant = prov.partition("/")
        body["provider"] = {"only": [name], "allow_fallbacks": False, **({"quantizations": [quant]} if quant else {})}
    r = None
    for attempt in range(4):  # retry dropped connections (peak-hour mainland networks)
        try:
            r = requests.post(f"{BASE}/chat/completions", headers={"Authorization": f"Bearer {k}",
                                                                   "Content-Type": "application/json"},
                              data=json.dumps(body), timeout=120)
            break
        except requests.RequestException as e:
            print(f"{spec:55s} network error ({type(e).__name__}), attempt {attempt + 1} of 4")
    if r is None:
        return
    if r.status_code != 200:
        print(f"{spec:55s} HTTP {r.status_code}: {r.text[:240]}")
        return
    d = r.json()
    u = d.get("usage") or {}
    text = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    print(f"{spec:55s} OK · provider {d.get('provider')} · in {u.get('prompt_tokens')} out {u.get('completion_tokens')}"
          f" (reasoning {rt}) · cost USD {u.get('cost')} · reply {text.strip()[:20]!r}"
          + (f" · reasoning={reasoning}" if reasoning else ""))


if __name__ == "__main__":
    k = key()
    args = sys.argv[1:]
    reasoning = ""
    if "--reasoning" in args:
        i = args.index("--reasoning")
        reasoning = args[i + 1]
        args = args[:i] + args[i + 2:]
    if not args or args == ["--key-status"]:
        key_status(k)
    else:
        key_status(k)
        for spec in args:
            probe(k, spec, reasoning)
