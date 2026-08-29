# ============================================================
# YAICESLAV V2 PASSIVE ENGINE
#
# Random drops используют уже существующий hard-mode слот случайной
# текстовой реплики — не создают второй независимый спам-канал.
# Fatigue — отдельная реакция на частые вызовы бота, с cooldown.
# ============================================================

from __future__ import annotations

import random
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import humor_engine
import voice_packs
import sticker_runtime  # noqa: F401 - installs Telegram sticker hooks at startup


RANDOM_DROP_MIN_ACTIVITY = 12
RANDOM_DROP_CHANCE_WHEN_SLOT_OPEN = 0.62
RANDOM_DROP_COOLDOWN_SECONDS = 8 * 60

FATIGUE_WINDOW_SECONDS = 10 * 60
FATIGUE_CALL_THRESHOLD = 8
FATIGUE_COOLDOWN_SECONDS = 12 * 60
FATIGUE_TRIGGER_CHANCE = 0.72


SHORT_ACK_RE = re.compile(
    r"^\s*(?:100\s*%|да|нет|ага|угу|точно|верно|согласен|согласна|"
    r"ок|окей|ладно|понял|поняла|ясно|\+1|[👍👎👌🤝🔥😂🤣🙂]+)[.!?,\s]*$",
    re.IGNORECASE,
)

CONTEXTUAL_TEXT_REASONS = frozenset(
    {
        "provocation",
        "contradiction",
        "absurdity",
        "dead_argument",
        "suspicious_drama",
        "mysticism",
        "direct_insult",
        "insult",
        "joke",
        "sarcasm",
        "cringe",
    }
)


def random_text_intervention_allowed(
    text: str,
    reaction_reason: str | None,
) -> bool:
    """Не позволяет hard-mode отвечать случайным текстом без смыслового повода."""

    stripped = text.strip()
    if not stripped or SHORT_ACK_RE.fullmatch(stripped):
        return False
    return bool(reaction_reason and reaction_reason in CONTEXTUAL_TEXT_REASONS)


@dataclass(frozen=True)
class PassiveDropDecision:
    active: bool = False
    pack_name: str | None = None
    text: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FatigueDecision:
    active: bool = False
    pack_name: str | None = None
    text: str | None = None
    call_count: int = 0
    reason: str | None = None


_ACTIVITY_SINCE_DROP: dict[int, int] = defaultdict(int)
_LAST_ACTIVITY_AT: dict[int, float] = {}
_LAST_DROP_AT: dict[int, float] = {}
_RECENT_DROPS: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=12))

_BOT_CALLS: dict[int, deque[float]] = defaultdict(deque)
_LAST_FATIGUE_AT: dict[int, float] = {}
_RECENT_FATIGUE: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=8))


def reset_state() -> None:
    _ACTIVITY_SINCE_DROP.clear()
    _LAST_ACTIVITY_AT.clear()
    _LAST_DROP_AT.clear()
    _RECENT_DROPS.clear()
    _BOT_CALLS.clear()
    _LAST_FATIGUE_AT.clear()
    _RECENT_FATIGUE.clear()


def note_group_activity(
    chat_id: int,
    *,
    serious_topic: bool = False,
) -> int:
    """Считает обычную активность. Серьёзная тема не разгоняет random drop."""

    if serious_topic:
        return _ACTIVITY_SINCE_DROP.get(chat_id, 0)

    _ACTIVITY_SINCE_DROP[chat_id] += 1
    _LAST_ACTIVITY_AT[chat_id] = time.monotonic()
    return _ACTIVITY_SINCE_DROP[chat_id]


def _not_recently_used(
    candidate: str,
    history: deque[str],
) -> bool:
    normalized = humor_engine.normalize_phrase(candidate)
    return not any(
        humor_engine.is_too_similar(normalized, past)
        for past in history
    )


def _pick_nonrepeating(
    pool: tuple[str, ...],
    history: deque[str],
    *,
    rng=random,
) -> str | None:
    if not pool:
        return None

    candidates = list(pool)
    rng.shuffle(candidates)

    for candidate in candidates:
        if _not_recently_used(candidate, history):
            history.append(humor_engine.normalize_phrase(candidate))
            return candidate

    history.clear()
    chosen = rng.choice(candidates)
    history.append(humor_engine.normalize_phrase(chosen))
    return chosen


def _drop_capable_packs() -> list[voice_packs.VoicePack]:
    return [
        pack
        for pack in voice_packs.VOICE_PACKS.values()
        if pack.drops
    ]


def maybe_random_drop(
    chat_id: int,
    *,
    existing_random_reply_slot_open: bool,
    serious_topic: bool = False,
    now: float | None = None,
    rng=random,
) -> PassiveDropDecision:
    """
    Иногда заменяет уже разрешённую hard-mode random reply на style drop.

    Самостоятельно новый слот сообщения не создаёт.
    """

    current = time.monotonic() if now is None else now

    if serious_topic:
        return PassiveDropDecision(reason="serious")
    if not existing_random_reply_slot_open:
        return PassiveDropDecision(reason="no_existing_slot")
    if _ACTIVITY_SINCE_DROP.get(chat_id, 0) < RANDOM_DROP_MIN_ACTIVITY:
        return PassiveDropDecision(reason="low_activity")

    last = _LAST_DROP_AT.get(chat_id)
    if last is not None and current - last < RANDOM_DROP_COOLDOWN_SECONDS:
        return PassiveDropDecision(reason="cooldown")

    if rng.random() >= RANDOM_DROP_CHANCE_WHEN_SLOT_OPEN:
        return PassiveDropDecision(reason="chance")

    packs = _drop_capable_packs()
    if not packs:
        return PassiveDropDecision(reason="no_packs")

    pack = rng.choice(packs)
    text = _pick_nonrepeating(
        pack.drops,
        _RECENT_DROPS[chat_id],
        rng=rng,
    )
    if not text:
        return PassiveDropDecision(reason="empty_pack")

    _LAST_DROP_AT[chat_id] = current
    _ACTIVITY_SINCE_DROP[chat_id] = 0

    return PassiveDropDecision(
        active=True,
        pack_name=pack.name,
        text=text,
        reason="styled_drop",
    )


def _prune_calls(chat_id: int, now: float) -> deque[float]:
    calls = _BOT_CALLS[chat_id]
    cutoff = now - FATIGUE_WINDOW_SECONDS
    while calls and calls[0] < cutoff:
        calls.popleft()
    return calls


def note_bot_call_and_maybe_fatigue(
    chat_id: int,
    *,
    pack_name: str,
    serious_topic: bool = False,
    now: float | None = None,
    rng=random,
) -> FatigueDecision:
    """Фиксирует вызов и иногда ворчит после частых обращений."""

    current = time.monotonic() if now is None else now

    if serious_topic:
        return FatigueDecision(reason="serious")

    calls = _prune_calls(chat_id, current)
    calls.append(current)
    call_count = len(calls)

    if call_count < FATIGUE_CALL_THRESHOLD:
        return FatigueDecision(call_count=call_count, reason="below_threshold")

    last = _LAST_FATIGUE_AT.get(chat_id)
    if last is not None and current - last < FATIGUE_COOLDOWN_SECONDS:
        return FatigueDecision(call_count=call_count, reason="cooldown")

    if rng.random() >= FATIGUE_TRIGGER_CHANCE:
        return FatigueDecision(call_count=call_count, reason="chance")

    pack = voice_packs.get_voice_pack(pack_name)
    if not pack.grumbling:
        # Не переключаем style только ради fatigue.
        return FatigueDecision(
            pack_name=pack.name,
            call_count=call_count,
            reason="pack_has_no_grumbling",
        )

    text = _pick_nonrepeating(
        pack.grumbling,
        _RECENT_FATIGUE[chat_id],
        rng=rng,
    )
    if not text:
        return FatigueDecision(call_count=call_count, reason="empty_pack")

    _LAST_FATIGUE_AT[chat_id] = current
    return FatigueDecision(
        active=True,
        pack_name=pack.name,
        text=text,
        call_count=call_count,
        reason="fatigue",
    )


def prune_stale_state(
    max_age_seconds: float,
    *,
    now: float | None = None,
) -> int:
    current = time.monotonic() if now is None else now
    chat_ids = set(_ACTIVITY_SINCE_DROP) | set(_LAST_ACTIVITY_AT) | set(_LAST_DROP_AT) | set(_RECENT_DROPS) | set(_BOT_CALLS) | set(_LAST_FATIGUE_AT) | set(_RECENT_FATIGUE)
    stale = []
    for chat_id in chat_ids:
        calls = _BOT_CALLS.get(chat_id)
        latest_call = calls[-1] if calls else 0.0
        latest = max(
            _LAST_ACTIVITY_AT.get(chat_id, 0.0),
            _LAST_DROP_AT.get(chat_id, 0.0),
            _LAST_FATIGUE_AT.get(chat_id, 0.0),
            latest_call,
        )
        if latest <= 0.0 or current - latest > max_age_seconds:
            stale.append(chat_id)
    for chat_id in stale:
        _ACTIVITY_SINCE_DROP.pop(chat_id, None)
        _LAST_ACTIVITY_AT.pop(chat_id, None)
        _LAST_DROP_AT.pop(chat_id, None)
        _RECENT_DROPS.pop(chat_id, None)
        _BOT_CALLS.pop(chat_id, None)
        _LAST_FATIGUE_AT.pop(chat_id, None)
        _RECENT_FATIGUE.pop(chat_id, None)
    return len(stale)



def build_fatigue_instruction(decision: FatigueDecision) -> str:
    if not decision.active or not decision.text:
        return ""

    return (
        "\n\nV2 fatigue: ботом слишком часто пользуются за короткий период. "
        "Можно ОДИН раз коротко поворчать, используя только текущий voice pack. "
        "Допустимый материал этого же пакета: "
        + repr(decision.text)
        + ". Не отказывайся отвечать на сам вопрос."
    )