"""Tracks reply-chain interaction between two ordinary (non-bot) members.

The pairwise table remains a bounded data source. Relationship Memory v2 is
prepared from this same application-owned relationship stage so social-history
behavior has one startup owner instead of adding another polling/bootstrap hook.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters

import reputation_engine
import relationship_memory_v2_runtime

MAX_PAIR_ROWS_PER_CHAT = 300
PAIR_INTERACTION_TTL_DAYS = 180

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
            CREATE TABLE IF NOT EXISTS member_pair_interactions (
                chat_id INTEGER NOT NULL,
                user_a_id INTEGER NOT NULL,
                user_b_id INTEGER NOT NULL,
                reply_count INTEGER NOT NULL DEFAULT 0,
                hostile_count INTEGER NOT NULL DEFAULT 0,
                positive_count INTEGER NOT NULL DEFAULT 0,
                last_interaction_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_a_id, user_b_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_pair_interactions_recency
            ON member_pair_interactions(chat_id, last_interaction_at)
            """
        )
        connection.commit()


def _normalize_pair(user_x_id: int, user_y_id: int) -> tuple[int, int]:
    a, b = int(user_x_id), int(user_y_id)
    return (a, b) if a <= b else (b, a)


def _record_pair_interaction_sync(
    bot_module,
    chat_id: int,
    user_x_id: int,
    user_y_id: int,
    *,
    hostile: bool,
    positive: bool,
) -> None:
    user_a_id, user_b_id = _normalize_pair(user_x_id, user_y_id)

    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_pair_interactions
                (chat_id, user_a_id, user_b_id, reply_count, hostile_count, positive_count)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(chat_id, user_a_id, user_b_id) DO UPDATE SET
                reply_count = reply_count + 1,
                hostile_count = hostile_count + excluded.hostile_count,
                positive_count = positive_count + excluded.positive_count,
                last_interaction_at = datetime('now'),
                updated_at = datetime('now')
            """,
            (
                int(chat_id),
                user_a_id,
                user_b_id,
                1 if hostile else 0,
                1 if positive else 0,
            ),
        )

        connection.execute(
            """
            DELETE FROM member_pair_interactions
            WHERE chat_id = ? AND last_interaction_at < datetime('now', ?)
            """,
            (int(chat_id), f"-{PAIR_INTERACTION_TTL_DAYS} days"),
        )

        rows = connection.execute(
            """
            SELECT user_a_id, user_b_id FROM member_pair_interactions
            WHERE chat_id = ?
            ORDER BY last_interaction_at DESC
            """,
            (int(chat_id),),
        ).fetchall()
        for stale_a, stale_b in rows[MAX_PAIR_ROWS_PER_CHAT:]:
            connection.execute(
                """
                DELETE FROM member_pair_interactions
                WHERE chat_id = ? AND user_a_id = ? AND user_b_id = ?
                """,
                (int(chat_id), stale_a, stale_b),
            )
        connection.commit()


def _pair_state_sync(bot_module, chat_id: int, user_x_id: int, user_y_id: int) -> dict[str, int]:
    user_a_id, user_b_id = _normalize_pair(user_x_id, user_y_id)
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT reply_count, hostile_count, positive_count
            FROM member_pair_interactions
            WHERE chat_id = ? AND user_a_id = ? AND user_b_id = ?
            """,
            (int(chat_id), user_a_id, user_b_id),
        ).fetchone()
    if not row:
        return {"reply_count": 0, "hostile_count": 0, "positive_count": 0}
    return {
        "reply_count": int(row[0] or 0),
        "hostile_count": int(row[1] or 0),
        "positive_count": int(row[2] or 0),
    }


async def _observe_pairwise(update, context) -> None:
    del context
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

    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None)
    if reply_user is None or getattr(reply_user, "is_bot", False):
        return
    if int(reply_user.id) == int(user.id):
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    text = str(message.text or "")
    hostile = reputation_engine.negative_delta(text) < 0
    positive = reputation_engine.positive_delta(text) > 0

    await asyncio.to_thread(
        _record_pair_interaction_sync,
        bot_module,
        int(chat.id),
        int(user.id),
        int(reply_user.id),
        hostile=hostile,
        positive=positive,
    )


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Pairwise relationship runtime: bot module not ready")
        return

    _initialize_table(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_pairwise),
        group=13,
    )
    relationship_memory_v2_runtime.prepare_application_runtime(application)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Pairwise relationship runtime ready: bounded pair data + relationship memory v2, max %s pairs/chat, %s-day TTL",
        MAX_PAIR_ROWS_PER_CHAT,
        PAIR_INTERACTION_TTL_DAYS,
    )