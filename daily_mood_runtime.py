"""Chat-wide daily mood: a background tone that rerolls once per day.

Unlike every other personality layer in this codebase, mood is scoped to
the CHAT, not to a specific member — it colors how Yayceslav sounds to
everyone in a group on a given day, independent of who he's replying to.
It only ever appends flavor text to the already-composed instruction; it
never overrides per-user reputation/relationship rules.
"""

from __future__ import annotations

import functools
import logging
import random
import sys
from datetime import date as date_type

from telegram.ext import Application

import daily_mood_engine

MOOD_HISTORY_KEEP_DAYS = 90

_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "get_db_connection", None))
            and callable(getattr(module, "build_full_system_instruction", None))
        ):
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
            CREATE TABLE IF NOT EXISTS chat_daily_mood (
                chat_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                mood_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, date)
            )
            """
        )
        connection.commit()


def _ensure_today_mood_sync(bot_module, chat_id: int, current_date: str, *, rng=random) -> str:
    with bot_module.get_db_connection() as connection:
        # Whichever concurrent caller wins this INSERT OR IGNORE decides
        # today's mood; every reader (including the loser of the race) then
        # gets the same canonical row back from the SELECT below.
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_daily_mood (chat_id, date, mood_key)
            VALUES (?, ?, ?)
            """,
            (int(chat_id), str(current_date), daily_mood_engine.pick_mood_key(rng)),
        )
        connection.execute(
            "DELETE FROM chat_daily_mood WHERE chat_id = ? AND date < date(?, ?)",
            (int(chat_id), str(current_date), f"-{MOOD_HISTORY_KEEP_DAYS} days"),
        )
        row = connection.execute(
            "SELECT mood_key FROM chat_daily_mood WHERE chat_id = ? AND date = ?",
            (int(chat_id), str(current_date)),
        ).fetchone()
        connection.commit()
    return str(row[0]) if row else "нейтральный"


def _patch_instruction(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_daily_mood_instruction_patch", False):
        return
    original = bot_module.build_full_system_instruction

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        instruction = str(original(*args, **kwargs))
        chat_id = kwargs.get("chat_id")
        chat_type = kwargs.get("chat_type")
        if chat_id is None or chat_type not in ("group", "supergroup"):
            return instruction

        style_text = args[0] if args else kwargs.get("style_text", "")
        try:
            mode = str(bot_module.detect_conversation_mode(str(style_text or "")))
        except Exception:
            mode = "normal"
        if mode == "serious":
            return instruction

        try:
            mood_key = _ensure_today_mood_sync(bot_module, int(chat_id), _current_date(bot_module))
        except Exception:
            logging.exception("Daily mood: failed to load mood for chat=%s", chat_id)
            return instruction

        return instruction + "\n\nCHAT MOOD LAYER:\n" + daily_mood_engine.mood_instruction(mood_key)

    bot_module.build_full_system_instruction = wrapped
    bot_module._yayceslav_daily_mood_instruction_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Daily mood runtime: bot module not ready")
        return

    _initialize_table(bot_module)
    _patch_instruction(bot_module)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Daily mood runtime ready: chat-wide tone, rerolled once per calendar day")
