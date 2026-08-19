import sqlite3
from datetime import datetime
from types import SimpleNamespace

from telegram.ext import Application, MessageHandler

import positive_runtime as runtime


def _db_bot(tmp_path):
    path = tmp_path / "positive.db"

    def get_db_connection():
        return sqlite3.connect(path)

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        current_msk_datetime=lambda: datetime(2026, 8, 20, 1, 0, 0),
        build_full_system_instruction=lambda *args, **kwargs: "BASE",
        detect_conversation_mode=lambda text: "normal",
        is_serious_text=lambda text: False,
    )


def test_positive_tables_and_daily_reward_caps(tmp_path):
    bot = _db_bot(tmp_path)
    runtime._initialize_tables(bot)

    rewarded = [
        runtime._record_event_sync(bot, 10, 20, "2026-08-20", "praise")
        for _ in range(5)
    ]
    assert rewarded == [True, True, True, False, False]

    state = runtime._state_sync(bot, 10, 20, "2026-08-20")
    assert state.praise_events_30d == 5
    assert state.affinity_points_30d == 3
    assert state.positive_streak == 3
    assert state.max_streak_30d == 3


def test_directed_hostility_resets_streak_but_not_earned_affinity(tmp_path):
    bot = _db_bot(tmp_path)
    runtime._initialize_tables(bot)
    runtime._record_event_sync(bot, 1, 2, "2026-08-20", "affection")
    runtime._record_event_sync(bot, 1, 2, "2026-08-20", "achievement")

    before = runtime._state_sync(bot, 1, 2, "2026-08-20")
    assert before.positive_streak == 2
    assert before.affinity_points_30d == 4

    runtime._reset_streak_sync(bot, 1, 2)
    after = runtime._state_sync(bot, 1, 2, "2026-08-20")
    assert after.positive_streak == 0
    assert after.affinity_points_30d == 4
    assert after.max_streak_30d == 2


def test_affinity_window_is_last_30_calendar_days(tmp_path):
    bot = _db_bot(tmp_path)
    runtime._initialize_tables(bot)
    runtime._record_event_sync(bot, 1, 2, "2026-07-20", "achievement")
    runtime._record_event_sync(bot, 1, 2, "2026-08-01", "achievement")
    runtime._record_event_sync(bot, 1, 2, "2026-08-20", "achievement")

    state = runtime._state_sync(bot, 1, 2, "2026-08-20")
    assert state.achievement_events_30d == 2
    assert state.affinity_points_30d == 4


def test_instruction_patch_celebrates_real_success(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    runtime._initialize_tables(bot)
    runtime._record_event_sync(bot, 1, 2, "2026-08-20", "achievement")
    monkeypatch.setattr(runtime, "_latest_user_text", lambda contents: str(contents or ""))

    runtime._patch_build_instruction(bot)
    result = bot.build_full_system_instruction(
        "я сдал экзамен",
        chat_id=1,
        user_id=2,
    )
    assert result.startswith("BASE")
    assert "POSITIVE/SOCIAL LAYER" in result
    assert "реальным успехом" in result
    assert "Не хвали без реального повода" in result


def test_prepare_application_registers_group9_once(monkeypatch):
    fake_bot = object()
    calls = []
    monkeypatch.setattr(runtime, "_find_bot_module", lambda: fake_bot)
    monkeypatch.setattr(runtime, "_initialize_tables", lambda bot: calls.append(("init", bot)))
    monkeypatch.setattr(runtime, "_patch_build_instruction", lambda bot: calls.append(("patch", bot)))

    application = Application.builder().token("123456:TESTTOKEN").build()
    runtime._PREPARED_APPLICATION_IDS.discard(id(application))
    runtime._prepare_application(application)
    runtime._prepare_application(application)

    assert calls == [("init", fake_bot), ("patch", fake_bot)]
    handlers = application.handlers.get(9, ())
    assert len(handlers) == 1
    assert isinstance(handlers[0], MessageHandler)
    assert handlers[0].callback is runtime._observe_positive


def test_relationship_snapshot_is_safe_when_legacy_table_is_absent(tmp_path):
    bot = _db_bot(tmp_path)
    runtime._initialize_tables(bot)
    assert runtime._relationship_snapshot_sync(bot, 1, 2, "2026-08-20") == {
        "active_insults": 0,
        "forgiveness_count": 0,
        "penance_pending": 0,
    }
