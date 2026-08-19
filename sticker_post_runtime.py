"""Rare semantic sticker punchlines after a normal Yayceslav text answer.

This is deliberately separate from:
- sticker -> sticker/text replies;
- <=5% direct-question sticker replacement;
- rare background sticker interventions.

A post-answer tag is a SECOND message after a real text answer, e.g. a concise
argument followed by ПЕРЕИГРАЛ И УНИЧТОЖИЛ, or an obvious explanation followed
by БАЗА. It never replaces the actual answer.
"""

from __future__ import annotations

import functools
import logging
import random
import re
import sys
from typing import Final

from telegram.constants import ChatType

import sticker_engine
import sticker_interaction


# Rare even after a semantic match. The shared sticker_runtime anti-spam gate
# further limits the actual rate in a group.
POST_TEXT_TAG_CHANCE: Final = 0.05

_OUTPLAY_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "self_own",
        "outplayed",
        "weak_take",
        "skill_issue",
        "swagger",
        "aura_loss",
        "fight",
    }
)

_OUTPLAY_ANSWER_RE = re.compile(
    r"(?:"
    r"сам(?:\s+себя|\s+себе)|"
    r"противореч\w*|"
    r"аргумент\w*|"
    r"логик\w*|"
    r"по\s+факт\w*|"
    r"факт\w*|"
    r"получается|"
    r"в\s+итоге|"
    r"на\s+деле|"
    r"потому\s+что|"
    r"не\s+вывез\w*|"
    r"поймал\w*|"
    r"опроверг\w*"
    r")",
    re.IGNORECASE,
)

_BASE_ANSWER_RE = re.compile(
    r"(?:"
    r"\bда[,.:;!?\s]|"
    r"\bнет[,.:;!?\s]|"
    r"очевидн\w*|"
    r"вс[её]\s+просто|"
    r"тут\s+вс[её]\s+просто|"
    r"по\s+сути|"
    r"именно|"
    r"разумеется|"
    r"конечно|"
    r"потому\s+что"
    r")",
    re.IGNORECASE,
)

_WRAPPER_INSTALLED = False


def choose_post_text_tag(source_user_text: str, answer_text: str) -> str | None:
    """Return a semantic SECOND-message sticker tag, or None.

    This function does not roll probability; it only decides whether one of the
    two currently approved post-answer punchlines actually fits the exchange.
    """

    source = (source_user_text or "").strip()
    answer = (answer_text or "").strip()
    if not source or not answer:
        return None

    if sticker_engine.is_serious_text(source) or sticker_engine.is_serious_text(answer):
        return None

    event = sticker_engine.detect_event(source, direct=False)

    # Textual counterargument / roast lands first, then the visual victory tag.
    if event in _OUTPLAY_EVENTS and len(answer) >= 24 and _OUTPLAY_ANSWER_RE.search(answer):
        return "pereigral_i_unichtozhil"

    # Short non-serious question gets a real explanation first; БАЗА can then
    # work as the dry mocking full stop when the answer states something basic.
    if (
        len(source) <= 240
        and sticker_interaction.is_question(source)
        and len(answer) >= 20
        and _BASE_ANSWER_RE.search(answer)
    ):
        return "baza"

    return None


def _extract_send_answer_call(args, kwargs):
    """Read send_answer optional args without depending on call style."""

    force_voice = bool(kwargs.get("force_voice", args[0] if len(args) >= 1 else False))
    source_user_text = kwargs.get(
        "source_user_text",
        args[2] if len(args) >= 3 else None,
    )
    return force_voice, source_user_text


async def maybe_send_post_text_tag(update, context, source_user_text: str, answer_text: str) -> bool:
    """Send the rare second-message sticker if all semantic/rate gates pass."""

    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if (
        not chat
        or not user
        or getattr(user, "is_bot", False)
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
    ):
        return False

    sticker_key = choose_post_text_tag(source_user_text, answer_text)
    if not sticker_key:
        return False

    if random.random() >= POST_TEXT_TAG_CHANCE:
        return False

    # Import lazily: sticker_runtime is fully initialized by the time an answer
    # can be sent, and this avoids a circular import during startup.
    import sticker_runtime

    now = __import__("time").monotonic()
    if not sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
        return False

    try:
        sent = await sticker_runtime.reply_sticker_by_key(update, context, sticker_key)
    except Exception as error:
        logging.warning("Post-answer sticker tag failed key=%s: %s", sticker_key, error)
        return False

    if not sent:
        return False

    sticker_runtime._record_sticker_slot(chat.id, user.id, now)
    logging.info(
        "Yayceslav post-answer sticker tag: sticker=%s chat=%s user=%s",
        sticker_engine.STICKER_LABELS.get(sticker_key, sticker_key),
        chat.id,
        user.id,
    )
    return True


def _find_bot_module():
    # Railway starts the project as `python bot.py`, where the live module is
    # __main__. Tests/imported runs may expose it as `bot` instead.
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "send_answer", None)):
            return module
    return None


def install_send_answer_wrapper() -> bool:
    """Wrap the already-defined bot.send_answer once, at polling startup."""

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
        if not source_user_text:
            return result

        await maybe_send_post_text_tag(
            update,
            context,
            str(source_user_text),
            str(text or ""),
        )
        return result

    wrapped_send_answer._yayceslav_post_sticker_wrapped = True
    module.send_answer = wrapped_send_answer
    _WRAPPER_INSTALLED = True
    logging.warning(
        "Post-answer sticker tags installed: БАЗА / ПЕРЕИГРАЛ И УНИЧТОЖИЛ; "
        "semantic-only, chance<=5%%, shared anti-spam gate"
    )
    return True
