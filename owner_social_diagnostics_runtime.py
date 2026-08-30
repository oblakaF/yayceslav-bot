"""Owner-only diagnostics for Yayceslav's social relationship state.

No model calls, no new tables and no background work. The command only reads
existing bounded profile/reputation/affinity state and explains the deterministic
relationship band used by ``social_priority_runtime``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler

import social_priority_runtime


_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "get_db_connection", None))
            and callable(getattr(module, "get_member_profile", None))
        ):
            return module
    return None


def _display_target(user: Any) -> str:
    username = str(getattr(user, "username", "") or "").strip()
    full_name = str(getattr(user, "full_name", "") or "").strip()
    if username:
        return f"{full_name or username} (@{username})"
    return full_name or f"user {getattr(user, 'id', '?')}"


def _resolve_target_sync(bot_module, chat_id: int, raw_query: str) -> dict[str, Any] | None:
    query = " ".join(str(raw_query or "").split()).strip()
    if not query:
        return None
    username = query[1:] if query.startswith("@") else query

    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id,
                   COALESCE(NULLIF(current_display_name, ''), username, 'участник'),
                   username
            FROM chat_member_profiles
            WHERE chat_id = ?
              AND (
                    lower(COALESCE(username, '')) = lower(?)
                 OR lower(COALESCE(current_display_name, '')) = lower(?)
              )
            ORDER BY last_seen_at DESC
            LIMIT 1
            """,
            (int(chat_id), username, query),
        ).fetchone()

    if row is None:
        return None
    return {
        "user_id": int(row[0]),
        "display_name": str(row[1] or "участник"),
        "username": (str(row[2]) if row[2] else None),
    }


def _why_band(snapshot: social_priority_runtime.RelationshipSnapshot, band: str) -> str:
    familiar = snapshot.familiarity >= 2 or snapshot.replies_to_bot >= 5
    if band == "feuding_familiar":
        return "есть повторяющаяся конфликтная история + человек уже знакомый"
    if band == "wary":
        return "есть повторяющаяся конфликтная история, но близкой знакомой динамики ещё нет"
    if band == "trusted":
        if snapshot.reputation_score >= 35:
            return "репутация >= +35"
        return "репутация не отрицательная и симпатия >= 3/4"
    if band == "friendly":
        if snapshot.reputation_score >= 10:
            return "репутация >= +10"
        return "репутация не хуже -9 и симпатия >= 1/4"
    if band == "neutral_familiar":
        return "устойчивой симпатии/вражды нет, но человек уже знакомый"
    if familiar:
        return "знакомство есть, но более сильный социальный сигнал не сработал"
    return "нет достаточного сигнала дружбы, вражды или близкого знакомства"


def _format_report(target_name: str, user_id: int, profile: dict[str, Any]) -> str:
    snapshot = social_priority_runtime.snapshot_from_profile(profile)
    band = social_priority_runtime.resolve_relationship_band(snapshot)
    reason = _why_band(snapshot, band)

    affinity_points = int(profile.get("positive_affinity_points_30d", 0) or 0)
    positive_streak = int(profile.get("positive_streak", 0) or 0)
    negative_events = int(profile.get("reputation_negative_events", 0) or 0)
    positive_events = int(profile.get("reputation_positive_events", 0) or 0)
    total_messages = int(profile.get("total_messages", 0) or 0)
    voice_messages = int(profile.get("total_voice_messages", 0) or 0)
    replies_to_bot = int(profile.get("replies_to_bot", 0) or 0)
    insults_to_bot = int(profile.get("insults_to_bot", 0) or 0)
    callback_count = len(profile.get("callback_terms") or ())

    return (
        "SOCIAL DEBUG\n"
        f"Участник: {target_name}\n"
        f"ID: {user_id}\n\n"
        f"Relationship band: {band}\n"
        f"Почему: {reason}\n\n"
        f"Репутация: {snapshot.reputation_score:+d}/100\n"
        f"Симпатия: {snapshot.positive_affinity_level}/4 ({affinity_points} pts / 30d)\n"
        f"Positive streak: {positive_streak}\n"
        f"Знакомство: {snapshot.familiarity}/4\n"
        f"Replies to bot: {replies_to_bot}\n"
        f"Insults to bot: {insults_to_bot}\n"
        f"Reputation events: +{positive_events} / -{negative_events}\n\n"
        f"Активность: {total_messages} сообщений, {voice_messages} voice\n"
        f"Callback memory terms: {callback_count}\n\n"
        "Это диагностика уже существующего состояния. Команда ничего не меняет."
    )


async def social_debug_command(update, context) -> None:
    chat = getattr(update, "effective_chat", None)
    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if chat is None or message is None or user is None:
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    owner_id = int(getattr(bot_module, "BOT_OWNER_ID", 0) or 0)
    if owner_id <= 0 or int(user.id) != owner_id:
        # Silent by design: do not reveal an owner-only diagnostics surface.
        return

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            "social_debug работает в группе: ответь командой на сообщение участника "
            "или используй /social_debug @username."
        )
        return

    target_id: int | None = None
    target_name = ""

    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None)
    if reply_user is not None and not bool(getattr(reply_user, "is_bot", False)):
        target_id = int(reply_user.id)
        target_name = _display_target(reply_user)
    else:
        raw_query = " ".join(getattr(context, "args", ()) or ()).strip()
        target = await asyncio.to_thread(
            _resolve_target_sync,
            bot_module,
            int(chat.id),
            raw_query,
        )
        if target is not None:
            target_id = int(target["user_id"])
            username = target.get("username")
            target_name = str(target.get("display_name") or "участник")
            if username:
                target_name += f" (@{username})"

    if target_id is None:
        await message.reply_text(
            "Ответь /social_debug на сообщение нужного участника или напиши "
            "/social_debug @username."
        )
        return

    try:
        profile = await bot_module.get_member_profile(int(chat.id), target_id)
    except Exception as error:
        logging.exception("Owner social diagnostics profile read failed: %s", error)
        await message.reply_text("Не смог прочитать социальный профиль участника.")
        return

    if not profile:
        await message.reply_text("Профиля этого участника пока нет.")
        return

    await message.reply_text(_format_report(target_name, target_id, dict(profile)))


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    application.add_handler(CommandHandler("social_debug", social_debug_command))
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Owner social diagnostics ready: /social_debug")
