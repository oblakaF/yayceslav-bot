from __future__ import annotations

import asyncio
from types import SimpleNamespace

import emergency_resource_guard_runtime as guard


def test_install_applies_low_cost_limits(monkeypatch):
    async def ask_gemini(contents, *args, **kwargs):
        return "ok"

    module = SimpleNamespace(
        ask_gemini=ask_gemini,
        GEMINI_SEMAPHORE=asyncio.Semaphore(3),
        SEARCH_SEMAPHORE=asyncio.Semaphore(2),
        MAX_FILE_SIZE=20 * 1024 * 1024,
        GROUP_MEMORY_SECONDS=7200,
        PRIVATE_MEMORY_SECONDS=7200,
        GROUP_MEMORY_MAX_MESSAGES=60,
        PRIVATE_MEMORY_MAX_MESSAGES=60,
    )
    monkeypatch.setattr(guard, "_INSTALLED", False)

    assert guard.install(module) is True
    assert module.MAX_FILE_SIZE == 6 * 1024 * 1024
    assert module.GROUP_MEMORY_SECONDS == 30 * 60
    assert module.PRIVATE_MEMORY_SECONDS == 30 * 60
    assert module.GROUP_MEMORY_MAX_MESSAGES == 30
    assert module.PRIVATE_MEMORY_MAX_MESSAGES == 30
    assert module.GEMINI_SEMAPHORE._value == 1
    assert module.SEARCH_SEMAPHORE._value == 1
    assert getattr(module.ask_gemini, "_yayceslav_emergency_resource_guard", False)


def test_multimodal_detection_is_conservative():
    assert guard._looks_multimodal("hello") is False
    assert guard._looks_multimodal(["hello", "world"]) is False
    assert guard._looks_multimodal([object(), "prompt"]) is True
