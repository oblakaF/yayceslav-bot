import asyncio
from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop, filters

import sticker_engine
import sticker_interaction
import sticker_runtime


class FakeBotNoCatalog:
    async def get_sticker_set(self, name):
        raise AssertionError(f"foreign sticker must not query catalog: {name}")


def test_pinned_ptb_has_any_sticker_filter():
    assert filters.Sticker.ALL is not None


def test_foreign_sticker_is_rejected_without_catalog_api_call():
    sticker = SimpleNamespace(
        set_name="some_other_pack",
        file_unique_id="foreign-unique-id",
    )
    result = asyncio.run(
        sticker_runtime.own_sticker_key(FakeBotNoCatalog(), sticker)
    )
    assert result is None


def test_question_sticker_slot_is_exactly_five_percent_at_boundary(monkeypatch):
    calls = []

    async def fake_reply(update, context, sticker_key):
        calls.append(sticker_key)
        return True

    monkeypatch.setattr(sticker_runtime, "_is_direct_call", lambda update, context: True)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_reply)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="Яйцеслав, где пруфы?"),
        effective_user=SimpleNamespace(id=123, is_bot=False),
        effective_chat=SimpleNamespace(id=-1001),
        edited_message=None,
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    monkeypatch.setattr(sticker_runtime.random, "random", lambda: 0.049999)
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(sticker_runtime.direct_question_sticker_listener(update, context))
    assert calls == ["gde_prufy"]

    calls.clear()
    monkeypatch.setattr(sticker_runtime.random, "random", lambda: 0.05)
    asyncio.run(sticker_runtime.direct_question_sticker_listener(update, context))
    assert calls == []


def test_serious_question_never_uses_sticker_even_when_rng_is_zero(monkeypatch):
    calls = []

    async def fake_reply(update, context, sticker_key):
        calls.append(sticker_key)
        return True

    monkeypatch.setattr(sticker_runtime, "_is_direct_call", lambda update, context: True)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_reply)
    monkeypatch.setattr(sticker_runtime.random, "random", lambda: 0.0)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="Яйцеслав, что делать при инфаркте?"),
        effective_user=SimpleNamespace(id=123, is_bot=False),
        effective_chat=SimpleNamespace(id=-1001),
        edited_message=None,
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    asyncio.run(sticker_runtime.direct_question_sticker_listener(update, context))
    assert calls == []


def test_all_background_events_are_at_most_two_percent():
    assert sticker_engine.BACKGROUND_STICKER_CHANCE_CAP == 0.02
    assert max(
        sticker_engine.event_chance(event)
        for event in sticker_engine.EVENT_STICKERS
    ) <= 0.02


def test_question_probability_constant_is_five_percent():
    assert sticker_interaction.QUESTION_STICKER_REPLY_CHANCE == 0.05
