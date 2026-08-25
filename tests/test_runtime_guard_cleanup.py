import asyncio
from datetime import datetime
from types import SimpleNamespace

import date_grounding_runtime
import search_context_runtime


def test_date_grounding_wraps_instruction_without_thread():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE",
        current_msk_datetime=lambda: datetime(2026, 8, 25, 10, 30),
    )
    assert date_grounding_runtime.install(module) is True
    result = module.build_full_system_instruction("x")
    assert result.startswith("BASE")
    assert "25.08.2026 10:30 МСК" in result
    assert "Сейчас 2026 год" in result
    first = module.build_full_system_instruction
    assert date_grounding_runtime.install(module) is True
    assert module.build_full_system_instruction is first


def test_search_context_recovers_private_previous_topic():
    calls = []

    async def original(**kwargs):
        calls.append(kwargs)

    module = SimpleNamespace(perform_web_search=original)
    assert search_context_runtime.install(module) is True

    update = SimpleNamespace(effective_chat=SimpleNamespace(type="private", id=10))
    context = SimpleNamespace(user_data={"last_user_query": "кто президент Франции"})
    asyncio.run(module.perform_web_search(update, context, ""))

    assert calls[0]["query"] == "кто президент Франции"


def test_search_context_answers_current_year_from_process_clock():
    replies = []
    stats = []

    async def original(**kwargs):
        raise AssertionError("web search should not run for current year")

    async def ok_limit(update, bucket):
        return True

    async def no_op(*args, **kwargs):
        return None

    async def increment(name):
        stats.append(name)

    async def reply_text(text):
        replies.append(text)

    module = SimpleNamespace(
        perform_web_search=original,
        enforce_rate_limit=ok_limit,
        current_msk_datetime=lambda: datetime(2026, 8, 25, 10, 30),
        register_user_and_chat=no_op,
        increment_stat=increment,
    )
    assert search_context_runtime.install(module) is True

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(type="private", id=10),
        effective_message=SimpleNamespace(reply_text=reply_text),
    )
    context = SimpleNamespace(user_data={})
    asyncio.run(module.perform_web_search(update, context, "какой сейчас год"))

    assert replies == ["Сейчас 2026 год. Системная дата: 25.08.2026 (МСК)."]
    assert "search_requests" in stats
