import asyncio
from datetime import datetime, timedelta, timezone

import bot


MSK = timezone(timedelta(hours=3))


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "daily-title.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    return db_path


def _seed_member(chat_id: int, user_id: int, name: str, date: str):
    with bot.get_db_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, 'group')",
            (chat_id,),
        )
        connection.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_member_profiles
                (chat_id, user_id, current_display_name)
            VALUES (?, ?, ?)
            """,
            (chat_id, user_id, name),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_activity_daily
                (chat_id, user_id, date, messages)
            VALUES (?, ?, ?, 1)
            """,
            (chat_id, user_id, date),
        )
        connection.commit()


def test_daily_title_replaces_previous_title(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -1001
    user_id = 42
    _seed_member(chat_id, user_id, "Петя", "2026-08-16")

    assert bot.try_assign_daily_title_sync(
        chat_id, "2026-08-16", user_id, "Первый титул"
    )
    assert bot.try_assign_daily_title_sync(
        chat_id, "2026-08-17", user_id, "Второй титул"
    )

    profile = bot.get_member_profile_sync(chat_id, user_id)
    assert profile is not None
    assert profile["current_title"] == "Второй титул"

    with bot.get_db_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM daily_title_assignments WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()[0]
    assert count == 2  # история дней есть, но current_title у человека ровно один


class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))


class _FakeApplication:
    def __init__(self):
        self.bot = _FakeBot()


def test_scheduler_assigns_even_when_hard_mode_is_off(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -2002
    user_id = 77
    date = "2026-08-16"
    _seed_member(chat_id, user_id, "Вася", date)

    bot.update_chat_setting_sync(chat_id, "hard_mode_enabled", False, "group")
    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 16, 19, 5, tzinfo=MSK),
    )
    monkeypatch.setattr(bot, "pick_new_title", lambda previous: "Титул теста")

    app = _FakeApplication()
    asyncio.run(bot.run_due_daily_titles(app))

    assert len(app.bot.messages) == 1
    assert "Вася" in app.bot.messages[0][1]
    assignment = bot.get_daily_title_assignment_sync(chat_id, date)
    assert assignment is not None
    assert assignment["announced_at"] is not None
    profile = bot.get_member_profile_sync(chat_id, user_id)
    assert profile["current_title"] == "Титул теста"

    # Повторная минутная проверка не должна отправить второй титул.
    asyncio.run(bot.run_due_daily_titles(app))
    assert len(app.bot.messages) == 1


def test_failed_announcement_retries_same_winner(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -3003
    user_id = 88
    date = "2026-08-16"
    _seed_member(chat_id, user_id, "Коля", date)

    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 16, 19, 10, tzinfo=MSK),
    )
    monkeypatch.setattr(bot, "pick_new_title", lambda previous: "Несменяемый победитель")

    class FlakyBot:
        def __init__(self):
            self.calls = 0
            self.messages = []

        async def send_message(self, *, chat_id, text):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("network")
            self.messages.append((chat_id, text))

    app = _FakeApplication()
    app.bot = FlakyBot()

    asyncio.run(bot.run_due_daily_titles(app))
    first = bot.get_daily_title_assignment_sync(chat_id, date)
    assert first is not None
    assert first["user_id"] == user_id
    assert first["announced_at"] is None

    asyncio.run(bot.run_due_daily_titles(app))
    second = bot.get_daily_title_assignment_sync(chat_id, date)
    assert second["user_id"] == first["user_id"]
    assert second["title"] == first["title"]
    assert second["announced_at"] is not None
    assert len(app.bot.messages) == 1


def test_chat_settings_expose_weekly_schedule(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -4004
    bot.update_chat_setting_sync(chat_id, "weekly_report_enabled", True, "group")
    bot.update_chat_setting_sync(chat_id, "weekly_report_weekday", 5, "group")
    bot.update_chat_setting_sync(chat_id, "weekly_report_time", "20:30", "group")

    settings = bot.get_chat_settings_sync(chat_id, "group")
    assert settings["weekly_report_enabled"] is True
    assert settings["weekly_report_weekday"] == 5
    assert settings["weekly_report_time"] == "20:30"
    assert "weekly_report_last_sent_date" in settings
