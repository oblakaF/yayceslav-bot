from __future__ import annotations

import asyncio
import logging
import sys

import social_engine
import whoami_dynamic_verdict
import whoami_profile_v3_runtime as v3
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler


_PREPARED_APPLICATION_IDS: set[int] = set()
_RUNTIME_HOOK_INSTALLED = False
_ORIGINAL_RUN_POLLING = None


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
    label = social_engine.hostility_label(active_insults)
    if penance_pending:
        return f"{label} — рецидив, помилование через мемный ритуал"
    if active_insults == 0:
        if apologies_today > 0 and total_today > 0:
            return f"{label} — сегодня уже помирились"
        return label
    if active_insults == 1:
        return f"{label} — 1 наезд сегодня"
    return f"{label} — {active_insults} наезда сегодня"


def _relationship_label(chat_level: int, active_hostility: int) -> str:
    if active_hostility >= 11:
        return "Гига-хейтер"
    if active_hostility >= 3:
        return "Мега-хейтер"
    if active_hostility >= 1:
        return "Мини-хейтер"
    if chat_level >= 4:
        return "Любимчик"
    if chat_level >= 3:
        return "Свой"
    if chat_level >= 2:
        return "Кореш"
    if chat_level >= 1:
        return "Знакомый"
    return "Незнакомец"


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


def _authoritative_counts_sync(bot_module, chat_id: int, user_id: int) -> tuple[int, int]:
    """Read message counters directly from daily activity.

    The profile counter is old/legacy state and can lag after migrations. The
    daily activity table is append-only statistics, so /whoami uses it as the
    authoritative non-decreasing source whenever it has data.
    """
    now = bot_module.current_msk_datetime()
    month_start = now.date().replace(day=1).isoformat()
    today = now.date().isoformat()
    with bot_module.get_db_connection() as connection:
        total_row = connection.execute(
            """
            SELECT COALESCE(SUM(messages), 0)
            FROM chat_activity_daily
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, user_id),
        ).fetchone()
        month_row = connection.execute(
            """
            SELECT COALESCE(SUM(messages), 0)
            FROM chat_activity_daily
            WHERE chat_id = ? AND user_id = ?
              AND date BETWEEN ? AND ?
            """,
            (chat_id, user_id, month_start, today),
        ).fetchone()
    return int((total_row[0] if total_row else 0) or 0), int((month_row[0] if month_row else 0) or 0)


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
        # Even a broken enrichment layer must not crash the command. Try the
        # base row directly so the user still gets a dossier.
        try:
            profile = await asyncio.to_thread(bot_module.get_member_profile_sync, chat.id, user.id)
        except Exception:
            profile = None
    if profile is None:
        await message.reply_text("Досье пока не собрано. Яйцеслав ещё не успел оформить компромат.")
        raise ApplicationHandlerStop

    try:
        activity_total, activity_month = await asyncio.to_thread(
            _authoritative_counts_sync, bot_module, chat.id, user.id
        )
    except Exception as error:
        logging.warning("/whoami activity counters failed: %s", error)
        activity_total = activity_month = 0

    profile_total = int(profile.get("total_messages", 0) or 0)
    profile_month = int(profile.get("messages_month", profile.get("messages_30d", 0)) or 0)
    total = max(profile_total, activity_total)
    messages_month = max(profile_month, activity_month)

    # Avoid impossible reports such as '51 total / 70 this month'.
    total = max(total, messages_month)

    chat_level = int(profile.get("chat_level", social_engine.chat_level_from_messages(messages_month)) or 0)
    is_king = bool(profile.get("is_month_king", False))
    active_hostility = int(profile.get("hostility_today", 0) or 0)
    total_hostility = int(profile.get("hostility_total_today", active_hostility) or 0)
    apologies = int(profile.get("apologies_today", 0) or 0)
    penance_pending = bool(profile.get("penance_pending", False))

    relationship = _relationship_label(chat_level, active_hostility)
    friendliness = _friendliness_line(active_hostility, total_hostility, apologies, penance_pending)

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
        f"🤝 Яйцеславу: {relationship}",
        f"🌡 Отношение сегодня: {friendliness}",
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
        lines.append("🧠 Темы месяца: ещё не набрались")

    # Gemini is decoration, not a dependency of /whoami. Timeout/error/odd
    # model output simply removes the verdict line instead of killing dossier.
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
                friendliness=friendliness,
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
        # Minimal emergency output uses no optional DB/Gemini data.
        await message.reply_text(
            f"🥚 ДОСЬЕ ЯЙЦЕСЛАВА НА {name}\n"
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


def install_runtime_hook() -> None:
    global _RUNTIME_HOOK_INSTALLED, _ORIGINAL_RUN_POLLING
    if _RUNTIME_HOOK_INSTALLED:
        return
    _ORIGINAL_RUN_POLLING = Application.run_polling

    def run_polling_with_profile_v4(self, *args, **kwargs):
        _prepare_application(self)
        return _ORIGINAL_RUN_POLLING(self, *args, **kwargs)

    Application.run_polling = run_polling_with_profile_v4
    _RUNTIME_HOOK_INSTALLED = True


install_runtime_hook()
