"""Context recovery and clock-safe handling for explicit web-search follow-ups.

Besides bare ``проверь в интернете`` follow-ups, this layer treats relative-time
phrases such as ``вчера``, ``сегодня`` and ``только что`` as freshness signals.
Weak/anaphoric queries are combined with the previous chat topic so a request
like ``он вчера прилетел, проверь`` does not lose the entity and accidentally
surface an old but lexically similar story.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any


_INSTALLED = False
_CURRENT_DATE_QUERY_RE = re.compile(
    r"(?:"
    r"\b(?:какой|который)\s+(?:сейчас\s+)?год\b|"
    r"\bгод\s+(?:сейчас\s+)?(?:какой|который)\b|"
    r"\b(?:какая|которая)\s+(?:сейчас\s+)?дата\b|"
    r"\bдата\s+(?:сейчас\s+)?(?:какая|которая)\b|"
    r"\bкакое\s+сегодня\s+число\b|"
    r"\bсегодняшн\w*\s+дата\b|"
    r"\bwhat\s+(?:year|date)\s+is\s+it\b|"
    r"\bwhat(?:'s|\s+is)\s+the\s+date\b"
    r")",
    re.IGNORECASE,
)

_FRESHNESS_RE = re.compile(
    r"(?:"
    r"\bсегодня\b|\bвчера\b|\bпозавчера\b|\bсейчас\b|"
    r"\bтолько\s+что\b|\bнедавно\b|\bсвеж\w*\b|\bактуальн\w*\b|"
    r"\bпоследн\w*\s+(?:новост\w*|событ\w*|данн\w*)\b|"
    r"\bза\s+(?:сегодня|вчера|последн\w*\s+(?:час|день|сутк|недел)\w*)\b|"
    r"\b(?:today|yesterday|just\s+now|latest|recent)\b"
    r")",
    re.IGNORECASE,
)

_WEAK_FOLLOWUP_RE = re.compile(
    r"(?:"
    r"^\s*(?:не\s+)?(?:вот\s+)?(?:он|она|они|это|там|так)\b|"
    r"\b(?:он|она|они|это)\s+(?:же\s+)?(?:вчера|сегодня|недавно|только\s+что)\b|"
    r"\b(?:я\s+же\s+говорю|вот\s+же|прям\s+вчера)\b"
    r")",
    re.IGNORECASE,
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "perform_web_search", None)):
            return module
    return None


def _is_current_date_query(query: str) -> bool:
    return bool(_CURRENT_DATE_QUERY_RE.search(query or ""))


def is_freshness_query(query: str) -> bool:
    return bool(_FRESHNESS_RE.search(str(query or "")))


def _looks_weak_followup(query: str) -> bool:
    text = " ".join(str(query or "").split()).strip()
    if not text:
        return True
    if _WEAK_FOLLOWUP_RE.search(text):
        return True
    # Very short fresh requests often contain only a pronoun/action/time marker.
    return is_freshness_query(text) and len(text.split()) <= 7


def _previous_search_topic(module: Any, update: Any, context: Any) -> str:
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return ""

    if str(getattr(chat, "type", "")) == "private":
        try:
            previous = str(context.user_data.get("last_user_query", "")).strip()
        except Exception:
            previous = ""
        if previous:
            return previous

    memory_store = getattr(module, "GROUP_MEMORY", {})
    memory = memory_store.get(getattr(chat, "id", None)) if memory_store else None
    if not memory:
        return ""

    extract_search_query = getattr(module, "extract_search_query", None)
    for entry in reversed(memory):
        try:
            _timestamp, role, _author, text = entry
        except (TypeError, ValueError):
            continue
        if role != "user":
            continue
        candidate = str(text or "").strip()
        if not candidate:
            continue
        if callable(extract_search_query):
            extracted = extract_search_query(candidate)
            if extracted is not None:
                extracted = str(extracted).strip()
                if extracted:
                    return extracted
                continue
        return candidate
    return ""


def _combine_with_previous_topic(module: Any, update: Any, context: Any, query: str) -> str:
    current = " ".join(str(query or "").split()).strip()
    if not current or not _looks_weak_followup(current):
        return current

    previous = _previous_search_topic(module, update, context)
    if not previous:
        return current
    if previous.lower() in current.lower() or current.lower() in previous.lower():
        return current

    combined = f"{previous}. Уточнение пользователя: {current}"
    logging.info("Fresh/anaphoric search reused previous topic: %r", combined[:220])
    return combined


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    # Extend the existing news/freshness gate without changing search cost or
    # adding another network call. search_web will keep using the same DDGS call,
    # but relative-date requests now receive the existing month timelimit.
    original_is_news_query = getattr(module, "is_news_query", None)
    if callable(original_is_news_query) and not getattr(original_is_news_query, "_yayceslav_freshness", False):
        def is_news_query_with_freshness(query: str) -> bool:
            return bool(original_is_news_query(query) or is_freshness_query(query))

        is_news_query_with_freshness._yayceslav_freshness = True
        module.is_news_query = is_news_query_with_freshness

    original = module.perform_web_search
    if getattr(original, "_yayceslav_search_context", False):
        _INSTALLED = True
        return True

    async def perform_web_search_with_context(
        update: Any,
        context: Any,
        query: str,
        force_voice: bool = False,
    ) -> None:
        resolved_query = str(query or "").strip()
        if not resolved_query:
            resolved_query = _previous_search_topic(module, update, context)
            if resolved_query:
                logging.info(
                    "Bare search follow-up reused previous topic: %r",
                    resolved_query[:160],
                )
        else:
            resolved_query = _combine_with_previous_topic(
                module, update, context, resolved_query
            )

        if resolved_query and _is_current_date_query(resolved_query):
            if not await module.enforce_rate_limit(update, "search"):
                return
            now_msk = module.current_msk_datetime()
            await module.register_user_and_chat(update)
            await module.increment_stat("total_requests")
            await module.increment_stat("search_requests")
            message = getattr(update, "effective_message", None)
            if message is not None:
                await message.reply_text(
                    f"Сейчас {now_msk.year} год. "
                    f"Системная дата: {now_msk.strftime('%d.%m.%Y')} (МСК)."
                )
                await module.increment_stat("bot_answers")
            return

        await original(
            update=update,
            context=context,
            query=resolved_query,
            force_voice=force_voice,
        )

    perform_web_search_with_context._yayceslav_search_context = True
    module.perform_web_search = perform_web_search_with_context
    module._yayceslav_search_context_installed = True
    _INSTALLED = True
    logging.warning(
        "Search context runtime ready: bare/anaphoric follow-ups + relative-date freshness + process-clock date answers"
    )
    return True
