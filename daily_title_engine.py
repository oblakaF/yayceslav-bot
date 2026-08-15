# ============================================================
# YAICESLAV V2 DAILY TITLE ENGINE
#
# Выбор кандидата отдельно от SQLite/Telegram, чтобы алгоритм был
# тестируемым. Персистентность и отправка находятся в bot.py.
# ============================================================

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping


DAILY_TITLE_START_HOUR_MSK = 18


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


def format_daily_title_message(
    display_name: str,
    title: str,
) -> str:
    return (
        "Титул дня определён. "
        f"{display_name} — «{title}». "
        "Решение окончательное до завтра, апелляции принимаются в воображении."
    )
