import aggression_engine
import bot
import passive_engine
import state_engine
import style_engine


def setup_function():
    state_engine.reset_state()
    style_engine.reset_length_history()
    passive_engine.reset_state()


def test_build_instruction_contains_one_state_and_one_voice_pack(monkeypatch):
    monkeypatch.setattr(
        bot.aggression_engine, "decide_aggression",
        lambda ctx: aggression_engine.AggressionDecision(),
    )
    instruction = bot.build_full_system_instruction(
        "обычная реплика", chat_id=9201, chat_type="group", user_id=1
    )
    assert instruction.count("V2 character state:") == 1
    assert instruction.count("Речевой пакет этого ответа:") == 1
    assert "не разрешение смешивать voice packs" in instruction


def test_fatigue_marks_following_state_annoyed(monkeypatch):
    monkeypatch.setattr(bot.style_engine, "choose_voice_pack", lambda ctx: "blat")
    monkeypatch.setattr(
        bot.passive_engine, "note_bot_call_and_maybe_fatigue",
        lambda *args, **kwargs: passive_engine.FatigueDecision(
            active=True, pack_name="blat", text="Опять весь этот кипиш мне разгребать.",
            call_count=8, reason="fatigue"
        ),
    )
    monkeypatch.setattr(
        bot.aggression_engine, "decide_aggression",
        lambda ctx: aggression_engine.AggressionDecision(),
    )
    bot.build_full_system_instruction(
        "эй", chat_id=9202, chat_type="group", user_id=2, bot_was_mentioned=True
    )
    assert state_engine.resolve_state(
        9202, conversation_mode="normal", record=False
    ) == "annoyed"


def test_dokop_marks_following_state_argumentative(monkeypatch):
    monkeypatch.setattr(
        bot.aggression_engine, "decide_aggression",
        lambda ctx: aggression_engine.AggressionDecision(
            active=True, mode="nitpick", reason="test"
        ),
    )
    bot.build_full_system_instruction(
        "это точно факт", chat_id=9203, chat_type="group", user_id=3
    )
    assert state_engine.resolve_state(
        9203, conversation_mode="normal", record=False
    ) == "argumentative"


def test_annoyed_state_biases_real_length_selection_shorter(monkeypatch):
    state_engine.resolve_state(9204, conversation_mode="normal", now=1000.0)
    state_engine.mark_annoyed(9204, now=1001.0)
    ctx = style_engine.ResponseLengthContext(
        user_text="обычный вопрос",
        conversation_mode="normal",
        response_preference="normal",
        character_state="annoyed",
    )
    weights = style_engine._base_length_weights(ctx)
    multipliers = state_engine.length_weight_multipliers("annoyed")
    assert multipliers["short"] > 1.0
    assert multipliers["long"] < 1.0
    assert weights["short"] * multipliers["short"] > weights["short"]


def test_argumentative_state_increases_aggression_base_probability():
    base = aggression_engine.AggressionContext(
        user_text="это точно факт", intent="group_banter", chat_type="group",
        roughness="high", chat_id=1, user_id=1, character_state="normal"
    )
    argumentative = aggression_engine.AggressionContext(
        user_text="это точно факт", intent="group_banter", chat_type="group",
        roughness="high", chat_id=1, user_id=1, character_state="argumentative"
    )
    assert aggression_engine._base_probability(argumentative) > aggression_engine._base_probability(base)
