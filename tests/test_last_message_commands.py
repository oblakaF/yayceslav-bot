import asyncio
import time
from types import SimpleNamespace

import bot


def _make_update(
    text=None,
    reply_text=None,
    chat_id=1,
    chat_type="group",
    user_id=1,
):
    reply_to_message = (
        SimpleNamespace(text=reply_text)
        if reply_text is not None
        else None
    )
    message = SimpleNamespace(
        text=text,
        reply_to_message=reply_to_message,
    )
    effective_chat = SimpleNamespace(id=chat_id, type=chat_type)
    effective_user = SimpleNamespace(id=user_id)
    return SimpleNamespace(
        message=message,
        effective_chat=effective_chat,
        effective_user=effective_user,
    )


def _make_context(args=None):
    return SimpleNamespace(args=args or [])


def test_resolve_topic_text_prefers_reply():
    update = _make_update(reply_text="ответная тема")
    context = _make_context(args=["игнорируется"])
    result = asyncio.run(bot.resolve_topic_text(update, context))
    assert result == "ответная тема"


def test_resolve_topic_text_falls_back_to_args():
    update = _make_update()
    context = _make_context(args=["текст", "после", "команды"])
    result = asyncio.run(bot.resolve_topic_text(update, context))
    assert result == "текст после команды"


def test_resolve_topic_text_falls_back_to_own_last_message():
    chat_id, user_id = 555201, 1
    bot.record_last_user_message(chat_id, user_id, "земля")

    update = _make_update(chat_id=chat_id, user_id=user_id)
    context = _make_context()
    result = asyncio.run(bot.resolve_topic_text(update, context))

    assert result == "земля"


def test_resolve_topic_text_chat_scope_uses_group_memory_for_judge():
    chat_id = 555202
    bot.GROUP_MEMORY[chat_id].clear()
    bot.remember_message(
        bot.GROUP_MEMORY,
        chat_id,
        "user",
        "тема из чата",
        bot.GROUP_MEMORY_SECONDS,
        bot.GROUP_MEMORY_MAX_MESSAGES,
        "Другой участник",
    )

    # Different user with no "own" last message of their own.
    update = _make_update(chat_id=chat_id, user_id=99999)
    context = _make_context()
    result = asyncio.run(
        bot.resolve_topic_text(update, context, fallback_scope="chat")
    )

    assert result == "тема из чата"


def test_resolve_topic_text_chat_scope_degrades_to_own_in_private():
    chat_id, user_id = 555203, 1
    bot.record_last_user_message(chat_id, user_id, "личная тема")

    update = _make_update(
        chat_id=chat_id, chat_type="private", user_id=user_id
    )
    context = _make_context()
    result = asyncio.run(
        bot.resolve_topic_text(update, context, fallback_scope="chat")
    )

    assert result == "личная тема"


def test_resolve_topic_text_returns_none_when_nothing_available():
    update = _make_update(chat_id=555204, user_id=777777)
    context = _make_context()
    result = asyncio.run(bot.resolve_topic_text(update, context))
    assert result is None


def test_get_last_user_message_expires_after_max_age():
    chat_id, user_id = 555205, 1
    bot.record_last_user_message(chat_id, user_id, "старое сообщение")

    recorded_at, text = bot.LAST_USER_TEXT_MESSAGE[(chat_id, user_id)]
    bot.LAST_USER_TEXT_MESSAGE[(chat_id, user_id)] = (
        time.monotonic() - bot.LAST_USER_TEXT_MESSAGE_MAX_AGE_SECONDS - 1,
        text,
    )

    assert bot.get_last_user_message(chat_id, user_id) is None


def test_pick_new_title_excludes_previous_when_possible():
    seen = set()
    for _ in range(50):
        seen.add(bot.pick_new_title("Скуф"))
    assert "Скуф" not in seen


def test_pick_new_title_falls_back_when_only_one_option(monkeypatch):
    monkeypatch.setattr(bot, "JOKE_TITLES", ["Единственный титул"])
    assert bot.pick_new_title("Единственный титул") == "Единственный титул"


def test_set_member_title_persists_and_replaces(tmp_path, monkeypatch):
    db_path = tmp_path / "title_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id, user_id = 1, 2
    bot.set_member_title_sync(chat_id, user_id, "Скуф", "group")

    profile = bot.get_member_profile_sync(chat_id, user_id)
    assert profile["current_title"] == "Скуф"

    bot.set_member_title_sync(chat_id, user_id, "Философ", "group")
    profile = bot.get_member_profile_sync(chat_id, user_id)
    assert profile["current_title"] == "Философ"
