import aggression_engine
import bot
import humor_engine
import style_engine


def test_member_profile_reaches_social_instruction():
    style_engine.reset_length_history()
    instruction = bot.build_full_system_instruction(
        "что думаешь?", chat_id=701, chat_type="group", user_id=77,
        member_profile={"relationship_level": 3, "current_title": None, "joke_archetype": None, "total_messages": 120},
    )
    assert "хорошо знакомый участник" in instruction


def test_relationship_level_is_passed_to_humor_context(monkeypatch):
    captured = {}

    def fake_decide(ctx, chat_id, **kwargs):
        del chat_id, kwargs
        captured["relationship_level"] = ctx.relationship_level
        return humor_engine.HumorDecision(humor_allowed=False)

    monkeypatch.setattr(bot.humor_engine, "decide_humor", fake_decide)
    monkeypatch.setattr(bot.aggression_engine, "decide_aggression", lambda ctx: aggression_engine.AggressionDecision())
    bot.build_full_system_instruction(
        "обычная реплика", chat_id=702, chat_type="group", user_id=78,
        member_profile={"relationship_level": 4},
    )
    assert captured["relationship_level"] == 4


def test_aggression_instruction_is_appended_without_second_pack(monkeypatch):
    monkeypatch.setattr(
        bot.aggression_engine, "decide_aggression",
        lambda ctx: aggression_engine.AggressionDecision(active=True, mode="nitpick", reason="test"),
    )
    instruction = bot.build_full_system_instruction(
        "это точно факт", chat_id=703, chat_type="group", user_id=79,
        member_profile={"relationship_level": 2},
    )
    assert "V2 aggression/dokop" in instruction
    assert instruction.count("Речевой пакет этого ответа:") == 1
    assert "ТОЛЬКО из уже выбранного voice pack" in instruction


def test_serious_profile_does_not_add_social_or_aggression_jokes(monkeypatch):
    monkeypatch.setattr(bot.aggression_engine, "decide_aggression", lambda ctx: aggression_engine.AggressionDecision())
    instruction = bot.build_full_system_instruction(
        "у меня умер родственник", chat_id=704, chat_type="group", user_id=80,
        member_profile={"relationship_level": 4, "current_title": "Лорд простыней", "joke_archetype": "душнила"},
    )
    assert "Лорд простыней" not in instruction
    assert "душнила" not in instruction
    assert "V2 aggression/dokop" not in instruction
    assert "Речевой пакет этого ответа: classic" in instruction


def test_dormant_irony_type_has_behavior_hint_without_pack_switch():
    decision = humor_engine.HumorDecision(humor_allowed=True, humor_type="irony")
    instruction = bot._build_humor_instruction(decision, lexical_examples=False)
    assert "сухая ирония" in instruction
    assert "Не меняй и не дополняй" in instruction
