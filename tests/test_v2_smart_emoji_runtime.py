import math

import bot
import reaction_engine


def test_bot_detects_v2_provocation_reason():
    assert bot.detect_reaction_reason("а тебе слабо доказать?") == "provocation"


def test_bot_detects_mysticism_reason_even_with_low_intent_confidence():
    assert bot.detect_reaction_reason("мне таро предсказали судьбу") == "mysticism"


def test_bot_picker_uses_v2_reason_map(monkeypatch):
    monkeypatch.setattr(reaction_engine, "pick_v2_emoji", lambda reason: "🧿" if reason == "mysticism" else None)
    assert bot.pick_reaction_emoji("mysticism") == "🧿"


def test_normal_hard_level_random_reply_chance_is_unchanged():
    # Главное регрессионное правило: текстовые вмешательства
    # не режем вместе с emoji.
    assert math.isclose(bot.HARD_LEVEL_CHANCES["normal"]["random_reply_chance"], 0.16)


def test_normal_emoji_probability_uses_current_multiplier_without_reason():
    normal = bot.HARD_LEVEL_CHANCES["normal"]["reaction_chance"]
    assert math.isclose(normal, 0.70)
    assert math.isclose(
        reaction_engine.effective_emoji_reaction_chance(normal, has_context_reason=False),
        0.504,
    )
