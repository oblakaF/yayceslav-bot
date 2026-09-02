"""Small sticker-behavior tuning layer.

Goals:
- make emotionally fitting stickers noticeably more common;
- keep hard anti-spam limits even with higher per-event probabilities;
- never let a random group sticker addressed to somebody else trigger Yayceslav.

No extra persistence or background workers are introduced.
"""

from __future__ import annotations

import functools
import logging

from telegram.constants import ChatType


_INSTALLED = False
_APPLIED = False

# User-facing tuning is expressed as percentage points rather than a multiplier:
# every sticker probability gets +5 pp from the previous tuning layer.
BACKGROUND_CAP = 0.08
QUESTION_CHANCE = 0.12
POST_TEXT_TAG_CHANCE = 0.13
AGGRESSIVE_EVENT_CAP = 0.06
PROBABILITY_BUMP = 0.05


def _apply_tuning() -> None:
    global _APPLIED
    if _APPLIED:
        return

    import sticker_engine
    import sticker_interaction
    import sticker_post_runtime
    import sticker_runtime

    # Higher probability does not mean unbounded spam: shared cooldown/window
    # gates still cap the actual number of stickers that can be sent.
    sticker_runtime.STICKER_CHAT_COOLDOWN_SECONDS = 8 * 60.0
    sticker_runtime.STICKER_USER_COOLDOWN_SECONDS = 15 * 60.0
    sticker_runtime.STICKER_MAX_PER_WINDOW = 3

    sticker_engine.BACKGROUND_STICKER_CHANCE_CAP = BACKGROUND_CAP
    for event, chance in tuple(sticker_engine.EVENT_CHANCE.items()):
        if event in {"hard_dismissal", "shut_up_escalated"}:
            # These used to sit below 1% and were practically invisible.
            # Raise them by the same +5 percentage points, but keep a separate
            # 6% ceiling so hostile visuals still do not dominate conversation.
            sticker_engine.EVENT_CHANCE[event] = min(
                AGGRESSIVE_EVENT_CAP,
                float(chance) + PROBABILITY_BUMP,
            )
        else:
            sticker_engine.EVENT_CHANCE[event] = min(
                BACKGROUND_CAP,
                float(chance) + PROBABILITY_BUMP,
            )

    # Snapshot the intentionally tuned semantic layer before fight-v2 installs.
    # Fight-v2 has its own guaranteed RAGE-sticker path; its legacy helper also
    # tries to raise hostile semantic event chances to 10%, which would silently
    # override the bounded +5pp contract above. Restore this snapshot afterwards
    # instead of letting the two independent mechanisms fight over one variable.
    tuned_event_chances = dict(sticker_engine.EVENT_CHANCE)

    sticker_interaction.QUESTION_STICKER_REPLY_CHANCE = QUESTION_CHANCE
    sticker_post_runtime.POST_TEXT_TAG_CHANCE = POST_TEXT_TAG_CHANCE

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

    # The focused fight layer reuses the existing semantic sticker registry and
    # conflict FSM. It is installed only after the base sticker runtime exists,
    # so no duplicate handlers or second conflict state machine are introduced.
    import fight_mode_v2_tuning
    fight_mode_v2_tuning.install()

    # Group-first policy is intentionally installed LAST.  It replaces the
    # accumulated post-answer wrapper chain with one visible outgoing group
    # policy while still reusing the same semantics, fight state and delivery.
    import group_sticker_behavior_v2
    group_sticker_behavior_v2.install()

    # Dedicated RAGE visuals remain active, while normal semantic probabilities
    # stay exactly at the values produced by the bounded tuning pass above.
    for event, chance in tuned_event_chances.items():
        sticker_engine.EVENT_CHANCE[event] = float(chance)

    _APPLIED = True
    logging.warning(
        "Sticker tuning ready: background/events<=8%%, aggressive-events<=6%%, "
        "private-question<=12%%, group=text-first + semantic post-tags, "
        "group RAGE=v2 diverse pool, cooldown=8m/chat 15m/user, max=3/hour; "
        "group sticker replies must target bot"
    )


def install() -> bool:
    """Attach tuning to the existing Aug19 semantic startup hook.

    runtime_hotfix calls this before polling. The actual sticker registry is
    extended later by runtime_bootstrap, so wrapping that extension guarantees
    new Aug19 events get the same probability tuning and the listener is patched
    before Telegram handlers are registered.
    """

    global _INSTALLED
    if _INSTALLED:
        return True

    import sticker_semantics_aug19

    original_install_runtime = sticker_semantics_aug19.install_runtime_behavior
    if not getattr(original_install_runtime, "_yayceslav_sticker_tuning", False):
        @functools.wraps(original_install_runtime)
        def install_runtime_with_tuning() -> None:
            original_install_runtime()
            _apply_tuning()

        install_runtime_with_tuning._yayceslav_sticker_tuning = True
        sticker_semantics_aug19.install_runtime_behavior = install_runtime_with_tuning

    # Tests or unusual startup paths may call us after semantic runtime setup.
    if getattr(sticker_semantics_aug19, "_INSTALLED_RUNTIME", False):
        _apply_tuning()

    _INSTALLED = True
    return True