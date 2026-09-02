"""Bounded multi-tier memory for one/small-number-of-chat Yayceslav deployments.

Tier 1 keeps the existing process-RAM conversation window, but extends it to two
hours and a bounded message count. Tier 2 stores semantic text only (never raw
media bytes) in the existing Railway-volume SQLite database for 30 days and
retrieves a few relevant snippets with local SQLite FTS5. Tier 3 expands the
already-existing compact digests and notable episodic notes.

The design deliberately avoids Google Sheets, Redis, Postgres, vector databases,
and extra Gemini calls. Storage and retrieval stay local and bounded.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import sys
from typing import Any

import chat_digest_runtime
import episodic_memory_runtime


RAM_TTL_SECONDS = 2 * 60 * 60
RAM_MAX_MESSAGES = 60
PERSISTENT_TTL_DAYS = 30
PERSISTENT_MAX_ROWS_PER_CHAT = 20_000
PERSISTENT_CONTENT_MAX_CHARS = 1200
RETRIEVAL_MAX_ROWS = 6
RETRIEVAL_SNIPPET_MAX_CHARS = 500
RETRIEVAL_MAX_QUERY_TERMS = 10
CLEANUP_EVERY_WRITES = 50

DIGEST_TTL_DAYS = 90
MAX_DIGESTS_PER_CHAT = 120
DIGESTS_FOR_RECAP = 6
EPISODIC_TTL_DAYS = 365
MAX_EPISODIC_NOTES_PER_MEMBER = 80
EPISODIC_PROFILE_NOTES = 8

_INSTALLED = False
_WRITE_COUNTS: dict[int, int] = {}

_STOP_WORDS = {
    "это", "как", "что", "чтобы", "тебя", "тебе", "твой", "твоя", "твои",
    "меня", "мне", "мой", "моя", "мои", "его", "ее", "она", "они", "оно",
    "для", "про", "или", "если", "только", "тоже", "там", "тут", "уже",
    "был", "была", "были", "будет", "есть", "нет", "давай", "можешь",
    "скажи", "ответь", "пользователь", "пользователя", "сообщение", "новое", "контекст",
    "ниже", "история", "группы", "группа", "яйцеслав", "yayceslav",
}
_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё_\-]{3,}")


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _clean_text(value: Any, limit: int = PERSISTENT_CONTENT_MAX_CHARS) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _initialize_tables(bot_module: Any) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_semantic_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                modality TEXT NOT NULL DEFAULT 'text',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_semantic_history_recency
            ON chat_semantic_history(chat_id, created_at, id)
            """
        )
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chat_semantic_history_fts
                USING fts5(
                    content,
                    content='chat_semantic_history',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS chat_semantic_history_ai
                AFTER INSERT ON chat_semantic_history BEGIN
                    INSERT INTO chat_semantic_history_fts(rowid, content)
                    VALUES (new.id, new.content);
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS chat_semantic_history_ad
                AFTER DELETE ON chat_semantic_history BEGIN
                    INSERT INTO chat_semantic_history_fts(chat_semantic_history_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS chat_semantic_history_au
                AFTER UPDATE ON chat_semantic_history BEGIN
                    INSERT INTO chat_semantic_history_fts(chat_semantic_history_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                    INSERT INTO chat_semantic_history_fts(rowid, content)
                    VALUES (new.id, new.content);
                END
                """
            )
        except Exception as error:
            # SQLite distributed with CPython normally includes FTS5. If a future
            # image does not, persistence still works; retrieval simply degrades
            # to the LIKE fallback below.
            logging.warning("Persistent memory FTS5 unavailable; using LIKE fallback: %s", error)
        connection.commit()


def _infer_modality(role: str, text: str) -> str:
    if role == "assistant":
        return "assistant"
    lowered = text.lower()
    if lowered.startswith("[голосовое:") or "голосовое сообщение" in lowered:
        return "voice"
    if lowered.startswith("[видео-кружок:") or "видео-кружок" in lowered:
        return "video_note"
    if lowered.startswith("[пользователь прислал видео]"):
        return "video"
    if lowered.startswith("[пользователь прислал фотографию]"):
        return "photo"
    if lowered.startswith("[пользователь прислал файл"):
        return "document"
    return "text"


def _cleanup_chat_sync(bot_module: Any, chat_id: int) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            DELETE FROM chat_semantic_history
            WHERE chat_id = ? AND created_at < datetime('now', ?)
            """,
            (int(chat_id), f"-{PERSISTENT_TTL_DAYS} days"),
        )
        rows = connection.execute(
            """
            SELECT id FROM chat_semantic_history
            WHERE chat_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET ?
            """,
            (int(chat_id), PERSISTENT_MAX_ROWS_PER_CHAT),
        ).fetchall()
        if rows:
            connection.executemany(
                "DELETE FROM chat_semantic_history WHERE id = ?",
                [(int(row[0]),) for row in rows],
            )
        connection.commit()


def _store_turn_sync(
    bot_module: Any,
    chat_id: int,
    role: str,
    author: str,
    text: str,
) -> None:
    clean = _clean_text(text)
    role = "assistant" if str(role) == "assistant" else "user"
    if not clean:
        return
    # Do not turn purely generic legacy placeholders into durable memories.
    if clean in {
        "[Пользователь отправил голосовое сообщение]",
        "[Пользователь отправил видео-кружок]",
    }:
        return
    modality = _infer_modality(role, clean)
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_semantic_history(chat_id, role, author, modality, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(chat_id), role, _clean_text(author, 80), modality, clean),
        )
        connection.commit()

    count = _WRITE_COUNTS.get(int(chat_id), 0) + 1
    if count >= CLEANUP_EVERY_WRITES:
        _WRITE_COUNTS[int(chat_id)] = 0
        _cleanup_chat_sync(bot_module, int(chat_id))
    else:
        _WRITE_COUNTS[int(chat_id)] = count


def _query_terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(str(text or "")):
        token = raw.lower().strip("-_")
        if len(token) < 3 or token in _STOP_WORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= RETRIEVAL_MAX_QUERY_TERMS:
            break
    return terms


def _fts_query(terms: list[str]) -> str:
    escaped = [term.replace('"', '""') for term in terms]
    return " OR ".join(f'"{term}"*' for term in escaped)


def _retrieve_relevant_sync(
    bot_module: Any,
    chat_id: int,
    query_text: str,
    limit: int = RETRIEVAL_MAX_ROWS,
) -> list[dict[str, str]]:
    terms = _query_terms(query_text)
    if not terms:
        return []
    rows: list[Any] = []
    with bot_module.get_db_connection() as connection:
        try:
            rows = connection.execute(
                """
                SELECT h.role, h.author, h.modality, h.content, h.created_at
                FROM chat_semantic_history_fts f
                JOIN chat_semantic_history h ON h.id = f.rowid
                WHERE f.content MATCH ?
                  AND h.chat_id = ?
                  AND h.created_at >= datetime('now', ?)
                  AND h.created_at <= datetime('now', '-10 seconds')
                ORDER BY bm25(chat_semantic_history_fts), h.created_at DESC
                LIMIT ?
                """,
                (_fts_query(terms), int(chat_id), f"-{PERSISTENT_TTL_DAYS} days", int(limit)),
            ).fetchall()
        except Exception:
            # Conservative fallback: use the first few distinctive words.
            like_terms = terms[:3]
            where = " OR ".join("content LIKE ?" for _ in like_terms)
            params = [f"%{term}%" for term in like_terms]
            rows = connection.execute(
                f"""
                SELECT role, author, modality, content, created_at
                FROM chat_semantic_history
                WHERE chat_id = ?
                  AND created_at >= datetime('now', ?)
                  AND created_at <= datetime('now', '-10 seconds')
                  AND ({where})
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                [int(chat_id), f"-{PERSISTENT_TTL_DAYS} days", *params, int(limit)],
            ).fetchall()

    result: list[dict[str, str]] = []
    seen_content: set[str] = set()
    for role, author, modality, content, created_at in rows:
        clean = _clean_text(content, RETRIEVAL_SNIPPET_MAX_CHARS)
        if not clean or clean in seen_content:
            continue
        seen_content.add(clean)
        result.append(
            {
                "role": str(role),
                "author": str(author or ""),
                "modality": str(modality or "text"),
                "content": clean,
                "created_at": str(created_at or ""),
            }
        )
    return result[: int(limit)]


def _extract_query_text(contents: Any) -> str:
    if isinstance(contents, str):
        return _clean_text(contents, 3000)
    if isinstance(contents, list):
        texts = [str(item) for item in contents if isinstance(item, str)]
        return _clean_text(" ".join(texts), 3000)
    return _clean_text(contents, 3000)


def _format_retrieval(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    lines = [
        "LONG-TERM RELEVANT MEMORY — старые фрагменты этого же чата. "
        "Используй только если они действительно относятся к текущему вопросу; "
        "не выдавай предположение за факт и не пересказывай память без причины."
    ]
    for row in reversed(rows):
        who = "Яйцеслав" if row["role"] == "assistant" else (row["author"] or "пользователь")
        lines.append(f"[{row['created_at']}] {who}: {row['content']}")
    return lines


def _patch_ram_limits(bot_module: Any) -> None:
    bot_module.GROUP_MEMORY_SECONDS = RAM_TTL_SECONDS
    bot_module.PRIVATE_MEMORY_SECONDS = RAM_TTL_SECONDS
    bot_module.GROUP_MEMORY_MAX_MESSAGES = RAM_MAX_MESSAGES
    bot_module.PRIVATE_MEMORY_MAX_MESSAGES = RAM_MAX_MESSAGES


def _patch_existing_long_memory_limits() -> None:
    chat_digest_runtime.DIGEST_TTL_DAYS = DIGEST_TTL_DAYS
    chat_digest_runtime.MAX_DIGESTS_PER_CHAT = MAX_DIGESTS_PER_CHAT
    chat_digest_runtime.DIGESTS_FOR_RECAP = DIGESTS_FOR_RECAP
    episodic_memory_runtime.EPISODIC_NOTE_TTL_DAYS = EPISODIC_TTL_DAYS
    episodic_memory_runtime.MAX_EPISODIC_NOTES_PER_MEMBER = MAX_EPISODIC_NOTES_PER_MEMBER
    episodic_memory_runtime.EPISODIC_PROFILE_NOTES = EPISODIC_PROFILE_NOTES


def _patch_group_memory_persistence(bot_module: Any) -> None:
    original = getattr(bot_module, "remember_message", None)
    if not callable(original) or getattr(original, "_yayceslav_persistent_tiered_memory", False):
        return

    @functools.wraps(original)
    def remember_and_persist(*args: Any, **kwargs: Any):
        result = original(*args, **kwargs)
        positional = list(args)
        memory_store = kwargs.get("memory_store") if "memory_store" in kwargs else (positional[0] if positional else None)
        memory_id = kwargs.get("memory_id") if "memory_id" in kwargs else (positional[1] if len(positional) > 1 else None)
        role = kwargs.get("role") if "role" in kwargs else (positional[2] if len(positional) > 2 else "user")
        text = kwargs.get("text") if "text" in kwargs else (positional[3] if len(positional) > 3 else "")
        author = kwargs.get("author") if "author" in kwargs else (positional[6] if len(positional) > 6 else "")

        # Persist only group conversation history. Private memory can be added later,
        # but the current deployment target is one group and this keeps scope clear.
        if memory_store is getattr(bot_module, "GROUP_MEMORY", None) and memory_id is not None:
            try:
                _store_turn_sync(bot_module, int(memory_id), str(role), str(author or ""), str(text or ""))
            except Exception as error:
                logging.warning("Persistent memory write failed for chat %s: %s", memory_id, error)
        return result

    remember_and_persist._yayceslav_persistent_tiered_memory = True
    bot_module.remember_message = remember_and_persist


def _patch_retrieval(bot_module: Any) -> None:
    original = getattr(bot_module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_persistent_memory_retrieval", False):
        return

    @functools.wraps(original)
    async def ask_with_relevant_memory(contents: Any, *args: Any, **kwargs: Any):
        chat_id = kwargs.get("chat_id")
        chat_type = str(kwargs.get("chat_type", "private") or "private").lower()
        if chat_id is None or "private" in chat_type:
            return await original(contents, *args, **kwargs)

        query_text = _extract_query_text(contents)
        try:
            rows = await asyncio.to_thread(
                _retrieve_relevant_sync,
                bot_module,
                int(chat_id),
                query_text,
                RETRIEVAL_MAX_ROWS,
            )
        except Exception as error:
            logging.debug("Persistent memory retrieval failed for chat %s: %s", chat_id, error)
            rows = []

        if rows:
            call_kwargs = dict(kwargs)
            current = list(call_kwargs.get("recent_messages") or [])
            long_memory = _format_retrieval(rows)
            # Keep the existing recent RAM context first; long-term snippets are an
            # explicit secondary tier and never replace fresh conversation state.
            call_kwargs["recent_messages"] = current + long_memory
            return await original(contents, *args, **call_kwargs)
        return await original(contents, *args, **kwargs)

    ask_with_relevant_memory._yayceslav_persistent_memory_retrieval = True
    bot_module.ask_gemini = ask_with_relevant_memory


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _initialize_tables(module)
    _patch_ram_limits(module)
    _patch_existing_long_memory_limits()
    _patch_group_memory_persistence(module)
    _patch_retrieval(module)
    _INSTALLED = True
    logging.warning(
        "Tiered memory ready: RAM=2h/%s msgs; SQLite=%sd/%s rows-chat; "
        "FTS retrieval<=%s; digests=%sd/%s; episodic=%sd/%s",
        RAM_MAX_MESSAGES,
        PERSISTENT_TTL_DAYS,
        PERSISTENT_MAX_ROWS_PER_CHAT,
        RETRIEVAL_MAX_ROWS,
        DIGEST_TTL_DAYS,
        MAX_DIGESTS_PER_CHAT,
        EPISODIC_TTL_DAYS,
        MAX_EPISODIC_NOTES_PER_MEMBER,
    )
    return True
