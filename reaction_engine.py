# ============================================================
# YAICESLAV V2 SMART EMOJI REACTIONS
#
# ВАЖНО: этот модуль управляет только Telegram emoji-реакциями.
# Он НЕ уменьшает вероятность текстовых random replies.
# ============================================================

from __future__ import annotations

import random
import re


# Снижаем текущую частоту emoji: 0.80 -> 0.72 -> 0.55. Слишком много
# реакций на ровном месте выглядело как шум, а не как живое внимание.
# Это множитель поверх сохранённого reaction_chance чата, поэтому
# существующие настройки в Railway SQLite менять не требуется.
EMOJI_REACTION_FREQUENCY_MULTIPLIER = 0.55
CONTEXT_REASON_FLOOR = 0.85

# Пулы для случая, когда конкретная причина в сообщении НЕ распознана --
# тогда выбор смещается по репутации отправителя у Яйцеслава, а не
# остаётся чистой монеткой по общему нейтральному пулу.
COLD_REACTION_EMOJIS: tuple[str, ...] = ("🤡", "💩", "👎")
WARM_REACTION_EMOJIS: tuple[str, ...] = ("🔥", "👍", "😂")
REPUTATION_COLD_THRESHOLD = -26
REPUTATION_WARM_THRESHOLD = 26


def reputation_biased_pool(
    reputation_score: int | None,
    neutral_pool,
) -> tuple[str, ...]:
    """Colors the reason-less reaction pool by standing with this person.

    Only applies when NO specific message-content reason was detected --
    a genuinely negative/positive reason already picks its own emoji via
    REACTION_REASON_EMOJIS/V2_REASON_EMOJIS, independent of reputation.
    """

    if reputation_score is None:
        return tuple(neutral_pool)
    score = int(reputation_score)
    if score <= REPUTATION_COLD_THRESHOLD:
        return COLD_REACTION_EMOJIS
    if score >= REPUTATION_WARM_THRESHOLD:
        return WARM_REACTION_EMOJIS
    return tuple(neutral_pool)

# Причина -> набор подходящих Telegram reaction emoji.
# Ключи дополняют уже существующие причины hard-mode.
V2_REASON_EMOJIS: dict[str, tuple[str, ...]] = {
    "provocation": ("🐍", "🗿", "🪦"),
    "praise": ("🔥", "👍"),
    "complaint": ("😭", "🗿"),
    "agreement": ("👍", "🔥"),
    "mysticism": ("🧿", "🗿"),
    "absurdity": ("🫃", "🍆", "🗿"),
    "dead_argument": ("🪦", "🗿"),
    "suspicious_drama": ("🐍", "👎"),
}

_INTENT_TO_REASON = {
    "provocation": "provocation",
    "praise": "praise",
    "complaint": "complaint",
    "agreement": "agreement",
}

_MYSTICISM_RE = re.compile(
    r"\b(?:гороскоп\w*|знак\s+зодиака|пророчеств\w*|предсказан\w*|"
    r"судьб\w*|карм\w*|зв[её]зд\w*\s+(?:говор\w*|шепч\w*|сошл\w*)|"
    r"сглаз\w*|порч\w*|таро|руны|экстрасенс\w*)\b",
    re.IGNORECASE,
)

_ABSURDITY_RE = re.compile(
    r"\b(?:абсурд\w*|сюр\w*|что\s+за\s+дичь|это\s+дичь|"
    r"какой\s+бред|что\s+за\s+бред|цирк\s+какой-то)\b",
    re.IGNORECASE,
)

_DEAD_ARGUMENT_RE = re.compile(
    r"\b(?:аргумент\w*\s+(?:умер\w*|сдох\w*|развал\w*)|"
    r"разн[её]с\w*\s+аргумент|убил\w*\s+аргумент|"
    r"разъеб\w*\s+аргумент|разъёб\w*\s+аргумент)\b",
    re.IGNORECASE,
)

_DRAMA_RE = re.compile(
    r"\b(?:подстав\w*|крыс\w*|срач\w*|интриг\w*|"
    r"стуч\w*|настуч\w*|слил\w*\s+(?:переписк\w*|инф\w*))\b",
    re.IGNORECASE,
)


def detect_context_reason(
    text: str,
    *,
    resolved_intent: str = "unknown",
    confidence: str = "low",
) -> str | None:
    """Дополнительные V2-причины после более точных старых эвристик."""

    stripped = text.strip()
    if not stripped:
        return None

    # Явные смысловые маркеры имеют приоритет даже при слабом intent.
    if _MYSTICISM_RE.search(stripped):
        return "mysticism"
    if _DEAD_ARGUMENT_RE.search(stripped):
        return "dead_argument"
    if _DRAMA_RE.search(stripped):
        return "suspicious_drama"
    if _ABSURDITY_RE.search(stripped):
        return "absurdity"

    if confidence == "low":
        return None

    return _INTENT_TO_REASON.get(resolved_intent)


def effective_emoji_reaction_chance(
    reaction_chance: float,
    *,
    has_context_reason: bool,
) -> float:
    """
    Применяет текущий множитель 0.72 именно к emoji reaction
    ПОСЛЕ context floor.

    Например normal 0.70 -> 0.504; context reason 0.85 -> 0.612.
    Текстовая random_reply_chance сюда вообще не передаётся.
    """

    base = float(reaction_chance)
    if has_context_reason:
        base = max(base, CONTEXT_REASON_FLOOR)

    return max(
        0.0,
        min(1.0, base * EMOJI_REACTION_FREQUENCY_MULTIPLIER),
    )


def pick_v2_emoji(
    reason: str | None,
    *,
    rng=random,
) -> str | None:
    if not reason:
        return None

    options = V2_REASON_EMOJIS.get(reason)
    if not options:
        return None
    return rng.choice(options)
