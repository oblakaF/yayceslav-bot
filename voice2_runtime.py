"""Structured Voice 2.0 control path for incoming audio/video messages.

This runtime keeps the existing multimodal handler and search flow intact, but
replaces the fragile prompt-only JSON control message with Gemini structured
output. The transcript exists only inside the current request and is never
written to chat memory or SQLite.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import sys
import time
from typing import Any

from pydantic import BaseModel, Field


class VoiceDecision(BaseModel):
    transcript: str = Field(
        default="",
        max_length=700,
        description="Short faithful transcript/summary of what the user said.",
    )
    needs_search: bool = False
    search_query: str = Field(default="", max_length=220)
    answer: str = Field(default="", max_length=1000)
    wants_voice: bool = False


_VOICE_REPLY_OVERRIDE: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "yayceslav_voice_reply_override",
    default=None,
)
_INSTALLED = False
_STRUCTURED_VOICE_MARKERS = ('"needs_search"', '"search_query"')
_EXPLICIT_VOICE_REPLY_RE = re.compile(
    r"(?:\b(?:ответь|ответьте|ответить|скажи|скажи-ка|говори|произнеси)\b.{0,36}\bголос(?:ом|овой|овое|овую)?\b"
    r"|\bголос(?:ом|овой|овое|овую)?\b.{0,36}\b(?:ответь|ответьте|ответить|скажи|говори|произнеси)\b)",
    flags=re.IGNORECASE | re.DOTALL,
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def _is_voice_decision_request(contents: Any) -> bool:
    if not isinstance(contents, list):
        return False
    text_parts = "\n".join(str(item) for item in contents if isinstance(item, str))
    return (
        "Прослушай сообщение пользователя" in text_parts
        and '"needs_search"' in text_parts
        and '"search_query"' in text_parts
        and '"answer"' in text_parts
    )


def _prompt_text(contents: Any) -> str:
    if isinstance(contents, list):
        return " ".join(str(item) for item in contents if isinstance(item, str))
    return str(contents or "")


def _extract_voice_payload(raw_answer: str) -> dict[str, Any] | None:
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


def _transcript_explicitly_requests_voice(transcript: str) -> bool:
    """Deterministically detect a spoken request to receive the reply as audio.

    The model still supplies ``wants_voice`` for flexible phrasing, but an
    obvious phrase such as ``ответь мне голосом`` must never be left to model
    classification or the ordinary 50/50 voice coin flip.
    """

    normalized = " ".join((transcript or "").split()).strip()
    if not normalized:
        return False
    return bool(_EXPLICIT_VOICE_REPLY_RE.search(normalized))


def _normalize_decision(decision: VoiceDecision) -> VoiceDecision:
    transcript = " ".join(decision.transcript.split()).strip()[:700]
    query = " ".join(decision.search_query.split()).strip()[:220]
    answer = " ".join(decision.answer.split()).strip()[:1000]

    if decision.needs_search:
        # A bare "проверь в интернете" should never collapse to an empty query.
        # The transcript is available for this single request only and is not
        # persisted anywhere after the handler finishes.
        if not query:
            query = transcript[:220]
        answer = ""
    else:
        query = ""

    wants_voice = bool(decision.wants_voice) or _transcript_explicitly_requests_voice(
        transcript
    )

    return VoiceDecision(
        transcript=transcript,
        needs_search=bool(decision.needs_search),
        search_query=query,
        answer=answer,
        wants_voice=wants_voice,
    )


async def _structured_voice_decision(bot_module, contents: Any, kwargs: dict[str, Any]) -> str:
    user_settings = kwargs.get("user_settings")
    chat_id = kwargs.get("chat_id")
    chat_type = kwargs.get("chat_type", "private")
    user_name = kwargs.get("user_name", "")
    recent_messages = kwargs.get("recent_messages")
    bot_was_mentioned = kwargs.get("bot_was_mentioned", True)
    user_id = kwargs.get("user_id")
    max_output_tokens = int(kwargs.get("max_output_tokens", 320) or 320)

    member_profile = None
    get_member_profile = getattr(bot_module, "get_member_profile", None)
    if callable(get_member_profile) and chat_id is not None and user_id is not None:
        try:
            member_profile = await get_member_profile(chat_id, user_id)
        except Exception as error:
            logging.warning("Voice 2.0 member profile lookup failed: %s", error)

    style_text = _prompt_text(contents)
    current_instruction = bot_module.build_full_system_instruction(
        style_text,
        user_settings,
        voice_style=False,
        chat_id=chat_id,
        chat_type=chat_type,
        user_name=user_name,
        recent_messages=recent_messages,
        bot_was_mentioned=bot_was_mentioned,
        member_profile=member_profile,
        user_id=user_id,
    )
    current_instruction += (
        "\n\nVOICE 2.0 CONTROL: return only the structured schema. "
        "transcript is a short faithful rendering of the user's actual request; "
        "needs_search is true only when current/verifiable web data is needed; "
        "search_query must contain the concrete subject to search; answer is the "
        "direct user-facing response when search is not needed; wants_voice is "
        "true only if the user explicitly asked to receive a voice/audio reply."
    )

    token_budget = max(512, min(1024, max_output_tokens * 2))
    last_error: Exception | None = None

    for attempt in range(1, 3):
        started = time.monotonic()
        try:
            async with bot_module.GEMINI_SEMAPHORE:
                response = await asyncio.wait_for(
                    bot_module.gemini_client.aio.models.generate_content(
                        model=bot_module.MODEL_NAME,
                        contents=contents,
                        config=bot_module.types.GenerateContentConfig(
                            system_instruction=current_instruction,
                            max_output_tokens=token_budget,
                            thinking_config=bot_module.types.ThinkingConfig(
                                thinking_level="low",
                            ),
                            response_mime_type="application/json",
                            response_schema=VoiceDecision,
                        ),
                    ),
                    timeout=90,
                )

            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, VoiceDecision):
                decision = parsed
            elif isinstance(parsed, dict):
                decision = VoiceDecision.model_validate(parsed)
            else:
                decision = VoiceDecision.model_validate_json(str(response.text or "{}"))

            decision = _normalize_decision(decision)
            _VOICE_REPLY_OVERRIDE.set(decision.wants_voice)
            logging.info(
                "Voice 2.0 decision: %.2fs search=%s query=%r wants_voice=%s",
                time.monotonic() - started,
                decision.needs_search,
                decision.search_query,
                decision.wants_voice,
            )
            return json.dumps(decision.model_dump(), ensure_ascii=False)
        except Exception as error:
            last_error = error
            logging.warning(
                "Voice 2.0 structured decision attempt %s/2 failed: %s",
                attempt,
                error,
            )
            if attempt < 2:
                token_budget = min(1024, token_budget * 2)
                await asyncio.sleep(1)

    if last_error:
        raise last_error
    raise RuntimeError("Voice 2.0 structured decision failed")


def _install_voice_resolver_guard(bot_module) -> None:
    original = bot_module._resolve_voice_search_answer
    if getattr(original, "_yayceslav_voice_json_guard", False):
        return

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
            transcript = str(payload.get("transcript") or "").strip()
            explicit_voice = bool(payload.get("wants_voice")) or _transcript_explicitly_requests_voice(
                transcript
            )
            if explicit_voice:
                _VOICE_REPLY_OVERRIDE.set(True)
            if not needs_search and not direct_answer:
                logging.warning("Voice-control JSON had no user answer; suppressed payload")
                return (
                    "Голосовуху понял, но нейросеть не сформировала ответ. "
                    "Повтори вопрос ещё раз."
                )

        return await original(update, raw_answer, user_settings=user_settings)

    resolve_voice_safely._yayceslav_voice_json_guard = True
    bot_module._resolve_voice_search_answer = resolve_voice_safely


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    bot_module = _find_bot_module()
    if bot_module is None:
        return False

    required = ("_should_reply_as_voice", "_resolve_voice_search_answer")
    if not all(hasattr(bot_module, name) for name in required):
        return False

    original_ask = bot_module.ask_gemini
    original_voice_choice = bot_module._should_reply_as_voice

    async def ask_gemini_voice2(contents: Any, *args, **kwargs):
        if not _is_voice_decision_request(contents):
            return await original_ask(contents, *args, **kwargs)
        try:
            return await _structured_voice_decision(bot_module, contents, kwargs)
        except Exception as error:
            # Safe fallback keeps the old path available if the installed SDK or
            # provider temporarily rejects schema output. Resolver containment
            # below guarantees malformed legacy control JSON is not user-visible.
            logging.warning("Voice 2.0 falling back to legacy JSON prompt: %s", error)
            _VOICE_REPLY_OVERRIDE.set(None)
            return await original_ask(contents, *args, **kwargs)

    def should_reply_as_voice_voice2(answer_length: int) -> bool:
        override = _VOICE_REPLY_OVERRIDE.get()
        _VOICE_REPLY_OVERRIDE.set(None)
        if override is True:
            return True
        return original_voice_choice(answer_length)

    ask_gemini_voice2._yayceslav_voice2 = True
    should_reply_as_voice_voice2._yayceslav_voice2 = True
    bot_module.ask_gemini = ask_gemini_voice2
    bot_module._should_reply_as_voice = should_reply_as_voice_voice2
    _install_voice_resolver_guard(bot_module)
    _INSTALLED = True
    logging.warning(
        "Voice 2.0 ready: structured schema, ephemeral transcript, member profile, explicit voice request, JSON containment"
    )
    return True
