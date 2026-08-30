from __future__ import annotations

import asyncio
import logging
import random
import sys
from datetime import date as date_type, timedelta
from typing import Any

import title_pools
from telegram.ext import Application

import member_profile_runtime
import member_repository


_PREPARED = False
RECENT_TITLE_COOLDOWN_DAYS = 14


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def classify_member(*, total_messages: int, week_messages: int) -> str:
    if int(total_messages or 0) <= 0:
        return "never_spoke"
    if int(week_messages or 0) <= 0:
        return "silent_week"
    return "active"


def choose_candidate(candidates: list[dict[str, Any]], previous_user_id: int | None, *, rng=random):
    eligible = [
        item for item in candidates
        if previous_user_id is None or int(item["user_id"]) != int(previous_user_id)
    ]
    if not eligible:
        return None
    return rng.choice(eligible)


def _ensure_schema(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(daily_title_assignments)")
        }
        if "title_kind" not in columns:
            connection.execute(
                "ALTER TABLE daily_title_assignments ADD COLUMN title_kind TEXT"
            )
        connection.commit()


def _known_chat_ids_sync(bot_module) -> list[int]:
    return member_repository.known_active_group_chat_ids(bot_module)


def _existing_assignment_sync(bot_module, chat_id: int, date: str):
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, title, announced_at, title_kind
            FROM daily_title_assignments
            WHERE chat_id = ? AND date = ?
            """,
            (chat_id, date),
        ).fetchone()
    if not row:
        return None
    return {
        "user_id": int(row[0]),
        "title": str(row[1]),
        "announced_at": row[2],
        "kind": str(row[3] or "active"),
    }


def _previous_winner_sync(bot_module, chat_id: int, current_date: str) -> int | None:
    previous_date = (date_type.fromisoformat(current_date) - timedelta(days=1)).isoformat()
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id
            FROM daily_title_assignments
            WHERE chat_id = ? AND date = ?
            """,
            (chat_id, previous_date),
        ).fetchone()
        if row:
            return int(row[0])
        try:
            row = connection.execute(
                """
                SELECT user_id
                FROM silent_title_assignments
                WHERE chat_id = ? AND date = ?
                """,
                (chat_id, previous_date),
            ).fetchone()
        except Exception:
            row = None
    return int(row[0]) if row else None


def _recent_titles_sync(bot_module, chat_id: int, current_date: str) -> tuple[str, ...]:
    cutoff = (date_type.fromisoformat(current_date) - timedelta(days=RECENT_TITLE_COOLDOWN_DAYS)).isoformat()
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT title
            FROM daily_title_assignments
            WHERE chat_id = ? AND date >= ? AND date < ?
            ORDER BY date DESC
            """,
            (int(chat_id), cutoff, str(current_date)),
        ).fetchall()
    return tuple(str(row[0]) for row in rows if row and row[0])


def _candidate_rows_sync(bot_module, chat_id: int, current_date: str) -> list[dict[str, Any]]:
    return member_repository.daily_title_candidates(bot_module, chat_id, current_date)


def _pick_title_for(
    candidate: dict[str, Any],
    kind: str,
    *,
    reputation_score: int | None = None,
    excluded_titles: tuple[str, ...] = (),
    rng=random,
) -> str:
    previous = candidate.get("previous_title")
    excluded = {str(item) for item in excluded_titles if str(item).strip()}
    if previous:
        excluded.add(str(previous))

    if kind == "never_spoke":
        pool = tuple(
            t for t in member_profile_runtime.SILENT_NEVER_TITLES
            if t not in excluded
        )
    elif kind == "silent_week":
        pool = tuple(
            t for t in member_profile_runtime.SILENT_WEEK_TITLES
            if t not in excluded
        )
    else:
        tier = (
            title_pools.tier_for_reputation(reputation_score)
            if reputation_score is not None
            else None
        )
        return title_pools.pick_title(
            previous,
            tier=tier,
            excluded_titles=excluded,
            rng=rng,
        )

    if not pool:
        base_pool = (
            member_profile_runtime.SILENT_NEVER_TITLES
            if kind == "never_spoke"
            else member_profile_runtime.SILENT_WEEK_TITLES
        )
        pool = tuple(t for t in base_pool if t != previous) or tuple(base_pool)
    return rng.choice(pool)


def _save_kind_sync(bot_module, chat_id: int, current_date: str, kind: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE daily_title_assignments
            SET title_kind = ?
            WHERE chat_id = ? AND date = ?
            """,
            (kind, chat_id, current_date),
        )
        connection.commit()


def _display_name_sync(bot_module, chat_id: int, user_id: int) -> str:
    return member_repository.display_name(bot_module, chat_id, user_id)


def _reputation_score_sync(bot_module, chat_id: int, user_id: int) -> int | None:
    try:
        import reputation_runtime
        return int(reputation_runtime._state_sync(bot_module, chat_id, user_id)["score"])
    except Exception:
        return None


def _format_message(display_name: str, title: str, kind: str) -> str:
    if kind == "never_spoke":
        return (
            f"Титул дня: {display_name} — «{title}». "
            "Сообщений за всю известную Яйцеславу историю: 0. Железная выдержка."
        )
    if kind == "silent_week":
        return (
            f"Титул дня: {display_name} — «{title}». "
            "За последние 7 дней: 0 сообщений. Читает профессионально."
        )
    return f"Титул дня: {display_name} — «{title}». До завтра носить не снимая."


async def run_unified_daily_titles(application: Application) -> None:
    bot_module = _find_bot_module()
    if bot_module is None:
        return

    now = bot_module.current_msk_datetime()
    if now.hour < 18:
        return
    current_date = now.date().isoformat()

    chat_ids = await asyncio.to_thread(_known_chat_ids_sync, bot_module)
    for chat_id in chat_ids:
        assignment = await asyncio.to_thread(
            _existing_assignment_sync, bot_module, chat_id, current_date
        )
        if assignment and assignment["announced_at"]:
            continue

        if assignment is None:
            candidates = await asyncio.to_thread(
                _candidate_rows_sync, bot_module, chat_id, current_date
            )
            previous_user_id = await asyncio.to_thread(
                _previous_winner_sync, bot_module, chat_id, current_date
            )
            chosen = choose_candidate(candidates, previous_user_id)
            if chosen is None:
                continue

            if not await member_profile_runtime._candidate_still_in_chat(
                application, chat_id, chosen["user_id"]
            ):
                remaining = [c for c in candidates if c["user_id"] != chosen["user_id"]]
                chosen = choose_candidate(remaining, previous_user_id)
                if chosen is None:
                    continue

            kind = classify_member(
                total_messages=chosen["total_messages"],
                week_messages=chosen["week_messages"],
            )
            reputation_score = await asyncio.to_thread(
                _reputation_score_sync, bot_module, chat_id, chosen["user_id"]
            )
            recent_titles = await asyncio.to_thread(
                _recent_titles_sync, bot_module, chat_id, current_date
            )
            title = _pick_title_for(
                chosen,
                kind,
                reputation_score=reputation_score,
                excluded_titles=recent_titles,
            )
            created = await asyncio.to_thread(
                bot_module.try_assign_daily_title_sync,
                chat_id,
                current_date,
                chosen["user_id"],
                title,
            )
            if not created:
                assignment = await asyncio.to_thread(
                    _existing_assignment_sync, bot_module, chat_id, current_date
                )
            else:
                await asyncio.to_thread(
                    _save_kind_sync, bot_module, chat_id, current_date, kind
                )
                assignment = {
                    "user_id": chosen["user_id"],
                    "title": title,
                    "announced_at": None,
                    "kind": kind,
                }

        if not assignment:
            continue

        display_name = await asyncio.to_thread(
            _display_name_sync, bot_module, chat_id, assignment["user_id"]
        )
        text = _format_message(display_name, assignment["title"], assignment["kind"])
        try:
            await application.bot.send_message(chat_id=chat_id, text=text)
        except Exception as error:
            logging.warning("Unified daily title announce failed chat=%s: %s", chat_id, error)
            continue
        await asyncio.to_thread(
            bot_module.mark_daily_title_announced_sync, chat_id, current_date
        )


def _prepare() -> None:
    global _PREPARED
    if _PREPARED:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    _ensure_schema(bot_module)
    bot_module.run_due_daily_titles = run_unified_daily_titles
    bot_module._yayceslav_silent_title_patch = True
    _PREPARED = True
    logging.warning(
        "Unified daily titles ready: one random member/day, no same winner two days in a row, "
        "recent chat-wide titles excluded for %s days",
        RECENT_TITLE_COOLDOWN_DAYS,
    )
