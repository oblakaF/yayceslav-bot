"""Rare semantic sticker punchlines after a normal Yayceslav text answer.

Normal chat keeps the shared background-sticker gate. During an active directed
fight, a separate bounded fight budget allows up to two semantic visual beats
without turning the exchange into sticker spam.
"""

from __future__ import annotations

import functools
import logging
import random
import re
import sys
from typing import Final

from telegram.constants import ChatType

import fight_sticker_budget
import hostile_streak_engine
import sticker_engine
import sticker_interaction


POST_TEXT_TAG_CHANCE: Final = 0.05

_RAGE_POST_STICKERS: Final[tuple[str, ...]] = (
    "obtekay",
    "pereigral_i_unichtozhil",
    "ne_vyvez",
    "idi_nahui",
    "vremya_zavalit_ebalo",
)

_OUTPLAY_EVENTS: Final[frozenset[str]] = frozenset(
    {"self_own", "outplayed", "weak_take", "skill_issue", "swagger", "aura_loss", "fight"}
)
_OUTPLAY_ANSWER_RE = re.compile(
    r"(?:сам(?:\s+себя|\s+себе)|противореч\w*|аргумент\w*|логик\w*|по\s+факт\w*|"
    r"факт\w*|получается|в\s+итоге|на\s+деле|потому\s+что|не\s+вывез\w*|поймал\w*|опроверг\w*)",
    re.IGNORECASE,
)
_BASE_ANSWER_RE = re.compile(
    r"(?:\bда[,.:;!?\s]|\bнет[,.:;!?\s]|очевидн\w*|вс[её]\s+просто|тут\s+вс[её]\s+просто|"
    r"по\s+сути|именно|разумеется|конечно|потому\s+что)",
    re.IGNORECASE,
)
_WRAPPER_INSTALLED = False


def choose_post_text_tag(source_user_text: str, answer_text: str) -> str | None:
    source = (source_user_text or "").strip()
    answer = (answer_text or "").strip()
    if not source or not answer:
        return None
    if sticker_engine.is_serious_text(source) or sticker_engine.is_serious_text(answer):
        return None
    event = sticker_engine.detect_event(source, direct=False)
    if event in _OUTPLAY_EVENTS and len(answer) >= 24 and _OUTPLAY_ANSWER_RE.search(answer):
        return "pereigral_i_unichtozhil"
    if len(source) <= 240 and sticker_interaction.is_question(source) and len(answer) >= 20 and _BASE_ANSWER_RE.search(answer):
        return "baza"
    return None


def _is_rage_exchange(chat_id: int, user_id: int, source_user_text: str) -> bool:
    if hostile_streak_engine.current(int(chat_id), int(user_id)) < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
        return False
    try:
        import conflict_fsm_runtime
        bot_module = conflict_fsm_runtime._find_bot_module()
        return bool(
            conflict_fsm_runtime.phase(int(chat_id), int(user_id)) is conflict_fsm_runtime.ConflictPhase.RAGE
            and (
                conflict_fsm_runtime.is_extra_hostile(source_user_text)
                or (bot_module is not None and conflict_fsm_runtime.is_direct_hostile(bot_module, source_user_text))
            )
        )
    except Exception:
        return False


def _extract_send_answer_call(args, kwargs):
    force_voice = bool(kwargs.get("force_voice", args[0] if len(args) >= 1 else False))
    source_user_text = kwargs.get("source_user_text", args[2] if len(args) >= 3 else None)
    return force_voice, source_user_text


async def maybe_send_post_text_tag(update, context, source_user_text: str, answer_text: str) -> bool:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if not chat or not user or getattr(user, "is_bot", False) or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False
    if sticker_engine.is_serious_text(source_user_text) or sticker_engine.is_serious_text(answer_text):
        return False

    import sticker_runtime
    now = __import__("time").monotonic()
    rage_exchange = _is_rage_exchange(chat.id, user.id, source_user_text)
    if rage_exchange:
        if not fight_sticker_budget.allowed(chat.id, user.id, now):
            return False
        if random.random() >= fight_sticker_budget.chance(chat.id, user.id, now):
            return False
        sticker_key = random.choice(_RAGE_POST_STICKERS)
    else:
        sticker_key = choose_post_text_tag(source_user_text, answer_text)
        if not sticker_key or random.random() >= POST_TEXT_TAG_CHANCE:
            return False
        if not sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
            return False

    try:
        sent = await sticker_runtime.reply_sticker_by_key(update, context, sticker_key)
    except Exception as error:
        logging.warning("Post-answer sticker tag failed key=%s: %s", sticker_key, error)
        return False
    if not sent:
        return False

    if rage_exchange:
        fight_sticker_budget.record(chat.id, user.id, now)
    else:
        sticker_runtime._record_sticker_slot(chat.id, user.id, now)
    logging.info(
        "Yayceslav post-answer sticker tag: sticker=%s rage=%s fight_count=%s chat=%s user=%s",
        sticker_engine.STICKER_LABELS.get(sticker_key, sticker_key),
        rage_exchange,
        fight_sticker_budget.count(chat.id, user.id, now) if rage_exchange else 0,
        chat.id,
        user.id,
    )
    return True


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "send_answer", None)):
            return module
    return None


def install_send_answer_wrapper() -> bool:
    global _WRAPPER_INSTALLED
    if _WRAPPER_INSTALLED:
        return True
    module = _find_bot_module()
    if module is None:
        logging.warning("Post-answer sticker wrapper: send_answer not found")
        return False
    original = module.send_answer
    if getattr(original, "_yayceslav_post_sticker_wrapped", False):
        _WRAPPER_INSTALLED = True
        return True

    @functools.wraps(original)
    async def wrapped_send_answer(update, context, text, *args, **kwargs):
        result = await original(update, context, text, *args, **kwargs)
        force_voice, source_user_text = _extract_send_answer_call(args, kwargs)
        if force_voice or bool(getattr(context, "user_data", {}).get("voice_mode", False)):
            return result
        if source_user_text:
            await maybe_send_post_text_tag(update, context, str(source_user_text), str(text or ""))
        return result

    wrapped_send_answer._yayceslav_post_sticker_wrapped = True
    module.send_answer = wrapped_send_answer
    _WRAPPER_INSTALLED = True
    logging.warning("Post-answer sticker tags installed: normal shared gate + bounded fight-aware RAGE budget")
    return True
