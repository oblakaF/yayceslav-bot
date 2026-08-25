"""First-class current-date grounding for Gemini instructions.

This replaces the old production-only runtime_hotfix thread. Installation is
explicit from runtime_bootstrap after the bot module is fully initialized.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


_INSTALLED = False


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(
            getattr(module, "build_full_system_instruction", None)
        ):
            return module
    return None


def install(bot_module: Any | None = None) -> bool:
    """Append authoritative Moscow process date/time to every Gemini prompt."""

    global _INSTALLED

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    original = module.build_full_system_instruction
    if getattr(original, "_yayceslav_date_grounding", False):
        _INSTALLED = True
        return True

    if not callable(getattr(module, "current_msk_datetime", None)):
        return False

    def build_with_current_date(*args: Any, **kwargs: Any) -> str:
        instruction = original(*args, **kwargs)
        now_msk = module.current_msk_datetime()
        return (
            instruction
            + "\n\nСИСТЕМНАЯ ДАТА (достоверные данные процесса): "
            + now_msk.strftime("%d.%m.%Y %H:%M МСК")
            + f". Сейчас {now_msk.year} год. "
            + "Если пользователь спрашивает текущий год, дату или время, "
            + "используй эти данные. Если кратковременная память или твой "
            + "предыдущий ответ им противоречат, предыдущий ответ ошибочен; "
            + "не защищай и не повторяй его."
        )

    build_with_current_date._yayceslav_date_grounding = True
    module.build_full_system_instruction = build_with_current_date
    module._yayceslav_date_grounding_installed = True
    _INSTALLED = True
    logging.warning("Date grounding runtime ready: authoritative Moscow date/time")
    return True
