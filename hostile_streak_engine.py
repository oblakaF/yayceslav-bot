from __future__ import annotations

import time
from dataclasses import dataclass


HOSTILE_STREAK_WINDOW_SECONDS = 10 * 60
HOSTILE_STREAK_MAX = 4
HOSTILE_ESCALATION_FROM = 3


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
    """Tracks consecutive hostile turns per (chat, user) and returns 0..4."""

    current = time.monotonic() if now is None else float(now)
    key = (int(chat_id), int(user_id))

    if not hostile:
        _STREAKS.pop(key, None)
        return 0

    previous = _STREAKS.get(key)
    if (
        previous is None
        or current - previous.last_at > HOSTILE_STREAK_WINDOW_SECONDS
    ):
        count = 1
    else:
        count = previous.count + 1
        if count > HOSTILE_STREAK_MAX:
            # After the 3rd/4th-turn flare-up, return to a short fuse cycle.
            count = 1

    _STREAKS[key] = HostileStreak(count=count, last_at=current)
    return count


def is_escalated(count: int) -> bool:
    return HOSTILE_ESCALATION_FROM <= int(count) <= HOSTILE_STREAK_MAX


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
    current = time.monotonic() if now is None else float(now)
    stale = [
        key
        for key, entry in _STREAKS.items()
        if current - entry.last_at > max_age_seconds
    ]
    for key in stale:
        _STREAKS.pop(key, None)
    return len(stale)
