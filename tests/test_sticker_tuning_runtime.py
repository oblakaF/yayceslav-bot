import asyncio
from types import SimpleNamespace

import sticker_engine
import sticker_interaction
import sticker_post_runtime
import sticker_runtime
import sticker_tuning_runtime


def test_sticker_tuning_is_more_visible_but_bounded(monkeypatch):
    monkeypatch.setattr(sticker_tuning_runtime, "_APPLIED", False)
    monkeypatch.setattr(sticker_runtime, "STICKER_CHAT_COOLDOWN_SECONDS", 600.0)
    monkeypatch.setattr(sticker_runtime, "STICKER_USER_COOLDOWN_SECONDS", 1200.0)
    monkeypatch.setattr(sticker_runtime, "STICKER_MAX_PER_WINDOW", 2)
    monkeypatch.setattr(sticker_engine, "BACKGROUND_STICKER_CHANCE_CAP", 0.02)
    baseline_events = dict(sticker_engine.EVENT_CHANCE)
    monkeypatch.setattr(sticker_engine, "EVENT_CHANCE", dict(baseline_events))
    monkeypatch.setattr(sticker_interaction, "QUESTION_STICKER_REPLY_CHANCE", 0.05)
    monkeypatch.setattr(sticker_post_runtime, "POST_TEXT_TAG_CHANCE", 0.05)

    sticker_tuning_runtime._apply_tuning()

    assert sticker_runtime.STICKER_CHAT_COOLDOWN_SECONDS == 8 * 60.0
    assert sticker_runtime.STICKER_USER_COOLDOWN_SECONDS == 15 * 60.0
    assert sticker_runtime.STICKER_MAX_PER_WINDOW == 3
    assert sticker_engine.BACKGROUND_STICKER_CHANCE_CAP == 0.08
    assert sticker_interaction.QUESTION_STICKER_REPLY_CHANCE == 0.12
    assert sticker_post_runtime.POST_TEXT_TAG_CHANCE == 0.13
    assert max(sticker_engine.EVENT_CHANCE.values()) <= 0.08
    assert sticker_engine.EVENT_CHANCE["hard_dismissal"] <= 0.06
    assert sticker_engine.EVENT_CHANCE["shut_up_escalated"] <= 0.06

    ordinary_event = next(
        event for event in baseline_events
        if event not in {"hard_dismissal", "shut_up_escalated"}
    )
    assert sticker_engine.EVENT_CHANCE[ordinary_event] == min(
        0.08, baseline_events[ordinary_event] + 0.05
    )
    assert sticker_engine.EVENT_CHANCE["hard_dismissal"] == min(
        0.06, baseline_events["hard_dismissal"] + 0.05
    )


def test_group_own_pack_sticker_not_addressed_to_bot_is_ignored(monkeypatch):
    monkeypatch.setattr(sticker_tuning_runtime, "_APPLIED", False)
    monkeypatch.setattr(sticker_engine, "EVENT_CHANCE", dict(sticker_engine.EVENT_CHANCE))

    calls = []

    async def fake_listener(update, context):
        calls.append("called")

    monkeypatch.setattr(sticker_runtime, "own_pack_sticker_listener", fake_listener)
    monkeypatch.setattr(sticker_runtime, "_is_direct_call", lambda update, context: False)

    sticker_tuning_runtime._apply_tuning()

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(type="group", id=-1001),
        effective_message=SimpleNamespace(sticker=object()),
    )
    context = SimpleNamespace(bot=SimpleNamespace(id=999))

    asyncio.run(sticker_runtime.own_pack_sticker_listener(update, context))
    assert calls == []


def test_group_own_pack_sticker_reply_to_bot_still_triggers(monkeypatch):
    monkeypatch.setattr(sticker_tuning_runtime, "_APPLIED", False)
    monkeypatch.setattr(sticker_engine, "EVENT_CHANCE", dict(sticker_engine.EVENT_CHANCE))

    calls = []

    async def fake_listener(update, context):
        calls.append("called")

    monkeypatch.setattr(sticker_runtime, "own_pack_sticker_listener", fake_listener)
    monkeypatch.setattr(sticker_runtime, "_is_direct_call", lambda update, context: True)

    sticker_tuning_runtime._apply_tuning()

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(type="group", id=-1001),
        effective_message=SimpleNamespace(sticker=object()),
    )
    context = SimpleNamespace(bot=SimpleNamespace(id=999))

    asyncio.run(sticker_runtime.own_pack_sticker_listener(update, context))
    assert calls == ["called"]
