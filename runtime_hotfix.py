"""Small production guards for conversation edge cases.

This module is loaded by birthday_engine only when the actual bot process is
started. It patches three narrow runtime behaviors without changing the rest
of Yaiceslav V2:

1. Ground Gemini with the real Moscow date/year so short follow-ups cannot
   reinforce an old hallucinated year from chat memory.
2. Never expose malformed internal voice-control JSON to Telegram users.
3. When a user says only "check/search the internet" as a follow-up, reuse
   the immediately preceding user topic instead of searching an empty string.

The patch is intentionally isolated and idempotent so it can be removed once
these guards are folded into bot.py directly.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any


_PATCH_TIMEOUT_SECONDS = 30.0
_PATCH_POLL_SECONDS = 0.05

_STRUCTURED_VOICE_MARKERS = (
    '"needs_search"',
    '"search_query"',
)

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


def _extract_voice_payload(raw_answer: str) -> dict[str, Any] | None:
    """Parse the control JSON only when a complete object is present."""

    match = re.search(r"\{.*\}", raw_answer or "", flags=re.DOTALL)
    if not match:
        return None

    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    return payload if isinstance(payload, dict) else None


def _looks_like_voice_control_output(raw_answer: str) -> bool:
    text = (raw_answer or "").strip()
    return bool(
        text.startswith("{")
        or any(marker in text for marker in _STRUCTURED_VOICE_MARKERS)
    )


def _is_current_date_query(query: str) -> bool:
    return bool(_CURRENT_DATE_QUERY_RE.search(query or ""))


def _previous_search_topic(module: Any, update: Any, context: Any) -> str:
    """Recover the topic for a bare follow-up such as 'check the internet'."""

    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return ""

    # In private chat the bot already stores the exact previous user query.
    if str(getattr(chat, "type", "")) == "private":
        try:
            previous = str(context.user_data.get("last_user_query", "")).strip()
        except Exception:
            previous = ""
        if previous:
            return previous

    # In groups, walk backwards through short-term memory. At this point the
    # current bare search command has not yet been appended by the main text
    # handler, so the most recent user entry is normally the requested topic.
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
                # Skip an older bare search command; it is not a topic.
                continue

        return candidate

    return ""


def _install(module: Any) -> bool:
    required = (
        "build_full_system_instruction",
        "_resolve_voice_search_answer",
        "perform_web_search",
        "current_msk_datetime",
    )
    if not all(hasattr(module, name) for name in required):
        return False

    # ------------------------------------------------------------------
    # 1. Real date/year in every Gemini system instruction.
    # ------------------------------------------------------------------
    original_build = module.build_full_system_instruction
    if not getattr(original_build, "_yayceslav_date_guard", False):

        def build_with_current_date(*args: Any, **kwargs: Any) -> str:
            instruction = original_build(*args, **kwargs)
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

        build_with_current_date._yayceslav_date_guard = True
        module.build_full_system_instruction = build_with_current_date

    # ------------------------------------------------------------------
    # 2. Voice control JSON must never leak into a user-visible answer.
    # ------------------------------------------------------------------
    original_voice_resolver = module._resolve_voice_search_answer
    if not getattr(original_voice_resolver, "_yayceslav_voice_json_guard", False):

        async def resolve_voice_safely(
            update: Any,
            raw_answer: str,
            *,
            user_settings: dict[str, Any] | None,
        ) -> str:
            payload = _extract_voice_payload(raw_answer)

            if payload is None and _looks_like_voice_control_output(raw_answer):
                logging.warning(
                    "Malformed voice-control JSON suppressed: %r",
                    (raw_answer or "")[:160],
                )
                return (
                    "Голосовуху понял, но служебный ответ нейросети обрезался. "
                    "Повтори вопрос ещё раз."
                )

            if payload is not None:
                needs_search = bool(payload.get("needs_search"))
                direct_answer = str(payload.get("answer") or "").strip()
                if not needs_search and not direct_answer:
                    logging.warning(
                        "Voice-control JSON had no user answer; suppressed payload"
                    )
                    return (
                        "Голосовуху понял, но нейросеть не сформировала ответ. "
                        "Повтори вопрос ещё раз."
                    )

            return await original_voice_resolver(
                update,
                raw_answer,
                user_settings=user_settings,
            )

        resolve_voice_safely._yayceslav_voice_json_guard = True
        module._resolve_voice_search_answer = resolve_voice_safely

    # ------------------------------------------------------------------
    # 3. Bare explicit search follow-ups reuse the previous topic.
    # ------------------------------------------------------------------
    original_web_search = module.perform_web_search
    if not getattr(original_web_search, "_yayceslav_empty_search_guard", False):

        async def perform_web_search_with_context(
            update: Any,
            context: Any,
            query: str,
            force_voice: bool = False,
        ) -> None:
            resolved_query = str(query or "").strip()
            if not resolved_query:
                resolved_query = _previous_search_topic(
                    module,
                    update,
                    context,
                )
                if resolved_query:
                    logging.info(
                        "Bare search follow-up reused previous topic: %r",
                        resolved_query[:160],
                    )

            # Current date/year comes from the process clock, not web snippets.
            # This avoids declaring a random TikTok/VK/promocode result a
            # 'verification' of the calendar year.
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

            await original_web_search(
                update=update,
                context=context,
                query=resolved_query,
                force_voice=force_voice,
            )

        perform_web_search_with_context._yayceslav_empty_search_guard = True
        module.perform_web_search = perform_web_search_with_context

    logging.warning(
        "Runtime hotfix installed: date grounding, voice JSON guard, contextual bare search"
    )
    return True


def _patch_when_bot_ready() -> None:
    deadline = time.monotonic() + _PATCH_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        module = sys.modules.get("__main__")
        if module is not None:
            try:
                if _install(module):
                    return
            except Exception as error:
                logging.exception("Runtime hotfix installation failed: %s", error)
                return
        time.sleep(_PATCH_POLL_SECONDS)

    logging.error("Runtime hotfix was not installed: bot module did not become ready")


def install_for_bot_process() -> None:
    """Start the narrow delayed patch only for `python bot.py` production."""

    if Path(sys.argv[0]).name != "bot.py":
        return

    thread = threading.Thread(
        target=_patch_when_bot_ready,
        name="yayceslav-runtime-hotfix",
        daemon=True,
    )
    thread.start()


install_for_bot_process()
