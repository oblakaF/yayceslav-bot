from __future__ import annotations

import asyncio
import logging
import sys

import positive_engine
import social_engine
import social_priority_runtime
import whoami_dynamic_verdict
import whoami_profile_v3_runtime as v3
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler


_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_member_profile", None)):
            return module
    return None


def _friendliness_line(
    active_insults: int,
    total_today: int,
    apologies_today: int,
    penance_pending: bool,
) -> str:
    """Legacy helper retained for compatibility with older callers/tests."""

    label = social_engine.hostility_label(active_insults)
    if label == "Не хейтер":
        label = "Нейтрально"
    if penance_pending:
        return f"{label} — рецидив, помилование через мемный ритуал"
    if active_insults == 0:
        if apologies_today > 0 and total_today > 0:
            return f"{label} — сегодня уже помирились"
        return label
    if active_insults == 1:
        return f"{label} — 1 наезд сегодня"
    return f"{label} — {active_insults} наезда сегодня"


def _today_line(
    active_insults: int,
    total_today: int,
    apologies_today: int,
    penance_pending: bool,
) -> str:
    """Describe only today's interaction climate, not lifetime attitude."""

    if penance_pending:
        return "Напряжённо — рецидив, помилование через мемный ритуал"
    if active_insults >= 11:
        return f"Война — {active_insults} наездов сегодня"
    if active_insults >= 3:
        return f"Конфликтно — {active_insults} наезда сегодня"
    if active_insults == 2:
        return "Напряжённо — 2 наезда сегодня"
    if active_insults == 1:
        return "Лёгкий конфликт — 1 наезд сегодня"
    if apologies_today > 0 and total_today > 0:
        return "Помирились"
    return "Спокойно"


def _score_relationship_label(reputation_score: int) -> str:
    score = max(-100, min(100, int(reputation_score or 0)))
    if score <= -76:
        return "Гига-хейтер"
    if score <= -51:
        return "Мега-хейтер"
    if score <= -26:
        return "Мини-хейтер"
    if score <= -1:
        return "Хейтерок"
    if score == 0:
        return "Нейтральный"
    if score <= 25:
        return "Доброжелательный"
    if score <= 50:
        return "Хороший знакомый"
    if score <= 75:
        return "Друг"
    return "Союзник"


def _relationship_label_from_profile(profile) -> str:
    """Expose the same relationship-first band that actually controls tone."""

    snapshot = social_priority_runtime.snapshot_from_profile(profile or {})
    band = social_priority_runtime.resolve_relationship_band(snapshot)
    return {
        "trusted": "Очень свой",
        "friendly": "Доброжелательный",
        "neutral_familiar": "Знакомый нейтрал",
        "feuding_familiar": "Старый спорщик",
        "wary": "Настороженный",
        "neutral": "Нейтральный",
    }.get(band, "Нейтральный")


def _relationship_label(
    chat_level: int,
    active_hostility: int,
    reputation_score: int = 0,
) -> str:
    """Legacy reputation-only relationship helper retained for compatibility."""

    del chat_level
    if active_hostility >= 11:
        return "Гига-хейтер"
    if active_hostility >= 3:
        return "Мега-хейтер"
    if active_hostility >= 1:
        return "Мини-хейтер"
    return _score_relationship_label(reputation_score)


def _positive_line(profile) -> str:
    _score, label = positive_engine.sympathy_from_profile(profile)
    return label


def _reputation_line(profile) -> str:
    """Legacy labeled representation retained for API/test compatibility."""

    score = max(-100, min(100, int(profile.get("reputation_score", 0) or 0)))
    return f"{score} ({_score_relationship_label(score)})"


def _reputation_score_line(profile) -> str:
    """Public dossier representation: raw score, without duplicating relationship."""

    score = max(-100, min(100, int(profile.get("reputation_score", 0) or 0)))
    return f"{score:+d}"


def _next_level_progress(messages_month: int, chat_level: int, is_king: bool) -> str | None:
    if is_king:
        return None
    if chat_level <= 0:
        return f"до 1 LVL: {max(0, 40 - messages_month)} сообщ."
    if chat_level == 1:
        return f"до 2 LVL: {max(0, 150 - messages_month)} сообщ."
    if chat_level == 2:
        return f"до 3 LVL: {max(0, 350 - messages_month)} сообщ."
    if chat_level == 3 and messages_month < 555:
        return f"до права на трон: {max(0, 555 - messages_month)} сообщ."
    if chat_level == 3:
        return "555+ набито; трон получит только лидер месяца"
    return None


async def _safe_member_profile(bot_module, chat_id: int, user_id: int):
    try:
        return await bot_module.get_member_profile(chat_id, user_id)
    except Exception as error:
        logging.exception("/whoami profile read failed chat=%s user=%s: %s", chat_id, user_id, error)
        return None


async def _whoami_v4(update, context) -> None:
    del context
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if not message or not chat or not user:
        raise ApplicationHandlerStop

    bot_module = _find_bot_module()
    if bot_module is None:
        raise ApplicationHandlerStop

    profile = await _safe_member_profile(bot_module, chat.id, user.id)
    if profile is None:
        try:
            profile = await asyncio.to_thread(bot_module.get_member_profile_sync, chat.id, user.id)
        except Exception:
            profile = None
    if profile is None:
        await message.reply_text("Досье пока не собрано. Яйцеслав ещё не успел оформить компромат.")
        raise ApplicationHandlerStop

    total = int(profile.get("total_messages", 0) or 0)
    messages_month = int(profile.get("messages_month", profile.get("messages_30d", 0)) or 0)

    chat_level = int(profile.get("chat_level", social_engine.chat_level_from_messages(messages_month)) or 0)
    is_king = bool(profile.get("is_month_king", False))
    active_hostility = int(profile.get("hostility_today", 0) or 0)
    total_hostility = int(profile.get("hostility_total_today", active_hostility) or 0)
    apologies = int(profile.get("apologies_today", 0) or 0)
    penance_pending = bool(profile.get("penance_pending", False))

    relationship = _relationship_label_from_profile(profile)
    today = _today_line(active_hostility, total_hostility, apologies, penance_pending)
    positive = _positive_line(profile)
    reputation = _reputation_score_line(profile)

    try:
        favorite_word, favorite_count = await asyncio.to_thread(
            v3._favorite_word_sync, bot_module, chat.id, user.id
        )
    except Exception as error:
        logging.warning("/whoami favorite word failed: %s", error)
        favorite_word, favorite_count = None, 0

    try:
        themes = await asyncio.to_thread(v3._themes_sync, bot_module, chat.id, user.id)
    except Exception as error:
        logging.warning("/whoami themes failed: %s", error)
        themes = []

    name = profile.get("current_display_name") or user.full_name or user.username or str(user.id)
    title = profile.get("current_title") or "пока без регалий"
    level_label = social_engine.chat_level_label(chat_level)

    lines = [
        f"🥚 ДОСЬЕ ЯЙЦЕСЛАВА НА {name}",
        f"🤝 Отношение: {relationship}",
        f"⭐ Репутация: {reputation}",
        f"💚 Симпатия: {positive}",
        f"🌡 Сегодня: {today}",
        f"🏅 Титул: {title}",
        f"💬 Сообщений: {total} всего / {messages_month} в этом месяце",
        f"🏚 Уровень: {chat_level}/4 — {level_label}",
    ]

    progress = _next_level_progress(messages_month, chat_level, is_king)
    if progress:
        lines.append(f"📈 XP: {progress}")

    if favorite_word:
        lines.append(f"🗣 Любимое слово месяца: «{favorite_word}» — {favorite_count} раз")
    else:
        lines.append("🗣 Любимое слово месяца: пока не определилось")

    if themes:
        lines.append("🧠 Темы месяца: " + ", ".join(themes))
    else:
        lines.append("🧠 Темы месяца: пока нет устойчивых тем")

    verdict = None
    try:
        verdict = await asyncio.wait_for(
            whoami_dynamic_verdict.generate_verdict(
                bot_module,
                chat_id=chat.id,
                user_id=user.id,
                name=str(name),
                themes=themes,
                chat_level=chat_level,
                level_label=level_label,
                relationship=relationship,
                friendliness=today,
            ),
            timeout=14.0,
        )
    except Exception as error:
        logging.warning("/whoami dynamic verdict skipped: %s", error)

    if verdict:
        if penance_pending:
            verdict = verdict.rstrip(".!?") + ". Амнистия пока на рассмотрении, дон."
        lines.append("🎯 Вердикт: " + verdict)

    try:
        await message.reply_text("\n".join(lines))
    except Exception as error:
        logging.exception("/whoami Telegram send failed: %s", error)
        await message.reply_text(
            f"🥚 ДОСЬЕ ЯЙЦЕСЛАВА НА {name}\n"
            f"⭐ Репутация: {reputation}\n"
            f"💚 Симпатия: {positive}\n"
            f"🏅 Титул: {title}\n"
            f"💬 Сообщений: {total} всего / {messages_month} в этом месяце\n"
            f"🏚 Уровень: {chat_level}/4 — {level_label}"
        )
    raise ApplicationHandlerStop


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    if _find_bot_module() is None:
        return
    application.add_handler(CommandHandler("whoami", _whoami_v4), group=-30)
    _PREPARED_APPLICATION_IDS.add(app_id)
