from __future__ import annotations

import asyncio
import sys

import social_engine
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


def _friendliness_line(active_insults: int, total_today: int, apologies_today: int) -> str:
    label = social_engine.hostility_label(active_insults)
    if active_insults == 0:
        if apologies_today > 0 and total_today > 0:
            return f"{label} — сегодня уже повинился"
        return label
    if active_insults == 1:
        return f"{label} — 1 наезд сегодня"
    return f"{label} — {active_insults} наезда сегодня"


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

    profile = await bot_module.get_member_profile(chat.id, user.id)
    if profile is None:
        await message.reply_text("Досье пустое. Пока даже обидно клеветать не на что.")
        raise ApplicationHandlerStop

    total = int(profile.get("total_messages", 0) or 0)
    messages_30d = int(profile.get("messages_30d", total) or 0)
    chat_level = int(
        profile.get("chat_level", social_engine.chat_level_from_messages(messages_30d)) or 0
    )
    active_hostility = int(profile.get("hostility_today", 0) or 0)
    total_hostility = int(profile.get("hostility_total_today", active_hostility) or 0)
    apologies = int(profile.get("apologies_today", 0) or 0)

    relationship = social_engine.relationship_status_label(chat_level, active_hostility)
    friendliness = _friendliness_line(active_hostility, total_hostility, apologies)

    favorite_word, favorite_count = await asyncio.to_thread(
        v3._favorite_word_sync, bot_module, chat.id, user.id
    )
    themes = await asyncio.to_thread(v3._themes_sync, bot_module, chat.id, user.id)

    name = profile.get("current_display_name") or user.full_name or user.username or str(user.id)
    title = profile.get("current_title") or "пока без регалий"

    lines = [
        "🥚 ДОСЬЕ ЯЙЦЕСЛАВА",
        str(name),
        f"🤝 Кто Яйцеславу: {relationship}",
        f"❤️ Дружелюбность: {friendliness}",
        f"🏅 Титул: {title}",
        f"💬 Наболтал: {total} всего / {messages_30d} за 30 дней",
        f"🏚 Уровень в чате: {chat_level}/4 — {social_engine.chat_level_label(chat_level)}",
    ]

    if favorite_word:
        lines.append(f"🗣 Любимое слово: «{favorite_word}» — {favorite_count} раз")
    else:
        lines.append("🗣 Любимое слово: пока не определилось")

    if themes:
        lines.append("👀 Видит вокруг: " + ", ".join(themes))

    verdict = v3.topical_verdict(themes, fallback_level=chat_level)
    if active_hostility >= 11:
        verdict = verdict.rstrip(".") + ". Но сначала пусть извинится перед Яйцеславом."
    lines.append("🎯 Вердикт: " + verdict)

    await message.reply_text("\n".join(lines))
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
