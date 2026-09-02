"""Append the ВСЁ ТЛЕН sticker when the final runtime rate limit rejects a turn."""

from __future__ import annotations

import functools
import logging
import sys
import time

import voice_live_bootstrap_hook  # noqa: F401


_INSTALLED = False


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "enforce_rate_limit", None)):
            return module
    return None


def install() -> bool:
    """Wrap the FINAL rate-limit function after dialogue_guard has prepared."""
    global _INSTALLED
    if _INSTALLED:
        return True

    bot_module = _find_bot_module()
    if bot_module is None:
        return False

    original = bot_module.enforce_rate_limit
    if getattr(original, "_yayceslav_rate_limit_tlen_final", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    async def wrapped(update, bucket: str):
        allowed = await original(update, bucket)
        if allowed:
            return True

        message = getattr(update, "effective_message", None)
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        if not message or not chat or not user:
            return False

        import sticker_runtime

        now = time.monotonic()
        if not sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
            return False

        try:
            get_bot = getattr(update, "get_bot", None)
            bot = get_bot() if callable(get_bot) else getattr(message, "get_bot", lambda: None)()
            if bot is None:
                return False
            mapping = await sticker_runtime.ensure_sticker_ids(bot)
            file_id = mapping.get("vse_tlen")
            if not file_id:
                return False
            await message.reply_sticker(sticker=file_id)
        except Exception as error:
            logging.info("Rate-limit ВСЁ ТЛЕН sticker skipped: %s", error)
            return False

        sticker_runtime._record_sticker_slot(chat.id, user.id, now)
        return False

    wrapped._yayceslav_rate_limit_tlen_final = True
    bot_module.enforce_rate_limit = wrapped
    _INSTALLED = True
    return True
