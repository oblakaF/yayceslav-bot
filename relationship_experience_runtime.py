from __future__ import annotations

import asyncio
import re
import sys
from datetime import date as date_type

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters


_PREPARED_APPLICATION_IDS: set[int] = set()

_APOLOGY_RE = re.compile(
    r"(?:^|\b)(?:извини(?:сь|те)?|прости(?:те)?|сорян|сори|виноват|мир\??)(?:\b|$)",
    re.IGNORECASE,
)

_PENANCE_RE = re.compile(
    r"(?:"
    r"200\s+(?:виртуальн\w+\s+)?извин\w*|"
    r"яйцеслав\s+(?:был\s+)?прав|"
    r"мир\s*,?\s*дон|"
    r"прости\s*,?\s*дон|"
    r"извини\s*,?\s*дон|"
    r"база\s*,?\s*яйцеслав"
    r")",
    re.IGNORECASE,
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def base_chat_level_from_month_messages(messages_month: int) -> int:
    value = max(0, int(messages_month or 0))
    if value >= 350:
        return 3
    if value >= 150:
        return 2
    if value >= 40:
        return 1
    return 0


def chat_level_from_monthly_messages(
    messages_month: int,
    *,
    is_month_leader: bool = False,
) -> int:
    """Calendar-month XP. Level 4 is unique: only the monthly leader at 555+."""
    value = max(0, int(messages_month or 0))
    if is_month_leader and value >= 555:
        return 4
    return base_chat_level_from_month_messages(value)


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


def _ensure_column(connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


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
                forgiveness_count INTEGER NOT NULL DEFAULT 0,
                relapse_count INTEGER NOT NULL DEFAULT 0,
                penance_pending INTEGER NOT NULL DEFAULT 0,
                last_insult_at TEXT,
                last_apology_at TEXT,
                PRIMARY KEY (chat_id, user_id, date)
            )
            """
        )
        _ensure_column(
            connection,
            "member_hostility_daily",
            "forgiveness_count",
            "forgiveness_count INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            connection,
            "member_hostility_daily",
            "relapse_count",
            "relapse_count INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            connection,
            "member_hostility_daily",
            "penance_pending",
            "penance_pending INTEGER NOT NULL DEFAULT 0",
        )
        connection.commit()


def _month_bounds(current_date: str) -> tuple[str, str]:
    current = date_type.fromisoformat(current_date)
    return current.replace(day=1).isoformat(), current.isoformat()


def _messages_month_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> int:
    month_start, month_end = _month_bounds(current_date)
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(messages), 0)
            FROM chat_activity_daily
            WHERE chat_id = ? AND user_id = ?
              AND date BETWEEN ? AND ?
            """,
            (chat_id, user_id, month_start, month_end),
        ).fetchone()
    return int((row[0] if row else 0) or 0)


def _month_leader_sync(bot_module, chat_id: int, current_date: str) -> tuple[int | None, int]:
    month_start, month_end = _month_bounds(current_date)
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, COALESCE(SUM(messages), 0) AS total
            FROM chat_activity_daily
            WHERE chat_id = ? AND date BETWEEN ? AND ?
            GROUP BY user_id
            ORDER BY total DESC, user_id ASC
            LIMIT 1
            """,
            (chat_id, month_start, month_end),
        ).fetchone()
    if not row:
        return None, 0
    return int(row[0]), int(row[1] or 0)


def _hostility_today_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> dict[str, int]:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT insults_total, active_insults, apologies,
                   forgiveness_count, relapse_count, penance_pending
            FROM member_hostility_daily
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (chat_id, user_id, current_date),
        ).fetchone()
    if not row:
        return {
            "insults_total": 0,
            "active_insults": 0,
            "apologies": 0,
            "forgiveness_count": 0,
            "relapse_count": 0,
            "penance_pending": 0,
        }
    return {
        "insults_total": int(row[0] or 0),
        "active_insults": int(row[1] or 0),
        "apologies": int(row[2] or 0),
        "forgiveness_count": int(row[3] or 0),
        "relapse_count": int(row[4] or 0),
        "penance_pending": int(row[5] or 0),
    }


def _record_insult_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> None:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT forgiveness_count, penance_pending
            FROM member_hostility_daily
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (chat_id, user_id, current_date),
        ).fetchone()
        forgiven_before = bool(row and int(row[0] or 0) > 0)
        already_pending = bool(row and int(row[1] or 0) > 0)

        connection.execute(
            """
            INSERT INTO member_hostility_daily
                (chat_id, user_id, date, insults_total, active_insults,
                 relapse_count, penance_pending, last_insult_at)
            VALUES (?, ?, ?, 1, 1, 0, 0, datetime('now'))
            ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                insults_total = insults_total + 1,
                active_insults = active_insults + 1,
                relapse_count = relapse_count + ?,
                penance_pending = CASE WHEN ? THEN 1 ELSE penance_pending END,
                last_insult_at = datetime('now')
            """,
            (
                chat_id,
                user_id,
                current_date,
                1 if forgiven_before and not already_pending else 0,
                1 if forgiven_before else 0,
            ),
        )
        connection.commit()


def _record_first_apology_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_hostility_daily
                (chat_id, user_id, date, apologies, forgiveness_count,
                 active_insults, penance_pending, last_apology_at)
            VALUES (?, ?, ?, 1, 1, 0, 0, datetime('now'))
            ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                apologies = apologies + 1,
                forgiveness_count = forgiveness_count + 1,
                active_insults = 0,
                penance_pending = 0,
                last_apology_at = datetime('now')
            """,
            (chat_id, user_id, current_date),
        )
        connection.commit()


def _record_relapse_apology_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> None:
    """After relapse, a plain apology softens the feud but cannot clear it."""
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE member_hostility_daily
            SET apologies = apologies + 1,
                active_insults = CASE WHEN active_insults > 1 THEN active_insults - 1 ELSE 1 END,
                penance_pending = 1,
                last_apology_at = datetime('now')
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (chat_id, user_id, current_date),
        )
        connection.commit()


def _complete_penance_sync(bot_module, chat_id: int, user_id: int, current_date: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE member_hostility_daily
            SET forgiveness_count = forgiveness_count + 1,
                active_insults = 0,
                penance_pending = 0,
                last_apology_at = datetime('now')
            WHERE chat_id = ? AND user_id = ? AND date = ?
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
        messages_month = _messages_month_sync(bot_module, chat_id, user_id, current_date)
        leader_id, leader_messages = _month_leader_sync(bot_module, chat_id, current_date)
        is_month_leader = leader_id == int(user_id) and leader_messages >= 555
        hostility = _hostility_today_sync(bot_module, chat_id, user_id, current_date)
        level = chat_level_from_monthly_messages(
            messages_month,
            is_month_leader=is_month_leader,
        )
        enriched.update(
            {
                "messages_month": messages_month,
                "messages_30d": messages_month,
                "chat_level": level,
                "chat_level_label": chat_level_label(level),
                "is_month_king": bool(is_month_leader),
                "month_leader_messages": leader_messages,
                "hostility_today": hostility["active_insults"],
                "hostility_total_today": hostility["insults_total"],
                "apologies_today": hostility["apologies"],
                "forgiveness_count_today": hostility["forgiveness_count"],
                "relapse_count_today": hostility["relapse_count"],
                "penance_pending": bool(hostility["penance_pending"]),
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

    # One-line meme penance ends a relapse feud. No 200 actual messages needed.
    if existing["penance_pending"] and _PENANCE_RE.search(text):
        await asyncio.to_thread(
            _complete_penance_sync, bot_module, chat.id, user.id, current_date
        )
        return

    if existing["active_insults"] > 0 and _APOLOGY_RE.search(text):
        if existing["penance_pending"] or existing["forgiveness_count"] > 0:
            await asyncio.to_thread(
                _record_relapse_apology_sync, bot_module, chat.id, user.id, current_date
            )
        else:
            await asyncio.to_thread(
                _record_first_apology_sync, bot_module, chat.id, user.id, current_date
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
