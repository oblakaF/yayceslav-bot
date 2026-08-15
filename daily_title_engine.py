# ============================================================
# YAICESLAV V2 DAILY TITLE ENGINE
#
# Выбор кандидата отдельно от SQLite/Telegram, чтобы алгоритм был
# тестируемым. Персистентность и отправка находятся в bot.py.
#
# V2 compatibility bridge:
# bot.py исторически импортирует JOKE_TITLES из vocabulary.py.
# Этот модуль загружается РАНЬШЕ этого импорта, поэтому здесь мы
# заменяем активный legacy-пул на чистые V2-пулы из title_pools.py.
# Старые уже сохранённые current_title в SQLite не меняются.
# ============================================================

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

import title_pools
import vocabulary as _legacy_vocabulary


DAILY_TITLE_START_HOUR_MSK = 18

# Единственный активный источник титулов в V2.
TITLE_POOLS = title_pools.TITLE_POOLS
ALL_TITLES = title_pools.ALL_TITLES

# Подменяем только активные экспортируемые пулы. Старые именованные
# константы V1 внутри vocabulary.py больше не участвуют в выдаче V2.
_legacy_vocabulary.JOKE_TITLE_CATEGORIES = TITLE_POOLS
_legacy_vocabulary.JOKE_TITLES = ALL_TITLES


@dataclass(frozen=True)
class DailyTitleCandidate:
    user_id: int
    messages_today: int
    display_name: str = ""
    previous_title: str | None = None


def is_assignment_window_open(msk_now: datetime) -> bool:
    return msk_now.hour >= DAILY_TITLE_START_HOUR_MSK


def build_candidates(
    daily_activity: Iterable[Mapping[str, Any]],
    known_members: Iterable[Mapping[str, Any]],
) -> list[DailyTitleCandidate]:
    members_by_id = {
        int(member["user_id"]): member
        for member in known_members
        if member.get("user_id") is not None
    }

    candidates: list[DailyTitleCandidate] = []

    for row in daily_activity:
        user_id = int(row.get("user_id", 0) or 0)
        messages = int(row.get("messages", 0) or 0)
        if user_id <= 0 or messages <= 0:
            continue

        member = members_by_id.get(user_id, {})
        candidates.append(
            DailyTitleCandidate(
                user_id=user_id,
                messages_today=messages,
                display_name=str(
                    member.get("current_display_name")
                    or f"участник {user_id}"
                ),
                previous_title=(
                    str(member["current_title"])
                    if member.get("current_title")
                    else None
                ),
            )
        )

    return candidates


def choose_candidate(
    candidates: list[DailyTitleCandidate],
    *,
    rng=random,
) -> DailyTitleCandidate | None:
    if not candidates:
        return None

    # Не превращаем титул в награду «кто больше всех пишет»:
    # активность только даёт право участвовать, затем выбор равновероятный.
    return rng.choice(candidates)


def pick_title(
    previous_title: str | None = None,
    *,
    rng=random,
) -> str:
    """Публичный V2-picker: личность -> один из её 10 титулов."""

    return title_pools.pick_title(
        previous_title,
        rng=rng,
    )


def format_daily_title_message(
    display_name: str,
    title: str,
) -> str:
    return (
        "Титул дня определён. "
        f"{display_name} — «{title}». "
        "Решение окончательное до завтра, апелляции принимаются в воображении."
    )
