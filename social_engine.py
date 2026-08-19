# ============================================================
# YAICESLAV V2 SOCIAL CONTEXT
#
# Uses the existing participant profile plus lightweight rotating callback
# topics. Automatic topics are NOT treated as personal facts: they only mean
# "this same user recently mentioned this word/phrase".
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
    user_id: int = 0
    memory_chat_id: int = 0
    self_reported_facts: tuple[str, ...] = ()
    callback_terms: tuple[str, ...] = ()


def from_profile(profile: Mapping[str, Any] | None) -> SocialContext:
    if not profile:
        return SocialContext()

    return SocialContext(
        relationship_level=max(0, int(profile.get("relationship_level", 0) or 0)),
        current_title=(str(profile["current_title"]) if profile.get("current_title") else None),
        joke_archetype=(str(profile["joke_archetype"]) if profile.get("joke_archetype") else None),
        total_messages=max(0, int(profile.get("total_messages", 0) or 0)),
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
        # Callback rotation is optional polish; never break a normal answer.
        return


def build_social_instruction(
    ctx: SocialContext,
    *,
    serious_topic: bool = False,
    rng=random,
) -> str:
    """
    Gives Gemini a small amount of social continuity.

    Stable user-supplied facts (/remember_me), titles and archetypes are rare
    callbacks. Automatic callback_terms are even more constrained: they mean
    only that this person recently mentioned the topic, never that it is a
    stable preference, hobby, job or biographical fact.
    """

    if serious_topic:
        return ""

    lines = [
        "Социальный контекст участника: " + familiarity_label(ctx.relationship_level) + "."
    ]

    if ctx.relationship_level >= 2:
        lines.append(
            "С ним можно быть чуть фамильярнее, чем с незнакомцем, но не превращай каждый ответ в подкол."
        )
    else:
        lines.append(
            "Не веди себя так, будто у вас уже многолетняя личная история."
        )

    if ctx.current_title and rng.random() < 0.16:
        lines.append(
            "Редкий допустимый callback на его шуточный титул: "
            + repr(ctx.current_title)
            + ". Используй только если реально подходит текущей реплике."
        )

    if ctx.joke_archetype and rng.random() < 0.11:
        lines.append(
            "Админ чата задал ему шуточный архетип: "
            + repr(ctx.joke_archetype)
            + ". Это только шутливый ярлык; можно редко обыграть, но не выдавай за факт о личности."
        )

    # Explicit user-supplied long-term memory. This is the only place where a
    # stored item may be phrased as a real fact, because the user asked the bot
    # to remember it with /remember_me.
    if ctx.self_reported_facts and rng.random() < 0.16:
        fact = rng.choice(ctx.self_reported_facts)
        lines.append(
            "Пользователь сам раньше попросил запомнить факт о себе: "
            + repr(fact)
            + ". Можно редко и естественно сослаться на него, если это к месту; не тащи его в каждый разговор."
        )

    # Automatic personal callback memory: one recent topic, chosen from this
    # exact user's own messages. "Steam" is allowed here a day later, but it
    # must be framed as a recent mention, not as an inferred permanent hobby.
    if ctx.callback_terms and rng.random() < 0.18:
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
