from __future__ import annotations

import threading
import time
from typing import Any, Callable

# Loaded early by bot.py, before thinking_engine installs its Gemini router.
# This lets the primitive compact guard sit underneath the router and apply
# equally to the primary and fallback chat models.
import primitive_compact_guard  # noqa: F401


_LOCK = threading.Lock()
_CACHE: dict[tuple[str, int], tuple[float, Any]] = {}


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
        cached = _CACHE.get(key)
        if cached is not None and cached[0] > current:
            return cached[1]

    value = loader()

    with _LOCK:
        _CACHE[key] = (current + max(0.0, float(ttl_seconds)), value)

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
