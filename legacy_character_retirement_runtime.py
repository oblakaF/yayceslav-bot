"""Retire the old user-selectable character mode without breaking stored settings.

The bot now has one durable identity: Yayceslav's mythic-Rus core, temperament,
self-canon and current social state. The historical `character` column remains in
SQLite for rollback/backward compatibility, but it no longer owns behavior.

This runtime:
- normalizes every loaded legacy character to `classic` before downstream logic;
- hides the obsolete character row from /settings;
- labels the remaining compatibility value as Yayceslav rather than a selectable
  "classic persona";
- gracefully handles callbacks from old Telegram messages that still contain the
  removed settings_character button.

No schema migration and no extra model call are introduced.
"""

from __future__ import annotations

import functools
import logging
import sys
from typing import Any


_INSTALLED = False
LEGACY_CHARACTER_KEY = "character"
EFFECTIVE_CHARACTER = "classic"


def normalize_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Return settings with the obsolete character dimension neutralized."""
    normalized = dict(settings or {})
    normalized[LEGACY_CHARACTER_KEY] = EFFECTIVE_CHARACTER
    return normalized


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_user_settings_sync", None)):
            return module
    return None


def _patch_settings_loader(bot_module: Any) -> None:
    original = getattr(bot_module, "get_user_settings_sync", None)
    if not callable(original) or getattr(original, "_yayceslav_character_retired", False):
        return

    @functools.wraps(original)
    def load_without_character(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return normalize_settings(original(*args, **kwargs))

    load_without_character._yayceslav_character_retired = True
    bot_module.get_user_settings_sync = load_without_character


def _patch_settings_keyboard(bot_module: Any) -> None:
    original = getattr(bot_module, "build_settings_keyboard", None)
    if not callable(original) or getattr(original, "_yayceslav_character_retired", False):
        return

    @functools.wraps(original)
    def keyboard_without_character(settings: dict[str, Any]):
        keyboard = original(normalize_settings(settings))
        rows = list(getattr(keyboard, "inline_keyboard", ()) or ())
        filtered_rows = []
        for row in rows:
            kept = [
                button
                for button in row
                if getattr(button, "callback_data", None) != "settings_character"
            ]
            if kept:
                filtered_rows.append(kept)
        try:
            return bot_module.InlineKeyboardMarkup(filtered_rows)
        except Exception:
            return keyboard

    keyboard_without_character._yayceslav_character_retired = True
    bot_module.build_settings_keyboard = keyboard_without_character


def _patch_legacy_callback(bot_module: Any) -> None:
    original = getattr(bot_module, "settings_button_callback", None)
    if not callable(original) or getattr(original, "_yayceslav_character_retired", False):
        return

    @functools.wraps(original)
    async def callback_without_character(update: Any, context: Any) -> Any:
        query = getattr(update, "callback_query", None)
        action = getattr(query, "data", None)
        if action != "settings_character":
            return await original(update, context)

        if query is not None:
            try:
                await query.answer("Переключатель персонажа убран: Яйцеслав теперь один.")
            except Exception:
                pass
            try:
                user_id = int(update.effective_user.id)
                settings = await bot_module.get_user_settings(user_id)
                await query.edit_message_reply_markup(
                    reply_markup=bot_module.build_settings_keyboard(settings)
                )
            except Exception as error:
                logging.debug("Legacy character callback cleanup failed: %s", error)
        return None

    callback_without_character._yayceslav_character_retired = True
    bot_module.settings_button_callback = callback_without_character


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    labels = getattr(module, "CHARACTER_LABELS", None)
    if isinstance(labels, dict):
        labels[EFFECTIVE_CHARACTER] = "🥚 Яйцеслав"

    _patch_settings_loader(module)
    _patch_settings_keyboard(module)
    _patch_legacy_callback(module)

    _INSTALLED = True
    logging.warning(
        "Legacy character selector retired: stored values ignored; one Yayceslav identity"
    )
    return True
