"""Telegram runtime for Yayceslav's sticker pack.

Imported for side effects by passive_engine. It patches Application.run_polling
once, adding:
- /stickers with the official public pack;
- recognition/replies only for Yayceslav's own sticker set;
- a 5% chance to replace a direct question answer with one own sticker;
- rare contextual sticker drops in background group chat.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    MessageHandler,
    filters,
)

import sticker_engine
import sticker_interaction


DATA_DIR = Path("/app/data") if Path("/app/data").exists() else Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
STICKER_ID_CACHE_PATH = DATA_DIR / "yayceslav_sticker_ids.json"

STICKER_CHAT_COOLDOWN_SECONDS = 180.0
STICKER_USER_COOLDOWN_SECONDS = 300.0
STICKER_WINDOW_SECONDS = 15 * 60.0
STICKER_MAX_PER_WINDOW = 3
QUIET_HOURS_START_MSK = 0
QUIET_HOURS_END_MSK = 7

_CHAT_LAST_STICKER: dict[int, float] = {}
_USER_LAST_STICKER: dict[tuple[int, int], float] = {}
_CHAT_STICKER_TIMES: dict[int, deque[float]] = defaultdict(deque)

# Learned from the live public pack on first use. file_unique_id is used for
# incoming recognition because it is stable and directly present on Message.sticker.
_STICKER_UNIQUE_IDS: dict[str, str] = {}


def _load_sticker_ids() -> dict[str, str]:
    try:
        payload = json.loads(STICKER_ID_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return {
        str(key): str(value)
        for key, value in payload.items()
        if key in sticker_engine.STICKER_ORDER and value
    }


def _save_sticker_ids(mapping: dict[str, str]) -> None:
    try:
        STICKER_ID_CACHE_PATH.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        logging.warning("Could not persist Yayceslav sticker ids: %s", error)


_STICKER_IDS: dict[str, str] = _load_sticker_ids()


async def ensure_sticker_catalog(bot, *, force: bool = False) -> dict[str, str]:
    """Resolve the live public pack to outgoing file_ids and incoming IDs."""

    global _STICKER_IDS, _STICKER_UNIQUE_IDS

    if _STICKER_IDS and _STICKER_UNIQUE_IDS and not force:
        return _STICKER_IDS

    sticker_set = await bot.get_sticker_set(sticker_engine.STICKER_SET_NAME)
    stickers = tuple(sticker_set.stickers or ())
    expected = len(sticker_engine.STICKER_ORDER)

    if len(stickers) < expected:
        raise RuntimeError(
            f"Sticker set has {len(stickers)} stickers, expected at least {expected}"
        )

    outgoing: dict[str, str] = {}
    incoming: dict[str, str] = {}

    for index, key in enumerate(sticker_engine.STICKER_ORDER):
        sticker = stickers[index]
        outgoing[key] = sticker.file_id
        incoming[sticker.file_unique_id] = key

    _STICKER_IDS = outgoing
    _STICKER_UNIQUE_IDS = incoming
    _save_sticker_ids(outgoing)
    logging.info("Yayceslav sticker catalog resolved: %s stickers", len(outgoing))
    return outgoing


async def ensure_sticker_ids(bot, *, force: bool = False) -> dict[str, str]:
    """Backward-compatible alias used by the sending path."""

    return await ensure_sticker_catalog(bot, force=force)


async def own_sticker_key(bot, sticker) -> str | None:
    """Recognize only stickers belonging to Yayceslav's official set."""

    if not sticker or sticker.set_name != sticker_engine.STICKER_SET_NAME:
        return None

    await ensure_sticker_catalog(bot)
    key = _STICKER_UNIQUE_IDS.get(sticker.file_unique_id)
    if key:
        return key

    # Pack order/file ids can change after the user edits the public pack.
    await ensure_sticker_catalog(bot, force=True)
    return _STICKER_UNIQUE_IDS.get(sticker.file_unique_id)


def _quiet_hours_msk() -> bool:
    hour = datetime.now(timezone(timedelta(hours=3))).hour
    return QUIET_HOURS_START_MSK <= hour < QUIET_HOURS_END_MSK


def sticker_slot_allowed(chat_id: int, user_id: int, now: float) -> bool:
    """Global anti-spam gate for unsolicited contextual sticker drops."""

    if _quiet_hours_msk():
        return False

    if now - _CHAT_LAST_STICKER.get(chat_id, 0.0) < STICKER_CHAT_COOLDOWN_SECONDS:
        return False

    if (
        now - _USER_LAST_STICKER.get((chat_id, user_id), 0.0)
        < STICKER_USER_COOLDOWN_SECONDS
    ):
        return False

    history = _CHAT_STICKER_TIMES[chat_id]
    while history and now - history[0] > STICKER_WINDOW_SECONDS:
        history.popleft()

    return len(history) < STICKER_MAX_PER_WINDOW


def _record_sticker_slot(chat_id: int, user_id: int, now: float) -> None:
    _CHAT_LAST_STICKER[chat_id] = now
    _USER_LAST_STICKER[(chat_id, user_id)] = now
    _CHAT_STICKER_TIMES[chat_id].append(now)


def _main_hard_mode_already_intervened(context, now: float) -> bool:
    """Do not stack sticker + emoji/text hard-mode intervention."""

    for key in (
        "hard_last_reaction",
        "hard_last_random_reply",
        "hard_last_trigger_reply",
    ):
        try:
            last_value = float(context.chat_data.get(key, 0.0))
        except (TypeError, ValueError):
            continue

        if last_value and now - last_value < 5.0:
            return True

    return False


def _is_direct_call(update, context) -> bool:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return False

    if chat.type == ChatType.PRIVATE:
        return True

    replied_to_bot = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == context.bot.id
    )
    if replied_to_bot:
        return True

    return sticker_engine.is_direct_address(
        message.text or "",
        context.bot.username or "",
    )


async def stickers_command(update, context) -> None:
    """Public command: link to the official Yayceslav sticker pack."""

    del context
    message = update.effective_message
    if not message:
        return

    await message.reply_text(
        "Стикеры Яйцеслава:\n"
        + sticker_engine.STICKER_PACK_URL
    )


async def reply_sticker_by_key(update, context, sticker_key: str) -> bool:
    """Reply with one sticker by canonical internal key."""

    message = update.effective_message
    if not message:
        return False

    mapping = await ensure_sticker_ids(context.bot)
    file_id = mapping.get(sticker_key)
    if not file_id:
        return False

    try:
        await message.reply_sticker(sticker=file_id)
        return True
    except BadRequest as error:
        # Cached Telegram file_ids are normally stable. If Telegram rejects one,
        # refresh the live set once and retry rather than silently dying forever.
        if "file" not in str(error).lower():
            raise

        mapping = await ensure_sticker_ids(context.bot, force=True)
        file_id = mapping.get(sticker_key)
        if not file_id:
            return False

        await message.reply_sticker(sticker=file_id)
        return True


async def own_pack_sticker_listener(update, context) -> None:
    """Reply only to stickers from Yayceslav's own public sticker set."""

    message = update.effective_message
    user = update.effective_user
    if not message or not message.sticker or not user or user.is_bot:
        return

    # This is the hard boundary requested by the user: all foreign packs are
    # ignored completely and never get a bot reaction from this subsystem.
    incoming_key = await own_sticker_key(context.bot, message.sticker)
    if not incoming_key:
        return

    reply_key = sticker_interaction.choose_own_pack_comeback(incoming_key)
    if not reply_key:
        return

    try:
        sent = await reply_sticker_by_key(update, context, reply_key)
    except Exception as error:
        logging.warning(
            "Yayceslav own-sticker reply failed incoming=%s reply=%s: %s",
            incoming_key,
            reply_key,
            error,
        )
        return

    if not sent:
        return

    logging.info(
        "Yayceslav own-sticker conversation: incoming=%s reply=%s chat=%s user=%s",
        sticker_engine.STICKER_LABELS.get(incoming_key, incoming_key),
        sticker_engine.STICKER_LABELS.get(reply_key, reply_key),
        update.effective_chat.id if update.effective_chat else None,
        user.id,
    )

    # No other bot subsystem should additionally answer the same own sticker.
    raise ApplicationHandlerStop


async def direct_question_sticker_listener(update, context) -> None:
    """Replace 5% of direct question answers with one own sticker."""

    message = update.effective_message
    user = update.effective_user
    if not message or not message.text or not user or user.is_bot:
        return

    # Do not answer edited messages a second time.
    if update.edited_message is not None:
        return

    text = message.text.strip()
    if (
        not text
        or text.startswith("/")
        or sticker_engine.is_serious_text(text)
        or not sticker_interaction.is_question(text)
        or not _is_direct_call(update, context)
    ):
        return

    if random.random() >= sticker_interaction.QUESTION_STICKER_REPLY_CHANCE:
        return

    sticker_key = sticker_interaction.choose_question_sticker(text)

    try:
        sent = await reply_sticker_by_key(update, context, sticker_key)
    except Exception as error:
        logging.warning(
            "Yayceslav 5%% question sticker failed key=%s: %s",
            sticker_key,
            error,
        )
        return

    if not sent:
        return

    logging.info(
        "Yayceslav direct question answered by sticker (5%% slot): %s chat=%s user=%s",
        sticker_engine.STICKER_LABELS.get(sticker_key, sticker_key),
        update.effective_chat.id if update.effective_chat else None,
        user.id,
    )

    # This sticker IS the answer. Stop answer_text_message and all later groups.
    raise ApplicationHandlerStop


async def contextual_sticker_listener(update, context) -> None:
    """Rare context-aware sticker reply to background group conversation."""

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not message.text or not chat or not user or user.is_bot:
        return

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    text = message.text.strip()
    if not text or text.startswith("/") or sticker_engine.is_serious_text(text):
        return

    # Direct calls are handled by bot.py, except the explicit 5% replacement
    # slot above. Never add a second sticker after a direct answer.
    if _is_direct_call(update, context):
        return

    event = sticker_engine.detect_event(text, direct=False)
    if not event:
        return

    now = time.monotonic()

    # group=2 runs after the existing hard-mode listener (group=1), so these
    # timestamps tell us whether that same message already got attention.
    if _main_hard_mode_already_intervened(context, now):
        return

    if not sticker_slot_allowed(chat.id, user.id, now):
        return

    if random.random() >= sticker_engine.event_chance(event):
        return

    sticker_key = sticker_engine.choose_sticker_key(event)
    if not sticker_key:
        return

    # Reserve before Telegram await: concurrent_updates cannot double-send.
    _record_sticker_slot(chat.id, user.id, now)

    try:
        sent = await reply_sticker_by_key(update, context, sticker_key)
    except Exception as error:
        logging.warning(
            "Yayceslav contextual sticker failed event=%s key=%s: %s",
            event,
            sticker_key,
            error,
        )
        return

    if sent:
        logging.info(
            "Yayceslav contextual sticker: event=%s sticker=%s chat=%s user=%s",
            event,
            sticker_engine.STICKER_LABELS.get(sticker_key, sticker_key),
            chat.id,
            user.id,
        )


def install_runtime_hooks() -> None:
    """Patch PTB once so existing bot.py gains sticker handlers at startup."""

    if getattr(Application, "_yayceslav_sticker_patch_installed", False):
        return

    original_run_polling = Application.run_polling

    def run_polling_with_yayceslav_stickers(self, *args, **kwargs):
        if not getattr(self, "_yayceslav_sticker_handlers_added", False):
            self.add_handler(
                CommandHandler("stickers", stickers_command),
                group=0,
            )

            # Negative group executes before bot.py group=0. If one of these
            # sends a sticker, ApplicationHandlerStop prevents a duplicate text
            # response. PTB officially supports this handler-group behavior.
            self.add_handler(
                MessageHandler(
                    filters.Sticker.ALL,
                    own_pack_sticker_listener,
                ),
                group=-1,
            )
            self.add_handler(
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    direct_question_sticker_listener,
                ),
                group=-1,
            )

            self.add_handler(
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    contextual_sticker_listener,
                ),
                group=2,
            )

            self._yayceslav_sticker_handlers_added = True
            logging.warning(
                "Yayceslav stickers installed: own-pack replies ON; foreign packs ignored; "
                "direct-question sticker chance=5%%; contextual map=%s events",
                len(sticker_engine.EVENT_STICKERS),
            )

        return original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_yayceslav_stickers
    Application._yayceslav_sticker_patch_installed = True


install_runtime_hooks()
