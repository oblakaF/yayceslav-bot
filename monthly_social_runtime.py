from __future__ import annotations

import asyncio
import logging
import re
import sys
from calendar import monthrange
from datetime import date as date_type, timedelta
from typing import Any

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters

import member_repository
import relationship_experience_runtime as relationship_runtime


_PREPARED_APPLICATION_IDS: set[int] = set()

_NEGATIVE_RE = re.compile(
    r"(?:плох\w*|ужас\w*|бесит\w*|заеб\w*|заёб\w*|надоел\w*|"
    r"хуйн\w*|пиздец\w*|говн\w*|дерьм\w*|ненавиж\w*|"
    r"тяжел\w*|тяжёл\w*|хуев\w*|хуёв\w*|отстой\w*|кринж\w*)",
    re.IGNORECASE,
)

_TOXIC_RE = re.compile(
    r"(?:иди\s+на\s*хуй|пош[её]л\s+на\s*хуй|заткнись|"
    r"мудак\w*|дебил\w*|долбо[её]б\w*|еблан\w*|чмо\b|"
    r"мраз\w*|урод\w*|твар\w*)",
    re.IGNORECASE,
)

_MONTH_NAMES = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def month_key(value: date_type) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def month_bounds(value: date_type) -> tuple[str, str]:
    last_day = monthrange(value.year, value.month)[1]
    return (
        value.replace(day=1).isoformat(),
        value.replace(day=last_day).isoformat(),
    )


def is_last_calendar_day(value: date_type) -> bool:
    return value.day == monthrange(value.year, value.month)[1]


def _target_report_date(now):
    """19:00 MSK on the last calendar day, with day-1 catch-up."""
    if is_last_calendar_day(now.date()) and now.hour >= 19:
        return now.date()
    if now.day == 1:
        return now.date() - timedelta(days=1)
    return None


def _initialize_tables(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_social_daily (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                direct_to_bot INTEGER NOT NULL DEFAULT 0,
                friendly_to_bot INTEGER NOT NULL DEFAULT 0,
                negative_messages INTEGER NOT NULL DEFAULT 0,
                toxic_messages INTEGER NOT NULL DEFAULT 0,
                bot_insults INTEGER NOT NULL DEFAULT 0,
                apologies INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id, date)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_chat_reports (
                chat_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                announced_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, month)
            )
            """
        )
        connection.commit()


def _record_social_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    date: str,
    *,
    direct_to_bot: int,
    friendly_to_bot: int,
    negative_messages: int,
    toxic_messages: int,
    bot_insults: int,
    apologies: int,
) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO monthly_social_daily(
                chat_id, user_id, date, direct_to_bot, friendly_to_bot,
                negative_messages, toxic_messages, bot_insults, apologies
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                direct_to_bot = direct_to_bot + excluded.direct_to_bot,
                friendly_to_bot = friendly_to_bot + excluded.friendly_to_bot,
                negative_messages = negative_messages + excluded.negative_messages,
                toxic_messages = toxic_messages + excluded.toxic_messages,
                bot_insults = bot_insults + excluded.bot_insults,
                apologies = apologies + excluded.apologies
            """,
            (
                chat_id,
                user_id,
                date,
                direct_to_bot,
                friendly_to_bot,
                negative_messages,
                toxic_messages,
                bot_insults,
                apologies,
            ),
        )
        connection.commit()


async def _observe_monthly_social(update, context) -> None:
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
    direct = relationship_runtime._directed_at_bot(update, context, text)
    toxic = bool(_TOXIC_RE.search(text))
    negative = bool(_NEGATIVE_RE.search(text))
    apology = bool(relationship_runtime._APOLOGY_RE.search(text))

    bot_insult = 0
    if direct:
        try:
            bot_insult = 1 if bot_module.detect_conversation_mode(text) == "hostile" else 0
        except Exception:
            bot_insult = 1 if toxic else 0

    friendly = 1 if direct and not bot_insult and not toxic and not negative else 0
    current_date = bot_module.current_msk_datetime().date().isoformat()

    await asyncio.to_thread(
        _record_social_sync,
        bot_module,
        chat.id,
        user.id,
        current_date,
        direct_to_bot=1 if direct else 0,
        friendly_to_bot=friendly,
        negative_messages=1 if negative else 0,
        toxic_messages=1 if toxic else 0,
        bot_insults=bot_insult,
        apologies=1 if apology else 0,
    )


def _report_already_sent_sync(bot_module, chat_id: int, month: str) -> bool:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM monthly_chat_reports WHERE chat_id = ? AND month = ?",
            (chat_id, month),
        ).fetchone()
    return bool(row)


def _mark_report_sent_sync(bot_module, chat_id: int, month: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO monthly_chat_reports(chat_id, month) VALUES (?, ?)",
            (chat_id, month),
        )
        connection.commit()


def _known_chat_ids_sync(bot_module) -> list[int]:
    return member_repository.known_active_group_chat_ids(bot_module)


def _monthly_stats_sync(bot_module, chat_id: int, current_date: date_type) -> dict[str, Any]:
    start, end = month_bounds(current_date)
    with bot_module.get_db_connection() as connection:
        activity_rows = connection.execute(
            """
            SELECT
                a.user_id,
                COALESCE(NULLIF(r.display_name, ''), p.current_display_name, ''),
                COALESCE(SUM(a.messages), 0) AS messages,
                COUNT(DISTINCT CASE WHEN a.messages > 0 THEN a.date END) AS active_days
            FROM chat_activity_daily AS a
            LEFT JOIN chat_membership_registry AS r
              ON r.chat_id = a.chat_id AND r.user_id = a.user_id
            LEFT JOIN chat_member_profiles AS p
              ON p.chat_id = a.chat_id AND p.user_id = a.user_id
            WHERE a.chat_id = ? AND a.date BETWEEN ? AND ?
            GROUP BY a.user_id, r.display_name, p.current_display_name
            """,
            (chat_id, start, end),
        ).fetchall()

        social_rows = connection.execute(
            """
            SELECT
                s.user_id,
                COALESCE(NULLIF(r.display_name, ''), p.current_display_name, ''),
                COALESCE(SUM(s.friendly_to_bot), 0),
                COALESCE(SUM(s.negative_messages), 0),
                COALESCE(SUM(s.toxic_messages), 0),
                COALESCE(SUM(s.bot_insults), 0),
                COALESCE(SUM(s.apologies), 0),
                COALESCE(SUM(s.direct_to_bot), 0)
            FROM monthly_social_daily AS s
            LEFT JOIN chat_membership_registry AS r
              ON r.chat_id = s.chat_id AND r.user_id = s.user_id
            LEFT JOIN chat_member_profiles AS p
              ON p.chat_id = s.chat_id AND p.user_id = s.user_id
            WHERE s.chat_id = ? AND s.date BETWEEN ? AND ?
            GROUP BY s.user_id, r.display_name, p.current_display_name
            """,
            (chat_id, start, end),
        ).fetchall()

    activity = [
        {
            "user_id": int(row[0]),
            "name": str(row[1] or f"участник {row[0]}"),
            "messages": int(row[2] or 0),
            "active_days": int(row[3] or 0),
        }
        for row in activity_rows
    ]
    social = [
        {
            "user_id": int(row[0]),
            "name": str(row[1] or f"участник {row[0]}"),
            "friendly": int(row[2] or 0),
            "negative": int(row[3] or 0),
            "toxic": int(row[4] or 0),
            "bot_insults": int(row[5] or 0),
            "apologies": int(row[6] or 0),
            "direct": int(row[7] or 0),
        }
        for row in social_rows
    ]

    total_messages = sum(item["messages"] for item in activity)
    talkative = max(activity, key=lambda item: (item["messages"], item["active_days"], -item["user_id"]), default=None)
    active = max(activity, key=lambda item: (item["active_days"], item["messages"], -item["user_id"]), default=None)
    negative = max(social, key=lambda item: (item["negative"], item["toxic"], -item["user_id"]), default=None)
    toxic = max(social, key=lambda item: (item["toxic"], item["bot_insults"], -item["user_id"]), default=None)

    friendly_candidates = [item for item in social if item["direct"] > 0]
    friendly = max(
        friendly_candidates,
        key=lambda item: (
            item["friendly"] + 2 * item["apologies"] - 2 * item["bot_insults"],
            item["friendly"],
            -item["user_id"],
        ),
        default=None,
    )

    king = talkative if talkative and talkative["messages"] >= 555 else None

    return {
        "total_messages": total_messages,
        "talkative": talkative,
        "active": active,
        "negative": negative,
        "toxic": toxic,
        "friendly": friendly,
        "king": king,
    }


def _winner_text(item: dict[str, Any] | None, field: str, unit: str) -> str:
    if not item or int(item.get(field, 0) or 0) <= 0:
        return "не выявлен"
    return f"{item['name']} — {int(item[field])} {unit}"


def format_monthly_report(stats: dict[str, Any], current_date: date_type) -> str:
    month_name = _MONTH_NAMES[current_date.month]
    lines = [
        f"📜 ИТОГИ {month_name.upper()} {current_date.year}",
        f"💬 Всего сообщений: {int(stats.get('total_messages', 0) or 0)}",
        "🔥 Самый активный: " + _winner_text(stats.get("active"), "active_days", "дн. в эфире"),
        "🗣 Самый разговорчивый: " + _winner_text(stats.get("talkative"), "messages", "сообщ."),
        "😒 Самый негативный: " + _winner_text(stats.get("negative"), "negative", "негативных заходов"),
        "☣️ Самый токсичный: " + _winner_text(stats.get("toxic"), "toxic", "токсичных заходов"),
    ]

    friendly = stats.get("friendly")
    if friendly:
        lines.append(f"❤️ Самый дружелюбный к Яйцеславу: {friendly['name']}")
    else:
        lines.append("❤️ Самый дружелюбный к Яйцеславу: никто не признался")

    king = stats.get("king")
    if king:
        lines.append(f"👑 Царь чата: {king['name']} — {king['messages']} сообщений")
    else:
        lines.append("👑 Царь чата: трон пуст — никто не набил 555 сообщений")

    lines.extend((
        "",
        "Завтра месячный XP, любимое слово и автоматические темы начинают сезон с нуля.",
        "Старые титулы остаются до новой ежедневной раздачи. Позор можно набирать заново.",
    ))
    return "\n".join(lines)


async def run_monthly_report_if_due(application: Application) -> None:
    bot_module = _find_bot_module()
    if bot_module is None:
        return

    now = bot_module.current_msk_datetime()
    target_date = _target_report_date(now)
    if target_date is None:
        return

    target_month = month_key(target_date)
    chat_ids = await asyncio.to_thread(_known_chat_ids_sync, bot_module)
    for chat_id in chat_ids:
        if await asyncio.to_thread(
            _report_already_sent_sync,
            bot_module,
            chat_id,
            target_month,
        ):
            continue

        stats = await asyncio.to_thread(
            _monthly_stats_sync,
            bot_module,
            chat_id,
            target_date,
        )
        text = format_monthly_report(stats, target_date)
        try:
            await application.bot.send_message(chat_id=chat_id, text=text)
        except Exception as error:
            logging.warning("Monthly chat report failed chat=%s: %s", chat_id, error)
            continue
        await asyncio.to_thread(
            _mark_report_sent_sync,
            bot_module,
            chat_id,
            target_month,
        )


def _patch_scheduler(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_monthly_report_patch", False):
        return
    original = bot_module.run_due_daily_titles

    async def wrapped(application: Application) -> None:
        await original(application)
        await run_monthly_report_if_due(application)

    bot_module.run_due_daily_titles = wrapped
    bot_module._yayceslav_monthly_report_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return

    _initialize_tables(bot_module)
    _patch_scheduler(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_monthly_social),
        group=8,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Monthly social season ready: calendar-month XP, final-day summary, monthly social memory")
