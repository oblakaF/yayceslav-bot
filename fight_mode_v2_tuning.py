"""Focused tuning for Yayceslav's live verbal fights.

This layer keeps the existing conflict FSM and sticker semantics as the single
owners of state/meaning. It only adjusts user-facing behavior agreed in live
Telegram testing:

* the first directed hit already gets a sharp answer instead of a timid warning;
* RAGE explicitly rewards contextual, darkly hyperbolic roasts while keeping
  diagnoses/orientation as jokes about visible chat behavior, not factual claims;
* a sufficiently long RAGE exchange gets two different Yayceslav stickers even
  though ordinary sticker cooldowns are intentionally much longer;
* one incoming Telegram message cannot accidentally produce two normal text
  answers through overlapping runtime routes.

No extra model calls and no persistent storage are introduced.
"""

from __future__ import annotations

import functools
import logging
import random
import re
import sys
import time
from typing import Any

from telegram.constants import ChatType


_INSTALLED = False

# Extra direct bait observed in the real fight transcript. This is not a generic
# profanity detector; the conflict FSM only asks this on a directed turn.
_EXTRA_FIGHT_BAIT_RE = re.compile(
    r"(?:"
    r"^\s*сосал\??\s*$|"
    r"\bнюхать\s+ху[йя]\b|"
    r"\b(?:ху[йя]|член)\s+или\s+умереть\b|"
    r"\bв\s+жопу\s+раз\b|"
    r"\bвилк(?:ой|у)\s+в\s+глаз\b|"
    r"\bзавали\s+ебало\b|"
    r"\b(?:иди|пош[её]л)\s+(?:на\s+)?ху[йя]\b"
    r")",
    re.IGNORECASE,
)

RAGE_STICKER_SESSION_SECONDS = 10 * 60.0
RAGE_GUARANTEED_STICKERS = 2
RAGE_SECOND_STICKER_FROM_TURN = 3
RAGE_STICKER_MAX_PER_SESSION = 3
RAGE_OPTIONAL_STICKER_CHANCE = 0.28
DUPLICATE_ANSWER_TTL_SECONDS = 3 * 60.0


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "send_answer", None)):
            return module
    return None


def _patch_conflict_fsm() -> None:
    import conflict_fsm_runtime

    original_extra_hostile = conflict_fsm_runtime.is_extra_hostile

    if not getattr(original_extra_hostile, "_yayceslav_fight_v2", False):
        @functools.wraps(original_extra_hostile)
        def extra_hostile_v2(text: str) -> bool:
            value = " ".join(str(text or "").split()).strip()
            return bool(
                original_extra_hostile(value)
                or (value and _EXTRA_FIGHT_BAIT_RE.search(value))
            )

        extra_hostile_v2._yayceslav_fight_v2 = True
        conflict_fsm_runtime.is_extra_hostile = extra_hostile_v2

    def sharp_warning_note() -> str:
        return (
            "\n\nCONFLICT FSM = WARNING. Это первый прямой наезд этого человека. "
            "Не разворачивай длинную войну, но отвечай сразу зубасто: один "
            "короткий контрудар по конкретной реплике, максимум 1–2 фразы. "
            "Если пользователь сам пришёл с матом, естественный мат в ответе "
            "допустим. Не говори «полегче», не оправдывайся, не читай мораль и "
            "не проси конструктив. Второй прямой наезд в 10-минутном окне "
            "переведёт именно этого человека в RAGE."
        )

    sharp_warning_note._yayceslav_fight_v2 = True
    conflict_fsm_runtime.build_warning_note = sharp_warning_note

    original_rage_prompt = conflict_fsm_runtime.build_rage_system_prompt
    if not getattr(original_rage_prompt, "_yayceslav_fight_v2", False):
        @functools.wraps(original_rage_prompt)
        def rage_prompt_v2(*args: Any, **kwargs: Any) -> str:
            prompt = str(original_rage_prompt(*args, **kwargs))
            prompt += (
                "\nВ RAGE особенно цени точный персональный панч по реально "
                "наблюдаемому паттерну переписки вместо универсального «ты тупой». "
                "Если оппонент сам десять раз тащит одну тему, можно довести её до "
                "злой карикатуры. Очевидно шуточные формулировки вроде «клиническая "
                "одержимость», «это уже граничит с диагнозом», «проекция» или "
                "метафорический «каминг-аут» допустимы как roast по его сообщениям. "
                "Не превращай шутку в утверждение о настоящем медицинском диагнозе, "
                "сексуальной ориентации или интимной жизни человека."
                "\nНе повторяй один и тот же тезис («зациклился», «словарный запас») "
                "раунд за раундом: меняй угол атаки, используй его же формулировку "
                "или закрой раунд одной короткой фразой."
            )
            return prompt

        rage_prompt_v2._yayceslav_fight_v2 = True
        conflict_fsm_runtime.build_rage_system_prompt = rage_prompt_v2


def _patch_duplicate_send_answer() -> None:
    """Suppress a second normal text answer to the same incoming group message."""

    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Fight-v2 duplicate guard: bot.send_answer not found")
        return

    original = bot_module.send_answer
    if getattr(original, "_yayceslav_fight_v2_dedup", False):
        return

    @functools.wraps(original)
    async def send_answer_once(update: Any, context: Any, text: str, *args: Any, **kwargs: Any):
        chat = getattr(update, "effective_chat", None)
        message = getattr(update, "message", None)
        callback_query = getattr(update, "callback_query", None)

        source_user_text = kwargs.get(
            "source_user_text",
            args[2] if len(args) >= 3 else None,
        )
        force_voice = bool(
            kwargs.get(
                "force_voice",
                args[0] if len(args) >= 1 else False,
            )
        )

        # Buttons, private chat, voice output and responses without a concrete
        # source text keep their original behavior. The live duplicate bug was
        # observed in a group text fight.
        should_guard = bool(
            chat
            and message
            and callback_query is None
            and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
            and source_user_text
            and not force_voice
        )

        if should_guard:
            now = time.monotonic()
            seen = context.chat_data.setdefault("fight_v2_answered_message_ids", {})

            stale = [
                key
                for key, seen_at in tuple(seen.items())
                if now - float(seen_at) > DUPLICATE_ANSWER_TTL_SECONDS
            ]
            for key in stale:
                seen.pop(key, None)

            message_key = int(message.message_id)
            if message_key in seen:
                logging.warning(
                    "Fight-v2 duplicate answer suppressed: chat=%s message=%s",
                    chat.id,
                    message_key,
                )
                return None

            seen[message_key] = now

        return await original(update, context, text, *args, **kwargs)

    send_answer_once._yayceslav_fight_v2_dedup = True
    bot_module.send_answer = send_answer_once


def _rage_sticker_state(context: Any, user_id: int, now: float) -> dict[str, Any]:
    states = context.chat_data.setdefault("fight_v2_rage_stickers", {})
    state = states.get(int(user_id))

    if (
        not isinstance(state, dict)
        or now - float(state.get("last_turn_at", 0.0)) > RAGE_STICKER_SESSION_SECONDS
    ):
        state = {
            "turns": 0,
            "sent": 0,
            "used_keys": [],
            "last_turn_at": now,
        }
        states[int(user_id)] = state

    state["turns"] = int(state.get("turns", 0)) + 1
    state["last_turn_at"] = now
    return state


def _choose_distinct_rage_key(sticker_post_runtime: Any, state: dict[str, Any]) -> str:
    used = set(str(key) for key in state.get("used_keys", []))
    pool = [
        key
        for key in sticker_post_runtime._RAGE_POST_STICKERS
        if key not in used
    ]
    return random.choice(pool or list(sticker_post_runtime._RAGE_POST_STICKERS))


def _patch_rage_stickers() -> None:
    import conflict_fsm_runtime
    import sticker_engine
    import sticker_post_runtime
    import sticker_runtime

    original = sticker_post_runtime.maybe_send_post_text_tag
    if getattr(original, "_yayceslav_fight_v2", False):
        return

    @functools.wraps(original)
    async def maybe_send_post_text_tag_v2(
        update: Any,
        context: Any,
        source_user_text: str,
        answer_text: str,
    ) -> bool:
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)

        if (
            not chat
            or not user
            or getattr(user, "is_bot", False)
            or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        ):
            return await original(update, context, source_user_text, answer_text)

        if (
            sticker_engine.is_serious_text(source_user_text)
            or sticker_engine.is_serious_text(answer_text)
        ):
            return await original(update, context, source_user_text, answer_text)

        # Use the actual production FSM phase, not the older rage-hotfix helper.
        # This makes sticker continuity survive taunts such as "сосал?" and also
        # neutral follow-ups while the same user's 10-minute RAGE latch is active.
        rage_active = (
            conflict_fsm_runtime.phase(chat.id, user.id)
            == conflict_fsm_runtime.ConflictPhase.RAGE
        )
        if not rage_active:
            return await original(update, context, source_user_text, answer_text)

        now = time.monotonic()
        state = _rage_sticker_state(context, user.id, now)
        turns = int(state.get("turns", 0))
        sent_count = int(state.get("sent", 0))

        if sent_count >= RAGE_STICKER_MAX_PER_SESSION:
            return False

        # Sticker #1 punctuates the first latched RAGE response. Sticker #2 is
        # guaranteed only from the third RAGE response, so they never arrive on
        # two consecutive turns. This dedicated two-sticker budget intentionally
        # bypasses the ordinary 8m/15m sticker cooldown that caused the live log
        # to show only one sticker during an entire argument.
        guaranteed = (
            sent_count < RAGE_GUARANTEED_STICKERS
            and (
                sent_count == 0
                or turns >= RAGE_SECOND_STICKER_FROM_TURN
            )
        )

        if not guaranteed:
            if random.random() >= RAGE_OPTIONAL_STICKER_CHANCE:
                return False
            if not sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
                return False

        sticker_key = _choose_distinct_rage_key(sticker_post_runtime, state)

        try:
            delivered = await sticker_runtime.reply_sticker_by_key(
                update,
                context,
                sticker_key,
            )
        except Exception as error:
            logging.warning(
                "Fight-v2 RAGE sticker failed key=%s: %s",
                sticker_key,
                error,
            )
            return False

        if not delivered:
            return False

        # Keep the ordinary sticker system aware that a visual was sent. The
        # second guaranteed RAGE visual may still bypass this gate by design;
        # anything after the agreed two returns to the normal anti-spam rules.
        sticker_runtime._record_sticker_slot(chat.id, user.id, now)
        state["sent"] = sent_count + 1
        used = list(state.get("used_keys", []))
        used.append(sticker_key)
        state["used_keys"] = used[-len(sticker_post_runtime._RAGE_POST_STICKERS):]

        logging.info(
            "Fight-v2 RAGE sticker: key=%s guaranteed=%s turn=%s sent=%s chat=%s user=%s",
            sticker_key,
            guaranteed,
            turns,
            state["sent"],
            chat.id,
            user.id,
        )
        return True

    maybe_send_post_text_tag_v2._yayceslav_fight_v2 = True
    sticker_post_runtime.maybe_send_post_text_tag = maybe_send_post_text_tag_v2


def _raise_aggressive_sticker_events() -> None:
    """Make hostile semantic stickers visible without changing normal-chat caps."""

    try:
        import sticker_engine

        for event in ("hard_dismissal", "shut_up_escalated"):
            if event in sticker_engine.EVENT_CHANCE:
                sticker_engine.EVENT_CHANCE[event] = max(
                    float(sticker_engine.EVENT_CHANCE[event]),
                    0.10,
                )
    except Exception as error:
        logging.warning("Fight-v2 aggressive sticker tuning failed: %s", error)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    _patch_conflict_fsm()
    _patch_duplicate_send_answer()
    _patch_rage_stickers()
    _raise_aggressive_sticker_events()

    _INSTALLED = True
    logging.warning(
        "Fight mode v2 ready: sharper hit #1, contextual RAGE roasts, "
        "two guaranteed own-pack stickers in long RAGE exchanges, duplicate guard"
    )
    return True
