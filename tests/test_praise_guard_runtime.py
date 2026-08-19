import sys
from types import SimpleNamespace

import aggression_engine
import intent
import praise_guard_runtime


def test_thanks_and_love_are_pure_praise_but_followup_request_is_not():
    assert praise_guard_runtime.is_pure_praise(
        "Спасибо яйцеслав мы тебя любим, но не знаем за что"
    )
    assert praise_guard_runtime.is_pure_praise("Яйцеслав, спасибо, ты лучший")
    assert not praise_guard_runtime.is_pure_praise(
        "Спасибо, а можешь теперь найти статью?"
    )


def test_praise_install_classifies_warmly_and_blocks_aggression(monkeypatch):
    original_classify = intent.classify_intent
    monkeypatch.setattr(intent, "classify_intent", original_classify)
    monkeypatch.setattr(
        aggression_engine,
        "_DOKOP_BLOCKED_INTENTS",
        set(aggression_engine._DOKOP_BLOCKED_INTENTS),
    )
    monkeypatch.setattr(praise_guard_runtime, "_INSTALLED", False)
    monkeypatch.setattr(praise_guard_runtime, "_ORIGINAL_CLASSIFY", None)

    fake_bot = SimpleNamespace(
        build_v2_base_instruction=lambda user_text="", *args, **kwargs: "BASE"
    )
    monkeypatch.setitem(sys.modules, "bot", fake_bot)

    assert praise_guard_runtime.install() is True
    assert intent.classify_intent(
        "Спасибо яйцеслав мы тебя любим, но не знаем за что"
    ) == ("praise", intent.HIGH)

    assert aggression_engine._base_probability(
        aggression_engine.AggressionContext(
            user_text="спасибо, красавчик",
            intent="praise",
            chat_type="group",
            roughness="high",
            relationship_level=4,
        )
    ) == 0.0

    instruction = fake_bot.build_v2_base_instruction(
        "Спасибо яйцеслав мы тебя любим, но не знаем за что"
    )
    assert "Не агрись" in instruction
    assert "не отвечай «чё?»" in instruction


def test_followup_request_keeps_normal_intent_path(monkeypatch):
    original_classify = intent.classify_intent
    monkeypatch.setattr(intent, "classify_intent", original_classify)
    monkeypatch.setattr(praise_guard_runtime, "_INSTALLED", False)
    monkeypatch.setattr(praise_guard_runtime, "_ORIGINAL_CLASSIFY", None)

    fake_bot = SimpleNamespace(
        build_v2_base_instruction=lambda user_text="", *args, **kwargs: "BASE"
    )
    monkeypatch.setitem(sys.modules, "bot", fake_bot)
    praise_guard_runtime.install()

    resolved, _confidence = intent.classify_intent(
        "Спасибо, а можешь теперь найти статью?"
    )
    assert resolved != "praise"
