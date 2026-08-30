import asyncio
import time
from types import SimpleNamespace

from telegram.constants import ChatType

import fight_sticker_budget
import sticker_post_runtime as post
import sticker_runtime


def setup_function():
    fight_sticker_budget.reset()
    sticker_runtime._CHAT_LAST_STICKER.clear()
    sticker_runtime._USER_LAST_STICKER.clear()
    sticker_runtime._CHAT_STICKER_TIMES.clear()


def _update(user_id=7):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, is_bot=False),
    )


def test_rage_sticker_respects_quiet_hours(monkeypatch):
    calls = []

    async def fake_send(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(post, "_is_rage_exchange", lambda *args: True)
    monkeypatch.setattr(sticker_runtime, "_quiet_hours_msk", lambda: True)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_send)

    sent = asyncio.run(
        post.maybe_send_post_text_tag(
            _update(),
            SimpleNamespace(),
            "ты пиздабол",
            "сам себя поймал на повторе",
        )
    )

    assert sent is False
    assert calls == []
    assert fight_sticker_budget.count(-100, 7, 1000.0) == 0


def test_rage_sticker_records_fight_and_shared_ledgers(monkeypatch):
    calls = []

    async def fake_send(update, context, sticker_key):
        calls.append(sticker_key)
        return True

    monkeypatch.setattr(post, "_is_rage_exchange", lambda *args: True)
    monkeypatch.setattr(sticker_runtime, "_quiet_hours_msk", lambda: False)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_send)
    monkeypatch.setattr(post.random, "random", lambda: 0.0)
    monkeypatch.setattr(post.random, "choice", lambda values: values[0])
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    sent = asyncio.run(
        post.maybe_send_post_text_tag(
            _update(),
            SimpleNamespace(),
            "ты пиздабол",
            "сам себя поймал на повторе",
        )
    )

    assert sent is True
    assert len(calls) == 1
    assert fight_sticker_budget.count(-100, 7, 1000.0) == 1
    assert fight_sticker_budget.chat_count(-100, 1000.0) == 1
    assert sticker_runtime._CHAT_LAST_STICKER[-100] == 1000.0
    assert sticker_runtime._USER_LAST_STICKER[(-100, 7)] == 1000.0
    assert list(sticker_runtime._CHAT_STICKER_TIMES[-100]) == [1000.0]


def test_long_rage_allows_two_visual_beats_then_stops(monkeypatch):
    calls = []
    now = {"value": 1000.0}

    async def fake_send(update, context, sticker_key):
        calls.append((update.effective_user.id, sticker_key))
        return True

    monkeypatch.setattr(post, "_is_rage_exchange", lambda *args: True)
    monkeypatch.setattr(sticker_runtime, "_quiet_hours_msk", lambda: False)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_send)
    monkeypatch.setattr(post.random, "random", lambda: 0.0)
    monkeypatch.setattr(post.random, "choice", lambda values: values[0])
    monkeypatch.setattr(time, "monotonic", lambda: now["value"])

    first = asyncio.run(
        post.maybe_send_post_text_tag(
            _update(7), SimpleNamespace(), "ты пиздабол", "сам себя поймал на повторе"
        )
    )
    now["value"] += fight_sticker_budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0
    second = asyncio.run(
        post.maybe_send_post_text_tag(
            _update(7), SimpleNamespace(), "ты опять пиздабол", "второй круг того же повтора"
        )
    )
    now["value"] += fight_sticker_budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0
    third = asyncio.run(
        post.maybe_send_post_text_tag(
            _update(8), SimpleNamespace(), "ты клоун", "ещё один участник влез в срач"
        )
    )

    assert first is True
    assert second is True
    assert third is False
    assert len(calls) == 2
    assert fight_sticker_budget.chat_count(-100, now["value"]) == 2
    assert len(sticker_runtime._CHAT_STICKER_TIMES[-100]) == 2
