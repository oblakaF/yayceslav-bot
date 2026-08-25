"""Small sticker-behavior tuning layer.

Goals:
- make emotionally fitting stickers a little more common;
- keep strong anti-spam limits;
- never let a random group sticker addressed to somebody else trigger Yayceslav.

No extra persistence or background workers are introduced.
"""

from __future__ import annotations

import functools
import logging

from telegram.constants import ChatType


_INSTALLED = False


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    import sticker_engine
    import sticker_interaction
    import sticker_post_runtime
    import sticker_runtime

    # Slightly more visible, still bounded. This is intentionally a small
    # increase rather than chaos-mode spam.
    sticker_runtime.STICKER_CHAT_COOLDOWN_SECONDS = 8 * 60.0
    sticker_runtime.STICKER_USER_COOLDOWN_SECONDS = 15 * 60.0
    sticker_runtime.STICKER_MAX_PER_WINDOW = 3

    sticker_engine.BACKGROUND_STICKER_CHANCE_CAP = 0.03
    for event, chance in tuple(sticker_engine.EVENT_CHANCE.items()):
        # Aggressive events stay below 1%; ordinary emotional events get a
        # modest lift and are still capped globally at 3%.
        if event in {"hard_dismissal", "shut_up_escalated"}:
            sticker_engine.EVENT_CHANCE[event] = min(0.009, float(chance) * 1.15)
        else:
            sticker_engine.EVENT_CHANCE[event] = min(0.03, float(chance) * 1.35)

    sticker_interaction.QUESTION_STICKER_REPLY_CHANCE = 0.07
    sticker_post_runtime.POST_TEXT_TAG_CHANCE = 0.08

    original_listener = sticker_runtime.own_pack_sticker_listener
    if not getattr(original_listener, "_yayceslav_directed_stickers", False):
        @functools.wraps(original_listener)
        async def directed_own_pack_listener(update, context):
            chat = getattr(update, "effective_chat", None)
            if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                # A sticker has no text mention, so in a group the only clear
                # way to address it to the bot is to send it as a reply to one
                # of Yayceslav's messages. Stickers between humans are ignored.
                if not sticker_runtime._is_direct_call(update, context):
                    return
            return await original_listener(update, context)

        directed_own_pack_listener._yayceslav_directed_stickers = True
        sticker_runtime.own_pack_sticker_listener = directed_own_pack_listener

    _INSTALLED = True
    logging.warning(
        "Sticker tuning ready: background<=3%%, question<=7%%, post-tag<=8%%, "
        "cooldown=8m/chat 15m/user, max=3/hour; group sticker replies must target bot"
    )
    return True
