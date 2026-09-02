"""Storage-bounded group digests for "what did I miss?".

Designed for Railway free tier:
- raw group history stays in the shared bounded RAM conversation store;
- a digest is attempted only after enough traffic and at most once/hour/chat;
- only short summaries are stored in SQLite;
- hard TTL and row-count caps make disk growth bounded.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections import defaultdict

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters


DIGEST_MESSAGE_THRESHOLD = 30
DIGEST_MIN_INTERVAL_SECONDS = 60 * 60
DIGEST_MAX_CHARS = 1200
DIGEST_TTL_DAYS = 14
MAX_DIGESTS_PER_CHAT = 12
DIGESTS_FOR_RECAP = 4

_MESSAGE_COUNTS: dict[int, int] = defaultdict(int)
_LAST_ATTEMPT_AT: dict[int, float] = {}
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
            CREATE TABLE IF NOT EXISTS chat_compact_digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_compact_digests_recency
            ON chat_compact_digests(chat_id, created_at)
            """
        )
        connection.commit()


def _store_digest_sync(bot_module, chat_id: int, summary: str) -> None:
    clean = " ".join(str(summary or "").split()).strip()[:DIGEST_MAX_CHARS]
    if not clean:
        return

    with bot_module.get_db_connection() as connection:
        connection.execute(
            "INSERT INTO chat_compact_digests (chat_id, summary) VALUES (?, ?)",
            (int(chat_id), clean),
        )
        connection.execute(
            """
            DELETE FROM chat_compact_digests
            WHERE chat_id = ? AND created_at < datetime('now', ?)
            """,
            (int(chat_id), f"-{DIGEST_TTL_DAYS} days"),
        )
        rows = connection.execute(
            """
            SELECT id FROM chat_compact_digests
            WHERE chat_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (int(chat_id),),
        ).fetchall()
        stale = [row[0] for row in rows[MAX_DIGESTS_PER_CHAT:]]
        if stale:
            connection.executemany(
                "DELETE FROM chat_compact_digests WHERE id = ?",
                [(item,) for item in stale],
            )
        connection.commit()


def _load_digests_sync(
    bot_module,
    chat_id: int,
    limit: int | None = None,
) -> list[str]:
    effective_limit = DIGESTS_FOR_RECAP if limit is None else int(limit)
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT summary FROM chat_compact_digests
            WHERE chat_id = ? AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(chat_id), f"-{DIGEST_TTL_DAYS} days", effective_limit),
        ).fetchall()
    return [str(row[0]) for row in reversed(rows)]


async def _maybe_digest(update, context) -> None:
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

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    chat_id = int(chat.id)
    _MESSAGE_COUNTS[chat_id] = min(DIGEST_MESSAGE_THRESHOLD, _MESSAGE_COUNTS[chat_id] + 1)
    if _MESSAGE_COUNTS[chat_id] < DIGEST_MESSAGE_THRESHOLD:
        return

    now = time.monotonic()
    last_attempt = _LAST_ATTEMPT_AT.get(chat_id, 0.0)
    if now - last_attempt < DIGEST_MIN_INTERVAL_SECONDS:
        return

    _LAST_ATTEMPT_AT[chat_id] = now
    _MESSAGE_COUNTS[chat_id] = 0

    context_text = bot_module.build_memory_context(
        bot_module.GROUP_MEMORY,
        chat_id,
        bot_module.GROUP_MEMORY_SECONDS,
    )
    if not context_text:
        return

    prompt = (
        "Сожми недавний фрагмент группового чата в очень короткую память для "
        "будущего ответа на вопрос «что я пропустил?». Сохрани только темы, "
        "решения, важные события и заметные споры. Не пиши протокол по сообщениям, "
        "не сохраняй пароли/секреты/чувствительные личные данные. Максимум 5 "
        "коротких предложений, без вступления.\n\n"
        + context_text
    )

    try:
        summary = await bot_module.ask_gemini(
            contents=prompt,
            max_output_tokens=180,
            chat_id=chat_id,
            chat_type=str(chat.type),
            thinking_level="minimal",
        )
    except Exception as error:
        logging.warning("Chat digest generation failed for %s: %s", chat_id, error)
        return

    await asyncio.to_thread(_store_digest_sync, bot_module, chat_id, summary)
    logging.info("Stored bounded chat digest for %s", chat_id)


async def missed_recap_command(update, context) -> None:
    del context
    chat = getattr(update, "effective_chat", None)
    message = getattr(update, "effective_message", None)
    if chat is None or message is None:
        return
    if chat.type == ChatType.PRIVATE:
        await message.reply_text("В личке пропускать особо нечего — это наш диалог.")
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    digests = await asyncio.to_thread(_load_digests_sync, bot_module, int(chat.id))
    recent = bot_module.build_memory_context(
        bot_module.GROUP_MEMORY,
        int(chat.id),
        bot_module.GROUP_MEMORY_SECONDS,
    )

    if not digests and not recent:
        await message.reply_text("Пока нечего пересказывать — данных почти нет.")
        return

    history = "\n".join(f"Сводка {i + 1}: {text}" for i, text in enumerate(digests))
    prompt = (
        "Ответь человеку, который спрашивает, что он пропустил в групповом чате. "
        "Собери 3–6 коротких предложений: главные темы, решения/события и один "
        "самый заметный спор или прикол, если он реально был. Не придумывай и "
        "не повторяй одно и то же.\n\n"
    )
    if history:
        prompt += "Старые компактные сводки:\n" + history + "\n\n"
    if recent:
        prompt += "Свежий контекст последних минут:\n" + recent

    try:
        answer = await bot_module.ask_gemini(
            contents=prompt,
            max_output_tokens=300,
            chat_id=int(chat.id),
            chat_type=str(chat.type),
            thinking_level="low",
        )
    except Exception as error:
        logging.warning("Missed recap failed: %s", error)
        answer = recent or (digests[-1] if digests else "Нечего пересказывать.")

    await message.reply_text(answer)


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Chat digest runtime: bot module not ready")
        return

    _initialize_table(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _maybe_digest),
        group=13,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Bounded chat digests ready: %s msgs, >=%ss, max %s rows/chat, %s-day TTL, recap=%s",
        DIGEST_MESSAGE_THRESHOLD,
        DIGEST_MIN_INTERVAL_SECONDS,
        MAX_DIGESTS_PER_CHAT,
        DIGEST_TTL_DAYS,
        DIGESTS_FOR_RECAP,
    )