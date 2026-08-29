from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sys
from datetime import timedelta
from typing import Any

import chat_native_engine
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

# Personal callback memory is intentionally lightweight:
# - only words/short phrases the SAME user actually wrote;
# - no inference that a mentioned topic is a stable fact or preference;
# - sensitive-looking terms are not stored automatically;
# - stale one-off terms disappear, repeated terms survive longer.
CALLBACK_ONE_OFF_TTL_DAYS = 14
CALLBACK_REPEATED_TTL_DAYS = 45
CALLBACK_HARD_TTL_DAYS = 180
MAX_CALLBACK_TERMS_PER_MEMBER = 48
PROFILE_CALLBACK_TERMS = 8
FAVORITE_WORD_MIN_COUNT = 2
SILENT_LOOKBACK_DAYS = 7

SILENT_WEEK_TITLES = (
    "Куколд-наблюдатель",
    "Куколдини в режиме чтения",
    "Смотрящий из-за шторки",
    "Зритель чужого движа",
    "Молчун особого назначения",
    "Свидетель без права голоса",
    "NPC в режиме AFK",
    "Читатель Premium",
    "Присутствует морально",
    "Подписчик без контента",
)

SILENT_NEVER_TITLES = (
    "Верховный Куколдини",
    "Куколд-наблюдатель нулевого уровня",
    "Невидимый участник",
    "Молчун с пожизненной подпиской",
    "NPC без реплик",
    "Читатель в режиме инкогнито",
    "Смотрящий, но не пишущий",
    "Почётный свидетель чата",
)

# We do not auto-store medical, financial, political/religious or other
# sensitive personal topics. Explicit /remember_me remains the controlled
# path for user-supplied long-term facts.
_SENSITIVE_FRAGMENTS = (
    "диагноз", "болез", "рак", "депресс", "тревож", "псих", "таблет",
    "лекар", "беремен", "инвалид", "здоров",
    "зарплат", "доход", "долг", "кредит", "банк", "ипотек", "деньг",
    "полит", "выбор", "президент", "путин", "трамп", "парт",
    "религи", "мусуль", "христиан", "иуд", "атеист",
    "сексуал", "ориентац",
)

_PROFANE_WORD_RE = re.compile(
    r"(?:бля|бляд|еб|ёб|еба|ху[йеия]|пизд|сука|мудак|долбо)",
    re.IGNORECASE,
)

_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _safe_callback_term(term: str) -> bool:
    term = (term or "").strip().lower()
    if not term or len(term) > 40:
        return False
    return not any(fragment in term for fragment in _SENSITIVE_FRAGMENTS)


def _initialize_tables(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_callback_terms (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                term TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at TEXT,
                PRIMARY KEY (chat_id, user_id, term)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_callback_terms_recent
            ON member_callback_terms(chat_id, user_id, last_seen)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_membership_registry (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT,
                username TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_bot INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS silent_title_assignments (
                chat_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
                announced_at TEXT,
                PRIMARY KEY (chat_id, date)
            )
            """
        )

        # Existing V2 chat-native data already knows "this concrete user used
        # this concrete term". Seed it as a one-off personal callback so
        # yesterday's Steam mention can still be recalled naturally.
        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO member_callback_terms
                    (chat_id, user_id, term, occurrences, first_seen, last_seen)
                SELECT chat_id, user_id, term, 1, first_seen, last_seen
                FROM chat_native_term_users
                """
            )
        except Exception:
            # Older/local DBs may not have chat_native tables yet.
            pass

        # Existing profiles become known members. At award time the selected
        # silent candidate is revalidated via Telegram get_chat_member().
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_membership_registry
                (chat_id, user_id, display_name, username, is_active, is_bot)
            SELECT chat_id, user_id, current_display_name, username, 1, 0
            FROM chat_member_profiles
            """
        )
        connection.commit()


def _upsert_member_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    display_name: str,
    username: str | None,
    *,
    is_active: bool = True,
    is_bot: bool = False,
    chat_type: str = "group",
) -> None:
    if user_id <= 0:
        return

    with bot_module.get_db_connection() as connection:
        # Use the bot's own FK-safe helper, already relied on by /remember_me.
        ensure = getattr(bot_module, "_ensure_member_profile_row", None)
        if callable(ensure):
            ensure(connection, chat_id, user_id, chat_type)
        else:
            connection.execute(
                "INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, ?)",
                (chat_id, chat_type),
            )
            connection.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
                (user_id,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO chat_member_profiles
                    (chat_id, user_id)
                VALUES (?, ?)
                """,
                (chat_id, user_id),
            )

        connection.execute(
            """
            UPDATE chat_member_profiles
            SET current_display_name = COALESCE(NULLIF(?, ''), current_display_name),
                username = COALESCE(?, username),
                updated_at = datetime('now')
            WHERE chat_id = ? AND user_id = ?
            """,
            (display_name, username, chat_id, user_id),
        )
        connection.execute(
            """
            INSERT INTO chat_membership_registry
                (chat_id, user_id, display_name, username, is_active, is_bot)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                display_name = COALESCE(NULLIF(excluded.display_name, ''), display_name),
                username = COALESCE(excluded.username, username),
                is_active = excluded.is_active,
                is_bot = excluded.is_bot,
                last_seen_at = datetime('now')
            """,
            (
                chat_id,
                user_id,
                display_name,
                username,
                1 if is_active else 0,
                1 if is_bot else 0,
            ),
        )
        connection.commit()


def _record_member_terms_sync(bot_module, chat_id: int, user_id: int, text: str) -> int:
    terms = tuple(
        term
        for term in chat_native_engine.extract_candidate_terms(text or "")
        if _safe_callback_term(term)
    )
    if not terms:
        return 0

    with bot_module.get_db_connection() as connection:
        for term in terms:
            connection.execute(
                """
                INSERT INTO member_callback_terms
                    (chat_id, user_id, term, occurrences)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(chat_id, user_id, term) DO UPDATE SET
                    occurrences = occurrences + 1,
                    last_seen = datetime('now')
                """,
                (chat_id, user_id, term),
            )

        # Expire one-off/weak topics. A repeated local running joke can remain
        # much longer, but nothing here is immortal.
        connection.execute(
            """
            DELETE FROM member_callback_terms
            WHERE chat_id = ? AND user_id = ?
              AND (
                (occurrences < 2 AND last_seen < datetime('now', ?))
                OR (occurrences < 5 AND last_seen < datetime('now', ?))
                OR last_seen < datetime('now', ?)
              )
            """,
            (
                chat_id,
                user_id,
                f"-{CALLBACK_ONE_OFF_TTL_DAYS} days",
                f"-{CALLBACK_REPEATED_TTL_DAYS} days",
                f"-{CALLBACK_HARD_TTL_DAYS} days",
            ),
        )

        rows = connection.execute(
            """
            SELECT term
            FROM member_callback_terms
            WHERE chat_id = ? AND user_id = ?
            ORDER BY
                CASE WHEN last_used_at IS NULL THEN 0 ELSE 1 END,
                last_seen DESC,
                occurrences DESC
            """,
            (chat_id, user_id),
        ).fetchall()
        for (term,) in rows[MAX_CALLBACK_TERMS_PER_MEMBER:]:
            connection.execute(
                """
                DELETE FROM member_callback_terms
                WHERE chat_id = ? AND user_id = ? AND term = ?
                """,
                (chat_id, user_id, term),
            )
        connection.commit()
    return len(terms)


def _load_member_memory_sync(bot_module, chat_id: int, user_id: int) -> dict[str, Any]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT term, occurrences, last_seen, last_used_at
            FROM member_callback_terms
            WHERE chat_id = ? AND user_id = ?
              AND last_seen >= datetime('now', ?)
            ORDER BY
                CASE
                    WHEN last_used_at IS NULL THEN 0
                    WHEN last_used_at < datetime('now', '-18 hours') THEN 1
                    ELSE 2
                END,
                last_seen DESC,
                occurrences DESC
            LIMIT ?
            """,
            (
                chat_id,
                user_id,
                f"-{CALLBACK_HARD_TTL_DAYS} days",
                PROFILE_CALLBACK_TERMS * 2,
            ),
        ).fetchall()

        callback_terms: list[str] = []
        for term, _occurrences, _last_seen, last_used_at in rows:
            # Keep a term out of the immediate callback pool for 18h once
            # reserved. This makes "Steam" rotate instead of becoming a tic.
            if last_used_at:
                recent_use = connection.execute(
                    "SELECT datetime(?) >= datetime('now', '-18 hours')",
                    (last_used_at,),
                ).fetchone()[0]
                if recent_use:
                    continue
            callback_terms.append(str(term))
            if len(callback_terms) >= PROFILE_CALLBACK_TERMS:
                break

        favorite = connection.execute(
            """
            SELECT term, occurrences
            FROM member_callback_terms
            WHERE chat_id = ? AND user_id = ?
              AND occurrences >= ?
              AND instr(term, ' ') = 0
              AND last_seen >= datetime('now', '-90 days')
            ORDER BY occurrences DESC, last_seen DESC, term ASC
            LIMIT 1
            """,
            (chat_id, user_id, FAVORITE_WORD_MIN_COUNT),
        ).fetchone()

    return {
        "callback_terms": callback_terms,
        "favorite_word": (str(favorite[0]) if favorite else None),
        "favorite_word_count": (int(favorite[1]) if favorite else 0),
    }


def _reserve_callback_term_sync(bot_module, chat_id: int, user_id: int, term: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE member_callback_terms
            SET last_used_at = datetime('now')
            WHERE chat_id = ? AND user_id = ? AND term = ?
            """,
            (chat_id, user_id, term),
        )
        connection.commit()


def reserve_callback_term(chat_id: int, user_id: int, term: str) -> None:
    """Mark one automatic callback topic as recently used so another can rotate in."""
    if not _safe_callback_term(term):
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    _reserve_callback_term_sync(bot_module, int(chat_id), int(user_id), str(term))


def _augment_profile_functions(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_member_memory_profile_patch", False):
        return

    original_sync = bot_module.get_member_profile_sync

    def get_member_profile_sync_with_memory(chat_id: int, user_id: int):
        profile = original_sync(chat_id, user_id)
        if profile is None:
            return None
        enriched = dict(profile)
        try:
            enriched.update(_load_member_memory_sync(bot_module, chat_id, user_id))
        except Exception as error:
            logging.debug("Member callback memory read failed: %s", error)
            enriched.setdefault("callback_terms", [])
            enriched.setdefault("favorite_word", None)
            enriched.setdefault("favorite_word_count", 0)
        enriched["_memory_chat_id"] = int(chat_id)
        return enriched

    async def get_member_profile_with_memory(chat_id: int, user_id: int):
        return await asyncio.to_thread(
            get_member_profile_sync_with_memory,
            chat_id,
            user_id,
        )

    bot_module.get_member_profile_sync = get_member_profile_sync_with_memory
    bot_module.get_member_profile = get_member_profile_with_memory
    bot_module._yayceslav_member_memory_profile_patch = True


async def _observe_text(update, context) -> None:
    del context
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

    display_name = user.full_name or user.username or f"участник {user.id}"
    await asyncio.to_thread(
        _upsert_member_sync,
        bot_module,
        chat.id,
        user.id,
        display_name,
        user.username,
        is_active=True,
        is_bot=False,
        chat_type=str(chat.type),
    )
    await asyncio.to_thread(
        _record_member_terms_sync,
        bot_module,
        chat.id,
        user.id,
        message.text,
    )


def _status_is_active(status: Any) -> bool:
    value = str(status or "").lower()
    return value not in {"left", "kicked", "banned"}


async def _observe_chat_member(update, context) -> None:
    del context
    change = getattr(update, "chat_member", None)
    chat = getattr(update, "effective_chat", None)
    if not change or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    user = change.new_chat_member.user
    bot_module = _find_bot_module()
    if bot_module is None or not user:
        return

    await asyncio.to_thread(
        _upsert_member_sync,
        bot_module,
        chat.id,
        user.id,
        user.full_name or user.username or f"участник {user.id}",
        user.username,
        is_active=_status_is_active(change.new_chat_member.status),
        is_bot=bool(user.is_bot),
        chat_type=str(chat.type),
    )


async def _observe_service_members(update, context) -> None:
    del context
    chat = getattr(update, "effective_chat", None)
    message = getattr(update, "effective_message", None)
    if not chat or not message or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return

    for user in tuple(getattr(message, "new_chat_members", None) or ()):
        await asyncio.to_thread(
            _upsert_member_sync,
            bot_module,
            chat.id,
            user.id,
            user.full_name or user.username or f"участник {user.id}",
            user.username,
            is_active=True,
            is_bot=bool(user.is_bot),
            chat_type=str(chat.type),
        )

    left = getattr(message, "left_chat_member", None)
    if left is not None:
        await asyncio.to_thread(
            _upsert_member_sync,
            bot_module,
            chat.id,
            left.id,
            left.full_name or left.username or f"участник {left.id}",
            left.username,
            is_active=False,
            is_bot=bool(left.is_bot),
            chat_type=str(chat.type),
        )


def _relationship_label(bot_module, level: int) -> str:
    labels = getattr(bot_module, "RELATIONSHIP_LEVEL_LABELS", {})
    return str(labels.get(level, "незнакомец"))


def _verdict_for_profile(profile: dict[str, Any]) -> str:
    total = int(profile.get("total_messages", 0) or 0)
    insults = int(profile.get("insults_to_bot", 0) or 0)
    replies = int(profile.get("replies_to_bot", 0) or 0)

    if total == 0:
        return "Числится в составе. Голос в эфир пока не выдавали."
    if insults >= 8 and insults * 5 >= max(total, 1):
        return "Отношения с Яйцеславом токсичные, зато стабильные."
    if replies >= 20:
        return "Внештатный оппонент Яйцеслава. Зарплата по-прежнему ноль."
    if total >= 150:
        return "Несущая конструкция этого дурдома. Выносить вместе с диваном."
    if total >= 60:
        return "Уже не прохожий. Мебель чата, местами говорящая."
    if total >= 20:
        return "Освоился. Теперь делает вид, что так и было задумано."
    return "Пока присматривается. Компромат только начинает копиться."


async def _whoami_v2(update, context) -> None:
    del context
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if not message or not chat or not user:
        raise ApplicationHandlerStop

    bot_module = _find_bot_module()
    if bot_module is None:
        raise ApplicationHandlerStop

    profile = await bot_module.get_member_profile(chat.id, user.id)
    if profile is None:
        await message.reply_text("Пока досье пустое. Даже Яйцеславу не из чего клевету собирать.")
        raise ApplicationHandlerStop

    name = profile.get("current_display_name") or user.full_name or user.username or str(user.id)
    lines = [
        "🥚 ДОСЬЕ ЯЙЦЕСЛАВА",
        str(name),
        f"Статус: {_relationship_label(bot_module, int(profile.get('relationship_level', 0) or 0))}",
    ]

    title = profile.get("current_title")
    if title:
        lines.append(f"🏅 Титул: {title}")

    lines.append(f"💬 Наболтал: {int(profile.get('total_messages', 0) or 0)} сообщений")

    favorite_word = profile.get("favorite_word")
    favorite_count = int(profile.get("favorite_word_count", 0) or 0)
    if favorite_word:
        lines.append(f"🗣 Любимое слово: «{favorite_word}» — {favorite_count} раз")

    callback_terms = [
        term for term in profile.get("callback_terms", []) if " " not in str(term)
    ][:3]
    if callback_terms:
        lines.append("🧠 Недавние темы: " + ", ".join(callback_terms))

    lines.extend(("", "Вердикт: " + _verdict_for_profile(profile)))
    await message.reply_text("\n".join(lines))
    raise ApplicationHandlerStop


def _silent_assignment_sync(bot_module, chat_id: int, date: str):
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, title, kind, announced_at
            FROM silent_title_assignments
            WHERE chat_id = ? AND date = ?
            """,
            (chat_id, date),
        ).fetchone()
    if not row:
        return None
    return {
        "user_id": int(row[0]),
        "title": str(row[1]),
        "kind": str(row[2]),
        "announced_at": row[3],
    }


def _silent_candidate_rows_sync(bot_module, chat_id: int, date: str):
    start_date = (
        bot_module.current_msk_datetime().date()
        - timedelta(days=SILENT_LOOKBACK_DAYS - 1)
    ).isoformat()

    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                registry.user_id,
                COALESCE(registry.display_name, profiles.current_display_name, ''),
                COALESCE(profiles.total_messages, 0),
                COALESCE(SUM(activity.messages), 0) AS week_messages
            FROM chat_membership_registry AS registry
            LEFT JOIN chat_member_profiles AS profiles
              ON profiles.chat_id = registry.chat_id
             AND profiles.user_id = registry.user_id
            LEFT JOIN chat_activity_daily AS activity
              ON activity.chat_id = registry.chat_id
             AND activity.user_id = registry.user_id
             AND activity.date BETWEEN ? AND ?
            WHERE registry.chat_id = ?
              AND registry.is_active = 1
              AND registry.is_bot = 0
            GROUP BY registry.user_id, registry.display_name,
                     profiles.current_display_name, profiles.total_messages
            HAVING week_messages = 0
            """,
            (start_date, date, chat_id),
        ).fetchall()

        recent_winners = {
            int(row[0])
            for row in connection.execute(
                """
                SELECT user_id
                FROM silent_title_assignments
                WHERE chat_id = ?
                  AND date >= date(?, '-6 days')
                """,
                (chat_id, date),
            ).fetchall()
        }

    candidates = [
        {
            "user_id": int(row[0]),
            "display_name": str(row[1] or f"участник {row[0]}"),
            "total_messages": int(row[2] or 0),
        }
        for row in rows
    ]
    fresh = [item for item in candidates if item["user_id"] not in recent_winners]
    return fresh or candidates


def _save_silent_assignment_sync(
    bot_module,
    chat_id: int,
    date: str,
    user_id: int,
    title: str,
    kind: str,
) -> bool:
    with bot_module.get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO silent_title_assignments
                (chat_id, date, user_id, title, kind)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, date, user_id, title, kind),
        )
        if cursor.rowcount:
            connection.execute(
                """
                UPDATE chat_member_profiles
                SET current_title = ?, updated_at = datetime('now')
                WHERE chat_id = ? AND user_id = ?
                """,
                (title, chat_id, user_id),
            )
        connection.commit()
        return bool(cursor.rowcount)


def _mark_silent_announced_sync(bot_module, chat_id: int, date: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE silent_title_assignments
            SET announced_at = datetime('now')
            WHERE chat_id = ? AND date = ?
            """,
            (chat_id, date),
        )
        connection.commit()


def _known_group_ids_sync(bot_module) -> list[int]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT registry.chat_id
            FROM chat_membership_registry AS registry
            JOIN chats ON chats.chat_id = registry.chat_id
            WHERE registry.is_active = 1
              AND registry.is_bot = 0
              AND chats.chat_type IN ('group', 'supergroup', 'ChatType.GROUP', 'ChatType.SUPERGROUP')
            ORDER BY registry.chat_id
            """
        ).fetchall()
    return [int(row[0]) for row in rows]


async def _candidate_still_in_chat(application: Application, chat_id: int, user_id: int) -> bool:
    bot_module = _find_bot_module()
    if bot_module is None:
        return False
    try:
        member = await application.bot.get_chat_member(chat_id, user_id)
        active = _status_is_active(member.status)
    except Exception as error:
        # If Telegram cannot validate (temporary network/permissions issue),
        # do not invent a removal. Existing registry remains the fallback.
        logging.debug("Silent-title get_chat_member failed %s/%s: %s", chat_id, user_id, error)
        return True

    if not active:
        await asyncio.to_thread(
            _upsert_member_sync,
            bot_module,
            chat_id,
            user_id,
            "",
            None,
            is_active=False,
            is_bot=False,
            chat_type="group",
        )
    return active


async def _run_silent_titles(application: Application) -> None:
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    now = bot_module.current_msk_datetime()
    if now.hour < 18:
        return
    date = now.date().isoformat()

    chat_ids = await asyncio.to_thread(_known_group_ids_sync, bot_module)
    for chat_id in chat_ids:
        assignment = await asyncio.to_thread(
            _silent_assignment_sync, bot_module, chat_id, date
        )

        if assignment and assignment["announced_at"]:
            continue

        if assignment is None:
            candidates = await asyncio.to_thread(
                _silent_candidate_rows_sync, bot_module, chat_id, date
            )
            if not candidates:
                continue

            random.shuffle(candidates)
            chosen = None
            for candidate in candidates:
                if await _candidate_still_in_chat(
                    application, chat_id, candidate["user_id"]
                ):
                    chosen = candidate
                    break
            if chosen is None:
                continue

            never_spoke = chosen["total_messages"] == 0
            title = random.choice(
                SILENT_NEVER_TITLES if never_spoke else SILENT_WEEK_TITLES
            )
            kind = "never_spoke" if never_spoke else "silent_week"
            created = await asyncio.to_thread(
                _save_silent_assignment_sync,
                bot_module,
                chat_id,
                date,
                chosen["user_id"],
                title,
                kind,
            )
            if not created:
                assignment = await asyncio.to_thread(
                    _silent_assignment_sync, bot_module, chat_id, date
                )
            else:
                assignment = {
                    "user_id": chosen["user_id"],
                    "title": title,
                    "kind": kind,
                    "announced_at": None,
                }

        if not assignment:
            continue

        profile = await bot_module.get_member_profile(chat_id, assignment["user_id"])
        display_name = (
            (profile or {}).get("current_display_name")
            or f"участник {assignment['user_id']}"
        )
        if assignment["kind"] == "never_spoke":
            text = (
                f"Титул молчуна дня. {display_name} — «{assignment['title']}». "
                "Сообщений за всю известную Яйцеславу историю: 0. "
                "Наблюдение поставлено безупречно."
            )
        else:
            text = (
                f"Титул молчуна дня. {display_name} — «{assignment['title']}». "
                f"За последние {SILENT_LOOKBACK_DAYS} дней — 0 сообщений. "
                "Чат смотрит, чат не трогает."
            )

        try:
            await application.bot.send_message(chat_id=chat_id, text=text)
        except Exception as error:
            logging.warning("Silent daily title announce failed chat=%s: %s", chat_id, error)
            continue
        await asyncio.to_thread(_mark_silent_announced_sync, bot_module, chat_id, date)


def _patch_daily_title_scheduler(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_silent_title_patch", False):
        return
    original = bot_module.run_due_daily_titles

    async def wrapped(application: Application) -> None:
        await original(application)
        await _run_silent_titles(application)

    bot_module.run_due_daily_titles = wrapped
    bot_module._yayceslav_silent_title_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Member profile runtime: bot module not ready")
        return

    _initialize_tables(bot_module)
    _augment_profile_functions(bot_module)
    _patch_daily_title_scheduler(bot_module)

    # Higher-priority /whoami replaces the old dry handler without touching
    # the giant bot.py. ApplicationHandlerStop prevents group-0 duplicate.
    application.add_handler(CommandHandler("whoami", _whoami_v2), group=-10)
    application.add_handler(
        ChatMemberHandler(_observe_chat_member, ChatMemberHandler.CHAT_MEMBER),
        group=-9,
    )
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
            _observe_service_members,
        ),
        group=-9,
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_text),
        group=5,
    )

    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Member profile runtime ready: rotating personal callbacks, favorite word, "
        "styled /whoami, silent daily titles"
    )
