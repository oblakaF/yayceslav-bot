"""Short-lived entity/topic continuity across text and search follow-ups.

Yayceslav already keeps broad recent conversation memory, but short anaphoric
follow-ups such as "а сколько ему лет?" are much more reliable when the last
explicitly named entity is tracked separately from general chat noise.

This runtime keeps one bounded topic per chat in RAM for two hours.  It does not
add model calls or a database table.  Strong new entity mentions replace the
old topic; only conservative anaphoric follow-ups receive the continuity hint.
Explicit web searches get the same resolution so "проверь, где он сейчас"
searches the previous entity instead of a context-free pronoun.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import fight_routing_v3


ENTITY_TTL_SECONDS = 2 * 60 * 60
MAX_ENTITY_CHATS = 256
MAX_TOPIC_CHARS = 180
_INSTALLED = False


@dataclass(frozen=True)
class EntityState:
    topic: str
    updated_at: float


_ENTITY_BY_CHAT: dict[int, EntityState] = {}

# Explicit introductions are preferred over generic capitalization because they
# make it clear which object the user is placing at the center of the dialogue.
_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:кто\s+(?:такой|такая)|что\s+(?:такое|за)|расскажи\s+(?:мне\s+)?про|"
        r"расскажи\s+(?:мне\s+)?об|что\s+думаешь\s+про|поговорим\s+про)\s+"
        r"(?P<topic>[^?!.,\n]{2,100})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:who\s+is|what\s+is|tell\s+me\s+about)\s+(?P<topic>[^?!.,\n]{2,100})",
        re.IGNORECASE,
    ),
)

# Conservative: do not treat every pronoun as an entity follow-up.  These are
# the common short questions where a missing antecedent is actually harmful.
_ANAPHORIC_FOLLOWUP_RE = re.compile(
    r"(?:"
    r"^\s*(?:а|ну\s+а|и)\s+(?:сколько|где|когда|почему|зачем|чем|кем|что)\s+"
    r"(?:ему|ей|у\s+него|у\s+не[её]|он|она|они|с\s+ним|с\s+ней|с\s+ними)\b|"
    r"^\s*(?:а|ну\s+а|и)\s+(?:что\s+с|как\s+там)\s+"
    r"(?:ним|ней|ними|этой\s+компанией|этим\s+фильмом|этой\s+машиной|этим\s+проектом)\b|"
    r"\b(?:сколько\s+(?:ему|ей)\s+лет|где\s+(?:он|она|они)\s+(?:сейчас\s+)?"
    r"(?:работает|работают|жив[её]т|находится|находятся)|"
    r"чем\s+(?:он|она|они)\s+(?:сейчас\s+)?занима(?:ется|ются)|"
    r"когда\s+(?:он|она|они)\b|что\s+с\s+(?:ним|ней|ними)\b|"
    r"(?:его|е[её])\s+(?:возраст|компания|работа|карьера|состояние|фильм|машина))"
    r")",
    re.IGNORECASE,
)

# If the current turn names a new likely proper noun, do not force the previous
# entity into it even when a pronoun also appears later in the sentence.
_PROPER_NOUN_RE = re.compile(
    r"(?<![.!?]\s)(?P<name>\b(?:[A-ZА-ЯЁ][a-zа-яё0-9.-]{2,}|[A-Z]{2,})"
    r"(?:\s+(?:[A-ZА-ЯЁ][a-zа-яё0-9.-]{2,}|[A-Z]{2,}|[A-Z0-9-]{2,})){0,3}\b)"
)

_INTERNAL_PREFIX_RE = re.compile(
    r"^(?:ниже\s+(?:находится|приведена)|результаты\s+поиска|system|instruction)\b",
    re.IGNORECASE,
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def _normalize_topic(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" \t\r\n,.:;!?—-\"'«»")
    text = re.sub(r"^(?:фильм|сериал|компания|машина|бренд|проект|игра)\s+", "", text, flags=re.IGNORECASE)
    return text[:MAX_TOPIC_CHARS]


def _current_turn_text(contents: Any) -> str:
    if isinstance(contents, list):
        strings = [str(item) for item in contents if isinstance(item, str)]
        value = strings[-1] if strings else ""
    else:
        value = str(contents or "")
    try:
        return str(fight_routing_v3.current_turn_text(value) or value or "").strip()
    except Exception:
        return value.strip()


def extract_explicit_topic(text: str) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value or _INTERNAL_PREFIX_RE.search(value):
        return ""

    for pattern in _TOPIC_PATTERNS:
        match = pattern.search(value)
        if match:
            topic = _normalize_topic(match.group("topic"))
            if topic and len(topic.split()) <= 8:
                return topic

    # Fallback for compact named-entity queries such as "NVIDIA сейчас как?" or
    # "Jensen Huang кто это?".  Ignore sentence-initial generic Russian words by
    # requiring either Latin/acronym content or two capitalized tokens.
    candidates = []
    for match in _PROPER_NOUN_RE.finditer(value):
        name = _normalize_topic(match.group("name"))
        if not name:
            continue
        tokens = name.split()
        if re.search(r"[A-Za-z]", name) or len(tokens) >= 2 or name.isupper():
            candidates.append(name)
    return candidates[-1] if candidates else ""


def is_anaphoric_followup(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return False
    return bool(_ANAPHORIC_FOLLOWUP_RE.search(value))


def _prune(now: float) -> None:
    stale = [chat_id for chat_id, state in _ENTITY_BY_CHAT.items() if now - state.updated_at > ENTITY_TTL_SECONDS]
    for chat_id in stale:
        _ENTITY_BY_CHAT.pop(chat_id, None)
    if len(_ENTITY_BY_CHAT) <= MAX_ENTITY_CHATS:
        return
    oldest = sorted(_ENTITY_BY_CHAT.items(), key=lambda item: item[1].updated_at)
    for chat_id, _state in oldest[: len(_ENTITY_BY_CHAT) - MAX_ENTITY_CHATS]:
        _ENTITY_BY_CHAT.pop(chat_id, None)


def remember_topic(chat_id: int, topic: str, *, now: float | None = None) -> str:
    clean = _normalize_topic(topic)
    if not clean:
        return ""
    timestamp = time.monotonic() if now is None else float(now)
    _prune(timestamp)
    _ENTITY_BY_CHAT[int(chat_id)] = EntityState(clean, timestamp)
    return clean


def current_topic(chat_id: int, *, now: float | None = None) -> str:
    timestamp = time.monotonic() if now is None else float(now)
    _prune(timestamp)
    state = _ENTITY_BY_CHAT.get(int(chat_id))
    if state is None or timestamp - state.updated_at > ENTITY_TTL_SECONDS:
        return ""
    return state.topic


def resolve_followup(chat_id: int, text: str) -> str:
    current = " ".join(str(text or "").split()).strip()
    if not current:
        return current

    explicit = extract_explicit_topic(current)
    if explicit:
        remember_topic(chat_id, explicit)
        return current
    if not is_anaphoric_followup(current):
        return current

    topic = current_topic(chat_id)
    if not topic:
        return current
    return f"{topic}. Уточнение пользователя: {current}"


def _continuity_hint(topic: str, current: str) -> str:
    return (
        "ENTITY CONTINUITY — последняя явно названная сущность/тема этого чата: "
        f"{topic}. Текущая реплика: {current}. Разрешай местоимения и короткие "
        "follow-up вопросы к этой сущности только если это семантически подходит. "
        "Если пользователь явно сменил предмет разговора, игнорируй этот hint. "
        "Не рассказывай пользователю про внутренний entity-state."
    )


def _patch_ask_gemini(module: Any) -> None:
    original = getattr(module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_entity_continuity", False):
        return

    @functools.wraps(original)
    async def ask_with_entity_continuity(contents: Any, *args: Any, **kwargs: Any):
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        if chat_id is None or user_id is None:
            return await original(contents, *args, **kwargs)

        current = _current_turn_text(contents)
        explicit = extract_explicit_topic(current)
        if explicit:
            remember_topic(int(chat_id), explicit)
        elif is_anaphoric_followup(current):
            topic = current_topic(int(chat_id))
            if topic:
                call_kwargs = dict(kwargs)
                recent = list(call_kwargs.get("recent_messages") or [])
                recent.append(_continuity_hint(topic, current))
                call_kwargs["recent_messages"] = recent
                return await original(contents, *args, **call_kwargs)

        return await original(contents, *args, **kwargs)

    ask_with_entity_continuity._yayceslav_entity_continuity = True
    module.ask_gemini = ask_with_entity_continuity


def _patch_web_search(module: Any) -> None:
    original = getattr(module, "perform_web_search", None)
    if not callable(original) or getattr(original, "_yayceslav_entity_search_continuity", False):
        return

    @functools.wraps(original)
    async def search_with_entity_continuity(
        update: Any,
        context: Any,
        query: str,
        force_voice: bool = False,
    ) -> None:
        chat = getattr(update, "effective_chat", None)
        if chat is None:
            return await original(update=update, context=context, query=query, force_voice=force_voice)

        resolved = resolve_followup(int(chat.id), str(query or ""))
        return await original(
            update=update,
            context=context,
            query=resolved,
            force_voice=force_voice,
        )

    search_with_entity_continuity._yayceslav_entity_search_continuity = True
    module.perform_web_search = search_with_entity_continuity


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _patch_ask_gemini(module)
    _patch_web_search(module)
    _INSTALLED = True
    logging.warning(
        "Entity continuity ready: last explicit topic/chat, 2h TTL, text + search follow-ups; no extra model call"
    )
    return True
