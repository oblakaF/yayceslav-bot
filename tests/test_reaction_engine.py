import math
import random

import reaction_engine


def test_emoji_chance_uses_current_frequency_multiplier_without_reason():
    assert math.isclose(
        reaction_engine.effective_emoji_reaction_chance(
            0.70,
            has_context_reason=False,
        ),
        0.504,
    )


def test_context_floor_is_applied_before_current_frequency_multiplier():
    assert math.isclose(
        reaction_engine.effective_emoji_reaction_chance(
            0.70,
            has_context_reason=True,
        ),
        0.612,
    )


def test_chaos_probability_is_scaled_not_clipped_upward():
    assert math.isclose(
        reaction_engine.effective_emoji_reaction_chance(
            0.90,
            has_context_reason=True,
        ),
        0.648,
    )


def test_mysticism_gets_evil_eye_reason():
    reason = reaction_engine.detect_context_reason(
        "Мне карты таро предсказали странную судьбу",
        resolved_intent="unknown",
        confidence="low",
    )
    assert reason == "mysticism"
    assert reaction_engine.pick_v2_emoji(
        reason,
        rng=random.Random(1),
    ) in {"🧿", "🗿"}


def test_provocation_gets_context_reason_with_medium_confidence():
    assert reaction_engine.detect_context_reason(
        "а тебе слабо доказать?",
        resolved_intent="provocation",
        confidence="medium",
    ) == "provocation"


def test_low_confidence_unknown_does_not_invent_intent_reason():
    assert reaction_engine.detect_context_reason(
        "обычное сообщение",
        resolved_intent="group_banter",
        confidence="low",
    ) is None


def test_dead_argument_has_gravestone_available():
    reason = reaction_engine.detect_context_reason(
        "ты только что разнес аргумент",
        confidence="low",
    )
    assert reason == "dead_argument"
    assert "🪦" in reaction_engine.V2_REASON_EMOJIS[reason]


def test_module_has_no_random_reply_multiplier():
    # Защита от случайного переноса снижения на текстовые вмешательства.
    assert not hasattr(reaction_engine, "RANDOM_REPLY_FREQUENCY_MULTIPLIER")
