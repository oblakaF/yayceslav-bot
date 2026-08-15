import random

import style_engine


def test_serious_topic_forces_classic_voice_pack():
    ctx = style_engine.VoicePackContext(
        conversation_mode="hostile",
        selected_character="chaos",
        serious_topic=True,
    )
    assert style_engine.choose_voice_pack(ctx) == "classic"


def test_rus_character_forces_old_russian_pack():
    ctx = style_engine.VoicePackContext(
        conversation_mode="normal",
        selected_character="rus",
    )
    assert style_engine.choose_voice_pack(ctx) == "old_russian"


def test_voice_pack_selector_returns_exactly_one_known_pack():
    rng = random.Random(12345)
    ctx = style_engine.VoicePackContext(
        conversation_mode="normal",
        selected_character="classic",
    )
    picks = [style_engine.choose_voice_pack(ctx, rng=rng) for _ in range(100)]
    assert all(isinstance(pack, str) for pack in picks)
    assert set(picks) <= set(style_engine.VOICE_PACKS)


def test_operative_is_hidden_internal_pack_not_forced_character():
    assert "operative" in style_engine.VOICE_PACKS
    assert "operative" not in style_engine._FORCED_PACK_BY_CHARACTER


def test_simple_message_can_be_micro_or_short_with_seeded_rng():
    style_engine.reset_length_history()
    rng = random.Random(1)
    ctx = style_engine.ResponseLengthContext(
        user_text="ну что?",
        conversation_mode="normal",
    )
    plan = style_engine.choose_response_length(1, ctx, rng=rng)
    assert plan.category in {"micro", "short", "normal", "long"}
    assert plan.min_chars <= plan.target_chars <= plan.max_chars


def test_long_answer_creates_verbosity_fatigue_bias():
    weights = {
        "micro": 1.0,
        "short": 1.0,
        "normal": 1.0,
        "long": 1.0,
    }
    style_engine._apply_history_bias(weights, ("long",))
    assert weights["short"] > weights["normal"]
    assert weights["long"] < weights["normal"]


def test_repeated_length_class_gets_strong_penalty():
    weights = {
        "micro": 1.0,
        "short": 1.0,
        "normal": 1.0,
        "long": 1.0,
    }
    style_engine._apply_history_bias(weights, ("normal", "normal"))
    assert weights["normal"] < 0.2
    assert weights["short"] == 1.0


def test_detailed_is_bias_not_forced_long():
    weights = style_engine._base_length_weights(
        style_engine.ResponseLengthContext(
            user_text="привет",
            conversation_mode="greeting",
            response_preference="detailed",
        )
    )
    style_engine._apply_preference_bias(weights, "detailed")
    assert weights["micro"] > 0
    assert weights["short"] > 0


def test_length_history_is_per_chat():
    style_engine.reset_length_history()
    ctx = style_engine.ResponseLengthContext(user_text="что думаешь?")
    style_engine.choose_response_length(10, ctx, rng=random.Random(10))
    style_engine.choose_response_length(20, ctx, rng=random.Random(20))
    assert len(style_engine.get_length_history(10)) == 1
    assert len(style_engine.get_length_history(20)) == 1


def test_length_instruction_explicitly_avoids_padding():
    plan = style_engine.ResponseLengthPlan(
        category="micro",
        min_chars=45,
        max_chars=170,
        target_chars=90,
    )
    instruction = style_engine.build_length_instruction(plan)
    assert "одна-две" in instruction
    assert "не обязанность" in instruction


def test_voice_pack_guard_forbids_mixing():
    instruction = style_engine.build_voice_pack_guard("blat")
    assert "blat" in instruction
    assert "Не смешивай" in instruction
