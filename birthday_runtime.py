"""Minimal birthday calendar: store one birthday per (chat, member) and
warmly congratulate + tag them on the day, once a year.

Follows the same wrap-the-scheduler pattern as daily_content_runtime: it
appends its own due-check to the already-composed run_due_daily_titles
chain instead of owning its own polling loop.
"""

from __future__ import annotations

import asyncio
import html
import logging
import sys
from datetime import datetime

from telegram.ext import Application

import birthday_engine

BIRTHDAY_GREETING_HOUR_MSK = 10

_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "get_db_connection", None))
            and callable(getattr(module, "current_msk_datetime", None))
        ):
            return module
    return None


def _initialize_table(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_birthdays (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                month INTEGER NOT NULL,
                day INTEGER NOT NULL,
                added_by_user_id INTEGER,
                last_greeted_year INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        connection.commit()


def set_birthday_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    display_name: str,
    month: int,
    day: int,
    added_by_user_id: int | None,
) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_birthdays
                (chat_id, user_id, display_name, month, day, added_by_user_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                display_name = excluded.display_name,
                month = excluded.month,
                day = excluded.day,
                added_by_user_id = excluded.added_by_user_id,
                last_greeted_year = NULL,
                updated_at = datetime('now')
            """,
            (int(chat_id), int(user_id), display_name, int(month), int(day), added_by_user_id),
        )
        connection.commit()


def get_birthday_sync(bot_module, chat_id: int, user_id: int) -> dict | None:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT display_name, month, day
            FROM member_birthdays
            WHERE chat_id = ? AND user_id = ?
            """,
            (int(chat_id), int(user_id)),
        ).fetchone()
    if row is None:
        return None
    return {"display_name": row[0], "month": int(row[1]), "day": int(row[2])}


def resolve_member_by_username_sync(bot_module, chat_id: int, username: str) -> dict | None:
    """Looks up a user_id/display_name from this chat's known members by
    @username. Only finds people who have already sent at least one
    message in the chat (chat_member_profiles is populated on activity).
    """

    cleaned = username.lstrip("@").strip().lower()
    if not cleaned:
        return None

    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, current_display_name, username
            FROM chat_member_profiles
            WHERE chat_id = ? AND lower(username) = ?
            ORDER BY last_seen_at DESC
            LIMIT 1
            """,
            (int(chat_id), cleaned),
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": int(row[0]),
        "display_name": row[1] or row[2] or "Участник",
    }


def _birthdays_due_sync(bot_module, now: datetime) -> list[dict]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT chat_id, user_id, display_name
            FROM member_birthdays
            WHERE month = ? AND day = ?
              AND (last_greeted_year IS NULL OR last_greeted_year != ?)
            """,
            (now.month, now.day, now.year),
        ).fetchall()
    return [
        {"chat_id": int(row[0]), "user_id": int(row[1]), "display_name": row[2]}
        for row in rows
    ]


def _mark_greeted_sync(bot_module, chat_id: int, user_id: int, year: int) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE member_birthdays
            SET last_greeted_year = ?, updated_at = datetime('now')
            WHERE chat_id = ? AND user_id = ?
            """,
            (int(year), int(chat_id), int(user_id)),
        )
        connection.commit()


def birthday_due(now: datetime) -> bool:
    return now.hour == BIRTHDAY_GREETING_HOUR_MSK


async def run_birthday_greetings_if_due(application: Application) -> None:
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    now = bot_module.current_msk_datetime()
    if not birthday_due(now):
        return

    due = await asyncio.to_thread(_birthdays_due_sync, bot_module, now)
    for entry in due:
        display_name = entry["display_name"]
        message = birthday_engine.pick_congratulation(display_name)
        mention = (
            f'<a href="tg://user?id={entry["user_id"]}">'
            f'{html.escape(display_name)}</a>'
        )
        text = f"{mention} {message}"
        try:
            await application.bot.send_message(
                chat_id=entry["chat_id"],
                text=text,
                parse_mode="HTML",
            )
        except Exception as error:
            logging.warning(
                "Birthday greeting failed chat=%s user=%s: %s",
                entry["chat_id"],
                entry["user_id"],
                error,
            )
            continue
        await asyncio.to_thread(
            _mark_greeted_sync, bot_module, entry["chat_id"], entry["user_id"], now.year
        )


def _patch_scheduler(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_birthday_patch", False):
        return
    original = bot_module.run_due_daily_titles

    async def wrapped(application: Application) -> None:
        await original(application)
        await run_birthday_greetings_if_due(application)

    bot_module.run_due_daily_titles = wrapped
    bot_module._yayceslav_birthday_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    _initialize_table(bot_module)
    _patch_scheduler(bot_module)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Birthday runtime ready: greeting window %s:00 MSK",
        BIRTHDAY_GREETING_HOUR_MSK,
    )
