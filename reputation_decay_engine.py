"""Pure decay-toward-neutral math for lifetime reputation scores.

Reputation should not be a permanent tattoo: an old grudge or an old
compliment both fade a little if nothing has happened since. Decay only
ever moves the score toward zero, never past it, and never while the
score is still "fresh" (touched within the grace window).

SQLite ``datetime('now')`` timestamps are UTC but carry no timezone suffix.
Normalize both stored timestamps and the caller's clock to UTC before doing
arithmetic so an aware MSK clock can never be subtracted from a naive SQLite
datetime.
"""

from __future__ import annotations

from datetime import datetime, timezone

DECAY_GRACE_DAYS = 5
DECAY_RATE_PER_DAY = 1
DECAY_MAX_LOOKBACK_DAYS = 120


def _as_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime; naive values are SQLite-style UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def decayed_score(score: int, updated_at_iso: str | None, now: datetime) -> int:
    value = int(score or 0)
    if value == 0 or not updated_at_iso:
        return value
    try:
        updated_at = datetime.fromisoformat(str(updated_at_iso))
    except ValueError:
        return value

    elapsed_days = (_as_utc(now) - _as_utc(updated_at)).total_seconds() / 86400
    if elapsed_days <= DECAY_GRACE_DAYS:
        return value

    decayable_days = min(elapsed_days - DECAY_GRACE_DAYS, DECAY_MAX_LOOKBACK_DAYS)
    reduction = min(abs(value), int(decayable_days * DECAY_RATE_PER_DAY))
    if reduction <= 0:
        return value
    return value - reduction if value > 0 else value + reduction
