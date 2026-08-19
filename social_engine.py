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
    chat_level: int = 0
    replies_to_bot: int = 0
    insults_to_bot: int = 0
    user_id: int = 0
    memory_chat_id: int = 0
    self_reported_facts: tuple[str, ...] = ()
    callback_terms: tuple[str, ...] = ()


def chat_level_from_messages(total_messages: int) -> int:
    total = max(0, int(total_messages or 0))
    if total >= 300:
        return 4
    if total >= 120:
        return 3
    if total >= 40:
        return 2
    if total >= 5:
        return 1
    return 0


def chat_level_label(level: int) -> str:
    if level >= 4:
        return "Несущая стена чата"
    if level >= 3:
        return "Старожил"
    if level >= 2:
        return "Местный"
    if level >= 1:
        return "Заселился"
    return "Турист"


def relationship_level_from_profile(profile: Mapping[str, Any] | None) -> int:
    if not profile:
        return 0

    # New V2 meaning: relationship is about interactions WITH Yaiceslav,
    # not merely the total number of messages in the group.
    if "replies_to_bot" in profile or "insults_to_bot" in profile:
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
        return 0

    # Compatibility for unit tests / old lightweight profiles.
    return max(0, int(profile.get("relationship_level", 0) or 0))


def relationship_status_label(level: int, *, insults_to_bot: int = 0) -> str:
    if level >= 4:
        return (
            "Заклятый кореш Яйцеслава"
            if insults_to_bot >= 8
            else "Боевой брат Яйцеслава"
        )
    if level >= 3:
        return "Кореш Яйцеслава"
    if level >= 2:
        return "Товарищ по перепалке"
    if level >= 1:
        return "Знакомый Яйцеслава"
    return "Пока чужой человек"


def from_profile(profile: Mapping[str, Any] | None) -> SocialContext:
    if not profile:
        return SocialContext()

    total_messages = max(0, int(profile.get("total_messages", 0) or 0))
    replies = max(0, int(profile.get("replies_to_bot", 0) or 0))
    insults = max(0, int(profile.get("insults_to_bot", 0) or 0))

    return SocialContext(
        relationship_level=relationship_level_from_profile(profile),
        current_title=(str(profile["current_title"]) if profile.get("current_title") else None),
        joke_archetype=(str(profile["joke_archetype"]) if profile.get("joke_archetype") else None),
        total_messages=total_messages,
        chat_level=chat_level_from_messages(total_messages),
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
    # Kept for prompt/test compatibility; UI uses relationship_status_label().
    if level >= 4:
        return "давний знакомый чата"
    if level >= 3:
        return "хорошо знакомый участник"
    if level >= 2:
        return "постоянный участник"
    if level >= 1:
        return "знакомый участник"
    return "почти незнакомый участник"


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
    # Chat level now has an actual behavioral effect. A veteran can receive
    # more callbacks/inside jokes; a newcomer should not be treated as an old
    # drinking buddy after five minutes in the group.
    by_level = (0.04, 0.08, 0.13, 0.18, 0.23)
    return by_level[min(max(ctx.chat_level, 0), 4)]


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
        f"Уровень в этом чате: {ctx.chat_level}/4 — {chat_level_label(ctx.chat_level)}.",
    ]

    if ctx.relationship_level >= 2 or ctx.chat_level >= 2:
        lines.append(
            "С ним можно быть чуть фамильярнее, чем с незнакомцем, но не превращай каждый ответ в подкол."
        )
    else:
        lines.append(
            "Не веди себя так, будто у вас уже многолетняя личная история."
        )

    if ctx.chat_level >= 3:
        lines.append(
            "Это старожил чата: допустимы более внутренние шутки и чуть более жёсткий дружеский стёб, если текущий контекст несерьёзный."
        )
    elif ctx.chat_level == 0:
        lines.append(
            "Это почти новичок: не перегружай ответ внутренними мемами и старыми callback-шутками."
        )

    if ctx.current_title and rng.random() < min(0.22, 0.08 + 0.03 * ctx.chat_level):
        lines.append(
            "Редкий допустимый callback на его шуточный титул: "
            + repr(ctx.current_title)
            + ". Используй только если реально подходит текущей реплике."
        )

    if ctx.joke_archetype and rng.random() < min(0.16, 0.06 + 0.025 * ctx.chat_level):
        lines.append(
            "Админ чата задал ему шуточный архетип: "
            + repr(ctx.joke_archetype)
            + ". Это только шутливый ярлык; можно редко обыграть, но не выдавай за факт о личности."
        )

    if ctx.self_reported_facts and rng.random() < min(0.20, 0.10 + 0.025 * ctx.chat_level):
        fact = rng.choice(ctx.self_reported_facts)
        lines.append(
            "Пользователь сам раньше попросил запомнить факт о себе: "
            + repr(fact)
            + ". Можно редко и естественно сослаться на него, если это к месту; не тащи его в каждый разговор."
        )

    if ctx.callback_terms and rng.random() < _callback_chance(ctx):
        term = rng.choice(ctx.callback_terms)
        lines.append(
            "Этот же пользователь недавно сам упоминал тему/слово: "
            + repr(term)
            + ". Можно один раз естественно припомнить это в шутке. "
            "ЖЁСТКО: это НЕ доказательство постоянного факта или предпочтения. "
            "Говори в духе «ты же недавно про X вещал», а не «ты всегда X / ты играешь в X / ты работаешь X», "
            "если такого явного факта нет в памяти пользователя."
        )
        _reserve_callback(ctx, term)

    return "\n".join(lines)
