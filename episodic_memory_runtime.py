"""Short, storage-bounded episodic memory per (chat_id, user_id).

Aggregate counters (reputation, affinity, callback terms) tell Yayceslav
*how* someone stands with him, but not any specific moment. This module
piggybacks on reputation_runtime's already-computed "was this message
notable" signal (a genuinely large directed praise/abuse delta) to save a
short excerpt of that moment, capped per member so storage never grows
unbounded on a Railway free-tier disk.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters

import reputation_engine
import reputation_runtime

EPISODIC_EXCERPT_MAX_CHARS = 140
EPISODIC_MIN_ABS_DELTA = 4
EPISODIC_NOTE_TTL_DAYS = 120
MAX_EPISODIC_NOTES_PER_MEMBER = 12
EPISODIC_PROFILE_NOTES = 4

_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _initialize_table(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_episodic_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                excerpt TEXT NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_episodic_notes_recency
            ON member_episodic_notes(chat_id, user_id, created_at)
            """
        )
        connection.commit()


def _record_episodic_note_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    text: str,
    delta: int,
    reason: str,
) -> None:
    excerpt = str(text or "").strip()[:EPISODIC_EXCERPT_MAX_CHARS]
    if not excerpt:
        return

    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_episodic_notes
                (chat_id, user_id, excerpt, delta, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(chat_id), int(user_id), excerpt, int(delta), str(reason or "")),
        )

        connection.execute(
            """
            DELETE FROM member_episodic_notes
            WHERE chat_id = ? AND user_id = ?
              AND created_at < datetime('now', ?)
            """,
            (int(chat_id), int(user_id), f"-{EPISODIC_NOTE_TTL_DAYS} days"),
        )

        rows = connection.execute(
            """
            SELECT id FROM member_episodic_notes
            WHERE chat_id = ? AND user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (int(chat_id), int(user_id)),
        ).fetchall()
        stale_ids = [row[0] for row in rows[MAX_EPISODIC_NOTES_PER_MEMBER:]]
        if stale_ids:
            connection.executemany(
                "DELETE FROM member_episodic_notes WHERE id = ?",
                [(stale_id,) for stale_id in stale_ids],
            )
        connection.commit()


def _load_episodic_notes_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    limit: int | None = None,
) -> list[str]:
    effective_limit = EPISODIC_PROFILE_NOTES if limit is None else int(limit)
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT excerpt FROM member_episodic_notes
            WHERE chat_id = ? AND user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(chat_id), int(user_id), effective_limit),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _augment_profile_functions(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_episodic_memory_profile_patch", False):
        return
    original_sync = getattr(bot_module, "get_member_profile_sync", None)
    original_async = getattr(bot_module, "get_member_profile", None)
    if not callable(original_sync) or not callable(original_async):
        return

    def sync_with_episodic(chat_id: int, user_id: int):
        profile = original_sync(chat_id, user_id)
        if profile is None:
            return None
        enriched = dict(profile)
        enriched["episodic_notes"] = _load_episodic_notes_sync(bot_module, chat_id, user_id)
        return enriched

    async def async_with_episodic(chat_id: int, user_id: int):
        profile = await original_async(chat_id, user_id)
        if profile is None:
            return None
        notes = await asyncio.to_thread(_load_episodic_notes_sync, bot_module, chat_id, user_id)
        enriched = dict(profile)
        enriched["episodic_notes"] = notes
        return enriched

    bot_module.get_member_profile_sync = sync_with_episodic
    bot_module.get_member_profile = async_with_episodic
    bot_module._yayceslav_episodic_memory_profile_patch = True


async def _observe_episodic(update, context) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        chat is None
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or user is None
        or user.is_bot
        or message is None
        or not getattr(message, "text", None)
    ):
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    text = str(message.text or "")
    directed = reputation_runtime._directed_at_bot(update, context, text)
    if not directed:
        return

    try:
        hostile = str(bot_module.detect_conversation_mode(text)) == "hostile"
    except Exception:
        hostile = False

    decision = reputation_engine.score_message(text, directed_at_bot=True, hostile_mode=hostile)
    if abs(decision.delta) < EPISODIC_MIN_ABS_DELTA:
        return

    await asyncio.to_thread(
        _record_episodic_note_sync,
        bot_module,
        int(chat.id),
        int(user.id),
        text,
        decision.delta,
        decision.reason,
    )


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Episodic memory runtime: bot module not ready")
        return

    _initialize_table(bot_module)
    _augment_profile_functions(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_episodic),
        group=12,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Episodic memory runtime ready: max %s notes/member, %s-day TTL; profile uses %s",
        MAX_EPISODIC_NOTES_PER_MEMBER,
        EPISODIC_NOTE_TTL_DAYS,
        EPISODIC_PROFILE_NOTES,
    )