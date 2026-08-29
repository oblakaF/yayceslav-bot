from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterable


_POSITIVE = {
    "😂": 2.0,
    "🤣": 2.0,
    "🔥": 1.6,
    "❤": 1.4,
    "❤️": 1.4,
    "🥰": 1.2,
    "👏": 1.0,
    "👍": 0.7,
}

_NEGATIVE = {
    "👎": -1.2,
    "🤡": -0.9,
    "💩": -0.9,
    "😐": -0.35,
}

_MAX_SHIFT = 0.15


@dataclass(frozen=True)
class ResponseTrace:
    chat_id: int | None = None
    chat_type: str = "private"
    voice_pack: str = "classic"
    humor_type: str | None = None
    verdict_used: bool = False
    serious_topic: bool = False
    conversation_mode: str = "normal"
    message_intent: str = "unknown"


_CURRENT_TRACE: ContextVar[ResponseTrace | None] = ContextVar(
    "yayceslav_response_trace",
    default=None,
)


def reset_current_trace() -> None:
    _CURRENT_TRACE.set(None)


def set_current_trace(trace: ResponseTrace) -> None:
    _CURRENT_TRACE.set(trace)


def get_current_trace() -> ResponseTrace | None:
    return _CURRENT_TRACE.get()


def _reaction_emoji(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    return getattr(item, "emoji", None)


def score_reactions(items: Iterable[Any]) -> tuple[float, int]:
    score = 0.0
    count = 0
    for item in items or ():
        emoji = _reaction_emoji(item)
        if not emoji:
            continue
        count += 1
        score += _POSITIVE.get(emoji, _NEGATIVE.get(emoji, 0.0))
    return score, count


def reaction_delta(old_items: Iterable[Any], new_items: Iterable[Any]) -> tuple[float, int]:
    old_score, old_count = score_reactions(old_items)
    new_score, new_count = score_reactions(new_items)
    return new_score - old_score, new_count - old_count


def _multiplier(values: list[float]) -> float:
    if not values:
        return 1.0
    recent = values[:20]
    avg = sum(recent) / len(recent)
    confidence = min(1.0, len(recent) / 6.0)
    normalized = max(-1.0, min(1.0, avg / 2.0))
    return max(1.0 - _MAX_SHIFT, min(1.0 + _MAX_SHIFT, 1.0 + normalized * _MAX_SHIFT * confidence))


def build_adaptation(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Строит мягкие коэффициенты по последним сообщениям с реакциями."""

    pack_values: dict[str, list[float]] = {}
    taunt_values: list[float] = []
    layered_values: list[float] = []
    verdict_values: list[float] = []
    reacted_messages = 0

    for row in rows:
        reaction_count = int(row.get("reaction_count") or 0)
        if reaction_count <= 0:
            continue
        reacted_messages += 1
        per_reaction = float(row.get("reaction_score") or 0.0) / max(1, reaction_count)

        pack_name = str(row.get("voice_pack") or "classic")
        pack_values.setdefault(pack_name, []).append(per_reaction)

        humor_type = str(row.get("humor_type") or "")
        if humor_type in {"taunt", "comeback"}:
            taunt_values.append(per_reaction)
        elif humor_type == "layered_taunt":
            layered_values.append(per_reaction)

        if bool(row.get("verdict_used")):
            verdict_values.append(per_reaction)

    return {
        "pack_multipliers": {
            pack: _multiplier(values)
            for pack, values in pack_values.items()
        },
        "taunt_multiplier": _multiplier(taunt_values),
        "layered_multiplier": _multiplier(layered_values),
        "verdict_multiplier": _multiplier(verdict_values),
        "reacted_messages": reacted_messages,
    }
