"""Pure decay-toward-neutral math for lifetime reputation scores.

Reputation should not be a permanent tattoo: an old grudge or an old
compliment both fade a little if nothing has happened since. Decay only
ever moves the score toward zero, never past it, and never while the
score is still "fresh" (touched within the grace window).
"""

from __future__ import annotations

from datetime import datetime

DECAY_GRACE_DAYS = 5
DECAY_RATE_PER_DAY = 1
DECAY_MAX_LOOKBACK_DAYS = 120


def decayed_score(score: int, updated_at_iso: str | None, now: datetime) -> int:
    value = int(score or 0)
    if value == 0 or not updated_at_iso:
        return value
    try:
        updated_at = datetime.fromisoformat(str(updated_at_iso))
    except ValueError:
        return value

    elapsed_days = (now - updated_at).total_seconds() / 86400
    if elapsed_days <= DECAY_GRACE_DAYS:
        return value

    decayable_days = min(elapsed_days - DECAY_GRACE_DAYS, DECAY_MAX_LOOKBACK_DAYS)
    reduction = min(abs(value), int(decayable_days * DECAY_RATE_PER_DAY))
    if reduction <= 0:
        return value
    return value - reduction if value > 0 else value + reduction
