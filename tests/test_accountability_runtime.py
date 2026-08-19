import sys
from types import SimpleNamespace

import aggression_engine
import accountability_runtime


def test_correction_signals_are_narrow_and_personal_to_bot():
    for text in (
        "Яйцеслав, ты не прав",
        "ты ошибся в прошлом ответе",
        "твой ответ неверный",
        "проверь свой ответ",
    ):
        assert accountability_runtime.is_correction_signal(text)

    assert not accountability_runtime.is_correction_signal("ошибка в моём коде")
    assert not accountability_runtime.is_correction_signal("этот человек неправ")


def test_correction_cannot_trigger_proactive_aggression(monkeypatch):
    monkeypatch.setattr(
        aggression_engine,
        "_DOKOP_BLOCKED_INTENTS",
        set(aggression_engine._DOKOP_BLOCKED_INTENTS),
    )
    monkeypatch.setattr(accountability_runtime, "_INSTALLED", False)

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
    monkeypatch.setattr(
        aggression_engine,
        "_DOKOP_BLOCKED_INTENTS",
        set(aggression_engine._DOKOP_BLOCKED_INTENTS),
    )
    monkeypatch.setattr(accountability_runtime, "_INSTALLED", False)

    fake_bot = SimpleNamespace(
        build_full_system_instruction=lambda style_text="", *args, **kwargs: "BASE"
    )
    monkeypatch.setitem(sys.modules, "bot", fake_bot)

    assert accountability_runtime.install() is True

    corrected = fake_bot.build_full_system_instruction("ты ошибся в прошлом ответе")
    assert "Моя ошибка." in corrected
    assert "Не пиши длинное покаянное сообщение" in corrected
    assert "НЕ извиняйся автоматически" in corrected

    ordinary = fake_bot.build_full_system_instruction("как сварить рис?")
    assert ordinary == "BASE"
