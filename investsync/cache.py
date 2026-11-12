"""SQLite disk cache with per-entry TTL, and the stale-copy backup for every source.

Financial statements are cached for 30 days, prices for 15 minutes (see TTL).
Values are stored as pickled objects so DataFrames round-trip unchanged.

Backup rule (11 Nov 2026): expired rows are kept. When a live call raises or returns an empty result
and an earlier non-empty copy exists, that copy is used, its original fetch time goes to the citations,
and the report gets a data note (provenance.stale_notes). An empty result never replaces a good copy and
is itself kept only a few minutes, so the source is tried again soon.
"""
from __future__ import annotations

import functools
import hashlib
import logging
import pickle
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .config import settings

log = logging.getLogger(__name__)

TTL = {
    "financials": 30 * 24 * 3600,
    "profile": 7 * 24 * 3600,
    "prices": 15 * 60,
    "quote": 15 * 60,
    "news": 60 * 60,
    "peers": 24 * 3600,
    "fx": 24 * 3600,
    "research": 6 * 3600,   # broker report lists, ratings and targets
}
EMPTY_TTL = 5 * 60    # an empty answer may be an outage: ask again after a few minutes
RETRY_AFTER = 5 * 60  # a source that just failed is not asked again for this long (its stale copy is used)

_lock = threading.Lock()


class Cache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS cache "
                      "(key TEXT PRIMARY KEY, expires REAL, value BLOB, fetched REAL)")
            if "fetched" not in {r[1] for r in c.execute("PRAGMA table_info(cache)")}:
                try:  # caches made before the stale-copy backup lack the fetch time
                    c.execute("ALTER TABLE cache ADD COLUMN fetched REAL")
                except sqlite3.OperationalError:
                    pass  # another process added it first

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def get(self, key: str) -> Any | None:
        hit = self.get_with_expiry(key)
        return hit[0] if hit else None

    def get_with_expiry(self, key: str) -> tuple[Any, float] | None:
        hit = self.entry(key)
        if not hit or hit[1] < time.time():
            return None
        return hit[0], hit[1]

    def entry(self, key: str) -> tuple[Any, float, Optional[float]] | None:
        """(value, expires, fetched) whether expired or not: the copy a failed source falls back on.
        ``fetched`` is None for rows written before the column existed."""
        with _lock, self._conn() as c:
            row = c.execute("SELECT expires, value, fetched FROM cache WHERE key = ?", (key,)).fetchone()
        return (pickle.loads(row[1]), row[0], row[2]) if row else None

    def set(self, key: str, value: Any, ttl: int, fetched: Optional[float] = None) -> None:
        """``fetched``: when the value was fetched from its source (a stale copy kept for a retry pause keeps
        its original time, so its citation never shows a later date)."""
        now = time.time()
        with _lock, self._conn() as c:
            c.execute("REPLACE INTO cache (key, expires, value, fetched) VALUES (?, ?, ?, ?)",
                      (key, now + ttl, pickle.dumps(value), fetched if fetched is not None else now))

    def clear(self) -> None:
        with _lock, self._conn() as c:
            c.execute("DELETE FROM cache")


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache(settings.cache_db_path)
    return _cache


def is_empty(value: Any) -> bool:
    """None, {}, [], "" or an empty DataFrame / Series: what the sources return when a call quietly failed."""
    if value is None:
        return True
    if hasattr(value, "empty") and not callable(value.empty):  # pandas objects
        return bool(value.empty)
    if isinstance(value, (dict, list, tuple, str)):
        return len(value) == 0
    return False


def cached(kind: str) -> Callable:
    """Cache a function's result under the TTL for ``kind``, with the stale-copy backup (module docstring).

    ``fn.fresh(...)``: the same call without the stale-copy backup (raises / returns empty instead), for callers
    that try another live source first. ``fn.last_copy(...)``: the stored copy at any age, or None.
    Set the environment variable INVESTSYNC_NO_CACHE=1 to bypass.
    """
    TTL[kind]  # an unknown kind fails at import, not at the first call

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return _call(fn, kind, args, kwargs, stale_ok=True)
        wrapper.fresh = lambda *a, **k: _call(fn, kind, a, k, stale_ok=False)
        wrapper.last_copy = lambda *a, **k: _last_copy(fn, kind, a, k)
        return wrapper
    return deco


def _key(fn: Callable, kind: str, args: tuple, kwargs: dict) -> str:
    raw = f"{fn.__module__}.{fn.__qualname__}:{args!r}:{sorted(kwargs.items())!r}"
    return f"{kind}:{hashlib.sha1(raw.encode()).hexdigest()}"


def _fetched(entry: tuple, ttl: int) -> float:
    value, expires, fetched = entry
    return fetched if fetched is not None else expires - ttl  # older rows: expiry minus TTL, as before


def _record(fn: Callable, args: tuple, fetched: float, from_cache: bool, stale: bool = False) -> None:
    from . import provenance  # every source call is recorded for the report's citations
    provenance.record(fn.__qualname__, args, fetched, from_cache, stale=stale)


def _call(fn: Callable, kind: str, args: tuple, kwargs: dict, stale_ok: bool) -> Any:
    if settings.no_cache:
        value = fn(*args, **kwargs)
        if not is_empty(value):
            _record(fn, args, time.time(), False)
        return value
    ttl, key, cache = TTL[kind], _key(fn, kind, args, kwargs), get_cache()
    old, now = cache.entry(key), time.time()
    if old is not None and old[1] >= now:
        age = now - _fetched(old, ttl)
        if stale_ok or age <= ttl:  # a stale copy inside its retry pause is a hit only for the backup path
            if not is_empty(old[0]):
                _record(fn, args, _fetched(old, ttl), True, stale=age > ttl)
            return old[0]
    good = old if old is not None and not is_empty(old[0]) else None
    try:
        value = fn(*args, **kwargs)
    except Exception as e:
        if good is None or not stale_ok:
            raise
        return _use_stale(fn, args, key, good, ttl, f"raised {type(e).__name__}")
    if is_empty(value):
        if good is not None and stale_ok:
            return _use_stale(fn, args, key, good, ttl, "returned nothing")
        if good is None and value is not None:  # None stays uncached, as before (callers rely on it)
            cache.set(key, value, EMPTY_TTL)
        return value  # not cited: the report shows nothing from a source that gave nothing
    cache.set(key, value, ttl)
    _record(fn, args, time.time(), False)
    return value


def _use_stale(fn: Callable, args: tuple, key: str, good: tuple, ttl: int, why: str) -> Any:
    fetched = _fetched(good, ttl)
    log.warning("%s%s: live call %s; using the copy fetched %s", fn.__qualname__, args, why,
                datetime.fromtimestamp(fetched).strftime("%Y-%m-%d %H:%M"))
    get_cache().set(key, good[0], RETRY_AFTER, fetched=fetched)  # the next calls in this run skip the dead source
    _record(fn, args, fetched, True, stale=True)
    return good[0]


def _last_copy(fn: Callable, kind: str, args: tuple, kwargs: dict) -> Any:
    """The stored non-empty copy at any age (recorded as stale when older than its TTL), or None."""
    if settings.no_cache:
        return None
    ttl = TTL[kind]
    old = get_cache().entry(_key(fn, kind, args, kwargs))
    if old is None or is_empty(old[0]):
        return None
    fetched = _fetched(old, ttl)
    _record(fn, args, fetched, True, stale=time.time() - fetched > ttl)
    return old[0]
