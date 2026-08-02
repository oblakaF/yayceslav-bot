import bot
import humor_engine


def test_serious_topic_gets_no_humor_instruction():
    instruction = bot.build_full_system_instruction(
        "у меня умер родственник, что делать",
        chat_id=5001,
    )
    assert "Дополнительная подсказка юмора" not in instruction


def test_hostile_message_gets_banter_instruction(monkeypatch):
    monkeypatch.setattr(humor_engine.random, "random", lambda: 0.99)
    instruction = bot.build_full_system_instruction(
        "ты мудак",
        chat_id=5002,
        chat_type="group",
    )
    assert "banter_hostile" in instruction
    assert "Стратегия ответа" in instruction


def test_third_party_insult_does_not_get_banter_instruction():
    instruction = bot.build_full_system_instruction(
        "мой начальник мудак, как мне уволиться?",
        chat_id=5003,
    )
    assert "banter_hostile" not in instruction


def test_empty_text_produces_base_instruction_without_crashing():
    instruction = bot.build_full_system_instruction("", chat_id=5004)
    assert "Яйцеслав" in instruction
    assert "Дополнительная подсказка юмора" not in instruction


def test_voice_style_still_appended_when_requested():
    instruction = bot.build_full_system_instruction(
        "расскажи анекдот",
        chat_id=5005,
        voice_style=True,
    )
    assert "будет озвучен голосом" in instruction


def test_build_humor_instruction_empty_when_not_allowed():
    decision = humor_engine.HumorDecision(humor_allowed=False)
    assert bot._build_humor_instruction(decision) == ""


def test_build_humor_instruction_mentions_selected_phrase():
    decision = humor_engine.HumorDecision(
        humor_allowed=True,
        humor_type="light_taunt",
        selected_phrase="Тестовая фраза",
    )
    instruction = bot._build_humor_instruction(decision)
    assert "Тестовая фраза" in instruction
    assert "light_taunt" in instruction
