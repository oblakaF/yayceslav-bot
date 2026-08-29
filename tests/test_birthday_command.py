import asyncio
from types import SimpleNamespace

import bot
import birthday_runtime


def _make_update(
    *,
    chat_id=1,
    chat_type="group",
    user_id=1,
    full_name="Пользователь",
    username=None,
    reply_from=None,
):
    replies = []

    async def reply_text(text, *args, **kwargs):
        replies.append(text)

    reply_to_message = (
        SimpleNamespace(from_user=SimpleNamespace(**reply_from))
        if reply_from is not None
        else None
    )
    message = SimpleNamespace(
        reply_text=reply_text,
        replies=replies,
        reply_to_message=reply_to_message,
    )
    effective_chat = SimpleNamespace(id=chat_id, type=chat_type)
    effective_user = SimpleNamespace(
        id=user_id, full_name=full_name, username=username
    )
    return SimpleNamespace(
        message=message,
        effective_chat=effective_chat,
        effective_user=effective_user,
    )


def _make_context(args=None):
    return SimpleNamespace(args=args or [])


def _setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "birthday_command_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    birthday_runtime._initialize_table(bot)


def test_birthday_command_sets_own_birthday(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    update = _make_update(chat_id=10, user_id=1, full_name="Вася")
    context = _make_context(args=["05.09"])

    asyncio.run(bot.birthday_command(update, context))

    assert "05.09" in update.message.replies[0]
    stored = birthday_runtime.get_birthday_sync(bot, 10, 1)
    assert stored == {"display_name": "Вася", "month": 9, "day": 5}


def test_birthday_command_shows_own_birthday_when_no_args(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    birthday_runtime.set_birthday_sync(bot, 10, 1, "Вася", 9, 5, added_by_user_id=1)

    update = _make_update(chat_id=10, user_id=1)
    context = _make_context(args=[])

    asyncio.run(bot.birthday_command(update, context))

    assert "05.09" in update.message.replies[0]


def test_birthday_command_shows_usage_when_nothing_set(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    update = _make_update(chat_id=10, user_id=1)
    context = _make_context(args=[])

    asyncio.run(bot.birthday_command(update, context))

    assert "Как пользоваться" in update.message.replies[0]


def test_birthday_command_rejects_invalid_date(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    update = _make_update(chat_id=10, user_id=1)
    context = _make_context(args=["31.04"])

    asyncio.run(bot.birthday_command(update, context))

    assert "Не понял дату" in update.message.replies[0]
    assert birthday_runtime.get_birthday_sync(bot, 10, 1) is None


def test_birthday_command_sets_birthday_via_reply(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    update = _make_update(
        chat_id=10,
        user_id=1,
        reply_from={"id": 2, "full_name": "Другой Участник", "username": None},
    )
    context = _make_context(args=["20.10"])

    asyncio.run(bot.birthday_command(update, context))

    stored = birthday_runtime.get_birthday_sync(bot, 10, 2)
    assert stored == {"display_name": "Другой Участник", "month": 10, "day": 20}
    # Registrar (user 1) should not have gotten a birthday row themselves.
    assert birthday_runtime.get_birthday_sync(bot, 10, 1) is None


def test_birthday_command_sets_birthday_via_username_lookup(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    bot.touch_member_profile_sync(10, 2, "group", "Петя", "petya123")

    update = _make_update(chat_id=10, user_id=1)
    context = _make_context(args=["@petya123", "01.01"])

    asyncio.run(bot.birthday_command(update, context))

    stored = birthday_runtime.get_birthday_sync(bot, 10, 2)
    assert stored == {"display_name": "Петя", "month": 1, "day": 1}


def test_birthday_command_reports_unknown_username(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    update = _make_update(chat_id=10, user_id=1)
    context = _make_context(args=["@nobody", "01.01"])

    asyncio.run(bot.birthday_command(update, context))

    assert "Не нашёл" in update.message.replies[0]


def test_birthday_command_prompts_for_date_after_bare_username(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    update = _make_update(chat_id=10, user_id=1)
    context = _make_context(args=["@petya123"])

    asyncio.run(bot.birthday_command(update, context))

    assert "Как пользоваться" in update.message.replies[0]
