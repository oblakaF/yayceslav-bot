from __future__ import annotations

import threading
import time
from typing import Any, Callable

# Loaded early by bot.py, before thinking_engine installs its Gemini router.
# Runtime guards only patch Application.run_polling here; they touch bot.py
# functions later, when the application is fully built and run_polling starts.
import primitive_compact_guard  # noqa: F401
import dialogue_guard_runtime  # noqa: F401
import member_profile_runtime  # noqa: F401
import member_memory_safety_patch  # noqa: F401
import dialogue_followup_mode_patch  # noqa: F401
import chat_member_updates_patch  # noqa: F401

# Monthly report must be imported BEFORE unified daily titles. Because each
# runtime wraps Application.run_polling, this order ensures unified titles are
# installed first at startup and the monthly report then wraps that final
# scheduler instead of being overwritten.
import monthly_social_runtime  # noqa: F401
import monthly_report_timing_patch  # noqa: F401
import unified_daily_title_runtime  # noqa: F401
import relationship_experience_runtime  # noqa: F401
import whoami_profile_v3_runtime  # noqa: F401
import monthly_memory_scope_patch  # noqa: F401
import monthly_theme_quality_patch  # noqa: F401
import whoami_profile_v4_runtime  # noqa: F401


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
