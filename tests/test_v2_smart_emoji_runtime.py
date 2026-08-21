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
        0.385,
    )


def test_default_reaction_pool_has_no_mocking_emoji():
    # Poop/clown are earned via a specific detected reason or a genuinely
    # negative reputation, not handed out to a reason-less coin flip.
    assert "🤡" not in bot.HARD_REACTION_EMOJIS
    assert "💩" not in bot.HARD_REACTION_EMOJIS


def test_reputation_biased_pool_goes_cold_for_low_reputation():
    pool = reaction_engine.reputation_biased_pool(-50, bot.HARD_REACTION_EMOJIS)
    assert pool == reaction_engine.COLD_REACTION_EMOJIS


def test_reputation_biased_pool_goes_warm_for_high_reputation():
    pool = reaction_engine.reputation_biased_pool(50, bot.HARD_REACTION_EMOJIS)
    assert pool == reaction_engine.WARM_REACTION_EMOJIS


def test_reputation_biased_pool_stays_neutral_in_between():
    pool = reaction_engine.reputation_biased_pool(0, bot.HARD_REACTION_EMOJIS)
    assert pool == tuple(bot.HARD_REACTION_EMOJIS)


def test_reputation_biased_pool_defaults_to_neutral_when_unknown():
    pool = reaction_engine.reputation_biased_pool(None, bot.HARD_REACTION_EMOJIS)
    assert pool == tuple(bot.HARD_REACTION_EMOJIS)


def test_pick_reaction_emoji_uses_cold_pool_for_low_reputation_no_reason():
    emoji = bot.pick_reaction_emoji(None, reputation_score=-50)
    assert emoji in reaction_engine.COLD_REACTION_EMOJIS


def test_pick_reaction_emoji_specific_reason_ignores_reputation():
    # A detected reason always wins over reputation-based pool selection.
    emoji = bot.pick_reaction_emoji("good_question", reputation_score=-50)
    assert emoji in bot.REACTION_REASON_EMOJIS["good_question"]
