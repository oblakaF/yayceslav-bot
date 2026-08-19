# ============================================================
# YAICESLAV V2 SOCIAL CONTEXT
# ============================================================

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SocialContext:
    relationship_level: int = 0
    current_title: str | None = None
    joke_archetype: str | None = None
    total_messages: int = 0
    messages_30d: int = 0
    chat_level: int = 0
    hostility_today: int = 0
    friendliness_label: str = "Не хейтер"
    replies_to_bot: int = 0
    insults_to_bot: int = 0
    user_id: int = 0
    memory_chat_id: int = 0
    self_reported_facts: tuple[str, ...] = ()
    callback_terms: tuple[str, ...] = ()


def chat_level_from_messages(messages_30d: int) -> int:
    """Monthly chat XP: 0..4 from the last ~30 days of messages."""
    value = max(0, int(messages_30d or 0))
    if value >= 1000:
        return 4
    if value >= 500:
        return 3
    if value >= 300:
        return 2
    if value >= 100:
        return 1
    return 0


def chat_level_label(level: int) -> str:
    return {
        0: "Дно чата",
        1: "Прижился",
        2: "Местный",
        3: "Старожил",
        4: "Царь чата",
    }.get(max(0, min(int(level), 4)), "Дно чата")


def hostility_label(active_insults: int) -> str:
    value = max(0, int(active_insults or 0))
    if value >= 11:
        return "Гига-хейтер"
    if value >= 3:
        return "Мега-хейтер"
    if value >= 1:
        return "Мини-хейтер"
    return "Не хейтер"


def relationship_level_from_profile(profile: Mapping[str, Any] | None) -> int:
    if not profile:
        return 0

    # This is familiarity WITH Yaiceslav, not generic chat activity.
    replies = max(0, int(profile.get("replies_to_bot", 0) or 0))
    insults = max(0, int(profile.get("insults_to_bot", 0) or 0))
    score = replies + min(insults, 20)
    if score >= 40:
        return 4
    if score >= 15:
        return 3
    if score >= 5:
        return 2
    if score >= 1:
        return 1

    # Compatibility for old/lightweight test profiles.
    return max(0, int(profile.get("relationship_level", 0) or 0))


def relationship_status_label(chat_level: int, hostility_today: int) -> str:
    if hostility_today >= 11:
        return "Заклятый хейтер Яйцеслава"
    if hostility_today >= 3:
        return "Токсичный знакомый Яйцеслава"
    if hostility_today >= 1:
        return "Знакомый с претензиями"
    if chat_level >= 4:
        return "Любимчик Яйцеслава"
    if chat_level >= 3:
        return "Свой человек Яйцеслава"
    if chat_level >= 2:
        return "Кореш Яйцеслава"
    if chat_level >= 1:
        return "Симпатичный знакомый"
    return "Незнакомец"


def unlocked_social_features(chat_level: int) -> tuple[str, ...]:
    level = max(0, min(int(chat_level), 4))
    unlocked = ["базовый характер"]
    if level >= 1:
        unlocked.extend(("редкие callback-шутки", "обращения по титулу"))
    if level >= 2:
        unlocked.extend(("внутренние мемы", "тёплая фамильярность"))
    if level >= 3:
        unlocked.extend(("жёсткий дружеский стёб", "старые локальные callbacks"))
    if level >= 4:
        unlocked.append("царский social-mode")
    return tuple(unlocked)


def from_profile(profile: Mapping[str, Any] | None) -> SocialContext:
    if not profile:
        return SocialContext()

    total_messages = max(0, int(profile.get("total_messages", 0) or 0))
    messages_30d = max(
        0,
        int(profile.get("messages_30d", total_messages) or 0),
    )
    chat_level = int(profile.get("chat_level", chat_level_from_messages(messages_30d)) or 0)
    hostility = max(0, int(profile.get("hostility_today", 0) or 0))
    replies = max(0, int(profile.get("replies_to_bot", 0) or 0))
    insults = max(0, int(profile.get("insults_to_bot", 0) or 0))

    return SocialContext(
        relationship_level=relationship_level_from_profile(profile),
        current_title=(str(profile["current_title"]) if profile.get("current_title") else None),
        joke_archetype=(str(profile["joke_archetype"]) if profile.get("joke_archetype") else None),
        total_messages=total_messages,
        messages_30d=messages_30d,
        chat_level=chat_level,
        hostility_today=hostility,
        friendliness_label=str(profile.get("friendliness_label") or hostility_label(hostility)),
        replies_to_bot=replies,
        insults_to_bot=insults,
        user_id=max(0, int(profile.get("user_id", 0) or 0)),
        memory_chat_id=int(profile.get("_memory_chat_id", 0) or 0),
        self_reported_facts=tuple(
            str(item)
            for item in (profile.get("self_reported_facts") or ())
            if str(item).strip()
        ),
        callback_terms=tuple(
            str(item)
            for item in (profile.get("callback_terms") or ())
            if str(item).strip()
        ),
    )


def familiarity_label(level: int) -> str:
    if level >= 4:
        return "давний знакомый Яйцеслава"
    if level >= 3:
        return "хорошо знакомый Яйцеславу участник"
    if level >= 2:
        return "знакомый Яйцеславу участник"
    if level >= 1:
        return "слегка знакомый Яйцеславу участник"
    return "почти незнакомый Яйцеславу участник"


def _reserve_callback(ctx: SocialContext, term: str) -> None:
    if not ctx.memory_chat_id or not ctx.user_id:
        return
    try:
        import member_profile_runtime

        member_profile_runtime.reserve_callback_term(
            ctx.memory_chat_id,
            ctx.user_id,
            term,
        )
    except Exception:
        return


def _callback_chance(ctx: SocialContext) -> float:
    # Level 0 deliberately gets no automatic personal callback memory.
    return (0.0, 0.07, 0.13, 0.19, 0.25)[min(max(ctx.chat_level, 0), 4)]


def build_social_instruction(
    ctx: SocialContext,
    *,
    serious_topic: bool = False,
    rng=random,
) -> str:
    if serious_topic:
        return ""

    lines = [
        "Социальный контекст участника: " + familiarity_label(ctx.relationship_level) + ".",
        (
            f"Опыт в чате: {ctx.chat_level}/4 — {chat_level_label(ctx.chat_level)}; "
            f"за последние 30 дней около {ctx.messages_30d} сообщений."
        ),
        f"Текущее отношение к Яйцеславу сегодня: {ctx.friendliness_label}.",
    ]

    # Experience changes the bot's attitude. It is not just a decorative number.
    if ctx.chat_level == 0:
        lines.append(
            "Это новичок/редкий участник. Не еби его слишком жёстко: меньше личных подколов, никаких старых внутренних мемов без явного контекста."
        )
    elif ctx.friendliness_label == "Не хейтер":
        if ctx.chat_level >= 3:
            lines.append(
                "Это свой старожил и не хейтер: будь заметно теплее, по-дружески фамильярен, можно иногда обращаться как к своему и любя подкалывать."
            )
        else:
            lines.append(
                "Он уже прижился и не хейтер: Яйцеслав к нему расположен, отвечает добрее и теплее, иногда почти ласково, но без приторности."
            )
    elif ctx.friendliness_label == "Мини-хейтер":
        lines.append(
            "Сегодня он уже один-два раза наехал на Яйцеслава. Отвечай с лёгким ворчанием и недоверием, но не раздувай войну."
        )
    elif ctx.friendliness_label == "Мега-хейтер":
        lines.append(
            "Сегодня он системно хейтит Яйцеслава. В несерьёзном разговоре держи раздражённую дистанцию и отвечай колче; тепло временно убери."
        )
    else:
        lines.append(
            "Сегодня это ГИГА-ХЕЙТЕР: до нормального извинения Яйцеслав раздражён на него в КАЖДОЙ несерьёзной прямой беседе. Не притворяйся добрым. Периодически уместно коротко потребовать извиниться или сказать, что сначала пусть извинится. Не повторяй одну и ту же формулировку."
        )

    if ctx.chat_level >= 1 and ctx.current_title and rng.random() < (0.08 + 0.03 * ctx.chat_level):
        lines.append(
            "Редкий допустимый callback на его шуточный титул: "
            + repr(ctx.current_title)
            + ". Используй только если подходит текущей реплике."
        )

    if ctx.chat_level >= 2 and ctx.joke_archetype and rng.random() < (0.05 + 0.02 * ctx.chat_level):
        lines.append(
            "Админ чата задал ему шуточный архетип: "
            + repr(ctx.joke_archetype)
            + ". Это шутливый ярлык, не факт о личности."
        )

    if ctx.self_reported_facts and rng.random() < min(0.20, 0.08 + 0.025 * ctx.chat_level):
        fact = rng.choice(ctx.self_reported_facts)
        lines.append(
            "Пользователь сам раньше попросил запомнить факт о себе: "
            + repr(fact)
            + ". Можно редко и естественно сослаться на него, если к месту."
        )

    if ctx.callback_terms and rng.random() < _callback_chance(ctx):
        term = rng.choice(ctx.callback_terms)
        lines.append(
            "Этот же пользователь недавно сам упоминал тему/слово: "
            + repr(term)
            + ". Можно один раз естественно припомнить это в шутке. "
            "Это НЕ доказательство постоянного факта или предпочтения."
        )
        _reserve_callback(ctx, term)

    return "\n".join(lines)
