# ============================================================
# YAICESLAV V2 AGGRESSION / DOKOP ENGINE
#
# roughness отвечает за лексику. Этот модуль отдельно решает,
# стоит ли Яйцеславу цепляться к тезису/противоречию.
# ============================================================

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass


_STRONG_CLAIM_RE = re.compile(
    r"\b(?:точно|очевидно|сто\s*процентов|100\s*%|без\s+вариантов|"
    r"все\s+знают|это\s+факт|я\s+уверен|я\s+уверена|однозначно|"
    r"неоспоримо|абсолютно\s+точно)\b",
    re.IGNORECASE,
)

_CONTRADICTION_CUE_RE = re.compile(
    r"\b(?:наоборот|вообще-то|нет,?\s+я|я\s+не\s+это\s+говорил|"
    r"я\s+не\s+это\s+говорила|ты\s+не\s+понял|ты\s+не\s+поняла|"
    r"я\s+передумал|я\s+передумала)\b",
    re.IGNORECASE,
)

_DOKOP_ELIGIBLE_INTENTS = {
    "disagreement",
    "correction",
    "provocation",
    "group_banter",
    "unknown",
}

_DOKOP_BLOCKED_INTENTS = {
    "serious_issue",
    "emotional_support",
    "technical_help",
    "factual_lookup",
    "recommendation",
    "request",
    "clarification",
}


@dataclass(frozen=True)
class AggressionContext:
    user_text: str
    intent: str = "unknown"
    confidence: str = "low"
    chat_type: str = "private"
    roughness: str = "medium"
    relationship_level: int = 0
    serious_topic: bool = False
    emotional_tone: str = "neutral"
    recent_messages: tuple[str, ...] = ()
    chat_id: int = 0
    user_id: int = 0


@dataclass(frozen=True)
class AggressionDecision:
    active: bool = False
    mode: str = "none"
    callback_reference: str | None = None
    reason: str | None = None


class AggressionCooldown:
    def __init__(self, cooldown_seconds: float = 110.0):
        self.cooldown_seconds = cooldown_seconds
        self._last: dict[tuple[int, int], float] = {}

    def ready(self, chat_id: int, user_id: int, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        last = self._last.get((chat_id, user_id))
        return last is None or current - last >= self.cooldown_seconds

    def record(self, chat_id: int, user_id: int, *, now: float | None = None) -> None:
        self._last[(chat_id, user_id)] = time.monotonic() if now is None else now

    def clear(self) -> None:
        self._last.clear()


COOLDOWN = AggressionCooldown()


def _base_probability(ctx: AggressionContext) -> float:
    if ctx.serious_topic:
        return 0.0
    if ctx.emotional_tone in {"sad", "anxious", "grieving"}:
        return 0.0
    if ctx.intent in _DOKOP_BLOCKED_INTENTS:
        return 0.0
    if ctx.chat_type not in {"group", "supergroup"}:
        return 0.0
    if ctx.roughness == "low":
        return 0.0

    chance = 0.08

    if ctx.intent in _DOKOP_ELIGIBLE_INTENTS:
        chance += 0.08
    if ctx.intent in {"provocation", "disagreement", "correction"}:
        chance += 0.12
    if _STRONG_CLAIM_RE.search(ctx.user_text):
        chance += 0.15
    if _CONTRADICTION_CUE_RE.search(ctx.user_text):
        chance += 0.10
    if ctx.roughness == "high":
        chance += 0.08
    if ctx.relationship_level >= 2:
        chance += 0.03
    if ctx.relationship_level >= 4:
        chance += 0.04

    return min(chance, 0.48)


def decide_aggression(
    ctx: AggressionContext,
    *,
    rng=random,
    cooldown: AggressionCooldown = COOLDOWN,
) -> AggressionDecision:
    """Решает, нужно ли инициативно докопаться до тезиса."""

    chance = _base_probability(ctx)
    if chance <= 0:
        return AggressionDecision()

    if not cooldown.ready(ctx.chat_id, ctx.user_id):
        return AggressionDecision(reason="cooldown")

    if rng.random() >= chance:
        return AggressionDecision(reason="chance")

    recent = tuple(message for message in ctx.recent_messages if message.strip())

    if recent and (
        ctx.intent in {"disagreement", "correction"}
        or _CONTRADICTION_CUE_RE.search(ctx.user_text)
    ):
        mode = "callback_challenge"
        callback = recent[-1]
        reason = "possible_shift_or_correction"
    elif _STRONG_CLAIM_RE.search(ctx.user_text):
        mode = "challenge_confidence"
        callback = None
        reason = "strong_claim"
    elif ctx.intent == "provocation":
        mode = "take_the_bait"
        callback = None
        reason = "provocation"
    else:
        mode = "nitpick"
        callback = None
        reason = "group_banter"

    cooldown.record(ctx.chat_id, ctx.user_id)
    return AggressionDecision(
        active=True,
        mode=mode,
        callback_reference=callback,
        reason=reason,
    )


def build_aggression_instruction(decision: AggressionDecision) -> str:
    if not decision.active:
        return ""

    rules = {
        "callback_challenge": (
            "Можно коротко прицепиться к возможной смене позиции: сопоставь текущую реплику с недавней. "
            "Не выдумывай противоречие — если его нет, просто не настаивай."
        ),
        "challenge_confidence": (
            "Пользователь говорит слишком категорично. Коротко потребуй смысл/основание или поддень самоуверенность."
        ),
        "take_the_bait": (
            "Пользователь явно провоцирует. Можно принять словесный вызов и ответить жёстче, но по теме."
        ),
        "nitpick": (
            "Можно инициативно докопаться до одного слабого места в формулировке или аргументе. Только одно место, без лекции."
        ),
    }

    text = (
        "\n\nV2 aggression/dokop: "
        + rules.get(decision.mode, rules["nitpick"])
        + " Это поведенческая установка, а не новый речевой стиль: лексику бери ТОЛЬКО из уже выбранного voice pack."
    )

    if decision.callback_reference:
        text += (
            "\nНедавняя реплика для возможного callback: "
            + repr(decision.callback_reference)
        )

    return text
