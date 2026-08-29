"""Keep sensitive one-off claims from becoming accidental biography.

There are two different memories in the bot and both need a guard:

* automatic member callback/theme memory must skip the WHOLE sensitive message,
  not merely the token ``умер`` while still learning ``собака`` from the same bait;
* 15-minute conversational RAM may keep the text for continuity, but the stored
  historical copy is explicitly labelled as a user claim/sensitive topic rather
  than an established personal fact.

The current incoming turn itself is not rewritten, so the bot still responds
normally and seriously when somebody says a dog is injured/dead.  Explicit
/remember_me remains the controlled path for facts the user actually wants saved.
"""

from __future__ import annotations

import functools
import logging
import re
from typing import Any

import member_profile_runtime


_EXTRA_SENSITIVE_FRAGMENTS = (
    "умер", "смерт", "похорон", "травм", "кровотеч", "сепсис",
    "рана", "ранен", "разрыв", "операц", "ветеринар", "инфекц",
)

_SENSITIVE_MESSAGE_RE = re.compile(
    r"(?:"
    r"\b(?:умер\w*|смерт\w*|похорон\w*|суицид\w*|депресс\w*)\b|"
    r"\b(?:ран\w*|порез\w*|кров\w*|сепсис\w*|инфекц\w*|травм\w*)\b|"
    r"\b(?:ветеринар\w*|врач\w*|операц\w*|диагноз\w*|лекарств\w*)\b"
    r")",
    re.IGNORECASE,
)

_HISTORY_PREFIX = (
    "[Чувствительная тема/утверждение пользователя; это контекст разговора, "
    "а не проверенный биографический факт] "
)

_INSTALLED = False
_SHORT_TERM_INSTALLED = False


def is_sensitive_claim_text(text: str) -> bool:
    return bool(_SENSITIVE_MESSAGE_RE.search(str(text or "")))


def _install_automatic_member_memory_guard() -> None:
    """Skip all callback/theme extraction from one sensitive message."""

    original = getattr(member_profile_runtime, "_record_member_terms_sync", None)
    if not callable(original) or getattr(original, "_yayceslav_claim_memory_v3", False):
        return

    @functools.wraps(original)
    def record_terms_guarded(bot_module: Any, chat_id: int, user_id: int, text: str) -> int:
        if is_sensitive_claim_text(text):
            return 0
        return int(original(bot_module, chat_id, user_id, text) or 0)

    record_terms_guarded._yayceslav_claim_memory_v3 = True
    member_profile_runtime._record_member_terms_sync = record_terms_guarded


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    current = tuple(getattr(member_profile_runtime, "_SENSITIVE_FRAGMENTS", ()))
    merged = current + tuple(
        fragment for fragment in _EXTRA_SENSITIVE_FRAGMENTS if fragment not in current
    )
    member_profile_runtime._SENSITIVE_FRAGMENTS = merged
    _install_automatic_member_memory_guard()
    _INSTALLED = True
    logging.warning(
        "Claim memory v3 ready: sensitive messages excluded wholesale from automatic member memory"
    )


def install_short_term_guard(bot_module: Any) -> bool:
    """Label historical RAM copies as claims without changing the live turn."""

    global _SHORT_TERM_INSTALLED
    if _SHORT_TERM_INSTALLED:
        return True

    original = getattr(bot_module, "remember_message", None)
    if not callable(original):
        return False
    if getattr(original, "_yayceslav_claim_history_v3", False):
        _SHORT_TERM_INSTALLED = True
        return True

    @functools.wraps(original)
    def remember_claim_safe(*args: Any, **kwargs: Any):
        positional = list(args)
        role = kwargs.get("role")
        if role is None and len(positional) > 2:
            role = positional[2]

        text_key = None
        for candidate in ("text", "content", "message"):
            if candidate in kwargs:
                text_key = candidate
                break

        if text_key is not None:
            text = kwargs.get(text_key)
        elif len(positional) > 3:
            text = positional[3]
        else:
            text = None

        if role == "user" and isinstance(text, str) and text and not text.startswith(_HISTORY_PREFIX):
            sensitive = is_sensitive_claim_text(text)
            if not sensitive:
                try:
                    sensitive = bool(bot_module.is_serious_text(text))
                except Exception:
                    sensitive = False
            if sensitive:
                safe_text = _HISTORY_PREFIX + text
                if text_key is not None:
                    kwargs[text_key] = safe_text
                elif len(positional) > 3:
                    positional[3] = safe_text

        return original(*positional, **kwargs)

    remember_claim_safe._yayceslav_claim_history_v3 = True
    bot_module.remember_message = remember_claim_safe
    _SHORT_TERM_INSTALLED = True
    logging.warning(
        "Claim memory v3 short-term guard ready: sensitive historical turns marked unverified"
    )
    return True


install()
