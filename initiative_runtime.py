"""Occasional unprompted ("initiative") messages into an active group chat.

Highest-risk of the personality additions: it's the only one that sends
a message nobody asked for. Mitigations: a low daily fire probability, a
quiet-hours window, at most one message per chat per day (enforced by
the table's primary key), and canned content (no live Gemini call) so
it costs nothing extra and stays predictable. There is no "is there a
lull right now" signal anywhere in this codebase (chat_activity_daily
only has a daily count, not a last-message timestamp), so this cannot
avoid interrupting a live conversation -- only reduce how often that
can happen at all.

Extends the SAME scheduler tick daily titles/jokes/news already use
(wraps bot_module.run_due_daily_titles again) instead of starting a
second polling loop.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import sys
from datetime import date as date_type

from telegram.ext import Application

import initiative_engine

INITIATIVE_FIRE_PROBABILITY = 0.15
INITIATIVE_MIN_ACTIVE_MESSAGES_TODAY = 8
INITIATIVE_EARLIEST_HOUR_MSK = 12
INITIATIVE_LATEST_HOUR_MSK = 22
INITIATIVE_LOG_KEEP_DAYS = 90

_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _current_date(bot_module) -> str:
    current = getattr(bot_module, "current_msk_datetime", None)
    if callable(current):
        return current().date().isoformat()
    return date_type.today().isoformat()


def _initialize_table(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_initiative_log (
                chat_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                will_fire INTEGER NOT NULL,
                fire_at_hour INTEGER NOT NULL,
                sent_at TEXT,
                PRIMARY KEY (chat_id, date)
            )
            """
        )
        connection.commit()


def _eligible_chat_ids_sync(bot_module, current_date: str) -> list[int]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT activity.chat_id
            FROM chat_activity_daily AS activity
            JOIN chats ON chats.chat_id = activity.chat_id
            WHERE activity.date = ?
              AND chats.chat_type IN ('group', 'supergroup')
            GROUP BY activity.chat_id
            HAVING SUM(activity.messages) >= ?
            """,
            (str(current_date), INITIATIVE_MIN_ACTIVE_MESSAGES_TODAY),
        ).fetchall()
    return [int(row[0]) for row in rows]


def _ensure_today_decision_sync(
    bot_module, chat_id: int, current_date: str, *, rng=random
) -> dict:
    will_fire = 1 if rng.random() < INITIATIVE_FIRE_PROBABILITY else 0
    fire_at_hour = rng.randint(INITIATIVE_EARLIEST_HOUR_MSK, INITIATIVE_LATEST_HOUR_MSK)

    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_initiative_log
                (chat_id, date, will_fire, fire_at_hour)
            VALUES (?, ?, ?, ?)
            """,
            (int(chat_id), str(current_date), will_fire, fire_at_hour),
        )
        connection.execute(
            "DELETE FROM chat_initiative_log WHERE chat_id = ? AND date < date(?, ?)",
            (int(chat_id), str(current_date), f"-{INITIATIVE_LOG_KEEP_DAYS} days"),
        )
        row = connection.execute(
            """
            SELECT will_fire, fire_at_hour, sent_at FROM chat_initiative_log
            WHERE chat_id = ? AND date = ?
            """,
            (int(chat_id), str(current_date)),
        ).fetchone()
        connection.commit()

    return {"will_fire": bool(row[0]), "fire_at_hour": int(row[1]), "sent_at": row[2]}


def _mark_sent_sync(bot_module, chat_id: int, current_date: str) -> bool:
    """Claim the send. Returns True only for the caller that wins the race."""
    with bot_module.get_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE chat_initiative_log
            SET sent_at = datetime('now')
            WHERE chat_id = ? AND date = ? AND sent_at IS NULL
            """,
            (int(chat_id), str(current_date)),
        )
        connection.commit()
        return int(cursor.rowcount or 0) == 1


def _pick_line_sync(bot_module, chat_id: int, current_date: str) -> str:
    mood_key = None
    try:
        import daily_mood_runtime

        mood_key = daily_mood_runtime._ensure_today_mood_sync(bot_module, chat_id, current_date)
    except Exception:
        mood_key = None
    return initiative_engine.pick_initiative_line(mood_key, random)


async def _run_initiative(application: Application) -> None:
    bot_module = _find_bot_module()
    if bot_module is None:
        return

    now = bot_module.current_msk_datetime() if callable(
        getattr(bot_module, "current_msk_datetime", None)
    ) else None
    if now is None:
        return
    current_date = now.date().isoformat()

    try:
        chat_ids = await asyncio.to_thread(_eligible_chat_ids_sync, bot_module, current_date)
    except Exception:
        logging.exception("Initiative: failed to load eligible chats")
        return

    for chat_id in chat_ids:
        try:
            decision = await asyncio.to_thread(
                _ensure_today_decision_sync, bot_module, chat_id, current_date
            )
        except Exception:
            logging.exception("Initiative: failed to load decision chat=%s", chat_id)
            continue

        if not decision["will_fire"] or decision["sent_at"] is not None:
            continue
        if now.hour < decision["fire_at_hour"]:
            continue

        try:
            if not await asyncio.to_thread(_mark_sent_sync, bot_module, chat_id, current_date):
                continue
            line = await asyncio.to_thread(_pick_line_sync, bot_module, chat_id, current_date)
            await application.bot.send_message(chat_id=chat_id, text=line)
        except Exception:
            logging.exception("Initiative: send failed chat=%s", chat_id)


def _patch_scheduler(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_initiative_patch", False):
        return
    original = bot_module.run_due_daily_titles

    @functools.wraps(original)
    async def wrapped(application: Application) -> None:
        await original(application)
        await _run_initiative(application)

    bot_module.run_due_daily_titles = wrapped
    bot_module._yayceslav_initiative_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Initiative runtime: bot module not ready")
        return

    _initialize_table(bot_module)
    _patch_scheduler(bot_module)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Initiative runtime ready: p=%s/day, window %s-%s MSK, >=%s msgs/day to qualify",
        INITIATIVE_FIRE_PROBABILITY,
        INITIATIVE_EARLIEST_HOUR_MSK,
        INITIATIVE_LATEST_HOUR_MSK,
        INITIATIVE_MIN_ACTIVE_MESSAGES_TODAY,
    )
