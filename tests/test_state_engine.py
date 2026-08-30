import state_engine


def setup_function():
    state_engine.reset_state()


def test_first_message_is_cold_start():
    assert state_engine.resolve_state(
        1,
        conversation_mode="normal",
        now=1000.0,
    ) == "cold_start"


def test_next_messages_warm_up_then_normal():
    assert state_engine.resolve_state(2, conversation_mode="normal", now=1000.0) == "cold_start"
    assert state_engine.resolve_state(2, conversation_mode="normal", now=1001.0) == "warming_up"
    assert state_engine.resolve_state(2, conversation_mode="normal", now=1002.0) == "warming_up"
    assert state_engine.resolve_state(2, conversation_mode="normal", now=1003.0) == "warming_up"
    assert state_engine.resolve_state(2, conversation_mode="normal", now=1004.0) == "normal"


def test_serious_has_highest_safety_priority():
    state_engine.mark_annoyed(3, now=1000.0)
    state_engine.mark_argumentative(3, now=1000.0)
    assert state_engine.resolve_state(
        3,
        conversation_mode="serious",
        now=1001.0,
    ) == "serious"


def test_hostile_response_overrides_annoyed():
    state_engine.mark_annoyed(4, now=1000.0)
    assert state_engine.resolve_state(
        4,
        conversation_mode="hostile",
        now=1001.0,
    ) == "hostile_response"


def test_fatigue_can_mark_annoyed_for_following_turns():
    state_engine.resolve_state(5, conversation_mode="normal", now=1000.0)
    state_engine.mark_annoyed(5, now=1001.0)
    assert state_engine.resolve_state(
        5,
        conversation_mode="normal",
        now=1002.0,
    ) == "annoyed"


def test_dokop_can_mark_argumentative_for_following_turns():
    state_engine.resolve_state(6, conversation_mode="normal", now=1000.0)
    state_engine.mark_argumentative(6, now=1001.0)
    assert state_engine.resolve_state(
        6,
        conversation_mode="normal",
        now=1002.0,
    ) == "argumentative"


def test_argumentative_state_does_not_leak_to_another_sender_in_same_chat():
    token = state_engine.push_actor_scope(101)
    try:
        state_engine.resolve_state(77, conversation_mode="normal", now=1000.0)
        state_engine.mark_argumentative(77, now=1001.0)
        assert state_engine.resolve_state(
            77, conversation_mode="normal", now=1002.0
        ) == "argumentative"
    finally:
        state_engine.pop_actor_scope(token)

    other = state_engine.push_actor_scope(202)
    try:
        assert state_engine.resolve_state(
            77, conversation_mode="normal", now=1002.0
        ) == "cold_start"
    finally:
        state_engine.pop_actor_scope(other)


def test_annoyed_biases_length_shorter():
    weights = state_engine.length_weight_multipliers("annoyed")
    assert weights["short"] > 1.0
    assert weights["long"] < 1.0


def test_argumentative_increases_aggression_probability():
    assert state_engine.aggression_probability_bonus("argumentative") > 0
    assert state_engine.aggression_probability_bonus("normal") == 0


def test_state_instruction_explicitly_does_not_mix_voice_packs():
    instruction = state_engine.build_state_instruction("argumentative")
    assert "НЕ речевой стиль" in instruction
    assert "не разрешение смешивать voice packs" in instruction
