from pathlib import Path

import bot
import feedback_engine


def test_persistent_state_survives_reinitialization(tmp_path, monkeypatch):
    db_path = tmp_path / "railway-volume" / "yayceslav_stats.db"
    db_path.parent.mkdir(parents=True)
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)

    bot.initialize_stats_database()

    chat_id = -100777
    user_id = 777
    bot.update_chat_setting_sync(chat_id, "hard_mode_enabled", False, "group")
    bot.update_chat_setting_sync(chat_id, "weekly_report_enabled", True, "group")

    with bot.get_db_connection() as connection:
        connection.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        connection.execute(
            "INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, 'group')",
            (chat_id,),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_native_profiles
                (chat_id, terms_json, distinct_users, compiled_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (chat_id, '["локалмем", "хуйприставка"]', 4),
        )
        connection.commit()

    trace = feedback_engine.ResponseTrace(
        chat_id=chat_id,
        chat_type="group",
        voice_pack="blat",
        humor_type="layered_taunt",
        verdict_used=False,
    )
    bot.store_bot_response_feedback_sync(chat_id, 12345, trace)
    assert bot.apply_bot_reaction_delta_sync(chat_id, 12345, 1.0, 1)

    # Simulate a fresh container/process opening the same mounted SQLite file.
    bot.initialize_stats_database()

    settings = bot.get_chat_settings_sync(chat_id, "group")
    assert settings["hard_mode_enabled"] is False
    assert settings["weekly_report_enabled"] is True

    profile = bot.get_chat_native_profile_sync(chat_id)
    assert profile["terms"] == ["локалмем", "хуйприставка"]
    assert profile["distinct_users"] == 4

    adaptation = bot.get_chat_feedback_adaptation_sync(chat_id)
    assert adaptation["pack_multipliers"]["blat"] > 1.0

    with bot.get_db_connection() as connection:
        row = connection.execute(
            "SELECT reaction_score, reaction_count FROM bot_response_feedback "
            "WHERE chat_id = ? AND message_id = ?",
            (chat_id, 12345),
        ).fetchone()
    assert row == (1.0, 1)


def test_all_persistent_feature_tables_exist_after_cold_init(tmp_path, monkeypatch):
    db_path = tmp_path / "cold.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    with bot.get_db_connection() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert {
        "chat_settings",
        "chat_member_profiles",
        "chat_activity_daily",
        "weekly_award_winners",
        "daily_title_assignments",
        "chat_native_terms",
        "chat_native_term_users",
        "chat_native_profiles",
        "bot_response_feedback",
    } <= tables


def test_startup_reschedules_all_background_loops():
    names = []

    class FakeApplication:
        def create_task(self, coro, *, name=None):
            names.append(name)
            coro.close()
            return None

    import asyncio

    asyncio.run(bot.on_application_startup(FakeApplication()))
    assert set(names) == {
        "periodic_cleanup",
        "weekly_report_scheduler",
        "daily_title_scheduler",
        "chat_native_refresh",
    }


def test_polling_configuration_keeps_reaction_updates_enabled():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "UpdateType.MESSAGE_REACTION" in source
    assert "drop_pending_updates=True" in source
