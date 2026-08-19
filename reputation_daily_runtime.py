"""Natural daily growth for Yayceslav lifetime reputation.

A person does not need to praise the bot to become well-regarded. Every active
calendar day in a group can earn one small +1..+5 reputation bonus as long as
that person's day stays broadly non-hostile. General hostility only removes the
passive clean-day bonus; explicit negative reputation points are still applied
only when abuse is directed at Yayceslav by reputation_runtime.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import sys
from datetime import date as date_type

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters

import reputation_engine
import reputation_runtime


_PREPARED_APPLICATION_IDS: set[int] = set()
DAILY_NORMAL_BONUS_MIN = 1
DAILY_NORMAL_BONUS_MAX = 5

_NEUTRAL_RELATION_TEXT = (
    "Это нейтральный человек. ВАЖНО: нейтральность имеет приоритет над старым generic «aggressive by default». "
    "Не начинай агрессию, докоп, оскорбление или токсичный подкол первым. Отвечай нормально и по делу; "
    "характер можно сохранить сухой/мемной подачей без нападения на человека."
)


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


def _initialize_table(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_reputation_daily (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                normal_bonus INTEGER NOT NULL DEFAULT 0,
                bonus_active INTEGER NOT NULL DEFAULT 0,
                negative_seen INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                PRIMARY KEY (chat_id, user_id, date)
            )
            """
        )
        connection.commit()


def _score_on_connection(connection, chat_id: int, user_id: int) -> int:
    row = connection.execute(
        "SELECT score FROM member_reputation WHERE chat_id = ? AND user_id = ?",
        (int(chat_id), int(user_id)),
    ).fetchone()
    return reputation_engine.clamp_score(int((row[0] if row else 0) or 0))


def _adjust_score_only_on_connection(
    connection,
    chat_id: int,
    user_id: int,
    delta: int,
    reason: str,
) -> int:
    """Adjust only lifetime score, not explicit praise/abuse event counters."""
    current = _score_on_connection(connection, chat_id, user_id)
    target = reputation_engine.clamp_score(current + int(delta or 0))
    applied = target - current
    if applied == 0:
        return 0

    connection.execute(
        """
        INSERT INTO member_reputation
            (chat_id, user_id, score, positive_points, negative_points,
             positive_events, negative_events, last_delta, last_reason, updated_at)
        VALUES (?, ?, ?, 0, 0, 0, 0, ?, ?, datetime('now'))
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            score = excluded.score,
            last_delta = excluded.last_delta,
            last_reason = excluded.last_reason,
            updated_at = datetime('now')
        """,
        (
            int(chat_id),
            int(user_id),
            target,
            applied,
            str(reason or "normal_day"),
        ),
    )
    return applied


def _grant_normal_day_bonus_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    current_date: str,
    *,
    rng=random,
) -> int:
    """Award one passive +1..+5 bonus for this active clean day, at most once."""
    requested = max(
        DAILY_NORMAL_BONUS_MIN,
        min(
            DAILY_NORMAL_BONUS_MAX,
            int(rng.randint(DAILY_NORMAL_BONUS_MIN, DAILY_NORMAL_BONUS_MAX)),
        ),
    )

    with bot_module.get_db_connection() as connection:
        # The PK is the concurrency gate: only one concurrent first message can
        # create today's row and therefore award the daily bonus.
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO member_reputation_daily
                (chat_id, user_id, date, normal_bonus, bonus_active,
                 negative_seen, updated_at)
            VALUES (?, ?, ?, 0, 0, 0, datetime('now'))
            """,
            (int(chat_id), int(user_id), str(current_date)),
        )
        if int(cursor.rowcount or 0) != 1:
            connection.commit()
            return 0

        current_score = _score_on_connection(connection, chat_id, user_id)
        applied = min(
            requested,
            max(0, reputation_engine.MAX_REPUTATION - current_score),
        )
        if applied > 0:
            _adjust_score_only_on_connection(
                connection,
                chat_id,
                user_id,
                applied,
                "normal_day_bonus",
            )
            connection.execute(
                """
                UPDATE member_reputation_daily
                SET normal_bonus = ?, bonus_active = 1, updated_at = datetime('now')
                WHERE chat_id = ? AND user_id = ? AND date = ?
                """,
                (applied, int(chat_id), int(user_id), str(current_date)),
            )
        connection.commit()
    return int(applied)


def _mark_negative_day_and_revoke_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    current_date: str,
) -> int:
    """Mark the day bad and remove only the passive bonus earned that day."""
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT normal_bonus, bonus_active, negative_seen
            FROM member_reputation_daily
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (int(chat_id), int(user_id), str(current_date)),
        ).fetchone()

        if row is None:
            connection.execute(
                """
                INSERT INTO member_reputation_daily
                    (chat_id, user_id, date, normal_bonus, bonus_active,
                     negative_seen, updated_at)
                VALUES (?, ?, ?, 0, 0, 1, datetime('now'))
                """,
                (int(chat_id), int(user_id), str(current_date)),
            )
            connection.commit()
            return 0

        bonus = max(0, int(row[0] or 0))
        active = bool(row[1])
        already_negative = bool(row[2])
        if already_negative:
            connection.commit()
            return 0

        revoked = 0
        if active and bonus > 0:
            applied = _adjust_score_only_on_connection(
                connection,
                chat_id,
                user_id,
                -bonus,
                "normal_day_bonus_revoked",
            )
            revoked = abs(int(applied))

        connection.execute(
            """
            UPDATE member_reputation_daily
            SET bonus_active = 0, negative_seen = 1, updated_at = datetime('now')
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (int(chat_id), int(user_id), str(current_date)),
        )
        connection.commit()
    return revoked


def _daily_state_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    current_date: str,
) -> dict[str, int]:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT normal_bonus, bonus_active, negative_seen
            FROM member_reputation_daily
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (int(chat_id), int(user_id), str(current_date)),
        ).fetchone()
    if row is None:
        return {"normal_bonus": 0, "bonus_active": 0, "negative_seen": 0}
    return {
        "normal_bonus": int(row[0] or 0),
        "bonus_active": int(row[1] or 0),
        "negative_seen": int(row[2] or 0),
    }


async def _observe_daily_reputation(update, context) -> None:
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
    directed = reputation_runtime._directed_at_bot(update, context, text)
    try:
        hostile_any = str(bot_module.detect_conversation_mode(text)) == "hostile"
    except Exception:
        hostile_any = False

    decision = reputation_engine.score_message(
        text,
        directed_at_bot=directed,
        hostile_mode=hostile_any and directed,
    )
    current_date = _current_date(bot_module)

    # General hostile behavior makes the calendar day ineligible for passive
    # goodwill. It does NOT create explicit -N reputation unless group-10's
    # directed-at-bot scoring found a real negative event.
    if hostile_any or decision.delta < 0:
        await asyncio.to_thread(
            _mark_negative_day_and_revoke_sync,
            bot_module,
            int(chat.id),
            int(user.id),
            current_date,
        )
        return

    # Any ordinary active text message counts as a normal social day. The user
    # does not need to mention or praise Yayceslav to slowly build good standing.
    await asyncio.to_thread(
        _grant_normal_day_bonus_sync,
        bot_module,
        int(chat.id),
        int(user.id),
        current_date,
    )


def _patch_instruction(bot_module) -> None:
    """Make exact zero neutral, small positive goodwill warm, small negative wary."""
    if getattr(bot_module, "_yayceslav_daily_reputation_instruction_patch", False):
        return

    original = bot_module.build_full_system_instruction

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        instruction = str(original(*args, **kwargs))
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        if chat_id is None or user_id is None:
            return instruction
        try:
            score = int(
                reputation_runtime._state_sync(
                    bot_module,
                    int(chat_id),
                    int(user_id),
                )["score"]
            )
        except Exception:
            return instruction

        if 1 <= score <= 9:
            replacement = (
                f"Репутация уже {score:+d}/100: это уже нормальный человек, а не нулевой незнакомец. "
                "Относись базово доброжелательно и спокойно. Не начинай агрессию или докоп первым; "
                "не хвали без повода, не льсти и не соглашайся автоматически."
            )
            if _NEUTRAL_RELATION_TEXT in instruction:
                return instruction.replace(_NEUTRAL_RELATION_TEXT, replacement, 1)
            return instruction + "\n\nNATURAL GOODWILL OVERRIDE:\n" + replacement

        if -9 <= score <= -1:
            replacement = (
                f"Репутация {score:+d}/100: человек слегка испортил впечатление, поэтому Яйцеслав насторожен. "
                "Не начинай травлю или докоп первым, но можешь быть прохладнее нейтрального."
            )
            if _NEUTRAL_RELATION_TEXT in instruction:
                return instruction.replace(_NEUTRAL_RELATION_TEXT, replacement, 1)
            return instruction + "\n\nMILD REPUTATION OVERRIDE:\n" + replacement

        return instruction

    bot_module.build_full_system_instruction = wrapped
    bot_module._yayceslav_daily_reputation_instruction_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Daily reputation runtime: bot module not ready")
        return

    _initialize_table(bot_module)
    _patch_instruction(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_daily_reputation),
        group=11,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Daily reputation runtime ready: one clean active day = +1..+5; hostile day revokes passive bonus"
    )
