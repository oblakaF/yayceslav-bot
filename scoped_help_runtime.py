"""Scope-aware /help for group, private chat and bot owner.

The visible Telegram command menus already have separate scopes. This runtime
makes typed /help use the exact same source of truth instead of advertising
commands hidden from the current user/chat.
"""

from __future__ import annotations

import os

from telegram.constants import ChatType
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler


_PREPARED_APPLICATION_IDS: set[int] = set()


def _owner_id() -> int:
    raw = os.getenv("BOT_OWNER_ID", "").strip()
    return int(raw) if raw.isdigit() else 0


async def scoped_help_command(update, context) -> None:
    del context

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    # Lazy import avoids a command_menu <-> runtime import cycle at startup.
    import command_menu

    is_owner = bool(_owner_id() and user.id == _owner_id())
    chat_type = str(chat.type)
    commands = command_menu.commands_for_help(
        chat_type=chat_type,
        is_owner=is_owner,
    )

    if is_owner:
        title = "Команды владельца Яйцеслава"
    elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        title = "Команды Яйцеслава в группе"
    else:
        title = "Команды Яйцеслава в личке"

    await message.reply_text(
        command_menu.render_help(commands, title=title)
    )

    # Stop the old legacy /help handler in group 0 from sending a second,
    # unscoped command dump.
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return

    application.add_handler(
        CommandHandler("help", scoped_help_command),
        group=-4,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
