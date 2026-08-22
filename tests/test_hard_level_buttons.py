import asyncio
from types import SimpleNamespace

import bot


def _make_message_update(chat_type="group"):
    message = SimpleNamespace(replies=[], markups=[])

    async def reply_text(text, *args, **kwargs):
        message.replies.append(text)
        message.markups.append(kwargs.get("reply_markup"))

    message.reply_text = reply_text
    return SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(id=1, type=chat_type),
        effective_user=SimpleNamespace(id=1),
    )


def _make_admin_context(is_admin, args=None):
    async def get_chat_member(chat_id, user_id):
        status = "administrator" if is_admin else "member"
        return SimpleNamespace(status=status)

    bot_stub = SimpleNamespace(get_chat_member=get_chat_member)
    return SimpleNamespace(args=args or [], bot=bot_stub)


def test_hard_level_with_no_args_offers_buttons_instead_of_free_text():
    update = _make_message_update()
    context = _make_admin_context(is_admin=True)

    asyncio.run(bot.hard_level_command(update, context))

    assert "Выбери уровень хард-мода" in update.message.replies[0]
    markup = update.message.markups[0]
    callback_datas = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    }
    assert callback_datas == {
        "hard_level:calm",
        "hard_level:normal",
        "hard_level:chaos",
    }


def test_hard_level_still_accepts_typed_argument(tmp_path, monkeypatch):
    db_path = tmp_path / "hard_level_typed.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    update = _make_message_update()
    context = _make_admin_context(is_admin=True, args=["chaos"])

    asyncio.run(bot.hard_level_command(update, context))

    settings = bot.get_chat_settings_sync(1, "group")
    assert settings["hard_level"] == "chaos"
    assert update.message.replies[-1] == bot.HARD_LEVEL_REPLIES["chaos"]


def _make_callback_update(level: str, chat_type="group"):
    message = SimpleNamespace(edits=[])

    async def edit_text(text, *args, **kwargs):
        message.edits.append(text)

    message.edit_text = edit_text

    query = SimpleNamespace(
        data=f"hard_level:{level}",
        answers=[],
    )

    async def answer(text=None, show_alert=False):
        query.answers.append((text, show_alert))

    query.answer = answer

    return SimpleNamespace(
        callback_query=query,
        effective_message=message,
        effective_chat=SimpleNamespace(id=1, type=chat_type),
        effective_user=SimpleNamespace(id=1),
    )


def test_button_callback_applies_level_when_admin(tmp_path, monkeypatch):
    db_path = tmp_path / "hard_level_button.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    update = _make_callback_update("calm")
    context = _make_admin_context(is_admin=True)

    asyncio.run(bot.hard_level_button_callback(update, context))

    settings = bot.get_chat_settings_sync(1, "group")
    assert settings["hard_level"] == "calm"
    assert update.effective_message.edits == [bot.HARD_LEVEL_REPLIES["calm"]]
    assert update.callback_query.answers == [(None, False)]


def test_button_callback_rejects_non_admin(tmp_path, monkeypatch):
    db_path = tmp_path / "hard_level_non_admin.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    update = _make_callback_update("chaos")
    context = _make_admin_context(is_admin=False)

    asyncio.run(bot.hard_level_button_callback(update, context))

    settings = bot.get_chat_settings_sync(1, "group")
    assert settings["hard_level"] != "chaos"
    assert update.effective_message.edits == []
    assert update.callback_query.answers[0][1] is True  # show_alert


def test_button_callback_rejects_unknown_level(tmp_path, monkeypatch):
    db_path = tmp_path / "hard_level_unknown.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    update = _make_callback_update("nonsense")
    context = _make_admin_context(is_admin=True)

    asyncio.run(bot.hard_level_button_callback(update, context))

    assert update.effective_message.edits == []
    assert update.callback_query.answers[0][1] is True


def test_button_callback_ignores_private_chat():
    update = _make_callback_update("calm", chat_type="private")
    context = _make_admin_context(is_admin=True)

    asyncio.run(bot.hard_level_button_callback(update, context))

    assert update.effective_message.edits == []
    assert update.callback_query.answers == [(None, False)]
