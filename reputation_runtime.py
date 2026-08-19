"""Persistent lifetime reputation toward Yayceslav.

Every member starts neutral at 0. Only praise/abuse actually directed at the
bot moves reputation. The score persists per chat/member in [-100, 100] and is
kept separate from monthly XP and 30-day positive affinity.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import sys

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters

import reputation_engine


_PREPARED_APPLICATION_IDS: set[int] = set()


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


def _initialize_table(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_reputation (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                positive_points INTEGER NOT NULL DEFAULT 0,
                negative_points INTEGER NOT NULL DEFAULT 0,
                positive_events INTEGER NOT NULL DEFAULT 0,
                negative_events INTEGER NOT NULL DEFAULT 0,
                last_delta INTEGER NOT NULL DEFAULT 0,
                last_reason TEXT,
                updated_at TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        connection.commit()


def _state_sync(bot_module, chat_id: int, user_id: int) -> dict[str, int | str | None]:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT score, positive_points, negative_points,
                   positive_events, negative_events, last_delta, last_reason
            FROM member_reputation
            WHERE chat_id = ? AND user_id = ?
            """,
            (int(chat_id), int(user_id)),
        ).fetchone()
    if not row:
        return {
            "score": 0,
            "positive_points": 0,
            "negative_points": 0,
            "positive_events": 0,
            "negative_events": 0,
            "last_delta": 0,
            "last_reason": None,
        }
    return {
        "score": reputation_engine.clamp_score(int(row[0] or 0)),
        "positive_points": int(row[1] or 0),
        "negative_points": int(row[2] or 0),
        "positive_events": int(row[3] or 0),
        "negative_events": int(row[4] or 0),
        "last_delta": int(row[5] or 0),
        "last_reason": row[6],
    }


def _apply_delta_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    delta: int,
    reason: str,
) -> int:
    value = max(-10, min(10, int(delta or 0)))
    if value == 0:
        return int(_state_sync(bot_module, chat_id, user_id)["score"])

    positive_points = value if value > 0 else 0
    negative_points = abs(value) if value < 0 else 0
    positive_events = 1 if value > 0 else 0
    negative_events = 1 if value < 0 else 0

    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO member_reputation
                (chat_id, user_id, score, positive_points, negative_points,
                 positive_events, negative_events, last_delta, last_reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                score = MAX(-100, MIN(100, member_reputation.score + excluded.score)),
                positive_points = positive_points + excluded.positive_points,
                negative_points = negative_points + excluded.negative_points,
                positive_events = positive_events + excluded.positive_events,
                negative_events = negative_events + excluded.negative_events,
                last_delta = excluded.last_delta,
                last_reason = excluded.last_reason,
                updated_at = datetime('now')
            """,
            (
                int(chat_id),
                int(user_id),
                value,
                positive_points,
                negative_points,
                positive_events,
                negative_events,
                value,
                str(reason or "event"),
            ),
        )
        connection.commit()
    return int(_state_sync(bot_module, chat_id, user_id)["score"])


def _directed_at_bot(update, context, text: str) -> bool:
    message = getattr(update, "effective_message", None)
    if message is None:
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


async def _observe_reputation(update, context) -> None:
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
    directed = _directed_at_bot(update, context, text)
    if not directed:
        return

    try:
        hostile = str(bot_module.detect_conversation_mode(text)) == "hostile"
    except Exception:
        hostile = False

    decision = reputation_engine.score_message(
        text,
        directed_at_bot=True,
        hostile_mode=hostile,
    )
    if decision.delta:
        await asyncio.to_thread(
            _apply_delta_sync,
            bot_module,
            int(chat.id),
            int(user.id),
            decision.delta,
            decision.reason,
        )


def _enrich_profile(bot_module, profile, chat_id: int, user_id: int):
    if profile is None:
        return None
    enriched = dict(profile)
    state = _state_sync(bot_module, int(chat_id), int(user_id))
    score = int(state["score"])
    enriched.update(
        {
            "reputation_score": score,
            "reputation_label": reputation_engine.reputation_label(score),
            "reputation_positive_points": int(state["positive_points"]),
            "reputation_negative_points": int(state["negative_points"]),
            "reputation_positive_events": int(state["positive_events"]),
            "reputation_negative_events": int(state["negative_events"]),
        }
    )
    return enriched


def _augment_profile_functions(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_reputation_profile_patch", False):
        return
    original_sync = getattr(bot_module, "get_member_profile_sync", None)
    original_async = getattr(bot_module, "get_member_profile", None)
    if not callable(original_sync) or not callable(original_async):
        return

    def sync_with_reputation(chat_id: int, user_id: int):
        return _enrich_profile(
            bot_module,
            original_sync(chat_id, user_id),
            int(chat_id),
            int(user_id),
        )

    async def async_with_reputation(chat_id: int, user_id: int):
        profile = await original_async(chat_id, user_id)
        if profile is None:
            return None
        return await asyncio.to_thread(
            _enrich_profile,
            bot_module,
            profile,
            int(chat_id),
            int(user_id),
        )

    bot_module.get_member_profile_sync = sync_with_reputation
    bot_module.get_member_profile = async_with_reputation
    bot_module._yayceslav_reputation_profile_patch = True


def _reputation_instruction(score: int, *, current_hostile: bool = False) -> str:
    value = reputation_engine.clamp_score(score)
    label = reputation_engine.reputation_label(value)
    base = (
        "\n\nLIFETIME REPUTATION LAYER:\n"
        f"Постоянная репутация этого человека у Яйцеслава: {value:+d}/100 ({label}).\n"
    )

    if current_hostile:
        return base + (
            "Текущее сообщение само по себе враждебное: можно защищаться и отвечать жёстко по существующим правилам. "
            "Но репутация определяет долгую память, а не отменяет полезность ответа."
        )
    if -9 <= value <= 9:
        return base + (
            "Это нейтральный человек. ВАЖНО: нейтральность имеет приоритет над старым generic «aggressive by default». "
            "Не начинай агрессию, докоп, оскорбление или токсичный подкол первым. Отвечай нормально и по делу; "
            "характер можно сохранить сухой/мемной подачей без нападения на человека."
        )
    if value >= 70:
        return base + (
            "Это очень свой человек. Будь заметно теплее и дружелюбнее, допускай редкую фамильярность, "
            "но не льсти и не соглашайся с ошибками ради симпатии."
        )
    if value >= 35:
        return base + (
            "У Яйцеслава устойчиво хорошее отношение к человеку. Тон обычно тёплый и уважительный, "
            "без приторности и без автоматического согласия."
        )
    if value >= 10:
        return base + (
            "Человек оставил положительное впечатление. Будь чуть теплее нейтрального, но без лишней похвалы."
        )
    if value <= -70:
        return base + (
            "Яйцеслав хорошо помнит устойчивую токсичность этого человека. В несерьёзном прямом разговоре держи "
            "жёсткую дистанцию и можешь отвечать резко; полезные и серьёзные вопросы всё равно обслуживай нормально."
        )
    if value <= -35:
        return base + (
            "У человека устойчивая негативная история с Яйцеславом. Будь холоднее и колче в несерьёзной беседе, "
            "но не начинай бессмысленную травлю."
        )
    return base + (
        "Репутация слегка отрицательная: Яйцеслав насторожен и помнит прошлые наезды, но ещё не считает человека врагом."
    )


def _patch_instruction(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_reputation_instruction_patch", False):
        return
    original = bot_module.build_full_system_instruction

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        instruction = original(*args, **kwargs)
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        if chat_id is None or user_id is None:
            return instruction
        try:
            score = int(_state_sync(bot_module, int(chat_id), int(user_id))["score"])
        except Exception:
            logging.exception("Reputation runtime: cannot load score")
            score = 0
        style_text = args[0] if args else kwargs.get("style_text", "")
        try:
            current_hostile = str(bot_module.detect_conversation_mode(str(style_text or ""))) == "hostile"
        except Exception:
            current_hostile = False
        return str(instruction) + _reputation_instruction(score, current_hostile=current_hostile)

    bot_module.build_full_system_instruction = wrapped
    bot_module._yayceslav_reputation_instruction_patch = True


def _patch_proactive_aggression(bot_module) -> None:
    """New/neutral/positive people do not receive initiative dokop."""
    import aggression_engine

    original = aggression_engine.decide_aggression
    if getattr(original, "_yayceslav_reputation_gate", False):
        return

    @functools.wraps(original)
    def gated(ctx, *args, **kwargs):
        try:
            score = int(_state_sync(bot_module, int(ctx.chat_id), int(ctx.user_id))["score"])
        except Exception:
            score = 0
        if score >= -9:
            return aggression_engine.AggressionDecision(reason="reputation_neutral")
        return original(ctx, *args, **kwargs)

    gated._yayceslav_reputation_gate = True
    aggression_engine.decide_aggression = gated


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Reputation runtime: bot module not ready")
        return

    _initialize_table(bot_module)
    _augment_profile_functions(bot_module)
    _patch_instruction(bot_module)
    _patch_proactive_aggression(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_reputation),
        group=10,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Reputation runtime ready: lifetime score -100..+100; neutral default=0")
