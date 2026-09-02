import asyncio
from types import SimpleNamespace

from telegram.constants import ChatType

import group_sticker_behavior_v2 as group_v2
import sticker_runtime


def setup_function():
    group_v2.reset_recent()
    sticker_runtime._CHAT_LAST_STICKER.clear()
    sticker_runtime._USER_LAST_STICKER.clear()
    sticker_runtime._CHAT_STICKER_TIMES.clear()


def _update(user_id=7):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, is_bot=False),
    )


def test_recent_memory_is_bounded():
    for index in range(8):
        group_v2.record_recent(-100, f"key-{index}")
    assert group_v2.recent_stickers(-100) == tuple(f"key-{index}" for index in range(3, 8))


def test_fatigue_post_does_not_repeat_tyazhelo_when_alternative_exists():
    group_v2.record_recent(-100, "tyazhelo_tyazhelo")
    key = group_v2.normal_post_key(
        "я устал, тяжело сегодня",
        "Да, день длинный. Держимся.",
        chat_id=-100,
        direct=True,
    )
    assert key is not None
    assert key != "tyazhelo_tyazhelo"
    assert key in {"mda", "vse_tlen"}


def test_short_direct_group_turn_can_use_non_fatigue_stickers():
    key = group_v2.normal_post_key(
        "ну?",
        "Ну, говори.",
        chat_id=-100,
        direct=True,
    )
    assert key in {"che_nado", "nu_i_che"}


def test_normal_policy_does_not_auto_send_hard_dismissal():
    key = group_v2.normal_post_key(
        "иди нахуй",
        "Сам иди.",
        chat_id=-100,
        direct=True,
    )
    assert key is None


def test_rage_default_pool_includes_funny_aug19_choices_when_catalog_knows_them(monkeypatch):
    semantics = dict(group_v2.sticker_engine.STICKER_SEMANTICS)
    for key in ("nu_i_suka_zhe_ty", "kto_opyat_ne_spravilsya", "fa_watafa"):
        semantics[key] = object()
    monkeypatch.setattr(group_v2.sticker_engine, "STICKER_SEMANTICS", semantics)

    pool = group_v2.rage_pool("ты опять пиздабол")
    assert "nu_i_suka_zhe_ty" in pool
    assert "kto_opyat_ne_spravilsya" in pool
    assert "fa_watafa" in pool
    assert "skill_issue" in pool
    assert "krinzh" in pool


def test_normal_direct_group_reply_sends_semantic_post_tag(monkeypatch):
    calls = []

    async def fake_send(update, context, sticker_key):
        calls.append(sticker_key)
        return True

    monkeypatch.setattr(group_v2, "_is_rage", lambda *args: False)
    monkeypatch.setattr(sticker_runtime, "_quiet_hours_msk", lambda: False)
    monkeypatch.setattr(sticker_runtime, "_is_direct_call", lambda *args: True)
    monkeypatch.setattr(sticker_runtime, "sticker_slot_allowed", lambda *args: True)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_send)
    monkeypatch.setattr(group_v2.random, "random", lambda: 0.0)

    sent = asyncio.run(
        group_v2.maybe_send_group_post_text_tag(
            _update(),
            SimpleNamespace(),
            "я устал, тяжело сегодня",
            "Да, день длинный. Держимся.",
        )
    )

    assert sent is True
    assert len(calls) == 1
    assert calls[0] in {"tyazhelo_tyazhelo", "mda", "vse_tlen"}


def test_first_rage_visual_is_guaranteed_and_uses_expanded_policy(monkeypatch):
    calls = []

    async def fake_send(update, context, sticker_key):
        calls.append(sticker_key)
        return True

    monkeypatch.setattr(group_v2, "_is_rage", lambda *args: True)
    monkeypatch.setattr(sticker_runtime, "_quiet_hours_msk", lambda: False)
    monkeypatch.setattr(sticker_runtime, "reply_sticker_by_key", fake_send)

    context = SimpleNamespace(chat_data={})
    sent = asyncio.run(
        group_v2.maybe_send_group_post_text_tag(
            _update(),
            context,
            "ты опять пиздабол",
            "Сильный заход, третий раз одна пластинка.",
        )
    )

    assert sent is True
    assert len(calls) == 1
    assert calls[0] in group_v2.rage_pool("ты опять пиздабол")
    state = context.chat_data["fight_v2_rage_stickers"][7]
    assert state["sent"] == 1
    assert state["used_keys"] == [calls[0]]
