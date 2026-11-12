"""Sector playbooks (markdown) added to the AI's facts: what an analyst checks for this kind of company."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _load() -> list[tuple[str, list[str], str]]:
    out = []
    for f in sorted(_DIR.glob("*.md")):
        if f.name == "README.md":
            continue
        head, _, body = f.read_text(encoding="utf-8").partition("\n")
        words = [w.strip().lower() for w in head.removeprefix("sectors:").split(",") if w.strip()]
        out.append((f.stem, words, body.strip()))
    return out


def playbook_for(sector: Optional[str], financial: bool = False) -> str:
    """General playbook + the first sector playbook whose words appear in ``sector``."""
    s = (sector or "").lower()
    general = next((b for n, _, b in _load() if n == "_general"), "")
    match = "banks" if financial else next((n for n, words, _ in _load() if n != "_general"
                                            and any(w in s for w in words)), None)
    body = next((b for n, _, b in _load() if n == match), "") if match else ""
    return "\n".join(x for x in (general, body) if x)
