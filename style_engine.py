# ============================================================
# YAICESLAV V2 STYLE ENGINE
#
# Один ответ = один voice pack. Здесь же выбирается динамическая
# длина ответа, чтобы бот не выдавал одинаковую стену текста.
# ============================================================

from __future__ import annotations

import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Mapping, MutableMapping, Sequence

import state_engine


VOICE_PACK_CLASSIC = "classic"
VOICE_PACK_YOUTH = "youth"
VOICE_PACK_SKOOF = "skoof"
VOICE_PACK_OLD_RUSSIAN = "old_russian"
VOICE_PACK_BLAT = "blat"
VOICE_PACK_OPERATIVE = "operative"
VOICE_PACK_BATTLE_2017 = "battle_2017"
VOICE_PACK_POST_IRONY = "post_irony"
VOICE_PACK_RUNET_2007 = "runet_2007"
VOICE_PACK_RUNET_2012_2016 = "runet_2012_2016"
VOICE_PACK_LAN_2000S = "lan_2000s"
VOICE_PACK_RUNET_CLASSIC = "runet_classic"
VOICE_PACK_CHAT_NATIVE = "chat_native"

VOICE_PACKS = (
    VOICE_PACK_CLASSIC,
    VOICE_PACK_YOUTH,
    VOICE_PACK_SKOOF,
    VOICE_PACK_OLD_RUSSIAN,
    VOICE_PACK_BLAT,
    VOICE_PACK_OPERATIVE,
    VOICE_PACK_BATTLE_2017,
    VOICE_PACK_POST_IRONY,
    VOICE_PACK_RUNET_2007,
    VOICE_PACK_RUNET_2012_2016,
    VOICE_PACK_LAN_2000S,
    VOICE_PACK_RUNET_CLASSIC,
    VOICE_PACK_CHAT_NATIVE,
)

# Пользовательские character-настройки, которые должны жёстко
# фиксировать стиль. Скрытые пакеты (operative/battle/post-irony/blat)
# сюда намеренно не входят: они являются редкими внутренними голосами.
_FORCED_PACK_BY_CHARACTER = {
    "rus": VOICE_PACK_OLD_RUSSIAN,
    "professor": VOICE_PACK_CLASSIC,
    "calm": VOICE_PACK_CLASSIC,
}

# Веса намеренно различаются по режимам. Они не являются вероятностью
# вмешательства бота — только распределением стиля, когда ответ уже есть.
_VOICE_PACK_WEIGHTS_BY_MODE: dict[str, dict[str, float]] = {
    "normal": {
        VOICE_PACK_CLASSIC: 0.28,
        VOICE_PACK_YOUTH: 0.22,
        VOICE_PACK_SKOOF: 0.18,
        VOICE_PACK_OLD_RUSSIAN: 0.045,
        VOICE_PACK_BLAT: 0.10,
        VOICE_PACK_OPERATIVE: 0.03,
        VOICE_PACK_BATTLE_2017: 0.06,
        VOICE_PACK_POST_IRONY: 0.06,
        VOICE_PACK_RUNET_2007: 0.025,
        VOICE_PACK_RUNET_2012_2016: 0.035,
        VOICE_PACK_LAN_2000S: 0.04,
        VOICE_PACK_RUNET_CLASSIC: 0.025,
    },
    "greeting": {
        VOICE_PACK_CLASSIC: 0.20,
        VOICE_PACK_YOUTH: 0.23,
        VOICE_PACK_SKOOF: 0.20,
        VOICE_PACK_OLD_RUSSIAN: 0.055,
        VOICE_PACK_BLAT: 0.15,
        VOICE_PACK_OPERATIVE: 0.03,
        VOICE_PACK_BATTLE_2017: 0.05,
        VOICE_PACK_POST_IRONY: 0.05,
        VOICE_PACK_RUNET_2007: 0.03,
        VOICE_PACK_RUNET_2012_2016: 0.04,
        VOICE_PACK_LAN_2000S: 0.05,
        VOICE_PACK_RUNET_CLASSIC: 0.03,
    },
    "challenge": {
        VOICE_PACK_CLASSIC: 0.08,
        VOICE_PACK_YOUTH: 0.22,
        VOICE_PACK_SKOOF: 0.16,
        VOICE_PACK_OLD_RUSSIAN: 0.040,
        VOICE_PACK_BLAT: 0.22,
        VOICE_PACK_OPERATIVE: 0.05,
        VOICE_PACK_BATTLE_2017: 0.11,
        VOICE_PACK_POST_IRONY: 0.10,
        VOICE_PACK_RUNET_2007: 0.025,
        VOICE_PACK_RUNET_2012_2016: 0.04,
        VOICE_PACK_LAN_2000S: 0.06,
        VOICE_PACK_RUNET_CLASSIC: 0.025,
    },
    "hostile": {
        VOICE_PACK_CLASSIC: 0.04,
        VOICE_PACK_YOUTH: 0.18,
        VOICE_PACK_SKOOF: 0.15,
        VOICE_PACK_OLD_RUSSIAN: 0.030,
        VOICE_PACK_BLAT: 0.27,
        VOICE_PACK_OPERATIVE: 0.07,
        VOICE_PACK_BATTLE_2017: 0.14,
        VOICE_PACK_POST_IRONY: 0.10,
        VOICE_PACK_RUNET_2007: 0.02,
        VOICE_PACK_RUNET_2012_2016: 0.03,
        VOICE_PACK_LAN_2000S: 0.06,
        VOICE_PACK_RUNET_CLASSIC: 0.02,
    },
    "serious": {
        VOICE_PACK_CLASSIC: 1.0,
    },
}


@dataclass(frozen=True)
class VoicePackContext:
    conversation_mode: str = "normal"
    selected_character: str = "classic"
    serious_topic: bool = False


@dataclass(frozen=True)
class ResponseLengthContext:
    user_text: str = ""
    conversation_mode: str = "normal"
    message_intent: str = "unknown"
    response_preference: str = "normal"
    serious_topic: bool = False
    character_state: str = "normal"
    hostile_streak: int = 0


@dataclass(frozen=True)
class ResponseLengthPlan:
    category: str
    min_chars: int
    max_chars: int
    target_chars: int
    conversation_mode: str = "normal"
    hostile_streak: int = 0


_LENGTH_RANGES = {
    "micro": (45, 170),
    "short": (120, 320),
    "normal": (260, 600),
    "long": (520, 950),
}

_LENGTH_HISTORY: dict[int, deque[str]] = defaultdict(
    lambda: deque(maxlen=5)
)
_LENGTH_LAST_SEEN: dict[int, float] = {}

_COMPLEX_MARKERS = (
    "почему",
    "объясни",
    "разбери",
    "сравни",
    "проанализируй",
    "подробно",
    "пошагово",
    "причины",
    "варианты",
    "как устроен",
    "как работает",
    "what is the difference",
    "explain",
    "compare",
    "analyze",
    "step by step",
)

_SIMPLE_MARKERS = (
    "да или нет",
    "кто это",
    "что это",
    "сколько",
    "где",
    "когда",
    "норм?",
    "нормально?",
)


def _weighted_choice(
    weights: Mapping[str, float],
    *,
    rng=random,
) -> str:
    positive = [(key, max(0.0, float(value))) for key, value in weights.items()]
    total = sum(weight for _, weight in positive)

    if total <= 0:
        return next(iter(weights))

    marker = rng.random() * total
    cumulative = 0.0

    for key, weight in positive:
        cumulative += weight
        if marker <= cumulative:
            return key

    return positive[-1][0]


def choose_voice_pack(
    ctx: VoicePackContext,
    *,
    rng=random,
    chat_native_weight: float = 0.0,
    pack_multipliers: Mapping[str, float] | None = None,
) -> str:
    """Выбирает ровно один взаимоисключающий речевой пакет."""

    if ctx.serious_topic or ctx.conversation_mode == "serious":
        return VOICE_PACK_CLASSIC

    forced = _FORCED_PACK_BY_CHARACTER.get(ctx.selected_character)
    if forced:
        return forced

    mode = ctx.conversation_mode
    weights = dict(
        _VOICE_PACK_WEIGHTS_BY_MODE.get(
            mode,
            _VOICE_PACK_WEIGHTS_BY_MODE["normal"],
        )
    )

    if pack_multipliers:
        for pack_name, multiplier in pack_multipliers.items():
            if pack_name in weights:
                weights[pack_name] *= max(0.85, min(1.15, float(multiplier)))

    if chat_native_weight > 0.0 and mode != "serious":
        native_multiplier = 1.0
        if pack_multipliers:
            native_multiplier = max(
                0.85,
                min(1.15, float(pack_multipliers.get(VOICE_PACK_CHAT_NATIVE, 1.0))),
            )
        weights[VOICE_PACK_CHAT_NATIVE] = max(0.0, chat_native_weight) * native_multiplier

    # Chaos не создаёт новый стиль и не смешивает существующие — просто
    # уменьшает шанс нейтрального classic в пользу характерных пакетов.
    if ctx.selected_character == "chaos":
        weights[VOICE_PACK_CLASSIC] = weights.get(VOICE_PACK_CLASSIC, 0.0) * 0.35
        weights[VOICE_PACK_POST_IRONY] = weights.get(VOICE_PACK_POST_IRONY, 0.0) * 1.5
        weights[VOICE_PACK_BATTLE_2017] = weights.get(VOICE_PACK_BATTLE_2017, 0.0) * 1.35
        weights[VOICE_PACK_BLAT] = weights.get(VOICE_PACK_BLAT, 0.0) * 1.25

    selected = _weighted_choice(weights, rng=rng)
    if selected not in VOICE_PACKS:
        return VOICE_PACK_CLASSIC
    return selected


def _looks_complex(text: str) -> bool:
    lowered = text.lower().strip()
    if len(lowered) >= 260:
        return True
    return any(marker in lowered for marker in _COMPLEX_MARKERS)


def _looks_simple(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if len(lowered) <= 45:
        return True
    return any(marker in lowered for marker in _SIMPLE_MARKERS)


def _base_length_weights(ctx: ResponseLengthContext) -> dict[str, float]:
    if ctx.serious_topic or ctx.conversation_mode == "serious":
        return {
            "micro": 0.02,
            "short": 0.13,
            "normal": 0.52,
            "long": 0.33,
        }

    if ctx.conversation_mode == "greeting":
        return {
            "micro": 0.62,
            "short": 0.31,
            "normal": 0.07,
            "long": 0.00,
        }

    if ctx.conversation_mode == "hostile":
        if ctx.hostile_streak >= 3:
            # Третий-четвёртый подряд наезд: Яйцеслав может уже нормально
            # развернуться, но это всё ещё злой ответ, а не эссе.
            return {
                "micro": 0.10,
                "short": 0.34,
                "normal": 0.56,
                "long": 0.00,
            }
        # Первый-второй наезд: чаще естественный короткий посыл.
        return {
            "micro": 0.78,
            "short": 0.22,
            "normal": 0.00,
            "long": 0.00,
        }

    if ctx.conversation_mode == "challenge":
        return {
            "micro": 0.78,
            "short": 0.22,
            "normal": 0.00,
            "long": 0.00,
        }

    if ctx.message_intent in ("joke", "reaction", "small_talk"):
        return {
            "micro": 0.42,
            "short": 0.42,
            "normal": 0.14,
            "long": 0.02,
        }

    if _looks_complex(ctx.user_text):
        return {
            "micro": 0.01,
            "short": 0.10,
            "normal": 0.43,
            "long": 0.46,
        }

    if _looks_simple(ctx.user_text):
        return {
            "micro": 0.28,
            "short": 0.47,
            "normal": 0.22,
            "long": 0.03,
        }

    return {
        "micro": 0.09,
        "short": 0.34,
        "normal": 0.46,
        "long": 0.11,
    }


def _apply_preference_bias(
    weights: MutableMapping[str, float],
    preference: str,
) -> None:
    if preference == "short":
        weights["micro"] *= 1.6
        weights["short"] *= 1.45
        weights["normal"] *= 0.72
        weights["long"] *= 0.35
    elif preference == "detailed":
        # detailed — это склонность, а не приказ писать стену текста.
        weights["micro"] *= 0.55
        weights["short"] *= 0.75
        weights["normal"] *= 1.20
        weights["long"] *= 1.55


def _apply_history_bias(
    weights: MutableMapping[str, float],
    history: Sequence[str],
) -> None:
    if not history:
        return

    last = history[-1]

    # Verbosity fatigue: после длинного ответа следующий без нужды
    # заметно тянется к короткому ритму.
    if last == "long":
        weights["micro"] *= 1.70
        weights["short"] *= 1.65
        weights["normal"] *= 0.80
        weights["long"] *= 0.35

    # Два одинаковых класса подряд — третий становится маловероятным.
    if len(history) >= 2 and history[-1] == history[-2]:
        repeated = history[-1]
        weights[repeated] *= 0.12

    # Уже на этапе весов слегка отталкиваемся от предыдущей длины.
    # Жёсткий запрет двух одинаковых классов подряд применяется ниже
    # после первого случайного выбора.
    weights[last] *= 0.72


def _range_for_context(
    ctx: ResponseLengthContext,
    category: str,
) -> tuple[int, int]:
    if ctx.conversation_mode == "hostile":
        if ctx.hostile_streak >= 3:
            return {
                "micro": (25, 95),
                "short": (80, 220),
                "normal": (200, 450),
                "long": (200, 450),
            }[category]
        return {
            "micro": (12, 90),
            "short": (55, 180),
            "normal": (120, 220),
            "long": (120, 220),
        }[category]
    return _LENGTH_RANGES[category]


def choose_response_length(
    chat_id: int,
    ctx: ResponseLengthContext,
    *,
    rng=random,
    record: bool = True,
) -> ResponseLengthPlan:
    """Выбирает контекстную, но непредсказуемую длину ответа."""

    weights = _base_length_weights(ctx)
    _apply_preference_bias(weights, ctx.response_preference)

    for category, multiplier in state_engine.length_weight_multipliers(
        ctx.character_state
    ).items():
        if category in weights:
            weights[category] *= multiplier

    history = (
        _LENGTH_HISTORY[chat_id]
        if record
        else deque(maxlen=5)
    )
    # В конфликте естественнее несколько коротких ответов подряд, чем
    # искусственное чередование micro -> short -> normal ради разнообразия.
    use_history_bias = ctx.conversation_mode != "hostile"
    if use_history_bias:
        _apply_history_bias(weights, tuple(history))

    category = _weighted_choice(weights, rng=rng)

    # Пользователь просил, чтобы длина реально менялась, а не просто
    # имела немного другой шанс. Поэтому два соседних ответа одного
    # чата не получают один и тот же класс длины, пока существует
    # хотя бы одна допустимая альтернатива с ненулевым весом.
    if use_history_bias and history and category == history[-1]:
        alternatives = dict(weights)
        alternatives[history[-1]] = 0.0
        if any(weight > 0 for weight in alternatives.values()):
            category = _weighted_choice(alternatives, rng=rng)

    min_chars, max_chars = _range_for_context(ctx, category)
    target_chars = rng.randint(min_chars, max_chars)

    if record:
        history.append(category)
        _LENGTH_LAST_SEEN[chat_id] = time.monotonic()

    return ResponseLengthPlan(
        category=category,
        min_chars=min_chars,
        max_chars=max_chars,
        target_chars=target_chars,
        conversation_mode=ctx.conversation_mode,
        hostile_streak=ctx.hostile_streak,
    )


def build_length_instruction(plan: ResponseLengthPlan) -> str:
    """Переводит план длины в короткое указание модели."""

    rules = {
        "micro": (
            "Ответь очень коротко: одна-две естественные реплики. "
            "Не объясняй очевидное и не добавляй итоговый абзац."
        ),
        "short": (
            "Ответь компактно: обычно 2–4 коротких предложения. "
            "После ответа по сути остановись, если пояснения не нужны."
        ),
        "normal": (
            "Ответь со средней подробностью, но без лекционного тона. "
            "Разъясняй только то, что реально помогает вопросу."
        ),
        "long": (
            "Можно ответить развёрнуто, потому что контекст это оправдывает. "
            "Не раздувай очевидные места и не повторяй один вывод разными словами."
        ),
    }

    hostile_rule = ""
    if plan.conversation_mode == "hostile":
        if plan.hostile_streak >= 3:
            hostile_rule = (
                "\nЭто уже третий-четвёртый подряд наезд этого человека: можно развернуться "
                "в злой ответ на 2–5 предложений, но максимум примерно 450 символов. "
                "Не превращай разнос в лекцию."
            )
        else:
            hostile_rule = (
                "\nЭто первый-второй подряд наезд: ответ должен быть особенно коротким. "
                "Одна матерная фраза или короткий огрызок считается полноценным ответом; "
                "после него остановись."
            )

    return (
        "\n\nДинамическая длина этого конкретного ответа:\n"
        f"Класс: {plan.category}; ориентир около {plan.target_chars} символов.\n"
        f"{rules[plan.category]}\n"
        "Это ориентир, а не обязанность добивать текст до числа символов."
        + hostile_rule
    )


def build_voice_pack_guard(pack: str) -> str:
    """Жёстко запрещает смешивание речевых пакетов в одном ответе."""

    if pack not in VOICE_PACKS:
        pack = VOICE_PACK_CLASSIC

    return (
        "\n\nРечевой пакет этого ответа: "
        f"{pack}.\n"
        "Используй только этот речевой пакет. Не смешивай его с другими "
        "пакетами Яйцеслава даже ради одной шутки, обращения или слова."
    )


def get_length_history(chat_id: int) -> tuple[str, ...]:
    return tuple(_LENGTH_HISTORY.get(chat_id, ()))


def reset_length_history(chat_id: int | None = None) -> None:
    if chat_id is None:
        _LENGTH_HISTORY.clear()
        _LENGTH_LAST_SEEN.clear()
    else:
        _LENGTH_HISTORY.pop(chat_id, None)
        _LENGTH_LAST_SEEN.pop(chat_id, None)


def prune_stale_state(
    max_age_seconds: float,
    *,
    now: float | None = None,
) -> int:
    current = time.monotonic() if now is None else now
    stale = [
        chat_id
        for chat_id, last_seen in _LENGTH_LAST_SEEN.items()
        if current - last_seen > max_age_seconds
    ]
    for chat_id in stale:
        _LENGTH_HISTORY.pop(chat_id, None)
        _LENGTH_LAST_SEEN.pop(chat_id, None)
    return len(stale)
