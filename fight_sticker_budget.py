"""Shared RAM-only budget for semantic stickers during an active fight.

This is a helper, not a runtime owner: conflict state stays in conflict_fsm_runtime
and sticker delivery stays in the existing sticker runtimes. The budget only
prevents a hot exchange from becoming sticker spam while allowing up to two
fight-specific visual beats in one session.
"""

from __future__ import annotations

from collections import defaultdict, deque


FIGHT_STICKER_SESSION_SECONDS = 12 * 60.0
FIGHT_STICKER_MIN_GAP_SECONDS = 75.0
FIGHT_STICKER_MAX_PER_SESSION = 2

_TIMES: dict[tuple[int, int], deque[float]] = defaultdict(deque)


def _history(chat_id: int, user_id: int, now: float) -> deque[float]:
    key = (int(chat_id), int(user_id))
    history = _TIMES[key]
    while history and now - history[0] > FIGHT_STICKER_SESSION_SECONDS:
        history.popleft()
    return history


def count(chat_id: int, user_id: int, now: float) -> int:
    return len(_history(chat_id, user_id, float(now)))


def allowed(chat_id: int, user_id: int, now: float) -> bool:
    history = _history(chat_id, user_id, float(now))
    if len(history) >= FIGHT_STICKER_MAX_PER_SESSION:
        return False
    if history and float(now) - history[-1] < FIGHT_STICKER_MIN_GAP_SECONDS:
        return False
    return True


def record(chat_id: int, user_id: int, now: float) -> None:
    history = _history(chat_id, user_id, float(now))
    history.append(float(now))


def chance(chat_id: int, user_id: int, now: float) -> float:
    """Prefer getting a first sticker into a long fight, then become stricter."""
    seen = count(chat_id, user_id, now)
    if seen <= 0:
        return 0.55
    if seen == 1:
        return 0.38
    return 0.0


def reset() -> None:
    _TIMES.clear()
