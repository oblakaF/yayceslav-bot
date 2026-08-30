"""Bounded pacing for strong RAGE exchanges.

This runtime does not own conflict state and does not make another model call.
It wraps the existing send_answer path once and may schedule one short follow-up
line in a sufficiently hot fight using only target-authored repeated wording.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import functools
import random
import sys
import time
from typing import Any

from telegram.constants import ChatType

import claim_memory_v3
import conflict_fsm_runtime
import fight_memory_afterburner_v2
import fight_routing_v3
import hostile_streak_engine


DOUBLE_PUNCH_MIN_HEAT = 4
DOUBLE_PUNCH_MIN_SOURCE_LEN = 4
DOUBLE_PUNCH_DELAY_MIN = 1.8
DOUBLE_PUNCH_DELAY_MAX = 4.0
DOUBLE_PUNCH_SESSION_SECONDS = 12 * 60.0
DOUBLE_PUNCH_CHANCE = 0.55

_INSTALLED = False


@dataclass
class PaceState:
    updated_at: float = 0.0
    fired: bool = False
    task: asyncio.Task[Any] | None = None


_STATES: dict[tuple[int, int], PaceState] = {}


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "send_answer", None)):
            return module
    return None


def _extract_send_answer_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[bool, str]:
    force_voice = bool(kwargs.get("force_voice", args[0] if len(args) >= 1 else False))
    source = kwargs.get("source_user_text", args[2] if len(args) >= 3 else "")
    return force_voice, str(source or "")


def _is_rage(chat_id: int, user_id: int) -> bool:
    try:
        return conflict_fsm_runtime.phase(int(chat_id), int(user_id)) is conflict_fsm_runtime.ConflictPhase.RAGE
    except Exception:
        return False


def _is_serious(text: str) -> bool:
    value = str(text or "")
    if claim_memory_v3.is_sensitive_claim_text(value):
        return True
    module = _find_bot_module()
    classifier = getattr(module, "is_serious_text", None) if module is not None else None
    try:
        return bool(classifier and classifier(value))
    except Exception:
        return False


def _state(chat_id: int, user_id: int, now: float) -> PaceState:
    key = (int(chat_id), int(user_id))
    current = _STATES.get(key)
    if current is None or now - current.updated_at > DOUBLE_PUNCH_SESSION_SECONDS:
        current = PaceState(updated_at=now)
        _STATES[key] = current
    current.updated_at = now
    return current


def _cancel(chat_id: int, user_id: int, *, drop: bool = True) -> None:
    key = (int(chat_id), int(user_id))
    state = _STATES.get(key)
    if state is not None and state.task is not None and not state.task.done():
        state.task.cancel()
    if drop:
        _STATES.pop(key, None)


def _callback_from_live_fight(chat_id: int, user_id: int, source_text: str) -> str:
    texts: list[str] = []
    try:
        after = fight_routing_v3._AFTERBURNER_STATES.get((int(chat_id), int(user_id)))
        if after is not None:
            texts.extend(list(getattr(after, "fight_texts", ()) or ()))
    except Exception:
        pass
    if source_text:
        texts.append(source_text)
    return fight_memory_afterburner_v2.callback_token(texts)


def followup_line(callback: str) -> str:
    token = str(callback or "").strip()
    if not token:
        return ""
    variants = (
        f"И да: «{token}» уже не аргумент, а подписка с автопродлением.",
        f"Кстати, «{token}» ты повторил так уверенно, будто за пятый раз дают достижение.",
        f"Оставлю «{token}» тебе как фирменный звук загрузки — всё равно больше всех пользуешься.",
        f"На «{token}» можешь уже ставить водяной знак. Контент стабильно один и тот же.",
    )
    return random.choice(variants)


def should_double_punch(chat_id: int, user_id: int, source_text: str, *, now: float | None = None) -> bool:
    moment = time.monotonic() if now is None else float(now)
    text = " ".join(str(source_text or "").split()).strip()
    if len(text) < DOUBLE_PUNCH_MIN_SOURCE_LEN:
        return False
    if _is_serious(text) or fight_routing_v3.is_reconciliation(text):
        return False
    if not _is_rage(chat_id, user_id):
        return False
    if hostile_streak_engine.current(int(chat_id), int(user_id), now=moment) < DOUBLE_PUNCH_MIN_HEAT:
        return False
    state = _state(chat_id, user_id, moment)
    return not state.fired


async def _send_followup(context: Any, chat_id: int, key: tuple[int, int], line: str, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    state = _STATES.get(key)
    if state is None or state.fired:
        return
    try:
        await context.bot.send_message(chat_id=chat_id, text=line)
    except Exception:
        return
    state.fired = True
    state.updated_at = time.monotonic()


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    module = _find_bot_module()
    if module is None:
        return False

    original = module.send_answer
    if getattr(original, "_yayceslav_rage_pacing_v1", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    async def wrapped_send_answer(update: Any, context: Any, text: Any, *args: Any, **kwargs: Any) -> Any:
        result = await original(update, context, text, *args, **kwargs)

        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        if (
            chat is None
            or user is None
            or getattr(user, "is_bot", False)
            or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        ):
            return result

        force_voice, source_text = _extract_send_answer_call(args, kwargs)
        if force_voice or bool(getattr(context, "user_data", {}).get("voice_mode", False)):
            return result

        # Stop conditions must also cancel an already armed follow-up from the
        # immediately preceding hostile turn. Otherwise a reconciliation or a
        # serious topic could be followed by a stale punch a second later.
        if (
            _is_serious(source_text)
            or _is_serious(str(text or ""))
            or fight_routing_v3.is_reconciliation(source_text)
        ):
            _cancel(chat.id, user.id)
            return result

        if not should_double_punch(chat.id, user.id, source_text):
            return result
        if random.random() >= DOUBLE_PUNCH_CHANCE:
            return result

        callback = _callback_from_live_fight(chat.id, user.id, source_text)
        line = followup_line(callback)
        if not line:
            return result

        key = (int(chat.id), int(user.id))
        state = _state(chat.id, user.id, time.monotonic())
        if state.task and not state.task.done():
            return result
        delay = random.uniform(DOUBLE_PUNCH_DELAY_MIN, DOUBLE_PUNCH_DELAY_MAX)
        coro = _send_followup(context, int(chat.id), key, line, delay)
        create_task = getattr(getattr(context, "application", None), "create_task", None)
        if callable(create_task):
            state.task = create_task(coro)
        else:
            state.task = asyncio.create_task(coro)
        return result

    wrapped_send_answer._yayceslav_rage_pacing_v1 = True
    module.send_answer = wrapped_send_answer
    _INSTALLED = True
    return True
