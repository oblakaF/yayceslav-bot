# ============================================================
# YAICESLAV V2 — DYNAMIC GEMINI THINKING POLICY
#
# Gemini 3.6 Flash supports: minimal / low / medium / high.
# The bot should not spend medium reasoning on every casual message.
#
# This module is imported explicitly by bot.py, so the Gemini fallback
# router below is installed on every Railway start.
# ============================================================

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
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


# ============================================================
# GEMINI MODEL FALLBACK
# ============================================================

PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-3.1-flash-lite"
PRIMARY_RETRY_SECONDS = 30 * 60

_RAILWAY_DATA_DIR = Path("/app/data")
_STATE_DIR = _RAILWAY_DATA_DIR if _RAILWAY_DATA_DIR.exists() else Path("data")
_STATE_FILE = _STATE_DIR / "gemini_model_router.json"

_primary_blocked_until_epoch = 0.0
_primary_probe_in_progress = False


def _load_router_state() -> None:
    global _primary_blocked_until_epoch

    try:
        payload = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        value = float(payload.get("primary_blocked_until_epoch", 0.0))
        _primary_blocked_until_epoch = max(0.0, value)
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError, OSError):
        _primary_blocked_until_epoch = 0.0


def _save_router_state() -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(
                {"primary_blocked_until_epoch": _primary_blocked_until_epoch},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        logging.warning("Gemini router: could not persist cooldown: %s", error)


def _start_primary_cooldown() -> None:
    global _primary_blocked_until_epoch

    _primary_blocked_until_epoch = time.time() + PRIMARY_RETRY_SECONDS
    _save_router_state()


def _clear_primary_cooldown() -> None:
    global _primary_blocked_until_epoch

    _primary_blocked_until_epoch = 0.0
    _save_router_state()


def _is_quota_429(error: BaseException) -> bool:
    for attribute in ("code", "status_code"):
        try:
            if int(getattr(error, attribute, 0) or 0) == 429:
                return True
        except (TypeError, ValueError):
            pass

    text = str(error).upper()
    return "429" in text and (
        "RESOURCE_EXHAUSTED" in text
        or "QUOTA" in text
        or "RATE" in text
    )


def _requested_model(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if "model" in kwargs:
        value = kwargs.get("model")
        return str(value) if value is not None else None
    if args:
        return str(args[0])
    return None


def _with_model(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    model: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    new_kwargs = dict(kwargs)

    if "model" in new_kwargs:
        new_kwargs["model"] = model
        return args, new_kwargs

    if args:
        new_args = list(args)
        new_args[0] = model
        return tuple(new_args), new_kwargs

    new_kwargs["model"] = model
    return args, new_kwargs


def _install_gemini_fallback_router() -> None:
    """
    Patch the exact async generate_content method used by bot.py.

    Policy:
    1) use Gemini 3.6 normally;
    2) first 429 from 3.6 -> immediately retry the same request on 3.1;
    3) for 30 minutes route all would-be 3.6 requests directly to 3.1;
    4) after 30 minutes allow one probe to 3.6;
    5) probe 429 -> immediate 3.1 and another 30-minute cooldown;
       probe success -> restore normal 3.6 traffic.
    """

    global _primary_probe_in_progress

    try:
        from google.genai.models import AsyncModels
    except Exception as import_error:
        logging.error(
            "Gemini router: cannot import AsyncModels; fallback disabled: %s",
            import_error,
        )
        return

    if getattr(AsyncModels.generate_content, "_yayceslav_fallback_installed", False):
        return

    original_generate_content = AsyncModels.generate_content

    async def routed_generate_content(self: Any, *args: Any, **kwargs: Any) -> Any:
        global _primary_probe_in_progress

        requested_model = _requested_model(args, kwargs)

        # Only redirect calls that explicitly target the primary chat model.
        if requested_model != PRIMARY_MODEL:
            return await original_generate_content(self, *args, **kwargs)

        now = time.time()

        # During cooldown, 3.6 is not called at all.
        if now < _primary_blocked_until_epoch:
            fallback_args, fallback_kwargs = _with_model(
                args,
                kwargs,
                FALLBACK_MODEL,
            )
            logging.info(
                "Gemini router: 3.6 cooldown active (%.0fs left) -> 3.1",
                _primary_blocked_until_epoch - now,
            )
            return await original_generate_content(
                self,
                *fallback_args,
                **fallback_kwargs,
            )

        recovering_from_cooldown = _primary_blocked_until_epoch > 0.0

        # Once 30 minutes expires, only one concurrent request probes 3.6.
        if recovering_from_cooldown:
            if _primary_probe_in_progress:
                fallback_args, fallback_kwargs = _with_model(
                    args,
                    kwargs,
                    FALLBACK_MODEL,
                )
                logging.info(
                    "Gemini router: 3.6 probe already in flight -> 3.1",
                )
                return await original_generate_content(
                    self,
                    *fallback_args,
                    **fallback_kwargs,
                )

            _primary_probe_in_progress = True
            logging.warning(
                "Gemini router: 30-minute cooldown expired; probing 3.6",
            )

        try:
            try:
                result = await original_generate_content(self, *args, **kwargs)
            except Exception as primary_error:
                if not _is_quota_429(primary_error):
                    raise

                _start_primary_cooldown()
                logging.warning(
                    "Gemini router: 3.6 returned 429 -> immediate 3.1; "
                    "next 3.6 probe in 30 minutes",
                )

                fallback_args, fallback_kwargs = _with_model(
                    args,
                    kwargs,
                    FALLBACK_MODEL,
                )
                return await original_generate_content(
                    self,
                    *fallback_args,
                    **fallback_kwargs,
                )

            if recovering_from_cooldown:
                _clear_primary_cooldown()
                logging.warning(
                    "Gemini router: 3.6 probe succeeded; primary restored",
                )

            return result
        finally:
            if recovering_from_cooldown:
                _primary_probe_in_progress = False

    routed_generate_content._yayceslav_fallback_installed = True
    AsyncModels.generate_content = routed_generate_content

    logging.warning(
        "Gemini router installed: 3.6 -> 3.1 on 429; retry 3.6 after 30 min",
    )


_load_router_state()
_install_gemini_fallback_router()


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
