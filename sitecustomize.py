"""Runtime Gemini model router for Yayceslav.

Policy:
- Use Gemini 3.6 Flash normally.
- On quota/rate-limit 429 from 3.6, immediately retry the same request on
  Gemini 3.1 Flash-Lite.
- For the next 30 minutes, route 3.6 requests directly to 3.1 Flash-Lite.
- After 30 minutes, let exactly one request probe 3.6 again. While that probe
  is in flight, concurrent requests keep using 3.1 Flash-Lite.
- If the probe succeeds, normal 3.6 traffic resumes. If it gets 429 again,
  another 30-minute cooldown starts.

This file is loaded automatically by Python's site module before bot.py.
Keeping the router here avoids invasive changes to the large bot.py file and
covers text, images, documents, voice and every other call that goes through
client.aio.models.generate_content().
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any


PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-3.1-flash-lite"
PRIMARY_RETRY_SECONDS = 30 * 60

# Railway mounts the persistent volume here in this project. Locally, use data/.
_RAILWAY_DATA_DIR = Path("/app/data")
_STATE_DIR = _RAILWAY_DATA_DIR if _RAILWAY_DATA_DIR.exists() else Path("data")
_STATE_FILE = _STATE_DIR / "gemini_model_router.json"

_blocked_until_epoch = 0.0
_primary_probe_in_progress = False


def _load_state() -> None:
    global _blocked_until_epoch

    try:
        payload = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        value = float(payload.get("primary_blocked_until_epoch", 0.0))
        _blocked_until_epoch = max(0.0, value)
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError, OSError):
        _blocked_until_epoch = 0.0


def _save_state() -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(
                {"primary_blocked_until_epoch": _blocked_until_epoch},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        # Routing must still work even if the persistent state cannot be saved.
        logging.warning("Gemini router: could not persist cooldown: %s", error)


def _set_primary_cooldown() -> None:
    global _blocked_until_epoch

    _blocked_until_epoch = time.time() + PRIMARY_RETRY_SECONDS
    _save_state()


def _clear_primary_cooldown() -> None:
    global _blocked_until_epoch

    _blocked_until_epoch = 0.0
    _save_state()


def _is_quota_429(error: BaseException) -> bool:
    """Recognize Gemini quota/rate-limit RESOURCE_EXHAUSTED errors."""

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


def _replace_model(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    model: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Return call arguments with the generate_content model replaced."""

    new_kwargs = dict(kwargs)

    if "model" in new_kwargs:
        new_kwargs["model"] = model
        return args, new_kwargs

    # generate_content is normally called with keyword-only model in bot.py,
    # but keep positional compatibility for SDK callers/tests.
    if args:
        new_args = list(args)
        new_args[0] = model
        return tuple(new_args), new_kwargs

    new_kwargs["model"] = model
    return args, new_kwargs


def _requested_model(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if "model" in kwargs:
        value = kwargs.get("model")
        return str(value) if value is not None else None
    if args:
        return str(args[0])
    return None


_load_state()

try:
    from google.genai.models import AsyncModels
except Exception as import_error:  # pragma: no cover - only protects startup
    logging.warning("Gemini router: AsyncModels patch unavailable: %s", import_error)
else:
    _original_generate_content = AsyncModels.generate_content

    async def _routed_generate_content(self: Any, *args: Any, **kwargs: Any) -> Any:
        global _primary_probe_in_progress

        requested_model = _requested_model(args, kwargs)

        # Never interfere with explicit calls to other Gemini models.
        if requested_model != PRIMARY_MODEL:
            return await _original_generate_content(self, *args, **kwargs)

        now = time.time()

        # Active cooldown: don't spend another 3.6 request at all.
        if now < _blocked_until_epoch:
            fallback_args, fallback_kwargs = _replace_model(
                args, kwargs, FALLBACK_MODEL
            )
            logging.info(
                "Gemini router: %s cooldown active (%.0fs left) -> %s",
                PRIMARY_MODEL,
                _blocked_until_epoch - now,
                FALLBACK_MODEL,
            )
            return await _original_generate_content(
                self, *fallback_args, **fallback_kwargs
            )

        # Cooldown expired. Exactly one concurrent request probes 3.6.
        recovering_from_cooldown = _blocked_until_epoch > 0.0
        if recovering_from_cooldown:
            if _primary_probe_in_progress:
                fallback_args, fallback_kwargs = _replace_model(
                    args, kwargs, FALLBACK_MODEL
                )
                logging.info(
                    "Gemini router: %s probe already in flight -> %s",
                    PRIMARY_MODEL,
                    FALLBACK_MODEL,
                )
                return await _original_generate_content(
                    self, *fallback_args, **fallback_kwargs
                )

            # This assignment happens before the first await, so within the
            # asyncio event loop it atomically reserves the single probe slot.
            _primary_probe_in_progress = True
            logging.info(
                "Gemini router: 30-minute cooldown expired; probing %s",
                PRIMARY_MODEL,
            )

        try:
            try:
                result = await _original_generate_content(self, *args, **kwargs)
            except Exception as primary_error:
                if not _is_quota_429(primary_error):
                    raise

                _set_primary_cooldown()
                logging.warning(
                    "Gemini router: %s returned 429; immediate fallback to %s; "
                    "next primary probe in 30 minutes",
                    PRIMARY_MODEL,
                    FALLBACK_MODEL,
                )

                fallback_args, fallback_kwargs = _replace_model(
                    args, kwargs, FALLBACK_MODEL
                )
                return await _original_generate_content(
                    self, *fallback_args, **fallback_kwargs
                )

            if recovering_from_cooldown:
                _clear_primary_cooldown()
                logging.info(
                    "Gemini router: %s probe succeeded; primary restored",
                    PRIMARY_MODEL,
                )

            return result
        finally:
            if recovering_from_cooldown:
                _primary_probe_in_progress = False

    AsyncModels.generate_content = _routed_generate_content
    logging.info(
        "Gemini router installed: %s -> %s on 429, retry primary after 30 min",
        PRIMARY_MODEL,
        FALLBACK_MODEL,
    )
