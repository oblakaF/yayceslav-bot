"""Context recovery and clock-safe handling for explicit web-search follow-ups."""

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


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "perform_web_search", None)):
            return module
    return None


def _is_current_date_query(query: str) -> bool:
    return bool(_CURRENT_DATE_QUERY_RE.search(query or ""))


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


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED

    module = bot_module or _find_bot_module()
    if module is None:
        return False

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
    logging.warning("Search context runtime ready: bare follow-ups + process-clock date answers")
    return True
