# ============================================================
# YAICESLAV V2 CHARACTER STATE MACHINE
#
# Состояние — НЕ речевой стиль. Оно регулирует ритм/агрессию/длину,
# но никогда не выбирает второй voice pack.
# ============================================================

from __future__ import annotations

import time
from dataclasses import dataclass


STATE_COLD_START = "cold_start"
STATE_WARMING_UP = "warming_up"
STATE_NORMAL = "normal"
STATE_HOSTILE_RESPONSE = "hostile_response"
STATE_SERIOUS = "serious"
STATE_ANNOYED = "annoyed"
STATE_ARGUMENTATIVE = "argumentative"

STATES = {
    STATE_COLD_START,
    STATE_WARMING_UP,
    STATE_NORMAL,
    STATE_HOSTILE_RESPONSE,
    STATE_SERIOUS,
    STATE_ANNOYED,
    STATE_ARGUMENTATIVE,
}

COLD_AFTER_SECONDS = 6 * 3600
WARMING_UP_MESSAGES = 4
ANNOYED_DURATION_SECONDS = 5 * 60
ARGUMENTATIVE_DURATION_SECONDS = 3 * 60


@dataclass
class _ChatState:
    message_count: int = 0
    last_seen_at: float | None = None
    annoyed_until: float = 0.0
    argumentative_until: float = 0.0
    annoyed_marked_at: float = 0.0
    argumentative_marked_at: float = 0.0
    annoyed_marked_at: float = 0.0
    argumentative_marked_at: float = 0.0


_CHAT_STATE: dict[int, _ChatState] = {}


def reset_state() -> None:
    _CHAT_STATE.clear()


def _entry(chat_id: int) -> _ChatState:
    return _CHAT_STATE.setdefault(chat_id, _ChatState())


def mark_annoyed(chat_id: int, *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    entry = _entry(chat_id)
    entry.annoyed_until = max(
        entry.annoyed_until,
        current + ANNOYED_DURATION_SECONDS,
    )
    entry.annoyed_marked_at = current
    entry.annoyed_marked_at = current


def mark_argumentative(chat_id: int, *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    entry = _entry(chat_id)
    entry.argumentative_until = max(
        entry.argumentative_until,
        current + ARGUMENTATIVE_DURATION_SECONDS,
    )
    entry.argumentative_marked_at = current
    entry.argumentative_marked_at = current


def resolve_state(
    chat_id: int,
    *,
    conversation_mode: str,
    now: float | None = None,
    record: bool = True,
) -> str:
    """Возвращает текущее состояние с приоритетом safety/конфликта."""

    current = time.monotonic() if now is None else now
    entry = _entry(chat_id)

    annoyed_active = current < entry.annoyed_until
    argumentative_active = current < entry.argumentative_until

    if conversation_mode == "serious":
        state = STATE_SERIOUS
    elif conversation_mode == "hostile":
        state = STATE_HOSTILE_RESPONSE
    elif annoyed_active and argumentative_active:
        state = (
            STATE_ARGUMENTATIVE
            if entry.argumentative_marked_at >= entry.annoyed_marked_at
            else STATE_ANNOYED
        )
    elif annoyed_active:
        state = STATE_ANNOYED
    elif argumentative_active:
        state = STATE_ARGUMENTATIVE
    elif entry.last_seen_at is None or current - entry.last_seen_at >= COLD_AFTER_SECONDS:
        state = STATE_COLD_START
    elif entry.message_count < WARMING_UP_MESSAGES:
        state = STATE_WARMING_UP
    else:
        state = STATE_NORMAL

    if record:
        # После долгого отсутствия начинаем новый локальный разговорный цикл.
        if entry.last_seen_at is None or current - entry.last_seen_at >= COLD_AFTER_SECONDS:
            entry.message_count = 1
        else:
            entry.message_count += 1
        entry.last_seen_at = current

    return state


def aggression_probability_bonus(state: str) -> float:
    if state == STATE_ARGUMENTATIVE:
        return 0.10
    if state == STATE_ANNOYED:
        return 0.04
    if state == STATE_HOSTILE_RESPONSE:
        return 0.08
    return 0.0


def length_weight_multipliers(state: str) -> dict[str, float]:
    """Поведенческий ритм: раздражённый/спорящий Яйцеслав обычно короче."""

    if state == STATE_ANNOYED:
        return {
            "micro": 1.65,
            "short": 1.45,
            "normal": 0.72,
            "long": 0.32,
        }
    if state in {STATE_ARGUMENTATIVE, STATE_HOSTILE_RESPONSE}:
        return {
            "micro": 1.25,
            "short": 1.35,
            "normal": 0.82,
            "long": 0.48,
        }
    if state == STATE_SERIOUS:
        return {
            "micro": 0.65,
            "short": 0.85,
            "normal": 1.15,
            "long": 1.15,
        }
    if state == STATE_COLD_START:
        return {
            "micro": 1.15,
            "short": 1.10,
            "normal": 0.95,
            "long": 0.80,
        }
    return {
        "micro": 1.0,
        "short": 1.0,
        "normal": 1.0,
        "long": 1.0,
    }


def build_state_instruction(state: str) -> str:
    rules = {
        STATE_COLD_START: "После долгой паузы не изображай сразу старую перепалку: начни естественно.",
        STATE_WARMING_UP: "Разговор только раскручивается: характер уже виден, но не форсируй конфликт.",
        STATE_NORMAL: "Обычный живой режим без дополнительного перекоса.",
        STATE_HOSTILE_RESPONSE: "Идёт прямая словесная перепалка: отвечай жёстко и коротко, без реальных угроз.",
        STATE_SERIOUS: "Серьёзное состояние: агрессия и мемные выходки отключены.",
        STATE_ANNOYED: "Яйцеслав слегка задолбан: допускается короткое ворчание, меньше объяснений и воды.",
        STATE_ARGUMENTATIVE: "Яйцеслав уже втянулся в спор: держи линию аргумента и не начинай тему заново.",
    }
    if state not in STATES:
        state = STATE_NORMAL
    return (
        "\n\nV2 character state: "
        + state
        + ". "
        + rules[state]
        + " Это НЕ речевой стиль и не разрешение смешивать voice packs."
    )
