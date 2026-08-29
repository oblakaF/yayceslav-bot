import sqlite3

import bot


def _create_main_schema(db_path):
    """Создаёт схему production/main до появления V2-таблиц и миграций."""

    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE stats (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY
            );

            CREATE TABLE chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL
            );

            CREATE TABLE user_settings (
                user_id INTEGER PRIMARY KEY,
                character TEXT NOT NULL DEFAULT 'classic',
                response_style TEXT NOT NULL DEFAULT 'bold',
                response_length TEXT NOT NULL DEFAULT 'normal',
                voice_enabled INTEGER NOT NULL DEFAULT 0,
                search_mode TEXT NOT NULL DEFAULT 'button',
                roughness TEXT NOT NULL DEFAULT 'medium'
            );
            """
        )

        connection.execute(
            "INSERT INTO stats (name, value) VALUES (?, ?)",
            ("total_requests", 123),
        )
        connection.execute(
            "INSERT INTO users (user_id) VALUES (?)",
            (42,),
        )
        connection.execute(
            "INSERT INTO chats (chat_id, chat_type) VALUES (?, ?)",
            (-100500, "supergroup"),
        )
        connection.execute(
            """
            INSERT INTO user_settings (
                user_id,
                character,
                response_style,
                response_length,
                voice_enabled,
                search_mode,
                roughness
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "professor",
                "serious",
                "detailed",
                1,
                "auto",
                "low",
            ),
        )
        connection.commit()


def test_v2_migrates_main_database_without_losing_data(tmp_path, monkeypatch):
    db_path = tmp_path / "production-main.db"
    _create_main_schema(db_path)

    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT value FROM stats WHERE name = 'total_requests'"
        ).fetchone() == (123,)
        assert connection.execute(
            "SELECT chat_type FROM chats WHERE chat_id = -100500"
        ).fetchone() == ("supergroup",)
        assert connection.execute(
            """
            SELECT
                character,
                response_style,
                response_length,
                voice_enabled,
                search_mode,
                roughness
            FROM user_settings
            WHERE user_id = 42
            """
        ).fetchone() == (
            "professor",
            "serious",
            "detailed",
            1,
            "auto",
            "low",
        )

        user_setting_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(user_settings)")
        }
        assert "custom_nickname" in user_setting_columns

        chat_setting_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(chat_settings)")
        }
        assert {
            "reactions_count",
            "random_replies_count",
            "trigger_replies_count",
            "last_intervention_at",
            "weekly_report_enabled",
            "weekly_report_weekday",
            "weekly_report_time",
            "weekly_report_last_sent_date",
        } <= chat_setting_columns

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "chat_settings",
            "chat_member_profiles",
            "chat_activity_daily",
            "weekly_award_winners",
            "daily_title_assignments",
        } <= tables

    settings = bot.get_user_settings_sync(42)
    assert settings == {
        "character": "professor",
        "response_style": "serious",
        "response_length": "detailed",
        "voice_enabled": True,
        "search_mode": "auto",
        "roughness": "low",
        "custom_nickname": None,
    }
