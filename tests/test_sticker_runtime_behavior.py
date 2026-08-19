import asyncio
from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop, filters

import sticker_engine
import sticker_interaction
import sticker_runtime
import sticker_semantics_aug19


sticker_semantics_aug19.install_catalog_semantics()


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


def test_aug19_pack_catalog_maps_all_48_registry_positions(monkeypatch):
    stickers = [
        SimpleNamespace(file_id=f"file-{i}", file_unique_id=f"unique-{i}")
        for i in range(48)
    ]

    class FakeBot:
        async def get_sticker_set(self, name):
            assert name == sticker_engine.STICKER_SET_NAME
            return SimpleNamespace(name=name, stickers=stickers)

    monkeypatch.setattr(sticker_runtime, "_STICKER_IDS", {})
    monkeypatch.setattr(sticker_runtime, "_STICKER_UNIQUE_IDS", {})
    monkeypatch.setattr(sticker_runtime, "_save_sticker_ids", lambda mapping: None)

    mapping = asyncio.run(sticker_runtime.ensure_sticker_catalog(FakeBot(), force=True))
    assert len(mapping) == 48
    assert mapping["ty_po_moemu_pereputal"] == "file-0"
    assert mapping["idi_nahui"] == "file-8"
    assert mapping["krinzh"] == "file-36"
    assert mapping["milfa"] == "file-37"
    assert mapping["delo_pahnet_ostrovom"] == "file-47"
    assert sticker_runtime._STICKER_UNIQUE_IDS["unique-0"] == "ty_po_moemu_pereputal"
    assert sticker_runtime._STICKER_UNIQUE_IDS["unique-47"] == "delo_pahnet_ostrovom"


def test_own_sticker_fifty_percent_visual_branch_uses_semantic_counter(monkeypatch):
    calls = []

    async def fake_own_key(bot, sticker):
        return "minus_aura"

    async def fake_reply(update, context, sticker_key):
        calls.append(sticker_key)
        return True

    async def must_not_text(_text):
        raise AssertionError("visual 50% branch must not also send text")

    monkeypatch.setattr(sticker_runtime, "own_sticker_key", fake_own_key)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_reply)
    monkeypatch.setattr(sticker_runtime.random, "random", lambda: 0.0)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(sticker=object(), reply_text=must_not_text),
        effective_user=SimpleNamespace(id=123, is_bot=False),
        effective_chat=SimpleNamespace(id=-1001),
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(sticker_runtime.own_pack_sticker_listener(update, context))
    assert calls == ["plus_aura"]


def test_own_sticker_other_half_uses_text_reply(monkeypatch):
    texts = []

    async def fake_own_key(bot, sticker):
        return "po_delu_govori"

    async def fake_text(text):
        texts.append(text)
        return True

    async def must_not_sticker(*args, **kwargs):
        raise AssertionError("text 50% branch must not force a sticker")

    monkeypatch.setattr(sticker_runtime, "own_sticker_key", fake_own_key)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", must_not_sticker)
    monkeypatch.setattr(sticker_runtime.random, "random", lambda: 0.75)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(sticker=object(), reply_text=fake_text),
        effective_user=SimpleNamespace(id=123, is_bot=False),
        effective_chat=SimpleNamespace(id=-1001),
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(sticker_runtime.own_pack_sticker_listener(update, context))
    assert len(texts) == 1
    assert texts[0]


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


def test_generic_question_never_calls_sticker_sender_even_with_zero_rng(monkeypatch):
    async def must_not_send(*args, **kwargs):
        raise AssertionError("generic direct question must stay a text answer")

    monkeypatch.setattr(sticker_runtime, "_is_direct_call", lambda update, context: True)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", must_not_send)
    monkeypatch.setattr(sticker_runtime.random, "random", lambda: 0.0)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="Яйцеслав, как тебе погода сегодня?"),
        effective_user=SimpleNamespace(id=123, is_bot=False),
        effective_chat=SimpleNamespace(id=-1001),
        edited_message=None,
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    asyncio.run(sticker_runtime.direct_question_sticker_listener(update, context))


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


def test_hard_hostile_background_events_are_below_one_percent():
    assert sticker_engine.event_chance("hard_dismissal") < 0.01
    assert sticker_engine.event_chance("shut_up_escalated") < 0.01


def test_question_probability_constant_is_five_percent_maximum():
    assert sticker_interaction.QUESTION_STICKER_REPLY_CHANCE == 0.05
