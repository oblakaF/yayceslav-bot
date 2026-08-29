from datetime import datetime, timedelta, timezone

import reputation_decay_engine as decay


def test_zero_score_never_decays():
    assert decay.decayed_score(0, "2026-08-01 00:00:00", datetime(2026, 12, 1)) == 0


def test_missing_timestamp_is_a_noop():
    assert decay.decayed_score(50, None, datetime(2026, 8, 20)) == 50


def test_within_grace_period_is_untouched():
    now = datetime(2026, 8, 20, 12, 0, 0)
    updated_at = "2026-08-16 12:00:00"  # 4 days ago, inside the grace window
    assert decay.decayed_score(50, updated_at, now) == 50


def test_decays_linearly_after_grace_period():
    now = datetime(2026, 8, 20, 0, 0, 0)
    updated_at = "2026-08-10 00:00:00"  # 10 days elapsed, 5 grace -> 5 decayable days
    assert decay.decayed_score(50, updated_at, now) == 45


def test_negative_score_decays_toward_zero_not_past_it():
    now = datetime(2026, 8, 20, 0, 0, 0)
    updated_at = "2026-05-01 00:00:00"  # far beyond grace + lookback clamp
    assert decay.decayed_score(-3, updated_at, now) == 0


def test_lookback_is_clamped_so_ancient_rows_dont_overshoot():
    now = datetime(2026, 8, 20, 0, 0, 0)
    updated_at = "2025-01-01 00:00:00"  # hundreds of days elapsed
    assert decay.decayed_score(-100, updated_at, now) == 0
    assert decay.decayed_score(100, updated_at, now) == 0


def test_positive_score_fades_downward():
    now = datetime(2026, 8, 20, 0, 0, 0)
    updated_at = "2026-08-05 00:00:00"  # 15 elapsed, 10 decayable
    assert decay.decayed_score(8, updated_at, now) == 0


def test_sqlite_naive_utc_timestamp_works_with_aware_msk_clock():
    # Production SQLite datetime('now') is UTC without tzinfo while
    # current_msk_datetime() is timezone-aware UTC+3. They represent the same
    # timeline and must never raise the naive-vs-aware TypeError seen in Railway.
    msk = timezone(timedelta(hours=3))
    now = datetime(2026, 8, 20, 15, 0, 0, tzinfo=msk)  # 12:00 UTC
    updated_at = "2026-08-10 12:00:00"  # SQLite UTC, 10 elapsed days
    assert decay.decayed_score(50, updated_at, now) == 45


def test_aware_iso_timestamp_is_normalized_to_utc_too():
    now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    updated_at = "2026-08-10T15:00:00+03:00"  # exactly 2026-08-10 12:00 UTC
    assert decay.decayed_score(50, updated_at, now) == 45
