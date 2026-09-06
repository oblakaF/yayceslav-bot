"""Emergency resource guardrails for low-cost Railway operation.

This module deliberately favors bounded memory/cost over maximum throughput.
It does not remove durable SQLite memory. It only constrains process RAM,
multimedia size, concurrent expensive work and stale cache growth.
"""

from __future__ import annotations

import asyncio
import ctypes
import functools
import gc
import logging
import sys
from typing import Any


MAX_MEDIA_BYTES = 6 * 1024 * 1024
RAM_TTL_SECONDS = 30 * 60
RAM_MAX_MESSAGES = 30
GEMINI_CONCURRENCY = 1
SEARCH_CONCURRENCY = 1
_INSTALLED = False


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def _looks_multimodal(contents: Any) -> bool:
    return isinstance(contents, (list, tuple)) and any(
        not isinstance(item, str) for item in contents
    )


def trim_process_heap() -> None:
    """Best-effort return of released arenas to the Linux container."""
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        trim = getattr(libc, "malloc_trim", None)
        if trim is not None:
            trim(0)
    except Exception:
        pass


def _schedule_heap_trim() -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.call_later(0.25, trim_process_heap)
    except RuntimeError:
        trim_process_heap()


def _patch_media_cleanup(bot_module: Any) -> None:
    original = getattr(bot_module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_emergency_resource_guard", False):
        return

    @functools.wraps(original)
    async def ask_with_resource_cleanup(contents: Any, *args: Any, **kwargs: Any):
        is_media = _looks_multimodal(contents)
        try:
            return await original(contents, *args, **kwargs)
        finally:
            if is_media:
                # Delay until the caller has had a chance to drop its local Part/bytes.
                _schedule_heap_trim()

    ask_with_resource_cleanup._yayceslav_emergency_resource_guard = True
    bot_module.ask_gemini = ask_with_resource_cleanup


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    # Expensive Gemini/media requests are serialized. This is intentional while
    # Railway budget is the limiting resource.
    module.GEMINI_SEMAPHORE = asyncio.Semaphore(GEMINI_CONCURRENCY)
    if hasattr(module, "SEARCH_SEMAPHORE"):
        module.SEARCH_SEMAPHORE = asyncio.Semaphore(SEARCH_CONCURRENCY)

    # All existing media handlers read MAX_FILE_SIZE dynamically from bot.py.
    module.MAX_FILE_SIZE = MAX_MEDIA_BYTES

    # Keep recent conversational RAM small; durable semantic history remains in
    # SQLite and can still be retrieved when relevant.
    module.GROUP_MEMORY_SECONDS = RAM_TTL_SECONDS
    module.PRIVATE_MEMORY_SECONDS = RAM_TTL_SECONDS
    module.GROUP_MEMORY_MAX_MESSAGES = RAM_MAX_MESSAGES
    module.PRIVATE_MEMORY_MAX_MESSAGES = RAM_MAX_MESSAGES

    _patch_media_cleanup(module)
    _INSTALLED = True
    logging.warning(
        "Emergency resource guard ready: Gemini=%s, search=%s, media<=%sMB, RAM=%smin/%s msgs",
        GEMINI_CONCURRENCY,
        SEARCH_CONCURRENCY,
        MAX_MEDIA_BYTES // (1024 * 1024),
        RAM_TTL_SECONDS // 60,
        RAM_MAX_MESSAGES,
    )
    return True
