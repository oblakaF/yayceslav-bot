import asyncio
from types import SimpleNamespace

import bot


def test_keep_chat_action_alive_refreshes_periodically():
    calls = []

    async def fake_send_chat_action(*, chat_id, action):
        calls.append((chat_id, action))

    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=fake_send_chat_action))

    async def run():
        task = asyncio.create_task(
            bot._keep_chat_action_alive(-100, context, interval_seconds=0.01)
        )
        await asyncio.sleep(0.045)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    assert len(calls) >= 2
    assert all(chat_id == -100 for chat_id, _ in calls)


def test_keep_chat_action_alive_swallows_send_errors_and_keeps_going():
    calls = []

    async def flaky_send_chat_action(*, chat_id, action):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("network blip")

    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=flaky_send_chat_action))

    async def run():
        task = asyncio.create_task(
            bot._keep_chat_action_alive(-100, context, interval_seconds=0.01)
        )
        await asyncio.sleep(0.045)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    # One send failed but the loop kept running afterward instead of dying.
    assert len(calls) >= 2
