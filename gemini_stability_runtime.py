"""Production stability layer for Gemini capacity failures and JSON responses.

This module is intentionally narrow.  It keeps the existing thinking_engine
router as the owner of normal 3.6 -> 3.1 routing, then adds the failure modes
seen in Railway production logs:

* Gemini 3.6 HTTP 503 / UNAVAILABLE falls back to 3.1 immediately;
* repeated 429/503 primary failures use a persisted 30/60/120 minute cooldown;
* if both models are capacity-limited, return a small graceful response instead
  of letting the caller spend minutes retrying the same outage;
* structured voice JSON accepts a valid JSON object wrapped in harmless prose;
* daily-news JSON uses the same bounded object recovery.

No user/chat content is persisted by this runtime.  The only persistent state is
an outage streak timestamp/counter beside the existing model-router state.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

import daily_content_runtime
import thinking_engine
import voice2_runtime


COOLDOWN_STEPS_SECONDS: tuple[int, ...] = (30 * 60, 60 * 60, 120 * 60)
FAILURE_STREAK_RESET_SECONDS = 6 * 60 * 60
CAPACITY_MESSAGE = "Нейронка сейчас перегружена. Попробуй ещё раз чуть позже."

_STATE_FILE = Path(thinking_engine._STATE_DIR) / "gemini_stability_state.json"
_failure_streak = 0
_last_failure_epoch = 0.0
_INSTALLED = False


def _load_stability_state() -> None:
    global _failure_streak, _last_failure_epoch
    try:
        payload = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        _failure_streak = max(0, int(payload.get("failure_streak", 0) or 0))
        _last_failure_epoch = max(0.0, float(payload.get("last_failure_epoch", 0.0) or 0.0))
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        _failure_streak = 0
        _last_failure_epoch = 0.0


def _save_stability_state() -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(
                {
                    "failure_streak": _failure_streak,
                    "last_failure_epoch": _last_failure_epoch,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        logging.warning("Gemini stability: could not persist outage streak: %s", error)


def cooldown_seconds_for_streak(streak: int) -> int:
    index = max(0, min(len(COOLDOWN_STEPS_SECONDS) - 1, int(streak) - 1))
    return COOLDOWN_STEPS_SECONDS[index]


def _adaptive_start_primary_cooldown() -> int:
    """Replace thinking_engine's fixed cooldown with persisted escalation."""

    global _failure_streak, _last_failure_epoch
    now = time.time()
    if _last_failure_epoch <= 0.0 or now - _last_failure_epoch > FAILURE_STREAK_RESET_SECONDS:
        _failure_streak = 0

    _failure_streak += 1
    _last_failure_epoch = now
    duration = cooldown_seconds_for_streak(_failure_streak)

    thinking_engine._primary_blocked_until_epoch = now + duration
    thinking_engine._save_router_state()
    _save_stability_state()

    logging.warning(
        "Gemini stability: primary capacity failure streak=%s; effective 3.6 cooldown=%sm",
        _failure_streak,
        duration // 60,
    )
    return duration


def _error_code(error: BaseException) -> int | None:
    for attribute in ("code", "status_code"):
        try:
            value = int(getattr(error, attribute, 0) or 0)
        except (TypeError, ValueError):
            continue
        if value:
            return value
    return None


def is_unavailable_503(error: BaseException) -> bool:
    if _error_code(error) == 503:
        return True
    text = str(error).upper()
    return "503" in text and (
        "UNAVAILABLE" in text
        or "HIGH DEMAND" in text
        or "SERVICE UNAVAILABLE" in text
    )


def is_capacity_error(error: BaseException) -> bool:
    return bool(thinking_engine._is_quota_429(error) or is_unavailable_503(error))


def extract_json_object(text: Any) -> dict[str, Any] | None:
    """Return the first complete JSON object, respecting quoted braces.

    Unlike a greedy ``{.*}`` regex, this scanner does not merge two objects and
    does not treat braces inside a JSON string as structure.  Truncated objects
    deliberately return ``None``; guessing missing model output is unsafe.
    """

    raw = str(text or "").strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    for start, char in enumerate(raw):
        if char != "{":
            continue

        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            current = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue

            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : index + 1]
                    try:
                        value = json.loads(candidate)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        break
                    if isinstance(value, dict):
                        return value
                    break
                if depth < 0:
                    break

    return None


def _config_from_kwargs(kwargs: dict[str, Any]) -> Any:
    return kwargs.get("config")


def _capacity_response(kwargs: dict[str, Any], error: BaseException) -> Any:
    """Produce a schema-compatible short response when both models are saturated."""

    config = _config_from_kwargs(kwargs)
    schema = getattr(config, "response_schema", None) if config is not None else None
    parsed = None

    fields = getattr(schema, "model_fields", {}) if schema is not None else {}
    if isinstance(fields, dict) and {"transcript", "needs_search", "answer"} <= set(fields):
        payload: dict[str, Any] = {
            "transcript": "",
            "needs_search": False,
            "search_query": "",
            "answer": CAPACITY_MESSAGE,
            "wants_voice": False,
        }
        if "memory_summary" in fields:
            payload["memory_summary"] = ""
        try:
            parsed = schema.model_validate(payload)
        except Exception:
            parsed = None

    logging.warning(
        "Gemini stability: primary and fallback unavailable; returning graceful capacity response: %s",
        error,
    )
    return SimpleNamespace(
        text=CAPACITY_MESSAGE,
        parsed=parsed,
        candidates=[],
    )


async def route_capacity_failure(
    original_generate_content: Callable[..., Awaitable[Any]],
    model_self: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Add 503 fallback outside the existing 429-aware router."""

    requested_model = thinking_engine._requested_model(args, kwargs)
    if requested_model != thinking_engine.PRIMARY_MODEL:
        return await original_generate_content(model_self, *args, **kwargs)

    try:
        return await original_generate_content(model_self, *args, **kwargs)
    except Exception as primary_error:
        if not is_capacity_error(primary_error):
            raise

        now = time.time()
        already_blocked = now < float(thinking_engine._primary_blocked_until_epoch or 0.0)

        if already_blocked:
            return _capacity_response(kwargs, primary_error)

        duration = _adaptive_start_primary_cooldown()
        reason = "503" if is_unavailable_503(primary_error) else "429"
        logging.warning(
            "Gemini stability: 3.6 returned %s -> immediate 3.1; next primary probe in %sm",
            reason,
            duration // 60,
        )

        fallback_args, fallback_kwargs = thinking_engine._with_model(
            args,
            kwargs,
            thinking_engine.FALLBACK_MODEL,
        )
        try:
            return await original_generate_content(
                model_self,
                *fallback_args,
                **fallback_kwargs,
            )
        except Exception as fallback_error:
            if is_capacity_error(fallback_error):
                return _capacity_response(kwargs, fallback_error)
            raise


def _install_capacity_router() -> None:
    try:
        from google.genai.models import AsyncModels
    except Exception as import_error:
        logging.warning("Gemini stability router unavailable: %s", import_error)
        return

    current = AsyncModels.generate_content
    if getattr(current, "_yayceslav_capacity_stability", False):
        return

    async def stable_generate_content(self: Any, *args: Any, **kwargs: Any) -> Any:
        return await route_capacity_failure(current, self, *args, **kwargs)

    stable_generate_content._yayceslav_capacity_stability = True
    AsyncModels.generate_content = stable_generate_content


def install_voice_json_recovery() -> bool:
    """Make only the current VoiceDecision schema tolerant of harmless wrappers."""

    schema = voice2_runtime.VoiceDecision
    current = schema.model_validate_json
    if getattr(current, "_yayceslav_json_recovery", False):
        return True

    def tolerant_model_validate_json(cls, json_data, *args, **kwargs):
        try:
            return current(json_data, *args, **kwargs)
        except Exception:
            payload = extract_json_object(json_data)
            if payload is None:
                raise
            return cls.model_validate(payload)

    tolerant_model_validate_json._yayceslav_json_recovery = True
    schema.model_validate_json = classmethod(tolerant_model_validate_json)
    return True


def parse_news_comment_json(raw: Any) -> tuple[str, str] | None:
    payload = extract_json_object(raw)
    if not payload:
        return None
    tone = str(payload.get("tone", "neutral")).strip().lower()
    comment = daily_content_runtime._clean_space(payload.get("comment", ""))
    if tone not in {"positive", "negative", "neutral"}:
        tone = "neutral"
    if not (8 <= len(comment) <= 140):
        return None
    return tone, comment


async def _robust_comment_news(bot_module: Any, title: str, source_name: str) -> tuple[str, str] | None:
    api_key = str(getattr(bot_module, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None

    prompt = (
        "Ниже заголовок ОДНОЙ новости из популярного российского СМИ. "
        "Не добавляй никаких фактов, которых нет в заголовке. "
        "Определи эмоциональный тон новости как positive, negative или neutral и придумай ОДИН короткий комментарий Яйцеслава. "
        "Позитивное можно отметить победно/иронично, негативное — ворчливо в духе «ну опять всё как всегда», нейтральное — сухо и смешно. "
        "Мат допустим, если он уместен, но не обязателен. Не агитируй и не искажай новость. "
        "Верни СТРОГО JSON: {\"tone\":\"positive|negative|neutral\",\"comment\":\"...\"}. "
        "Комментарий максимум 110 символов.\n\n"
        f"Источник: {source_name}\nЗаголовок: {title}"
    )
    try:
        client = daily_content_runtime.genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=str(getattr(bot_module, "MODEL_NAME", "gemini-3.6-flash")),
            contents=prompt,
            config=daily_content_runtime.types.GenerateContentConfig(
                temperature=0.85,
                max_output_tokens=320,
                system_instruction=(
                    "Ты Яйцеслав. Комментарий к новости — короткий мемный хвост, а не пересказ и не политическая агитация."
                ),
            ),
        )
        parsed = parse_news_comment_json(getattr(response, "text", "") or "")
    except Exception as error:
        logging.warning("Daily news comment generation failed: %s", error)
        return None

    if parsed is None:
        logging.warning("Daily news comment generation returned unusable JSON; omitting comment")
    return parsed


def _install_daily_news_json_recovery() -> None:
    current = daily_content_runtime._comment_news
    if getattr(current, "_yayceslav_json_recovery", False):
        return
    _robust_comment_news._yayceslav_json_recovery = True
    daily_content_runtime._comment_news = _robust_comment_news


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    thinking_engine._start_primary_cooldown = _adaptive_start_primary_cooldown
    _install_capacity_router()
    _install_daily_news_json_recovery()
    install_voice_json_recovery()

    _INSTALLED = True
    logging.warning(
        "Gemini stability ready: 429/503 -> 3.1, adaptive 30/60/120m cooldown, JSON recovery"
    )
    return True


_load_stability_state()
