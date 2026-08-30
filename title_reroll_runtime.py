"""Allow today's title owner to request a bounded contextual reroll.

The automatic title remains one winner per chat/day. This runtime only changes
that winner's title text when the winner explicitly asks. It does not create a
second title assignment and does not let other members rewrite somebody else's
title.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from datetime import date as date_type, timedelta
from typing import Any

from telegram.constants import ChatType
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters

import title_pools


_PREPARED_APPLICATION_IDS: set[int] = set()
MAX_REROLLS_PER_DAY = 2
RECENT_TITLE_COOLDOWN_DAYS = 14

_REROLL_RE = re.compile(
    r"(?:"
    r"\b(?:поменяй|смени|меняй|перевыдай|замени)\b.{0,30}\bтитул\w*\b|"
    r"\bтитул\w*\b.{0,30}\b(?:поменяй|смени|меняй|другой|новый|нормальн\w*|придумай)\b|"
    r"\b(?:дай|верни|придумай)\b.{0,30}\b(?:другой|новый|нормальн\w*)?\s*титул\w*\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_RESTORE_OLD_RE = re.compile(
    r"\b(?:стар(?:ый|ого)|прошл(?:ый|ого)|предыдущ(?:ий|его))\b.{0,24}\b(?:титул\w*|верни)\b|"
    r"\bверни\b.{0,24}\b(?:стар(?:ый|ого)|прошл(?:ый|ого)|предыдущ(?:ий|его))\b",
    re.IGNORECASE | re.DOTALL,
)
_COMPLAINT_REROLL_RE = re.compile(
    r"\b(?:хуйня|говно|хуёв\w*|плох\w*|скучн\w*)\b.{0,45}\b(?:титул\w*|меняй|другой)\b|"
    r"\bтитул\w*\b.{0,45}\b(?:хуйня|говно|хуёв\w*|плох\w*|скучн\w*)\b",
    re.IGNORECASE | re.DOTALL,
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _ensure_schema(bot_module: Any) -> None:
    with bot_module.get_db_connection() as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(daily_title_assignments)")
        }
        if "reroll_count" not in columns:
            connection.execute(
                "ALTER TABLE daily_title_assignments ADD COLUMN reroll_count INTEGER NOT NULL DEFAULT 0"
            )
        if "original_title" not in columns:
            connection.execute(
                "ALTER TABLE daily_title_assignments ADD COLUMN original_title TEXT"
            )
        connection.commit()


def is_title_reroll_request(text: str, *, replied_to_daily_title: bool = False) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _REROLL_RE.search(value) or _RESTORE_OLD_RE.search(value) or _COMPLAINT_REROLL_RE.search(value):
        return True
    if replied_to_daily_title and re.search(r"\b(?:меняй|другой|новый|старый\s+верни)\b", value, re.I):
        return True
    return False


def _today_assignment_sync(bot_module: Any, chat_id: int, current_date: str) -> dict[str, Any] | None:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, title, COALESCE(reroll_count, 0), original_title
            FROM daily_title_assignments
            WHERE chat_id = ? AND date = ?
            """,
            (int(chat_id), str(current_date)),
        ).fetchone()
    if not row:
        return None
    return {
        "user_id": int(row[0]),
        "title": str(row[1]),
        "reroll_count": int(row[2] or 0),
        "original_title": str(row[3]) if row[3] else None,
    }


def _recent_titles_sync(bot_module: Any, chat_id: int, current_date: str) -> tuple[str, ...]:
    cutoff = (date_type.fromisoformat(current_date) - timedelta(days=RECENT_TITLE_COOLDOWN_DAYS)).isoformat()
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT title FROM daily_title_assignments
            WHERE chat_id = ? AND date >= ? AND date <= ?
            ORDER BY date DESC
            """,
            (int(chat_id), cutoff, str(current_date)),
        ).fetchall()
    return tuple(str(row[0]) for row in rows if row and row[0])


def _previous_title_for_user_sync(
    bot_module: Any,
    chat_id: int,
    user_id: int,
    current_date: str,
) -> str | None:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT title
            FROM daily_title_assignments
            WHERE chat_id = ? AND user_id = ? AND date < ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (int(chat_id), int(user_id), str(current_date)),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def _apply_reroll_sync(
    bot_module: Any,
    chat_id: int,
    current_date: str,
    user_id: int,
    old_title: str,
    new_title: str,
) -> bool:
    with bot_module.get_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE daily_title_assignments
            SET title = ?,
                original_title = COALESCE(original_title, ?),
                reroll_count = COALESCE(reroll_count, 0) + 1
            WHERE chat_id = ? AND date = ? AND user_id = ?
              AND COALESCE(reroll_count, 0) < ?
            """,
            (
                str(new_title),
                str(old_title),
                int(chat_id),
                str(current_date),
                int(user_id),
                MAX_REROLLS_PER_DAY,
            ),
        )
        if int(cursor.rowcount or 0) != 1:
            connection.rollback()
            return False

        connection.execute(
            """
            UPDATE chat_member_profiles
            SET current_title = ?, updated_at = datetime('now')
            WHERE chat_id = ? AND user_id = ?
            """,
            (str(new_title), int(chat_id), int(user_id)),
        )
        connection.commit()
    return True


def _sanitize_generated_title(raw: str, excluded: set[str]) -> str | None:
    text = " ".join(str(raw or "").strip().split())
    text = re.sub(r"^(?:титул\s*:\s*|вариант\s*:\s*)", "", text, flags=re.I)
    text = text.strip("`*_«»\"' .,-")
    if not text or len(text) < 3 or len(text) > 64:
        return None
    if any(ch in text for ch in "\n\r"):
        return None
    if text in excluded:
        return None
    # A title is a noun-phrase label, not another bot speech/lecture.
    if len(text.split()) > 8 or text.endswith(("!", "?")):
        return None
    return text


async def _generate_contextual_title(
    bot_module: Any,
    *,
    chat_id: int,
    user_id: int,
    user_name: str,
    old_title: str,
    excluded_titles: tuple[str, ...],
) -> str:
    excluded = {str(item) for item in excluded_titles if str(item).strip()}
    excluded.add(str(old_title))

    recent_context = ""
    try:
        recent_context = bot_module.build_memory_context(
            bot_module.GROUP_MEMORY,
            int(chat_id),
            bot_module.GROUP_MEMORY_SECONDS,
        )
    except Exception:
        recent_context = ""

    prompt = (
        "Придумай ОДИН новый смешной титул дня для участника группового чата. "
        "Используй только реально видимые мотивы из недавнего диалога ниже; если "
        "там мало материала, придумай абсурдный нейтрально-едкий титул без "
        "выдумывания биографии. Это должен быть короткий ярлык 2–6 слов, без "
        "пояснений, без кавычек и без префикса 'титул:'. Не повторяй запрещённые "
        "варианты.\n\n"
        f"Участник: {user_name}\n"
        f"Текущий титул: {old_title}\n"
        f"Запрещённые недавние титулы: {', '.join(sorted(excluded))[:1200]}\n"
        f"Недавний диалог:\n{recent_context[-3500:]}"
    )

    try:
        raw = await bot_module.ask_gemini(
            prompt,
            max_output_tokens=80,
            chat_id=int(chat_id),
            chat_type="group",
            user_name=user_name,
            recent_messages=recent_context.splitlines()[-16:] if recent_context else [],
            bot_was_mentioned=True,
            user_id=int(user_id),
        )
        candidate = _sanitize_generated_title(raw, excluded)
        if candidate:
            return candidate
    except Exception as error:
        logging.warning("Contextual title generation failed: %s", error)

    return title_pools.pick_title(
        old_title,
        excluded_titles=excluded,
    )


async def _handle_title_reroll(update: Any, context: Any) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        chat is None
        or user is None
        or message is None
        or getattr(user, "is_bot", False)
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
    ):
        return

    text = str(getattr(message, "text", "") or "")
    reply = getattr(message, "reply_to_message", None)
    reply_text = str(getattr(reply, "text", "") or "") if reply is not None else ""
    replied_to_daily_title = reply_text.startswith("Титул дня:")
    if not is_title_reroll_request(text, replied_to_daily_title=replied_to_daily_title):
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return
    current_date = bot_module.current_msk_datetime().date().isoformat()
    assignment = await asyncio.to_thread(
        _today_assignment_sync, bot_module, int(chat.id), current_date
    )
    if assignment is None or int(assignment["user_id"]) != int(user.id):
        return

    if assignment["reroll_count"] >= MAX_REROLLS_PER_DAY:
        await message.reply_text(
            "Всё, лимит переобуваний титула на сегодня выбрал. До завтра живи с этим."
        )
        raise ApplicationHandlerStop

    old_title = str(assignment["title"])
    restore_old = bool(_RESTORE_OLD_RE.search(text))
    if restore_old:
        new_title = await asyncio.to_thread(
            _previous_title_for_user_sync,
            bot_module,
            int(chat.id),
            int(user.id),
            current_date,
        )
        if not new_title or new_title == old_title:
            await message.reply_text(
                "Старого отдельного титула у меня не нашлось. Скажи «дай другой титул» — придумаю новый."
            )
            raise ApplicationHandlerStop
    else:
        recent_titles = await asyncio.to_thread(
            _recent_titles_sync, bot_module, int(chat.id), current_date
        )
        display_name = (
            getattr(user, "full_name", None)
            or getattr(user, "username", None)
            or "участник"
        )
        new_title = await _generate_contextual_title(
            bot_module,
            chat_id=int(chat.id),
            user_id=int(user.id),
            user_name=str(display_name),
            old_title=old_title,
            excluded_titles=recent_titles,
        )

    changed = await asyncio.to_thread(
        _apply_reroll_sync,
        bot_module,
        int(chat.id),
        current_date,
        int(user.id),
        old_title,
        str(new_title),
    )
    if not changed:
        await message.reply_text("Опоздал: титульная канцелярия уже закрыла окно переобувания.")
        raise ApplicationHandlerStop

    await message.reply_text(
        f"Ладно, уговорил. «{old_title}» снимаем. Новый титул: «{new_title}»."
    )
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Title reroll runtime: bot module not ready")
        return
    _ensure_schema(bot_module)

    add_handler = getattr(application, "add_handler", None)
    if callable(add_handler):
        # Earlier than generic natural-language routing. Non-title requests fall
        # through immediately and are unaffected.
        add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_title_reroll),
            group=-5,
        )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Title reroll runtime ready: current owner only, max=%s/day, contextual title + old-title restore",
        MAX_REROLLS_PER_DAY,
    )
