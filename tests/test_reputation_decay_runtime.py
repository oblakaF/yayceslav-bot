import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

import reputation_decay_runtime as decay_runtime
import reputation_runtime as lifetime


def _db_bot(tmp_path, now_holder):
    path = tmp_path / "decay_runtime.db"

    def get_db_connection():
        return sqlite3.connect(path)

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        current_msk_datetime=lambda: now_holder["now"],
    )


def _fresh_bot(tmp_path, now_holder):
    bot = _db_bot(tmp_path, now_holder)
    lifetime._initialize_table(bot)
    return bot


def _set_updated_at(bot, chat_id: int, user_id: int, iso: str) -> None:
    # _apply_delta_sync stamps updated_at with SQLite's own real-clock
    # datetime('now'), independent of the bot's mocked current_msk_datetime.
    # Tests need a fixed, known updated_at to compute decay deterministically.
    with bot.get_db_connection() as connection:
        connection.execute(
            "UPDATE member_reputation SET updated_at = ? WHERE chat_id = ? AND user_id = ?",
            (iso, chat_id, user_id),
        )
        connection.commit()


@pytest.fixture
def isolated_state_sync_patch():
    """Patch reputation_runtime._state_sync for one test only, then restore it.

    reputation_runtime is a shared module singleton; leaving the patch
    applied after a test would silently affect every other test that
    imports reputation_runtime for the rest of the suite.
    """
    original = lifetime._state_sync
    had_guard = hasattr(lifetime, "_yayceslav_reputation_decay_patch")
    try:
        yield
    finally:
        lifetime._state_sync = original
        if not had_guard and hasattr(lifetime, "_yayceslav_reputation_decay_patch"):
            del lifetime._yayceslav_reputation_decay_patch


def test_apply_decay_leaves_fresh_row_untouched(tmp_path):
    now_holder = {"now": datetime(2026, 8, 20, 12, 0, 0)}
    bot = _fresh_bot(tmp_path, now_holder)
    lifetime._apply_delta_sync(bot, 1, 2, 9, "positive")
    _set_updated_at(bot, 1, 2, "2026-08-20 12:00:00")

    decay_runtime._apply_decay_sync(bot, 1, 2)
    assert lifetime._state_sync(bot, 1, 2)["score"] == 9


def test_apply_decay_reduces_stale_negative_score(tmp_path):
    now_holder = {"now": datetime(2026, 8, 21, 0, 0, 0)}
    bot = _fresh_bot(tmp_path, now_holder)
    lifetime._apply_delta_sync(bot, 1, 2, -10, "negative")
    _set_updated_at(bot, 1, 2, "2026-08-11 00:00:00")  # 10 days elapsed, 5 decayable

    decay_runtime._apply_decay_sync(bot, 1, 2)
    assert lifetime._state_sync(bot, 1, 2)["score"] == -5


def test_apply_decay_positive_score_also_fades(tmp_path):
    now_holder = {"now": datetime(2026, 8, 21, 0, 0, 0)}
    bot = _fresh_bot(tmp_path, now_holder)
    lifetime._apply_delta_sync(bot, 1, 2, 10, "positive")
    _set_updated_at(bot, 1, 2, "2026-08-11 00:00:00")

    decay_runtime._apply_decay_sync(bot, 1, 2)
    assert lifetime._state_sync(bot, 1, 2)["score"] == 5


def test_apply_decay_same_now_is_idempotent(tmp_path):
    now_holder = {"now": datetime(2026, 8, 21, 0, 0, 0)}
    bot = _fresh_bot(tmp_path, now_holder)
    lifetime._apply_delta_sync(bot, 1, 2, -10, "negative")
    _set_updated_at(bot, 1, 2, "2026-08-11 00:00:00")

    decay_runtime._apply_decay_sync(bot, 1, 2)
    first = lifetime._state_sync(bot, 1, 2)["score"]
    # The write-back stamps a fresh updated_at (SQLite real-clock "now"), so a
    # second pass at the same mocked "now" must not decay it any further.
    decay_runtime._apply_decay_sync(bot, 1, 2)
    second = lifetime._state_sync(bot, 1, 2)["score"]
    assert first == second == -5


def test_apply_decay_on_missing_member_is_a_noop(tmp_path):
    now_holder = {"now": datetime(2026, 8, 20, 0, 0, 0)}
    bot = _fresh_bot(tmp_path, now_holder)
    decay_runtime._apply_decay_sync(bot, 1, 2)  # must not raise
    assert lifetime._state_sync(bot, 1, 2)["score"] == 0


def test_patch_state_sync_applies_decay_transparently(tmp_path, isolated_state_sync_patch):
    now_holder = {"now": datetime(2026, 8, 21, 0, 0, 0)}
    bot = _fresh_bot(tmp_path, now_holder)
    lifetime._apply_delta_sync(bot, 1, 2, -10, "negative")
    _set_updated_at(bot, 1, 2, "2026-08-11 00:00:00")

    decay_runtime._patch_state_sync(lifetime)
    assert lifetime._state_sync(bot, 1, 2)["score"] == -5


def test_patch_state_sync_guards_against_double_patch(tmp_path, isolated_state_sync_patch):
    now_holder = {"now": datetime(2026, 8, 21, 0, 0, 0)}
    bot = _fresh_bot(tmp_path, now_holder)
    lifetime._apply_delta_sync(bot, 1, 2, -10, "negative")
    _set_updated_at(bot, 1, 2, "2026-08-11 00:00:00")

    decay_runtime._patch_state_sync(lifetime)
    wrapped_once = lifetime._state_sync
    decay_runtime._patch_state_sync(lifetime)
    assert lifetime._state_sync is wrapped_once
