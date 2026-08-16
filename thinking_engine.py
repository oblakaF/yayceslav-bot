# ============================================================
# YAICESLAV V2 — DYNAMIC GEMINI THINKING POLICY
#
# Gemini 3.6 Flash supports: minimal / low / medium / high.
# The bot should not spend medium reasoning on every casual message.
# ============================================================

from __future__ import annotations

# ============================================================
# GEMINI MODEL FALLBACK
#
# 3.6 Flash remains primary. If Google explicitly reports that the
# per-day free-tier quota for that model is exhausted, the same request
# is retried once with 3.1 Flash-Lite. Further requests use the fallback
# until the Pacific calendar day changes, when 3.6 is tried again.
# ============================================================

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.genai import models as _genai_models


PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-3.1-flash-lite"

try:
    _PACIFIC_TIMEZONE = ZoneInfo("America/Los_Angeles")
except ZoneInfoNotFoundError:
    # Missing tzdata must never prevent the bot from starting.
    # UTC is only a conservative fallback; at worst the bot tries 3.6
    # once before the real Pacific reset and immediately falls back again.
    _PACIFIC_TIMEZONE = timezone.utc

_PRIMARY_QUOTA_EXHAUSTED_PT_DATE: str | None = None
_ORIGINAL_ASYNC_GENERATE_CONTENT = _genai_models.AsyncModels.generate_content


def _today_pacific_date() -> str:
    """Calendar date used by Google free-tier daily quota resets."""

    return datetime.now(_PACIFIC_TIMEZONE).date().isoformat()


def _is_primary_daily_quota_error(error: Exception) -> bool:
    """Match only the per-day model quota, not transient RPM/TPM 429s."""

    message = str(error).lower()

    if "429" not in message or "resource_exhausted" not in message:
        return False

    return (
        "generaterequestsperdayperprojectpermodel-freetier" in message
        or "requestsperdayperprojectpermodel" in message
    )


def _route_gemini_model(requested_model: str) -> str:
    """Select primary/fallback model from the remembered quota state."""

    global _PRIMARY_QUOTA_EXHAUSTED_PT_DATE

    if requested_model != PRIMARY_MODEL:
        return requested_model

    today = _today_pacific_date()

    if _PRIMARY_QUOTA_EXHAUSTED_PT_DATE == today:
        return FALLBACK_MODEL

    if _PRIMARY_QUOTA_EXHAUSTED_PT_DATE is not None:
        logging.info(
            "Gemini daily quota window changed; trying %s again.",
            PRIMARY_MODEL,
        )
        _PRIMARY_QUOTA_EXHAUSTED_PT_DATE = None

    return PRIMARY_MODEL


async def _generate_content_with_fallback(
    self: Any,
    *,
    model: str,
    contents: Any,
    config: Any = None,
) -> Any:
    """Transparent 3.6 -> 3.1 fallback for an exhausted daily quota."""

    global _PRIMARY_QUOTA_EXHAUSTED_PT_DATE

    routed_model = _route_gemini_model(model)

    try:
        return await _ORIGINAL_ASYNC_GENERATE_CONTENT(
            self,
            model=routed_model,
            contents=contents,
            config=config,
        )

    except Exception as error:
        if (
            model == PRIMARY_MODEL
            and routed_model == PRIMARY_MODEL
            and _is_primary_daily_quota_error(error)
        ):
            _PRIMARY_QUOTA_EXHAUSTED_PT_DATE = _today_pacific_date()

            logging.warning(
                "Gemini daily quota exhausted for %s; switching to %s "
                "for Pacific date %s.",
                PRIMARY_MODEL,
                FALLBACK_MODEL,
                _PRIMARY_QUOTA_EXHAUSTED_PT_DATE,
            )

            return await _ORIGINAL_ASYNC_GENERATE_CONTENT(
                self,
                model=FALLBACK_MODEL,
                contents=contents,
                config=config,
            )

        raise


def _install_gemini_model_fallback() -> None:
    """Install the wrapper once for every async generate_content call."""

    current = _genai_models.AsyncModels.generate_content

    if getattr(current, "_yayceslav_model_fallback", False):
        return

    setattr(
        _generate_content_with_fallback,
        "_yayceslav_model_fallback",
        True,
    )

    _genai_models.AsyncModels.generate_content = (  # type: ignore[method-assign]
        _generate_content_with_fallback
    )


_install_gemini_model_fallback()

import re
from typing import Any


THINKING_MINIMAL = "minimal"
THINKING_LOW = "low"
THINKING_MEDIUM = "medium"

SUPPORTED_LEVELS = {
    THINKING_MINIMAL,
    THINKING_LOW,
    THINKING_MEDIUM,
    "high",
}

_INITIAL_TOKEN_FLOOR = {
    THINKING_MINIMAL: 384,
    THINKING_LOW: 512,
    THINKING_MEDIUM: 768,
    "high": 1024,
}


_COMPLEX_RE = re.compile(
    r"\b(?:"
    r"проанализир\w*|анализ\w*|сравни\w*|сопостав\w*|"
    r"разбери\w*\s+подроб|подробн\w*\s+разбор|"
    r"докажи\w*|обоснуй\w*|аргумент\w*\s+(?:за|против)|"
    r"дебат\w*|пошагов\w*|по\s+шагам|"
    r"плюс\w*\s+и\s+минус\w*|сильн\w*\s+и\s+слаб\w*\s+сторон|"
    r"оцени\w*\s+(?:достоверност|риски|вариант)|"
    r"результат\w*\s+поиск|интернет-проверк\w*|источник\w*"
    r")\b",
    re.IGNORECASE,
)

_EXPLICIT_EXPLAIN_RE = re.compile(
    r"\b(?:объясни\w*|разъясни\w*|растолкуй\w*|разбери\w*)\b",
    re.IGNORECASE,
)

_SUBSTANTIVE_QUESTION_RE = re.compile(
    r"\b(?:почему|каким\s+образом|как\s+работает|что\s+такое|"
    r"что\s+(?:ты\s+)?думаешь|как\s+(?:ты\s+)?считаешь|"
    r"расскажи\w*|зачем|стоит\s+ли)\b",
    re.IGNORECASE,
)

_FAST_STYLE_RE = re.compile(
    r"\b(?:прожарь\w*|мемн\w*\s+подпис|коротк\w*\s+подкол|"
    r"плохой\s+совет|одна[-–— ]две\s+строк)\b",
    re.IGNORECASE,
)

_CASUAL_RE = re.compile(
    r"\b(?:привет|здарова|здорово|ку|лол|кек|ахах\w*|хаха\w*|"
    r"ага|угу|да|нет|ок(?:ей)?|база|кринж|рофл|"
    r"дебил\w*|дурак\w*|нищ\w*|скуф\w*|"
    r"согласен|точно|реально|жиза)\b",
    re.IGNORECASE,
)


def content_to_text(contents: Any) -> str:
    """Extract only useful textual content for the thinking policy."""

    if isinstance(contents, str):
        return contents

    if isinstance(contents, (list, tuple)):
        parts: list[str] = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)

    return ""


def choose_thinking_level(
    contents: Any,
    *,
    explicit: str | None = None,
) -> str:
    """
    Choose latency/quality balance for Gemini 3.6 Flash.

    Rules:
    - explicit validated level always wins;
    - search/analysis/debate/explicit explanation => medium;
    - short casual/banter/simple style tasks => minimal;
    - ordinary substantive chat => low.
    """

    if explicit is not None:
        normalized = explicit.strip().lower()
        if normalized not in SUPPORTED_LEVELS:
            raise ValueError(f"Unsupported thinking level: {explicit}")
        return normalized

    text = content_to_text(contents).strip()
    if not text:
        return THINKING_LOW

    if _COMPLEX_RE.search(text) or _EXPLICIT_EXPLAIN_RE.search(text):
        return THINKING_MEDIUM

    if _FAST_STYLE_RE.search(text):
        return THINKING_MINIMAL

    if _SUBSTANTIVE_QUESTION_RE.search(text):
        return (
            THINKING_MEDIUM
            if len(text) >= 320
            else THINKING_LOW
        )

    words = re.findall(r"[\wёЁ]+", text, flags=re.UNICODE)

    if len(text) <= 120 and len(words) <= 18:
        return THINKING_MINIMAL

    if _CASUAL_RE.search(text) and len(text) <= 220:
        return THINKING_MINIMAL

    return THINKING_LOW


def initial_token_budget(requested: int, thinking_level: str) -> int:
    """Keep visible-length instructions, but avoid tiny reasoning budgets."""

    if thinking_level not in SUPPORTED_LEVELS:
        raise ValueError(f"Unsupported thinking level: {thinking_level}")

    requested = max(1, int(requested))
    return max(requested, _INITIAL_TOKEN_FLOOR[thinking_level])
