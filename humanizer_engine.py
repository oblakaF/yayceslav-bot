from __future__ import annotations

import random
import re
from dataclasses import dataclass


SPLIT_CHANCE = 0.08
TYPO_CHANCE = 0.012
LAZY_SHORT_CHANCE = 0.004
LAZY_REFUSAL_CHANCE = 0.0008

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+")
_CYRILLIC_WORD_RE = re.compile(r"\b[а-яё]{5,12}\b", re.IGNORECASE)

_IMPORTANT_INTENTS = {
    "technical_help",
    "factual_lookup",
    "recommendation",
    "serious_issue",
    "emotional_support",
    "request",
}

_IMPORTANT_MARKERS = (
    "объясни",
    "почему",
    "как сделать",
    "как работает",
    "помоги",
    "ошибка",
    "код",
    "документ",
    "файл",
    "деньги",
    "здоров",
    "врач",
    "лекар",
    "право",
    "срочно",
    "найди",
    "проверь",
    "сравни",
    "проанализируй",
)


@dataclass(frozen=True)
class HumanizedReply:
    messages: tuple[str, ...]
    delays: tuple[float, ...]
    effect: str = "none"


def _eligible_group_chat(trace) -> bool:
    return bool(
        trace
        and getattr(trace, "chat_type", "") in {"group", "supergroup"}
        and not getattr(trace, "serious_topic", False)
        and getattr(trace, "conversation_mode", "normal") != "serious"
    )


def _important_request(user_text: str, trace) -> bool:
    intent = getattr(trace, "message_intent", "unknown") if trace else "unknown"
    if intent in _IMPORTANT_INTENTS:
        return True
    lowered = (user_text or "").lower()
    if len(lowered) >= 160:
        return True
    return any(marker in lowered for marker in _IMPORTANT_MARKERS)


def _first_compact_sentence(text: str, limit: int = 190) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    parts = _SENTENCE_BOUNDARY_RE.split(text, maxsplit=1)
    first = parts[0].strip()
    if len(first) <= limit:
        return first
    clipped = first[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return clipped + "…"


def _split_naturally(text: str) -> tuple[str, str] | None:
    if len(text) < 120 or len(text) > 850:
        return None
    if "```" in text or "http://" in text or "https://" in text:
        return None

    matches = list(_SENTENCE_BOUNDARY_RE.finditer(text))
    if not matches:
        return None

    target = len(text) * 0.52
    match = min(matches, key=lambda item: abs(item.start() - target))
    first = text[: match.start()].strip()
    second = text[match.end() :].strip()
    if len(first) < 45 or len(second) < 35:
        return None
    return first, second


def _make_typo(text: str, *, rng=random) -> tuple[str, str] | None:
    candidates = [
        match
        for match in _CYRILLIC_WORD_RE.finditer(text)
        if match.group(0).islower()
    ]
    if not candidates:
        return None

    match = rng.choice(candidates)
    word = match.group(0)
    if len(set(word)) < 3:
        return None

    indexes = [i for i in range(1, len(word) - 2) if word[i] != word[i + 1]]
    if not indexes:
        return None
    index = rng.choice(indexes)
    typo = word[:index] + word[index + 1] + word[index] + word[index + 2 :]
    changed = text[: match.start()] + typo + text[match.end() :]
    return changed, "*" + word


def humanize_reply(
    text: str,
    *,
    user_text: str = "",
    trace=None,
    rng=random,
) -> HumanizedReply:
    """Применяет максимум один человеческий эффект за ответ."""

    clean = (text or "").strip()
    if not clean or not _eligible_group_chat(trace):
        return HumanizedReply((clean,), (0.0,))

    important = _important_request(user_text, trace)

    if not important:
        roll = rng.random()
        if roll < LAZY_REFUSAL_CHANCE:
            return HumanizedReply(("бля лень. гугл есть.",), (0.0,), "lazy_refusal")
        if roll < LAZY_REFUSAL_CHANCE + LAZY_SHORT_CHANCE:
            short = _first_compact_sentence(clean)
            if short:
                return HumanizedReply(("бля лень расписывать. короче: " + short,), (0.0,), "lazy_short")

    if rng.random() < TYPO_CHANCE:
        typo = _make_typo(clean, rng=rng)
        if typo:
            changed, correction = typo
            return HumanizedReply(
                (changed, correction),
                (0.0, rng.uniform(0.55, 1.45)),
                "typo_correction",
            )

    if rng.random() < SPLIT_CHANCE:
        split = _split_naturally(clean)
        if split:
            first, second = split
            return HumanizedReply(
                (first, second),
                (0.0, rng.uniform(0.7, 2.4)),
                "split",
            )

    return HumanizedReply((clean,), (0.0,))
