import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import birthday_runtime


def _db_bot(tmp_path, now=None):
    path = tmp_path / "birthday.db"

    def get_db_connection():
        return sqlite3.connect(path)

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        current_msk_datetime=lambda: now or datetime(2026, 9, 5, 10, 0, 0),
    )


def _with_chat_member_profiles(bot):
    with bot.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE chat_member_profiles (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                current_display_name TEXT,
                username TEXT,
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        connection.commit()
    return bot


def test_set_and_get_birthday_round_trips(tmp_path):
    bot = _db_bot(tmp_path)
    birthday_runtime._initialize_table(bot)

    birthday_runtime.set_birthday_sync(bot, -100, 1, "Вася", 9, 5, added_by_user_id=1)
    result = birthday_runtime.get_birthday_sync(bot, -100, 1)

    assert result == {"display_name": "Вася", "month": 9, "day": 5}


def test_get_birthday_returns_none_when_not_set(tmp_path):
    bot = _db_bot(tmp_path)
    birthday_runtime._initialize_table(bot)
    assert birthday_runtime.get_birthday_sync(bot, -100, 1) is None


def test_set_birthday_upserts_and_resets_greeted_year(tmp_path):
    bot = _db_bot(tmp_path)
    birthday_runtime._initialize_table(bot)

    birthday_runtime.set_birthday_sync(bot, -100, 1, "Вася", 9, 5, added_by_user_id=1)
    birthday_runtime._mark_greeted_sync(bot, -100, 1, 2026)

    # Re-registering (e.g. a correction) should clear the old greeted-year
    # mark so a changed date is reconsidered by the due-check.
    birthday_runtime.set_birthday_sync(bot, -100, 1, "Вася", 10, 20, added_by_user_id=1)
    result = birthday_runtime.get_birthday_sync(bot, -100, 1)
    assert result == {"display_name": "Вася", "month": 10, "day": 20}

    due = birthday_runtime._birthdays_due_sync(bot, datetime(2026, 10, 20, 10, 0, 0))
    assert due == [{"chat_id": -100, "user_id": 1, "display_name": "Вася"}]


def test_resolve_member_by_username_finds_case_insensitive_match(tmp_path):
    bot = _with_chat_member_profiles(_db_bot(tmp_path))
    with bot.get_db_connection() as connection:
        connection.execute(
            "INSERT INTO chat_member_profiles (chat_id, user_id, current_display_name, username) "
            "VALUES (-100, 42, 'Петя', 'PetyaTheGreat')"
        )
        connection.commit()

    result = birthday_runtime.resolve_member_by_username_sync(bot, -100, "@petyathegreat")
    assert result == {"user_id": 42, "display_name": "Петя"}


def test_resolve_member_by_username_returns_none_when_unknown(tmp_path):
    bot = _with_chat_member_profiles(_db_bot(tmp_path))
    assert birthday_runtime.resolve_member_by_username_sync(bot, -100, "@nobody") is None


def test_birthdays_due_only_returns_todays_matches_not_yet_greeted(tmp_path):
    bot = _db_bot(tmp_path)
    birthday_runtime._initialize_table(bot)
    birthday_runtime.set_birthday_sync(bot, -100, 1, "Сегодня", 9, 5, added_by_user_id=1)
    birthday_runtime.set_birthday_sync(bot, -100, 2, "Другой день", 1, 1, added_by_user_id=1)

    due = birthday_runtime._birthdays_due_sync(bot, datetime(2026, 9, 5, 10, 0, 0))
    assert due == [{"chat_id": -100, "user_id": 1, "display_name": "Сегодня"}]


def test_birthdays_due_excludes_already_greeted_this_year(tmp_path):
    bot = _db_bot(tmp_path)
    birthday_runtime._initialize_table(bot)
    birthday_runtime.set_birthday_sync(bot, -100, 1, "Вася", 9, 5, added_by_user_id=1)
    birthday_runtime._mark_greeted_sync(bot, -100, 1, 2026)

    due = birthday_runtime._birthdays_due_sync(bot, datetime(2026, 9, 5, 10, 0, 0))
    assert due == []

    # But a NEW year should be greeted again.
    due_next_year = birthday_runtime._birthdays_due_sync(bot, datetime(2027, 9, 5, 10, 0, 0))
    assert due_next_year == [{"chat_id": -100, "user_id": 1, "display_name": "Вася"}]


def test_birthday_due_checks_the_greeting_hour_window():
    assert birthday_runtime.birthday_due(datetime(2026, 9, 5, 10, 0, 0)) is True
    assert birthday_runtime.birthday_due(datetime(2026, 9, 5, 9, 59, 0)) is False
    assert birthday_runtime.birthday_due(datetime(2026, 9, 5, 11, 0, 0)) is False


def test_run_birthday_greetings_sends_mention_and_marks_greeted(tmp_path):
    bot = _db_bot(tmp_path)
    birthday_runtime._initialize_table(bot)
    birthday_runtime.set_birthday_sync(bot, -100, 1, "Вася", 9, 5, added_by_user_id=1)

    sent = []

    class FakeTelegramBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)

    application = SimpleNamespace(bot=FakeTelegramBot())

    import birthday_runtime as module

    orig_find = module._find_bot_module
    module._find_bot_module = lambda: bot
    try:
        asyncio.run(module.run_birthday_greetings_if_due(application))
    finally:
        module._find_bot_module = orig_find

    assert len(sent) == 1
    assert sent[0]["chat_id"] == -100
    assert sent[0]["parse_mode"] == "HTML"
    assert 'tg://user?id=1"' in sent[0]["text"]
    assert "Вася" in sent[0]["text"]

    # Second run the same day must not re-send.
    module._find_bot_module = lambda: bot
    try:
        asyncio.run(module.run_birthday_greetings_if_due(application))
    finally:
        module._find_bot_module = orig_find
    assert len(sent) == 1


def test_run_birthday_greetings_skips_outside_the_due_hour(tmp_path):
    bot = _db_bot(tmp_path, now=datetime(2026, 9, 5, 14, 0, 0))
    birthday_runtime._initialize_table(bot)
    birthday_runtime.set_birthday_sync(bot, -100, 1, "Вася", 9, 5, added_by_user_id=1)

    sent = []

    class FakeTelegramBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)

    application = SimpleNamespace(bot=FakeTelegramBot())

    import birthday_runtime as module

    orig_find = module._find_bot_module
    module._find_bot_module = lambda: bot
    try:
        asyncio.run(module.run_birthday_greetings_if_due(application))
    finally:
        module._find_bot_module = orig_find

    assert sent == []


def test_patch_scheduler_chains_after_original_and_guards_double_patch(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    calls = []

    async def original(application):
        del application
        calls.append("original")

    async def fake_greetings(application):
        del application
        calls.append("birthday")

    monkeypatch.setattr(birthday_runtime, "run_birthday_greetings_if_due", fake_greetings)

    bot.run_due_daily_titles = original
    bot._yayceslav_birthday_patch = False

    birthday_runtime._patch_scheduler(bot)
    wrapped_once = bot.run_due_daily_titles
    birthday_runtime._patch_scheduler(bot)
    assert bot.run_due_daily_titles is wrapped_once

    asyncio.run(bot.run_due_daily_titles(SimpleNamespace()))
    assert calls == ["original", "birthday"]


def test_prepare_application_registers_once(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    calls = []
    monkeypatch.setattr(birthday_runtime, "_find_bot_module", lambda: bot)
    monkeypatch.setattr(birthday_runtime, "_initialize_table", lambda value: calls.append("table"))
    monkeypatch.setattr(birthday_runtime, "_patch_scheduler", lambda value: calls.append("scheduler"))

    application = SimpleNamespace()
    birthday_runtime._PREPARED_APPLICATION_IDS.discard(id(application))
    birthday_runtime._prepare_application(application)
    birthday_runtime._prepare_application(application)
    assert calls == ["table", "scheduler"]
