"""Ground third-party social opinions and isolate per-user conversational state.

This runtime fixes a class of live-chat failures where Yayceslav could invent a
social dossier for an @mentioned member, then see its own previous prose in the
five-minute group memory and treat that prose as evidence on the next turn.

It deliberately does NOT implement the future Social Scene Graph.  The scope is
small and conservative:

* high-confidence "what do you think about @user" requests are resolved to the
  actual known member and answered from bounded existing profile evidence;
* if the target is unknown / evidence is too thin, the bot says so instead of
  improvising personality or group consensus;
* previous assistant messages are explicitly non-evidence for claims about a
  person;
* historical hostility may color tone, but cannot turn a neutral current turn
  into an attack;
* legacy state_engine annoyed/argumentative state is scoped to the current
  sender while the system instruction is built, instead of leaking across the
  whole group chat.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import sys
from typing import Any, Mapping

from telegram.constants import ChatType
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters

import state_engine


_INSTALLED = False
_PREPARED_APPLICATION_IDS: set[int] = set()

_MENTION = r"@[A-Za-z0-9_]{3,32}"
_MEMBER_OPINION_PATTERNS = (
    re.compile(
        rf"\b(?:что|че|чё)\s+(?:ты\s+)?(?:думаешь|скажешь)\s+(?:о|об|про)\s+(?P<target>{_MENTION})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bкак\s+тебе\s+(?P<target>{_MENTION})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:мнение|вердикт)\s+(?:о|об|про)\s+(?P<target>{_MENTION})\b",
        re.IGNORECASE,
    ),
)

_FINAL_GROUNDING_RULES = """

SOCIAL EVIDENCE GROUNDING — ФИНАЛЬНЫЙ ПРИОРИТЕТ:
- Предыдущие ответы самого Яйцеслава в истории группы — это только реплики
  разговора, НЕ независимое доказательство фактов, привычек или характера
  участника. Не подтверждай собственную прошлую выдумку самим фактом, что она
  уже появилась в истории.
- Нельзя превращать прошлую формулировку Яйцеслава в «констатацию факта»,
  «все это видят», «он всегда так делает» и подобные утверждения без отдельного
  наблюдаемого основания: реальных сообщений самого человека, явного
  self-reported факта или конкретной статистики профиля.
- Если спрашивают мнение о ТРЕТЬЕМ участнике и отдельного блока подтверждённых
  данных о нём в текущем запросе нет, прямо скажи, что данных мало. Не сочиняй
  социальное досье, профессии, привычки, позиции в спорах или мнение всей группы.
- История hostility/reputation относится к отношениям Яйцеслава с ТЕКУЩИМ
  отправителем и может только окрашивать тон. Она НЕ делает нейтральную текущую
  реплику атакой. Это правило отменяет более ранние указания отвечать зло «в
  любой несерьёзной беседе» только из-за старой вражды: без текущего наезда не
  нападай первым.
"""


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _call_argument(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    name: str,
    position: int,
    default: Any = None,
) -> Any:
    if name in kwargs:
        return kwargs[name]
    if len(args) > position:
        return args[position]
    return default


def extract_member_opinion_target(text: str) -> str | None:
    """Return an explicit @target only for high-confidence opinion requests."""

    value = str(text or "").strip()
    if not value:
        return None
    for pattern in _MEMBER_OPINION_PATTERNS:
        match = pattern.search(value)
        if match:
            return str(match.group("target"))
    return None


def _resolve_target_user_id_sync(bot_module: Any, chat_id: int, mention: str) -> int | None:
    username = str(mention or "").lstrip("@").strip().lower()
    if not username:
        return None

    with bot_module.get_db_connection() as connection:
        # member_profile_runtime owns this registry in current production.  Keep
        # a fallback for older/local databases used by tests or rollback builds.
        try:
            row = connection.execute(
                """
                SELECT user_id
                FROM chat_membership_registry
                WHERE chat_id = ? AND lower(username) = ? AND is_active = 1
                LIMIT 1
                """,
                (int(chat_id), username),
            ).fetchone()
        except Exception:
            row = None

        if row is None:
            row = connection.execute(
                """
                SELECT user_id
                FROM chat_member_profiles
                WHERE chat_id = ? AND lower(username) = ?
                LIMIT 1
                """,
                (int(chat_id), username),
            ).fetchone()

    return int(row[0]) if row else None


def _evidence_is_meaningful(profile: Mapping[str, Any] | None) -> bool:
    if not profile:
        return False
    if int(profile.get("total_messages", 0) or 0) >= 3:
        return True
    if int(profile.get("replies_to_bot", 0) or 0) >= 2:
        return True
    if tuple(profile.get("self_reported_facts") or ()):
        return True
    if tuple(profile.get("callback_terms") or ()):
        return True
    return False


def build_target_evidence(mention: str, profile: Mapping[str, Any]) -> str:
    """Serialize only bounded observed/profile facts, never inferred traits."""

    lines = [
        f"Цель: {mention}",
        f"Отображаемое имя: {profile.get('current_display_name') or mention}",
        f"Сообщений в профиле: {int(profile.get('total_messages', 0) or 0)}",
        f"Ответов Яйцеславу: {int(profile.get('replies_to_bot', 0) or 0)}",
        f"Зафиксированных оскорблений Яйцеслава: {int(profile.get('insults_to_bot', 0) or 0)}",
    ]

    if profile.get("current_title"):
        lines.append(
            "Текущий шуточный титул (НЕ факт о личности): "
            + repr(str(profile.get("current_title")))
        )

    facts = [
        str(item).strip()
        for item in (profile.get("self_reported_facts") or ())
        if str(item).strip()
    ][:4]
    if facts:
        lines.append("Факты, которые человек сам просил запомнить: " + "; ".join(facts))

    terms = [
        str(item).strip()
        for item in (profile.get("callback_terms") or ())
        if str(item).strip()
    ][:4]
    if terms:
        lines.append(
            "Недавние темы/слова, реально встречавшиеся у этого автора "
            "(не считать чертами личности): " + ", ".join(terms)
        )

    return "\n".join(lines)


def build_member_opinion_prompt(mention: str, profile: Mapping[str, Any]) -> str:
    evidence = build_target_evidence(mention, profile)
    return f"""
Пользователь спрашивает мнение Яйцеслава именно о {mention}.

ПОДТВЕРЖДЁННЫЕ ДАННЫЕ О ЦЕЛИ — единственный источник для персональных выводов:
{evidence}

ЖЁСТКИЕ ПРАВИЛА ЭТОГО ОТВЕТА:
- предыдущие реплики самого Яйцеслава про {mention} НЕ являются доказательством;
- не приписывай человеку привычки вроде «лезет в каждый спор», профессию,
  знания, мотивы, отношения или мнение всей группы, если этого нет выше;
- статистику можно обыграть и подколоть, но не превращать её в выдуманную
  биографию;
- если доказательств для конкретной характеристики мало, так и скажи;
- ответ 1–2 короткими живыми предложениями в характере Яйцеслава, без
  канцелярского «оперативного досье» и без длинной лекции.
""".strip()


async def _member_opinion_handler(update: Any, context: Any) -> None:
    chat = getattr(update, "effective_chat", None)
    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if (
        chat is None
        or message is None
        or user is None
        or getattr(user, "is_bot", False)
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
    ):
        return

    text = str(getattr(message, "text", "") or "")
    mention = extract_member_opinion_target(text)
    if mention is None:
        return

    bot_username = str(getattr(getattr(context, "bot", None), "username", "") or "")
    if bot_username and mention.lower() == ("@" + bot_username.lstrip("@")).lower():
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    target_user_id = await asyncio.to_thread(
        _resolve_target_user_id_sync,
        bot_module,
        int(chat.id),
        mention,
    )
    if target_user_id is None:
        await message.reply_text(
            f"Про {mention} у меня пока мало подтверждённых данных. "
            "Могу судить по тому, что он реально пишет в этом чате, а досье из воздуха лепить не буду."
        )
        raise ApplicationHandlerStop

    profile = await bot_module.get_member_profile(int(chat.id), target_user_id)
    if not _evidence_is_meaningful(profile):
        await message.reply_text(
            f"{mention} у меня пока почти без истории. Пару сообщений — не повод назначать человеку характер на всю жизнь."
        )
        raise ApplicationHandlerStop

    prompt = build_member_opinion_prompt(mention, profile)
    await bot_module._reply_with_gemini_feature(update, prompt, max_output_tokens=180)
    raise ApplicationHandlerStop


def install(bot_module: Any | None = None) -> bool:
    """Install the final prompt grounding wrapper after social_priority_runtime."""

    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    original = module.build_full_system_instruction
    if getattr(original, "_yayceslav_social_grounding", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def build_with_social_grounding(*args: Any, **kwargs: Any) -> str:
        user_id = _call_argument(
            args,
            kwargs,
            name="user_id",
            position=9,
            default=0,
        )
        token = state_engine.push_actor_scope(user_id)
        try:
            instruction = original(*args, **kwargs)
        finally:
            state_engine.pop_actor_scope(token)
        return instruction + _FINAL_GROUNDING_RULES

    build_with_social_grounding._yayceslav_social_grounding = True
    module.build_full_system_instruction = build_with_social_grounding
    module._yayceslav_social_grounding_installed = True
    _INSTALLED = True
    logging.warning(
        "Social grounding runtime ready: third-party evidence guard + per-sender legacy state scope"
    )
    return True


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    if not install():
        logging.warning("Social grounding runtime: bot module not ready")
        return

    add_handler = getattr(application, "add_handler", None)
    if callable(add_handler):
        # Before natural_router (-2) and ordinary group text handlers.  This is
        # intentionally narrow: only explicit @member opinion requests stop the
        # chain; every other message falls through untouched.
        add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, _member_opinion_handler),
            group=-4,
        )
    _PREPARED_APPLICATION_IDS.add(app_id)
