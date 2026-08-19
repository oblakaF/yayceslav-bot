"""Positive/social behavior policy for Yayceslav.

This is the warm counterpart to the hostile/dokop engines.  It detects real
positive events, keeps praise grounded in something the user actually said,
and deliberately caps warmth so the character never turns into a sycophantic
cheerleader.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass


PRAISE_RE = re.compile(
    r"\b(?:спасибо|спс|благодар\w*|молодец|красава|красавчик|"
    r"респект|уважух\w*|хорош(?:ая|ую)\s+работ\w*|ты\s+лучший)\b",
    re.IGNORECASE,
)

AFFECTION_RE = re.compile(
    r"\b(?:люблю\s+тебя|мы\s+тебя\s+любим|обожаю\s+тебя|"
    r"обожаем\s+тебя|ты\s+наш(?:\s+яйцеслав)?|родной\s+яйцеслав)\b",
    re.IGNORECASE,
)

ACHIEVEMENT_RE = re.compile(
    r"\b(?:я\s+(?:сдал|сдала|защитил|защитила|победил|победила|"
    r"закончил|закончила|доделал|доделала|сделал|сделала|получил|получила)|"
    r"меня\s+(?:взяли|приняли|повысили)|"
    r"у\s+меня\s+(?:получилось|получилас[ья]|вышло)|"
    r"наконец(?:-то)?\s+(?:сдал|сдала|закончил|закончила|сделал|сделала))\b",
    re.IGNORECASE,
)

SUPPORT_RE = re.compile(
    r"\b(?:пожелай\s+(?:мне\s+)?удачи|держи\s+за\s+меня\s+кулаки|"
    r"у\s+меня\s+(?:завтра|сегодня)\s+(?:экзамен|собеседование|защита|выступление)|"
    r"мне\s+(?:завтра|сегодня)\s+(?:на\s+)?(?:экзамен|собеседование|защиту|выступление))\b",
    re.IGNORECASE,
)

SHOW_RESULT_RE = re.compile(
    r"\b(?:зацени|оцени|смотри\s+что\s+(?:я\s+)?сделал|"
    r"вот\s+что\s+(?:я\s+)?сделал|вот\s+мой\s+(?:результат|проект|текст|дизайн|код))\b",
    re.IGNORECASE,
)

APOLOGY_RE = re.compile(
    r"\b(?:извини|извинись|прости|сорян|сори|виноват|виновата)\b",
    re.IGNORECASE,
)


_EVENT_WEIGHTS = {
    "praise": 1,
    "affection": 2,
    "achievement": 2,
    "support": 1,
    "show_result": 1,
    "reconciliation": 3,
}


@dataclass(frozen=True)
class PositiveState:
    affinity_points_30d: int = 0
    positive_streak: int = 0
    max_streak_30d: int = 0
    praise_events_30d: int = 0
    affection_events_30d: int = 0
    achievement_events_30d: int = 0
    support_events_30d: int = 0
    reconciliation_events_30d: int = 0


@dataclass(frozen=True)
class PositiveDecision:
    event: str | None = None
    affinity_level: int = 0
    affinity_label: str = "нейтрально"
    allow_spontaneous_warmth: bool = False


def event_weight(event: str | None) -> int:
    return int(_EVENT_WEIGHTS.get(str(event or ""), 0))


def detect_event(text: str, *, reconciliation: bool = False) -> str | None:
    """Return one strongest positive event for a message.

    One event per message is intentional: a single enthusiastic sentence must
    not inflate affinity by matching several overlapping regexes.
    """
    value = str(text or "").strip()
    if not value:
        return None
    if reconciliation and APOLOGY_RE.search(value):
        return "reconciliation"
    if AFFECTION_RE.search(value):
        return "affection"
    if PRAISE_RE.search(value):
        return "praise"
    if SUPPORT_RE.search(value):
        return "support"
    if SHOW_RESULT_RE.search(value):
        return "show_result"
    if ACHIEVEMENT_RE.search(value):
        return "achievement"
    return None


def affinity_level(points: int) -> int:
    value = max(0, int(points or 0))
    if value >= 35:
        return 4
    if value >= 18:
        return 3
    if value >= 8:
        return 2
    if value >= 3:
        return 1
    return 0


def affinity_label(level: int) -> str:
    return {
        0: "нейтрально",
        1: "симпатия",
        2: "расположен",
        3: "свой человек",
        4: "очень свой",
    }.get(max(0, min(int(level), 4)), "нейтрально")


def spontaneous_warmth_probability(state: PositiveState) -> float:
    """Small, bounded chance; never turns every reply into praise."""
    level = affinity_level(state.affinity_points_30d)
    if level <= 0 or state.positive_streak < 2:
        return 0.0
    chance = 0.015 + 0.012 * level + 0.006 * min(state.positive_streak, 5)
    return min(chance, 0.08)


def decide(
    text: str,
    state: PositiveState,
    *,
    reconciliation: bool = False,
    cooldown_ready: bool = True,
    serious_topic: bool = False,
    hostile: bool = False,
    rng=random,
) -> PositiveDecision:
    level = affinity_level(state.affinity_points_30d)
    event = detect_event(text, reconciliation=reconciliation)
    if hostile:
        return PositiveDecision(event=None, affinity_level=level, affinity_label=affinity_label(level))

    spontaneous = False
    if not serious_topic and event is None and cooldown_ready:
        chance = spontaneous_warmth_probability(state)
        spontaneous = chance > 0.0 and rng.random() < chance

    return PositiveDecision(
        event=event,
        affinity_level=level,
        affinity_label=affinity_label(level),
        allow_spontaneous_warmth=spontaneous,
    )


def build_instruction(
    decision: PositiveDecision,
    state: PositiveState,
    *,
    serious_topic: bool = False,
) -> str:
    """Build a compact behavior instruction, not a canned user-visible reply."""
    if serious_topic:
        return ""

    lines = [
        "\n\nPOSITIVE/SOCIAL LAYER:",
        "Позитив не должен быть приторным. Не хвали без реального повода и не соглашайся ради симпатии.",
        "Тепло выражай в характере Яйцеслава: коротко, живо, иногда с дружеской грубоватостью, но без унижения человека.",
    ]

    if decision.affinity_level >= 1:
        lines.append(
            f"За последние 30 дней Яйцеслав к этому человеку расположен на уровне "
            f"{decision.affinity_level}/4 ({decision.affinity_label}); позитивный streak={state.positive_streak}."
        )
    if decision.affinity_level >= 3:
        lines.append(
            "Это уже свой человек: допустимы редкие тёплые обращения и дружеская взаимность, но не лизоблюдство."
        )

    event = decision.event
    if event == "praise":
        lines.append("Пользователь похвалил/поблагодарил. Прими это коротко; не разворачивай монолог.")
    elif event == "affection":
        lines.append(
            "Пользователь проявил привязанность. Можно коротко ответить взаимностью в стиле персонажа: "
            "что-то уровня «И вы нормальные», «Свои», «Люблю вас, дебилов» — только если тон чата это допускает."
        )
    elif event == "achievement":
        lines.append(
            "Пользователь поделился реальным успехом. Искренне порадуйся и поздравь в 1–2 коротких фразах; "
            "сошлись на конкретном успехе из сообщения, не выдумывай заслуг."
        )
    elif event == "show_result":
        lines.append(
            "Пользователь показывает результат своей работы. Если в доступном контексте действительно видно/описано, "
            "что получилось хорошо, отметь 1 конкретную сильную сторону. Не выдумывай качество того, чего не видел."
        )
    elif event == "support":
        lines.append(
            "Пользователь просит поддержки перед событием. Дай короткое ободрение/удачу без лекции: уверенно и по-человечески."
        )
    elif event == "reconciliation":
        lines.append(
            "Это нормальное примирение после конфликта. Не продолжай старую ссору; коротко прими мир и временно будь теплее."
        )
    elif decision.allow_spontaneous_warmth:
        lines.append(
            "Редкий момент инициативного тепла: можно ОДНУ короткую дружескую позитивную реплику, "
            "но только если текущий текст даёт реальный повод. Если повода нет — ничего не добавляй."
        )

    return "\n".join(lines)
