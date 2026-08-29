import sqlite3
from datetime import datetime
from types import SimpleNamespace

import daily_mood_engine
import daily_mood_runtime as mood_runtime


def _db_bot(tmp_path, now=None, mode="normal"):
    path = tmp_path / "mood.db"

    def get_db_connection():
        return sqlite3.connect(path)

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        current_msk_datetime=lambda: now or datetime(2026, 8, 20, 12, 0, 0),
        build_full_system_instruction=lambda *args, **kwargs: "BASE",
        detect_conversation_mode=lambda text: mode,
    )


def test_same_day_repeated_calls_return_identical_mood(tmp_path):
    bot = _db_bot(tmp_path)
    mood_runtime._initialize_table(bot)

    first = mood_runtime._ensure_today_mood_sync(bot, -100, "2026-08-20")
    second = mood_runtime._ensure_today_mood_sync(bot, -100, "2026-08-20")
    assert first == second


def test_new_date_can_reroll_independently(tmp_path):
    bot = _db_bot(tmp_path)
    mood_runtime._initialize_table(bot)

    mood_runtime._ensure_today_mood_sync(bot, -100, "2026-08-20")
    # A different chat_id/date row is independent bookkeeping either way.
    other_day = mood_runtime._ensure_today_mood_sync(bot, -100, "2026-08-21")
    assert other_day in {key for key, _ in daily_mood_engine.MOOD_POOL}


def test_ttl_sweep_removes_old_rows(tmp_path):
    bot = _db_bot(tmp_path)
    mood_runtime._initialize_table(bot)
    mood_runtime._ensure_today_mood_sync(bot, -100, "2026-01-01")

    mood_runtime._ensure_today_mood_sync(bot, -100, "2026-08-20")
    with bot.get_db_connection() as connection:
        dates = [
            row[0]
            for row in connection.execute(
                "SELECT date FROM chat_daily_mood WHERE chat_id = -100 ORDER BY date"
            ).fetchall()
        ]
    assert dates == ["2026-08-20"]


def test_instruction_wrap_ignores_private_chat(tmp_path):
    bot = _db_bot(tmp_path)
    mood_runtime._initialize_table(bot)
    mood_runtime._patch_instruction(bot)

    result = bot.build_full_system_instruction("привет", chat_id=1, chat_type="private")
    assert result == "BASE"


def test_instruction_wrap_ignores_missing_chat_id(tmp_path):
    bot = _db_bot(tmp_path)
    mood_runtime._initialize_table(bot)
    mood_runtime._patch_instruction(bot)

    result = bot.build_full_system_instruction("привет", chat_type="group")
    assert result == "BASE"


def test_instruction_wrap_skips_serious_topic(tmp_path):
    bot = _db_bot(tmp_path, mode="serious")
    mood_runtime._initialize_table(bot)
    mood_runtime._patch_instruction(bot)

    result = bot.build_full_system_instruction("умер дедушка", chat_id=-100, chat_type="group")
    assert result == "BASE"


def test_instruction_wrap_appends_mood_for_group_chat(tmp_path):
    bot = _db_bot(tmp_path)
    mood_runtime._initialize_table(bot)
    mood_runtime._patch_instruction(bot)

    result = bot.build_full_system_instruction("привет всем", chat_id=-100, chat_type="group")
    assert result.startswith("BASE")
    assert "CHAT MOOD LAYER" in result


def test_patch_instruction_guards_against_double_patch(tmp_path):
    bot = _db_bot(tmp_path)
    mood_runtime._initialize_table(bot)
    mood_runtime._patch_instruction(bot)
    wrapped_once = bot.build_full_system_instruction
    mood_runtime._patch_instruction(bot)
    assert bot.build_full_system_instruction is wrapped_once


def test_prepare_application_registers_once(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    calls = []
    monkeypatch.setattr(mood_runtime, "_find_bot_module", lambda: bot)
    monkeypatch.setattr(mood_runtime, "_initialize_table", lambda value: calls.append("table"))
    monkeypatch.setattr(mood_runtime, "_patch_instruction", lambda value: calls.append("instruction"))

    application = SimpleNamespace()
    mood_runtime._PREPARED_APPLICATION_IDS.discard(id(application))
    mood_runtime._prepare_application(application)
    mood_runtime._prepare_application(application)
    assert calls == ["table", "instruction"]
