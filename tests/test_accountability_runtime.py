import asyncio
import sys
from types import SimpleNamespace

import aggression_engine
import accountability_runtime


def _reset_runtime(monkeypatch):
    monkeypatch.setattr(
        aggression_engine,
        "_DOKOP_BLOCKED_INTENTS",
        set(aggression_engine._DOKOP_BLOCKED_INTENTS),
    )
    monkeypatch.setattr(accountability_runtime, "_INSTALLED", False)
    accountability_runtime._RECENT_SEND_KEYS.clear()
    accountability_runtime._INFLIGHT_SEND_KEYS.clear()


def test_correction_signals_are_narrow_and_personal_to_bot():
    for text in (
        "Яйцеслав, ты не прав",
        "ты ошибся в прошлом ответе",
        "твой ответ неверный",
        "проверь свой ответ",
        "ты не проверяешь факты",
        "ты факты не проверял",
        "смотри картинку и извинись",
        "посмотри скрин и извинись",
        "извинись, ты ошибся",
    ):
        assert accountability_runtime.is_correction_signal(text)

    assert not accountability_runtime.is_correction_signal("ошибка в моём коде")
    assert not accountability_runtime.is_correction_signal("этот человек неправ")
    assert not accountability_runtime.is_correction_signal("извинись перед Серегой")


def test_correction_cannot_trigger_proactive_aggression(monkeypatch):
    _reset_runtime(monkeypatch)

    fake_bot = SimpleNamespace(
        build_full_system_instruction=lambda style_text="", *args, **kwargs: "BASE"
    )
    monkeypatch.setitem(sys.modules, "bot", fake_bot)

    assert accountability_runtime.install() is True
    assert aggression_engine._base_probability(
        aggression_engine.AggressionContext(
            user_text="Яйцеслав, ты не прав",
            intent="correction",
            chat_type="group",
            roughness="high",
            relationship_level=4,
        )
    ) == 0.0


def test_real_mistake_instruction_requires_short_apology_but_not_blind_agreement(monkeypatch):
    _reset_runtime(monkeypatch)
    monkeypatch.setattr(accountability_runtime.random, "random", lambda: 1.0)

    fake_bot = SimpleNamespace(
        build_full_system_instruction=lambda style_text="", *args, **kwargs: "BASE"
    )
    monkeypatch.setitem(sys.modules, "bot", fake_bot)

    assert accountability_runtime.install() is True

    corrected = fake_bot.build_full_system_instruction("ты не проверяешь факты")
    assert "Моя ошибка." in corrected
    assert "Не пиши длинное покаянное сообщение" in corrected
    assert "НЕ извиняйся автоматически" in corrected
    assert "не защищай" in corrected.lower() or "Не защищай" in corrected
    assert "новостную выдачу" in corrected

    ordinary = fake_bot.build_full_system_instruction("как сварить рис?")
    assert ordinary == "BASE"


def test_don_parody_is_exactly_a_rare_correction_mode(monkeypatch):
    assert accountability_runtime.DON_PARODY_CHANCE == 0.05

    class AlwaysZero:
        @staticmethod
        def random():
            return 0.0

    class AlwaysOne:
        @staticmethod
        def random():
            return 1.0

    assert accountability_runtime.should_use_don_parody("ты не прав", rng=AlwaysZero)
    assert not accountability_runtime.should_use_don_parody("ты не прав", rng=AlwaysOne)
    assert not accountability_runtime.should_use_don_parody("как дела?", rng=AlwaysZero)


def test_don_instruction_never_reverses_a_real_bot_mistake(monkeypatch):
    _reset_runtime(monkeypatch)
    monkeypatch.setattr(accountability_runtime.random, "random", lambda: 0.0)

    fake_bot = SimpleNamespace(
        build_full_system_instruction=lambda style_text="", *args, **kwargs: "BASE"
    )
    monkeypatch.setitem(sys.modules, "bot", fake_bot)

    assert accountability_runtime.install() is True
    text = fake_bot.build_full_system_instruction("смотри картинку и извинись")
    assert "РЕДКИЙ МЕМНЫЙ РЕЖИМ «ДОН»" in text
    assert "Если ошибся ЯЙЦЕСЛАВ, не требуй извинений" in text
    assert "НЕ изображение конкретного реального человека" in text


def test_send_answer_is_deduplicated_per_incoming_update(monkeypatch):
    _reset_runtime(monkeypatch)
    calls = []

    async def original_send(update, context, answer, **kwargs):
        calls.append(answer)
        return answer

    fake_bot = SimpleNamespace(
        build_full_system_instruction=lambda style_text="", *args, **kwargs: "BASE",
        send_answer=original_send,
    )
    monkeypatch.setitem(sys.modules, "bot", fake_bot)

    assert accountability_runtime.install() is True
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001),
        effective_message=SimpleNamespace(message_id=77),
    )

    async def scenario():
        first = await fake_bot.send_answer(update, object(), "первый")
        second = await fake_bot.send_answer(update, object(), "дубль")
        return first, second

    first, second = asyncio.run(scenario())
    assert first == "первый"
    assert second is None
    assert calls == ["первый"]
