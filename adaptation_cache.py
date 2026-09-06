from __future__ import annotations

import threading
import time
from typing import Any, Callable


_LOCK = threading.Lock()
_CACHE: dict[tuple[str, int], tuple[float, Any]] = {}
MAX_CACHE_ENTRIES = 256


def _prune_locked(current: float) -> None:
    expired = [key for key, (expires_at, _value) in _CACHE.items() if expires_at <= current]
    for key in expired:
        _CACHE.pop(key, None)

    while len(_CACHE) > MAX_CACHE_ENTRIES:
        oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
        _CACHE.pop(oldest, None)


def get_or_load(
    namespace: str,
    chat_id: int,
    loader: Callable[[], Any],
    *,
    ttl_seconds: float,
    now: Callable[[], float] = time.monotonic,
) -> Any:
    """Маленький thread-safe TTL cache для локальных SQLite-срезов чата."""

    key = (namespace, int(chat_id))
    current = now()

    with _LOCK:
        _prune_locked(current)
        cached = _CACHE.get(key)
        if cached is not None and cached[0] > current:
            return cached[1]

    value = loader()

    with _LOCK:
        _CACHE[key] = (current + max(0.0, float(ttl_seconds)), value)
        _prune_locked(current)

    return value


def invalidate(namespace: str, chat_id: int) -> None:
    with _LOCK:
        _CACHE.pop((namespace, int(chat_id)), None)


def invalidate_chat(chat_id: int) -> None:
    chat_id = int(chat_id)
    with _LOCK:
        doomed = [key for key in _CACHE if key[1] == chat_id]
        for key in doomed:
            _CACHE.pop(key, None)


def clear() -> None:
    with _LOCK:
        _CACHE.clear()


# bot.py already imports adaptation_cache very early. Keep that public import
# stable for compatibility, but make the unrelated side-effect runtime loader
# explicit and separate. Loading it after the cache functions are defined also
# makes circular imports safer: runtime modules can import adaptation_cache and
# see a fully initialized utility module.
import runtime_bootstrap as _runtime_bootstrap  # noqa: F401,E402
