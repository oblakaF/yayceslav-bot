import asyncio
import random
import sys
from types import SimpleNamespace

import aggression_engine
import intent
import praise_guard_runtime


def test_short_praise_phrases_are_recognized_but_followup_request_is_not():
    for text in (
        "Спасибо яйцеслав мы тебя любим, но не знаем за что",
        "Яйцеслав, спасибо, ты лучший",
        "молодец",
        "красава",
        "уважуха",
        "респект",
        "спс",
    ):
        assert praise_guard_runtime.is_pure_praise(text)

    assert not praise_guard_runtime.is_pure_praise(
        "Спасибо, а можешь теперь найти статью?"
    )


def test_praise_reply_pool_is_deliberately_tiny():
    for seed in range(20):
        reply = praise_guard_runtime.choose_short_praise_reply(random.Random(seed))
        assert reply in praise_guard_runtime.SHORT_PRAISE_REPLIES
        assert len(reply.split()) <= 3
        assert len(reply) <= 20


def _fake_bot(calls):
    async def ask_gemini(contents, *args, **kwargs):
        calls.append(str(contents))
        return "LONG GEMINI ANSWER"

    return SimpleNamespace(
        build_v2_base_instruction=lambda user_text="", *args, **kwargs: "BASE",
        ask_gemini=ask_gemini,
    )


def _reset_guard(monkeypatch):
    monkeypatch.setattr(praise_guard_runtime, "_INSTALLED", False)
    monkeypatch.setattr(praise_guard_runtime, "_ORIGINAL_CLASSIFY", None)
    monkeypatch.setattr(praise_guard_runtime, "_ORIGINAL_ASK_GEMINI", None)
    monkeypatch.setattr(
        aggression_engine,
        "_DOKOP_BLOCKED_INTENTS",
        set(aggression_engine._DOKOP_BLOCKED_INTENTS),
    )


def test_praise_install_classifies_warmly_blocks_aggression_and_skips_gemini(monkeypatch):
    calls = []
    _reset_guard(monkeypatch)
    fake_bot = _fake_bot(calls)
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

    reply = asyncio.run(fake_bot.ask_gemini("молодец, красава"))
    assert reply in praise_guard_runtime.SHORT_PRAISE_REPLIES
    assert len(reply.split()) <= 3
    assert calls == []


def test_followup_request_keeps_normal_gemini_path(monkeypatch):
    calls = []
    _reset_guard(monkeypatch)
    fake_bot = _fake_bot(calls)
    monkeypatch.setitem(sys.modules, "bot", fake_bot)

    assert praise_guard_runtime.install() is True
    result = asyncio.run(
        fake_bot.ask_gemini("Спасибо, а можешь теперь найти статью?")
    )

    assert result == "LONG GEMINI ANSWER"
    assert calls == ["Спасибо, а можешь теперь найти статью?"]

    resolved, _confidence = intent.classify_intent(
        "Спасибо, а можешь теперь найти статью?"
    )
    assert resolved != "praise"
