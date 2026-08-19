from __future__ import annotations

import asyncio
import re
import sys
from datetime import date as date_type, timedelta
from typing import Any

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters


_PREPARED_APPLICATION_IDS: set[int] = set()
_RUNTIME_HOOK_INSTALLED = False
_ORIGINAL_RUN_POLLING = None

_APOLOGY_RE = re.compile(
    r"(?:^|\b)(?:извини(?:сь|те)?|прости(?:те)?|сорян|сори|виноват|мир\??)(?:\b|$)",
    re.IGNORECASE,
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def chat_level_from_monthly_messages(messages_30d: int) -> int:
    value = max(0, int(messages_30d or 0))
    if value >= 1000:
        return 4
    if value >= 500:
        return 3
    if value >= 300:
        return 2
    if value >= 100:
        return 1
    return 0


def chat_level_label(level: int) -> str:
    return {
        0: "Дно чата",
        1: "Прижился",
        2: "Местный",
        3: "Старожил",
        4: "Царь чата",
    }.get(max(0, min(int(level), 4)), "Дно чата")


def hostility_label(active_insults: int) -> str:
    value = max(0, int(active_insults or 0))
    if value >= 11:
        return "Гига-хейтер"
    if value >= 3:
        return "Мега-хейтер"
    if value >= 1:
        return "Мини-хейтер"
    return "Не хейтер"


def _initialize_tables(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_hostility_daily (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                insults_total INTEGER NOT NULL DEFAULT 0,
                active_insults INTEGER NOT NULL DEFAULT 0,
                apologies INTEGER NOT NULL DEFAULT 0,
                last_insult_at TEXT,
                last_apology_at TEXT,
                PRIMARY KEY (chat_id, user_id, date)
            )
            """
        )
        connection.commit()


def _messages_30d_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> int:
    start_date = (date_type.fromisoformat(current_date) - timedelta(days=29)).isoformat()
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(messages), 0)
            FROM chat_activity_daily
            WHERE chat_id = ? AND user_id = ?
              AND date BETWEEN ? AND ?
            """,
            (chat_id, user_id, start_date, current_date),
        ).fetchone()
    return int((row[0] if row else 0) or 0)


def _hostility_today_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> dict[str, int]:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT insults_total, active_insults, apologies
            FROM member_hostility_daily
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (chat_id, user_id, current_date),
        ).fetchone()
    if not row:
        return {"insults_total": 0, "active_insults": 0, "apologies": 0}
    return {
        "insults_total": int(row[0] or 0),
        "active_insults": int(row[1] or 0),
        "apologies": int(row[2] or 0),
    }


def _record_insult_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_hostility_daily
                (chat_id, user_id, date, insults_total, active_insults, last_insult_at)
            VALUES (?, ?, ?, 1, 1, datetime('now'))
            ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                insults_total = insults_total + 1,
                active_insults = active_insults + 1,
                last_insult_at = datetime('now')
            """,
            (chat_id, user_id, current_date),
        )
        connection.commit()


def _record_apology_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_hostility_daily
                (chat_id, user_id, date, apologies, active_insults, last_apology_at)
            VALUES (?, ?, ?, 1, 0, datetime('now'))
            ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                apologies = apologies + 1,
                active_insults = 0,
                last_apology_at = datetime('now')
            """,
            (chat_id, user_id, current_date),
        )
        connection.commit()


def _directed_at_bot(update, context, text: str) -> bool:
    message = getattr(update, "effective_message", None)
    if not message:
        return False

    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None)
    bot_id = getattr(getattr(context, "bot", None), "id", None)
    if reply_user is not None and bot_id is not None and int(reply_user.id) == int(bot_id):
        return True

    lowered = (text or "").lower()
    username = str(getattr(getattr(context, "bot", None), "username", "") or "").lower()
    if username and f"@{username}" in lowered:
        return True
    return "яйцеслав" in lowered


def _augment_profile_functions(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_relationship_experience_patch", False):
        return

    original_sync = bot_module.get_member_profile_sync

    def get_member_profile_sync_with_relationship(chat_id: int, user_id: int):
        profile = original_sync(chat_id, user_id)
        if profile is None:
            return None
        enriched = dict(profile)
        current_date = bot_module.current_msk_datetime().date().isoformat()
        messages_30d = _messages_30d_sync(bot_module, chat_id, user_id, current_date)
        hostility = _hostility_today_sync(bot_module, chat_id, user_id, current_date)
        level = chat_level_from_monthly_messages(messages_30d)
        enriched.update(
            {
                "messages_30d": messages_30d,
                "chat_level": level,
                "chat_level_label": chat_level_label(level),
                "hostility_today": hostility["active_insults"],
                "hostility_total_today": hostility["insults_total"],
                "apologies_today": hostility["apologies"],
                "friendliness_label": hostility_label(hostility["active_insults"]),
            }
        )
        return enriched

    async def get_member_profile_with_relationship(chat_id: int, user_id: int):
        return await asyncio.to_thread(
            get_member_profile_sync_with_relationship,
            chat_id,
            user_id,
        )

    bot_module.get_member_profile_sync = get_member_profile_sync_with_relationship
    bot_module.get_member_profile = get_member_profile_with_relationship
    bot_module._yayceslav_relationship_experience_patch = True


async def _observe_relationship(update, context) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        not chat
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or not user
        or user.is_bot
        or not message
        or not getattr(message, "text", None)
    ):
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    text = str(message.text or "")
    current_date = bot_module.current_msk_datetime().date().isoformat()
    existing = await asyncio.to_thread(
        _hostility_today_sync, bot_module, chat.id, user.id, current_date
    )

    if existing["active_insults"] > 0 and _APOLOGY_RE.search(text):
        await asyncio.to_thread(
            _record_apology_sync, bot_module, chat.id, user.id, current_date
        )
        return

    if not _directed_at_bot(update, context, text):
        return

    try:
        mode = bot_module.detect_conversation_mode(text)
    except Exception:
        mode = "normal"
    if mode == "hostile":
        await asyncio.to_thread(
            _record_insult_sync, bot_module, chat.id, user.id, current_date
        )


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return

    _initialize_tables(bot_module)
    _augment_profile_functions(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_relationship),
        group=7,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)


def install_runtime_hook() -> None:
    global _RUNTIME_HOOK_INSTALLED, _ORIGINAL_RUN_POLLING
    if _RUNTIME_HOOK_INSTALLED:
        return
    _ORIGINAL_RUN_POLLING = Application.run_polling

    def run_polling_with_relationship_experience(self, *args, **kwargs):
        _prepare_application(self)
        return _ORIGINAL_RUN_POLLING(self, *args, **kwargs)

    Application.run_polling = run_polling_with_relationship_experience
    _RUNTIME_HOOK_INSTALLED = True


install_runtime_hook()
