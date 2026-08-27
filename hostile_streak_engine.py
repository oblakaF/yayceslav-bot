from __future__ import annotations

import time
from dataclasses import dataclass


HOSTILE_STREAK_WINDOW_SECONDS = 10 * 60
HOSTILE_STREAK_MAX = 4
HOSTILE_ESCALATION_FROM = 2


@dataclass(frozen=True)
class HostileStreak:
    count: int
    last_at: float


_STREAKS: dict[tuple[int, int], HostileStreak] = {}


def observe(
    chat_id: int,
    user_id: int,
    *,
    hostile: bool,
    now: float | None = None,
) -> int:
    """Track directed hostility heat per ``(chat, user)``.

    A neutral turn no longer erases a hot conflict. The heat expires naturally
    after the window, or can be cleared explicitly by the reconciliation layer.
    Repeated attacks saturate at ``HOSTILE_STREAK_MAX`` instead of wrapping back
    to one, so a long argument cannot accidentally make the bot soft again.
    """

    current_time = time.monotonic() if now is None else float(now)
    key = (int(chat_id), int(user_id))
    previous = _STREAKS.get(key)

    if previous is not None and current_time - previous.last_at > HOSTILE_STREAK_WINDOW_SECONDS:
        _STREAKS.pop(key, None)
        previous = None

    if not hostile:
        return previous.count if previous is not None else 0

    count = 1 if previous is None else min(HOSTILE_STREAK_MAX, previous.count + 1)
    _STREAKS[key] = HostileStreak(count=count, last_at=current_time)
    return count


def is_escalated(count: int) -> bool:
    return int(count) >= HOSTILE_ESCALATION_FROM


def current(chat_id: int, user_id: int, *, now: float | None = None) -> int:
    current_time = time.monotonic() if now is None else float(now)
    key = (int(chat_id), int(user_id))
    entry = _STREAKS.get(key)
    if entry is None:
        return 0
    if current_time - entry.last_at > HOSTILE_STREAK_WINDOW_SECONDS:
        _STREAKS.pop(key, None)
        return 0
    return entry.count


def reset(chat_id: int | None = None, user_id: int | None = None) -> None:
    if chat_id is None and user_id is None:
        _STREAKS.clear()
        return

    stale = [
        key
        for key in _STREAKS
        if (chat_id is None or key[0] == int(chat_id))
        and (user_id is None or key[1] == int(user_id))
    ]
    for key in stale:
        _STREAKS.pop(key, None)


def prune_stale_state(
    max_age_seconds: float,
    *,
    now: float | None = None,
) -> int:
    current_time = time.monotonic() if now is None else float(now)
    stale = [
        key
        for key, entry in _STREAKS.items()
        if current_time - entry.last_at > max_age_seconds
    ]
    for key in stale:
        _STREAKS.pop(key, None)
    return len(stale)
