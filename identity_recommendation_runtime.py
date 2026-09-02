"""Provider-neutral helpers for identity-derived recommendations.

Specialist providers own objective candidate facts. This module exposes only a
bounded view of Yayceslav's existing chat-local self-canon as a preference lens.
Recommendations may use this lens to explain a personal pick but must never
silently mutate canon or present taste as provider evidence.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

import self_canon_runtime


RECOMMENDATION_CANON_FIELDS: tuple[str, ...] = (
    "aesthetic",
    "values",
    "hobbies",
    "lifestyle",
    "quirks",
    "music",
)
MAX_CANON_VALUE_CHARS = 180


def load_identity_lens(bot_module: Any, chat_id: int) -> dict[str, str]:
    try:
        canon = self_canon_runtime.load_canon_sync(bot_module, int(chat_id))
    except Exception:
        logging.exception("Identity recommendation runtime could not load self-canon")
        return {}

    result: dict[str, str] = {}
    for key in RECOMMENDATION_CANON_FIELDS:
        value = " ".join(str(canon.get(key) or "").split()).strip()
        if value:
            result[key] = value[:MAX_CANON_VALUE_CHARS]
    return result


def format_identity_lens(lens: Mapping[str, str] | None) -> str:
    if not lens:
        return "не установлен"
    lines = [f"{key}: {str(value).strip()}" for key, value in lens.items() if str(value).strip()]
    return "\n".join(lines) if lines else "не установлен"


def identity_separation_rules(category: str) -> str:
    return (
        f"Провайдерские данные ниже описывают реальные кандидаты категории {category}; "
        "self-canon Яйцеслава — только его личный фильтр/реакция. Не выдавай вкус за объективный факт. "
        "Не добавляй кандидата, автора, жанр или тему в self-canon автоматически и не переписывай существующие "
        "черты из-за одной рекомендации. Если данных провайдера недостаточно, скажи это прямо вместо выдумки."
    )
