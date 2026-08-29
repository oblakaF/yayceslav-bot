"""Conflict-aware /title gate.

A user who still has unresolved hostility toward Yayceslav today must not be
rewarded with a wholesome/random title just because they invoke /title. For a
self-title request, unresolved hostility forces a negative title and a hostile
framing. Explicitly assigning a title to somebody else via reply remains
unchanged so one person's feud cannot punish an innocent target.

No Gemini calls, background work, or new storage are added; this reuses the
existing daily hostility profile and title pools.
"""

from __future__ import annotations

import logging
import random
import sys

from telegram.constants import ChatType
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler

import hostile_streak_engine
import title_pools


_PREPARED_APPLICATION_IDS: set[int] = set()


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_member_profile", None)):
            return module
    return None


def should_punish_self_title(
    *,
    requester_id: int,
    target_id: int,
    active_insults_today: int,
    penance_pending: bool,
) -> bool:
    """Only unresolved self-title requests are conflict-gated."""

    if int(requester_id) != int(target_id):
        return False
    return int(active_insults_today or 0) > 0 or bool(penance_pending)


def choose_hostile_title(previous_title: str | None, *, rng=random) -> str:
    """Force one of the deliberately negative pools."""

    return title_pools.pick_title(previous_title, tier="negative", rng=rng)


def format_hostile_title_reply(display_name: str, title: str, *, rage: bool) -> str:
    name = display_name or "участник"
    if rage:
        return (
            f"Титул ещё клянчишь после того, как со мной срался? Наглости вагон. "
            f"Держи заслуженное: {name} — «{title}». И не ной теперь."
        )
    return (
        f"После сегодняшних наездов добрый титул ты не заслужил. "
        f"Держи по поведению: {name} — «{title}»."
    )


async def _conflict_title_gate(update, context) -> None:
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    requester = getattr(update, "effective_user", None)
    if message is None or chat is None or requester is None or requester.is_bot:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Preserve the existing /title semantics: a reply gives the title to the
    # replied-to human. A feud of the requester must never punish that target.
    target = requester
    replied = getattr(message, "reply_to_message", None)
    replied_user = getattr(replied, "from_user", None) if replied is not None else None
    if replied_user is not None and not replied_user.is_bot:
        target = replied_user

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    profile = await bot_module.get_member_profile(int(chat.id), int(requester.id))
    active_insults = int((profile or {}).get("hostility_today", 0) or 0)
    penance_pending = bool((profile or {}).get("penance_pending", False))

    if not should_punish_self_title(
        requester_id=int(requester.id),
        target_id=int(target.id),
        active_insults_today=active_insults,
        penance_pending=penance_pending,
    ):
        return

    target_profile = await bot_module.get_member_profile(int(chat.id), int(target.id))
    previous_title = (target_profile or {}).get("current_title")
    new_title = choose_hostile_title(previous_title)

    await bot_module.set_member_title(
        int(chat.id),
        int(target.id),
        new_title,
        str(chat.type),
    )

    display_name = target.first_name or target.username or "участник"
    rage = hostile_streak_engine.current(int(chat.id), int(requester.id)) >= 2
    await message.reply_text(
        format_hostile_title_reply(display_name, new_title, rage=rage)
    )

    # The hostile title fully replaces the ordinary /title handler; otherwise
    # the old handler would immediately overwrite it with a random nice title.
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return

    application.add_handler(CommandHandler("title", _conflict_title_gate), group=-4)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Conflict-aware /title ready: unresolved self-feuds force negative titles"
    )
