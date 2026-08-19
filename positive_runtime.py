"""Persistent positive-affinity runtime for Yayceslav.

Non-destructive companion to relationship_experience_runtime:
- records bounded positive events in separate tables;
- keeps a real positive streak that directed hostility resets;
- aggregates affinity over the last 30 calendar days;
- appends grounded warm behavior to the final system instruction;
- never owns or wraps Application.run_polling.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date as date_type, timedelta

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters

import positive_engine
import primitive_compact_guard


_PREPARED_APPLICATION_IDS: set[int] = set()
_LAST_SPONTANEOUS_MONO: dict[tuple[int, int], float] = {}
SPONTANEOUS_COOLDOWN_SECONDS = 6 * 60 * 60

_EVENT_COLUMNS = {
    "praise": "praise_events",
    "affection": "affection_events",
    "achievement": "achievement_events",
    "support": "support_events",
    "show_result": "result_events",
    "reconciliation": "reconciliation_events",
}

# Score/streak farming protection. Counts may continue increasing for stats,
# but only the first N events of each kind per calendar day affect affinity.
_DAILY_REWARD_CAP = {
    "praise": 3,
    "affection": 2,
    "achievement": 3,
    "support": 2,
    "show_result": 2,
    "reconciliation": 1,
}


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "get_db_connection", None))
            and callable(getattr(module, "build_full_system_instruction", None))
        ):
            return module
    return None


def _current_date(bot_module) -> str:
    current = getattr(bot_module, "current_msk_datetime", None)
    if callable(current):
        return current().date().isoformat()
    return date_type.today().isoformat()


def _window_start(current_date: str) -> str:
    return (date_type.fromisoformat(current_date) - timedelta(days=29)).isoformat()


def _initialize_tables(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_positive_daily (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                praise_events INTEGER NOT NULL DEFAULT 0,
                affection_events INTEGER NOT NULL DEFAULT 0,
                achievement_events INTEGER NOT NULL DEFAULT 0,
                support_events INTEGER NOT NULL DEFAULT 0,
                result_events INTEGER NOT NULL DEFAULT 0,
                reconciliation_events INTEGER NOT NULL DEFAULT 0,
                affinity_points INTEGER NOT NULL DEFAULT 0,
                last_positive_at TEXT,
                PRIMARY KEY (chat_id, user_id, date)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_positive_state (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                current_streak INTEGER NOT NULL DEFAULT 0,
                max_streak INTEGER NOT NULL DEFAULT 0,
                last_positive_at TEXT,
                last_hostile_at TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        connection.commit()


def _daily_event_count_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    current_date: str,
    event: str,
) -> int:
    column = _EVENT_COLUMNS[event]
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            f"SELECT {column} FROM member_positive_daily "
            "WHERE chat_id = ? AND user_id = ? AND date = ?",
            (chat_id, user_id, current_date),
        ).fetchone()
    return int((row[0] if row else 0) or 0)


def _record_event_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    current_date: str,
    event: str,
) -> bool:
    """Record an event; return whether it earned affinity/streak this time."""
    if event not in _EVENT_COLUMNS:
        return False
    column = _EVENT_COLUMNS[event]
    previous_count = _daily_event_count_sync(
        bot_module, chat_id, user_id, current_date, event
    )
    rewarded = previous_count < _DAILY_REWARD_CAP[event]
    points = positive_engine.event_weight(event) if rewarded else 0

    with bot_module.get_db_connection() as connection:
        connection.execute(
            f"""
            INSERT INTO member_positive_daily
                (chat_id, user_id, date, {column}, affinity_points, last_positive_at)
            VALUES (?, ?, ?, 1, ?, datetime('now'))
            ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                {column} = {column} + 1,
                affinity_points = affinity_points + excluded.affinity_points,
                last_positive_at = datetime('now')
            """,
            (chat_id, user_id, current_date, points),
        )
        if rewarded:
            connection.execute(
                """
                INSERT INTO member_positive_state
                    (chat_id, user_id, current_streak, max_streak, last_positive_at)
                VALUES (?, ?, 1, 1, datetime('now'))
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    current_streak = current_streak + 1,
                    max_streak = MAX(max_streak, current_streak + 1),
                    last_positive_at = datetime('now')
                """,
                (chat_id, user_id),
            )
        connection.commit()
    return rewarded


def _reset_streak_sync(bot_module, chat_id: int, user_id: int) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_positive_state
                (chat_id, user_id, current_streak, max_streak, last_hostile_at)
            VALUES (?, ?, 0, 0, datetime('now'))
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                current_streak = 0,
                last_hostile_at = datetime('now')
            """,
            (chat_id, user_id),
        )
        connection.commit()


def _state_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    current_date: str,
) -> positive_engine.PositiveState:
    start = _window_start(current_date)
    with bot_module.get_db_connection() as connection:
        daily = connection.execute(
            """
            SELECT
                COALESCE(SUM(affinity_points), 0),
                COALESCE(SUM(praise_events), 0),
                COALESCE(SUM(affection_events), 0),
                COALESCE(SUM(achievement_events), 0),
                COALESCE(SUM(support_events), 0),
                COALESCE(SUM(reconciliation_events), 0)
            FROM member_positive_daily
            WHERE chat_id = ? AND user_id = ? AND date BETWEEN ? AND ?
            """,
            (chat_id, user_id, start, current_date),
        ).fetchone()
        streak = connection.execute(
            """
            SELECT current_streak, max_streak
            FROM member_positive_state
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, user_id),
        ).fetchone()

    values = daily or (0, 0, 0, 0, 0, 0)
    streak_values = streak or (0, 0)
    return positive_engine.PositiveState(
        affinity_points_30d=int(values[0] or 0),
        positive_streak=int(streak_values[0] or 0),
        max_streak_30d=int(streak_values[1] or 0),
        praise_events_30d=int(values[1] or 0),
        affection_events_30d=int(values[2] or 0),
        achievement_events_30d=int(values[3] or 0),
        support_events_30d=int(values[4] or 0),
        reconciliation_events_30d=int(values[5] or 0),
    )


def _relationship_snapshot_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    current_date: str,
) -> dict[str, int]:
    """Best-effort read of the existing hostility/forgiveness subsystem."""
    try:
        with bot_module.get_db_connection() as connection:
            row = connection.execute(
                """
                SELECT active_insults, forgiveness_count, penance_pending
                FROM member_hostility_daily
                WHERE chat_id = ? AND user_id = ? AND date = ?
                """,
                (chat_id, user_id, current_date),
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return {"active_insults": 0, "forgiveness_count": 0, "penance_pending": 0}
    return {
        "active_insults": int(row[0] or 0),
        "forgiveness_count": int(row[1] or 0),
        "penance_pending": int(row[2] or 0),
    }


def _directed_at_bot(update, context, text: str) -> bool:
    message = getattr(update, "effective_message", None)
    if not message:
        return False

    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None)
    bot_id = getattr(getattr(context, "bot", None), "id", None)
    if reply_user is not None and bot_id is not None and int(reply_user.id) == int(bot_id):
        return True

    lowered = str(text or "").lower()
    username = str(getattr(getattr(context, "bot", None), "username", "") or "").lower()
    if username and f"@{username}" in lowered:
        return True
    return "яйцеслав" in lowered


def _is_directed_hostile(bot_module, update, context, text: str) -> bool:
    if not _directed_at_bot(update, context, text):
        return False
    try:
        return str(bot_module.detect_conversation_mode(text)) == "hostile"
    except Exception:
        return False


async def _observe_positive(update, context) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        chat is None
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or user is None
        or user.is_bot
        or message is None
        or not getattr(message, "text", None)
    ):
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    text = str(message.text or "")
    if _is_directed_hostile(bot_module, update, context, text):
        _reset_streak_sync(bot_module, int(chat.id), int(user.id))
        return

    current_date = _current_date(bot_module)
    directed = _directed_at_bot(update, context, text)
    relationship = _relationship_snapshot_sync(
        bot_module, int(chat.id), int(user.id), current_date
    )
    reconciliation = bool(
        directed
        and positive_engine.APOLOGY_RE.search(text)
        and (
            relationship["active_insults"] > 0
            or relationship["forgiveness_count"] > 0
            or relationship["penance_pending"] > 0
        )
    )
    event = positive_engine.detect_event(
        text,
        directed_at_bot=directed,
        reconciliation=reconciliation,
    )
    if event:
        _record_event_sync(
            bot_module,
            int(chat.id),
            int(user.id),
            current_date,
            event,
        )


def _latest_user_text(contents) -> str:
    if isinstance(contents, str):
        try:
            return primitive_compact_guard.latest_user_text(contents)
        except Exception:
            return contents
    return ""


def _patch_build_instruction(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_positive_instruction_patch", False):
        return

    original = bot_module.build_full_system_instruction

    def wrapped(*args, **kwargs):
        instruction = original(*args, **kwargs)
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        if chat_id is None or user_id is None:
            return instruction

        contents = args[0] if args else kwargs.get("style_text", "")
        text = _latest_user_text(contents)
        if not text:
            text = str(contents or "")
        current_date = _current_date(bot_module)
        try:
            state = _state_sync(bot_module, int(chat_id), int(user_id), current_date)
        except Exception:
            logging.exception("Positive runtime: cannot load affinity state")
            return instruction

        relationship = _relationship_snapshot_sync(
            bot_module, int(chat_id), int(user_id), current_date
        )
        hostile = relationship["active_insults"] > 0
        try:
            hostile = hostile or str(bot_module.detect_conversation_mode(text)) == "hostile"
        except Exception:
            pass
        try:
            serious = bool(bot_module.is_serious_text(text))
        except Exception:
            serious = False

        reconciliation = bool(
            positive_engine.APOLOGY_RE.search(text)
            and (
                relationship["active_insults"] > 0
                or relationship["forgiveness_count"] > 0
                or relationship["penance_pending"] > 0
            )
        )
        chat_type = str(kwargs.get("chat_type", ""))
        group_prompt = chat_type in {
            str(ChatType.GROUP),
            str(ChatType.SUPERGROUP),
            "group",
            "supergroup",
        }
        explicitly_addresses_bot = "яйцеслав" in text.lower()
        directed_for_prompt = (not group_prompt) or explicitly_addresses_bot or reconciliation

        key = (int(chat_id), int(user_id))
        now = time.monotonic()
        last = _LAST_SPONTANEOUS_MONO.get(key)
        cooldown_ready = last is None or now - last >= SPONTANEOUS_COOLDOWN_SECONDS

        decision = positive_engine.decide(
            text,
            state,
            directed_at_bot=directed_for_prompt,
            reconciliation=reconciliation,
            cooldown_ready=cooldown_ready,
            serious_topic=serious,
            hostile=hostile,
        )
        if (
            decision.event is None
            and decision.affinity_level <= 0
            and not decision.allow_spontaneous_warmth
        ):
            return instruction

        if decision.allow_spontaneous_warmth:
            _LAST_SPONTANEOUS_MONO[key] = now

        addition = positive_engine.build_instruction(
            decision,
            state,
            serious_topic=serious,
        )
        return instruction + addition if addition else instruction

    bot_module.build_full_system_instruction = wrapped
    bot_module._yayceslav_positive_instruction_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Positive runtime: bot module not ready")
        return

    _initialize_tables(bot_module)
    _patch_build_instruction(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_positive),
        group=9,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Positive runtime ready: 30d affinity + streak + celebrations/support; spontaneous cap=8%%"
    )
