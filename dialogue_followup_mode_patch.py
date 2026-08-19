from __future__ import annotations

import re
import sys

from telegram.ext import Application


_PATCHED = False
_RUNTIME_HOOK_INSTALLED = False
_ORIGINAL_RUN_POLLING = None

# These are not standalone hostile facts; they are short ping-pong continuations
# that should inherit the banter/challenge controller instead of slipping back
# to normal mode and repeating the previous comeback.
_BANTER_FOLLOWUP_RE = re.compile(
    r"^\s*(?:"
    r"нет\s+ты|"
    r"не\s+ты|"
    r"сам(?:\s+ты|\s+такой)?|"
    r"сам\s+иди(?:\s+на\s*хуй|\s+нахуй)?|"
    r"да\s+ты|"
    r"ты\s+сам|"
    r"от\s+такого\s+слышу"
    r")\s*[.!?]*\s*$",
    flags=re.IGNORECASE,
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "detect_conversation_mode", None)):
            return module
    return None


def install() -> bool:
    global _PATCHED
    if _PATCHED:
        return True

    bot_module = _find_bot_module()
    if bot_module is None:
        return False

    original = bot_module.detect_conversation_mode
    if getattr(original, "_yayceslav_followup_mode_patch", False):
        _PATCHED = True
        return True

    def wrapped(text: str):
        mode = original(text)
        if mode == "normal" and _BANTER_FOLLOWUP_RE.match(text or ""):
            return "challenge"
        return mode

    wrapped._yayceslav_followup_mode_patch = True
    bot_module.detect_conversation_mode = wrapped
    _PATCHED = True
    return True


def install_runtime_hook() -> None:
    global _RUNTIME_HOOK_INSTALLED, _ORIGINAL_RUN_POLLING
    if _RUNTIME_HOOK_INSTALLED:
        return

    _ORIGINAL_RUN_POLLING = Application.run_polling

    def run_polling_with_followup_mode(self, *args, **kwargs):
        install()
        return _ORIGINAL_RUN_POLLING(self, *args, **kwargs)

    Application.run_polling = run_polling_with_followup_mode
    _RUNTIME_HOOK_INSTALLED = True


install_runtime_hook()
