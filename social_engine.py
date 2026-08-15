# ============================================================
# YAICESLAV V2 SOCIAL CONTEXT
#
# Использует уже существующий профиль участника. Не хранит новые
# чувствительные данные и не делает скрытых выводов о человеке.
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


def from_profile(profile: Mapping[str, Any] | None) -> SocialContext:
    if not profile:
        return SocialContext()

    return SocialContext(
        relationship_level=max(0, int(profile.get("relationship_level", 0) or 0)),
        current_title=(str(profile["current_title"]) if profile.get("current_title") else None),
        joke_archetype=(str(profile["joke_archetype"]) if profile.get("joke_archetype") else None),
        total_messages=max(0, int(profile.get("total_messages", 0) or 0)),
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


def familiarity_humor_bonus(level: int) -> float:
    """Небольшой бонус к фамильярности, не приказ обязательно шутить."""
    if level >= 4:
        return 0.10
    if level >= 3:
        return 0.07
    if level >= 2:
        return 0.04
    if level >= 1:
        return 0.02
    return 0.0


def build_social_instruction(
    ctx: SocialContext,
    *,
    serious_topic: bool = False,
    rng=random,
) -> str:
    """
    Даёт Gemini минимум социального контекста.

    Титул и архетип всплывают редко; иначе они быстро превращаются
    из callback-шутки в навязчивое обращение.
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

    return "\n".join(lines)
