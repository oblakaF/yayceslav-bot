from __future__ import annotations

import re
import sys


_PATCHED = False

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
    """Install the follow-up mode wrapper once when the bot module is ready."""
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


# Deliberately no Application.run_polling monkeypatch here. The central
# runtime_bootstrap invokes install() immediately before polling starts.
