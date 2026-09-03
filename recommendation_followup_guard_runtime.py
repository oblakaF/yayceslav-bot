"""Keep generic recommendation follow-ups owned by the latest category.

Each specialist vertical already has its own short-lived seed state. Before this
guard, those states could coexist and Telegram handler group order decided which
vertical captured a generic ``а ещё?``. That meant an older game request could
steal a follow-up from a newer movie request.

This module adds one tiny chat-local owner pointer. Explicit recommendation
intents move the pointer to their category. Once an owner exists, generic
follow-ups are accepted only by that category. Before the first owner is created
(for example immediately after deploy while old RAM topic state still exists),
the legacy category-local behavior is preserved for compatibility.

Category-named follow-ups (for example ``ещё игры``) remain free to switch back
intentionally because the user supplied the category.

No provider calls, model calls, database tables or polling wrappers are added.
"""

from __future__ import annotations

import functools
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import book_recommendation_runtime
import game_recommendation_runtime
import movie_recommendation_runtime
import music_recommendation_runtime


OWNER_TTL_SECONDS = 2 * 60 * 60
OWNER_MAX_CHATS = 256
_INSTALLED = False


@dataclass(frozen=True)
class RecommendationOwner:
    category: str
    updated_at: float


_ACTIVE_CATEGORY_BY_CHAT: dict[int, RecommendationOwner] = {}

# Deliberately only category-less forms. ``ещё игры`` / ``ещё книги`` are not
# generic: they explicitly tell us which specialist the user wants.
_GENERIC_FOLLOWUP_RE = re.compile(
    r"^\s*(?:"
    r"(?:а\s+)?ещ[её]|"
    r"(?:а\s+)?что\s+ещ[её]|"
    r"дай\s+ещ[её]|"
    r"а\s+похожее|"
    r"похожее\s+ещ[её]"
    r")\s*[?!.]*\s*$",
    re.IGNORECASE,
)


def _prune(now: float) -> None:
    stale = [
        chat_id
        for chat_id, owner in _ACTIVE_CATEGORY_BY_CHAT.items()
        if now - owner.updated_at > OWNER_TTL_SECONDS
    ]
    for chat_id in stale:
        _ACTIVE_CATEGORY_BY_CHAT.pop(chat_id, None)
    while len(_ACTIVE_CATEGORY_BY_CHAT) > OWNER_MAX_CHATS:
        oldest = min(
            _ACTIVE_CATEGORY_BY_CHAT,
            key=lambda key: _ACTIVE_CATEGORY_BY_CHAT[key].updated_at,
        )
        _ACTIVE_CATEGORY_BY_CHAT.pop(oldest, None)


def remember_active_category(chat_id: int, category: str, *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else float(now)
    _prune(current)
    value = str(category or "").strip().lower()
    if value:
        _ACTIVE_CATEGORY_BY_CHAT[int(chat_id)] = RecommendationOwner(value, current)


def active_category(chat_id: int, *, now: float | None = None) -> str:
    current = time.monotonic() if now is None else float(now)
    _prune(current)
    owner = _ACTIVE_CATEGORY_BY_CHAT.get(int(chat_id))
    return owner.category if owner else ""


def is_generic_followup(text: str) -> bool:
    return bool(_GENERIC_FOLLOWUP_RE.fullmatch(str(text or "")))


def _wrap_classifier(module: Any, function_name: str, category: str) -> None:
    original: Callable[..., str] | None = getattr(module, function_name, None)
    if not callable(original) or getattr(original, "_yayceslav_followup_owner_guard", False):
        return

    @functools.wraps(original)
    def guarded(text: str, *, chat_id: int | None = None) -> str:
        value = str(text or "")
        if is_generic_followup(value):
            if chat_id is None:
                return ""
            owner = active_category(int(chat_id))
            if owner and owner != category:
                return ""
            # No owner means a pre-guard/just-deployed local topic may still be
            # valid. Preserve that one legacy path until the next explicit
            # recommendation establishes a deterministic owner.
            return str(original(value, chat_id=chat_id) or "")

        result = str(original(value, chat_id=chat_id) or "")
        if result and chat_id is not None:
            # Explicit or category-named intent becomes the latest owner. This
            # occurs before provider work so a failed specialist lookup cannot
            # leave an older category owning a later generic follow-up.
            remember_active_category(int(chat_id), category)
        return result

    guarded._yayceslav_followup_owner_guard = True
    guarded._yayceslav_followup_owner_category = category
    setattr(module, function_name, guarded)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    _wrap_classifier(book_recommendation_runtime, "classify_book_recommendation_intent", "books")
    _wrap_classifier(movie_recommendation_runtime, "classify_movie_recommendation_intent", "movies")
    _wrap_classifier(game_recommendation_runtime, "classify_game_recommendation_intent", "games")
    _wrap_classifier(music_recommendation_runtime, "classify_recommendation_intent", "music")
    _INSTALLED = True
    return True


install()
