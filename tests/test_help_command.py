import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import bot

# Commands intentionally excluded from /help:
# - start/help are meta, not features to list;
# - stats/geminiversion are owner-only and must never appear in /help at all.
COMMANDS_EXCLUDED_FROM_HELP = {"start", "help", "stats", "geminiversion"}

ADMIN_ONLY_COMMANDS = {
    "hard_on",
    "hard_off",
    "hard_level",
    "hard_stats",
    "people",
    "set_archetype",
    "week_auto_on",
    "week_auto_off",
    "week_time",
}


def _all_registered_commands():
    source = Path(bot.__file__).read_text(encoding="utf-8")
    matches = re.findall(r'CommandHandler\(\s*"(\w+)"', source)
    return set(matches)


def _make_update(chat_type="group"):
    message = SimpleNamespace(replies=[])

    async def reply_text(text, *args, **kwargs):
        message.replies.append(text)

    message.reply_text = reply_text
    effective_chat = SimpleNamespace(id=1, type=chat_type)
    effective_user = SimpleNamespace(id=1)
    return SimpleNamespace(
        message=message,
        effective_chat=effective_chat,
        effective_user=effective_user,
    )


def _make_admin_context(is_admin):
    async def get_chat_member(chat_id, user_id):
        status = "administrator" if is_admin else "member"
        return SimpleNamespace(status=status)

    bot_stub = SimpleNamespace(get_chat_member=get_chat_member)
    return SimpleNamespace(args=[], bot=bot_stub)


def test_help_lists_every_registered_command_for_admins():
    update = _make_update()
    context = _make_admin_context(is_admin=True)
    asyncio.run(bot.help_command(update, context))

    text = update.message.replies[0]
    for command in _all_registered_commands() - COMMANDS_EXCLUDED_FROM_HELP:
        assert f"/{command}" in text, command


def test_help_hides_admin_only_commands_from_regular_users():
    update = _make_update()
    context = _make_admin_context(is_admin=False)
    asyncio.run(bot.help_command(update, context))

    text = update.message.replies[0]
    for command in ADMIN_ONLY_COMMANDS:
        assert f"/{command}" not in text, command


def test_help_shows_admin_only_commands_to_group_admins():
    update = _make_update()
    context = _make_admin_context(is_admin=True)
    asyncio.run(bot.help_command(update, context))

    text = update.message.replies[0]
    for command in ADMIN_ONLY_COMMANDS:
        assert f"/{command}" in text, command


def test_help_shows_admin_only_commands_in_private_chat():
    update = _make_update(chat_type="private")
    context = _make_admin_context(is_admin=False)
    asyncio.run(bot.help_command(update, context))

    text = update.message.replies[0]
    assert "/set_archetype" in text
