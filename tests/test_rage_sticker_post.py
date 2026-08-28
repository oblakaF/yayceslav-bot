import hostile_streak_engine
import sticker_engine
import sticker_post_runtime


def setup_function():
    hostile_streak_engine.reset()


def test_rage_sticker_requires_second_hostile_turn():
    hostile_streak_engine.observe(10, 20, hostile=True, now=1.0)
    assert not sticker_post_runtime._is_rage_exchange(10, 20, "Пес ебливый")

    hostile_streak_engine.observe(10, 20, hostile=True, now=2.0)
    assert sticker_post_runtime._is_rage_exchange(10, 20, "Пес ебливый")


def test_hot_state_does_not_make_neutral_message_an_aggressive_sticker_event():
    hostile_streak_engine.observe(10, 20, hostile=True, now=1.0)
    hostile_streak_engine.observe(10, 20, hostile=True, now=2.0)
    assert not sticker_post_runtime._is_rage_exchange(10, 20, "как погода сегодня?")


def test_all_rage_post_stickers_exist_in_official_pack():
    for key in sticker_post_runtime._RAGE_POST_STICKERS:
        assert key in sticker_engine.STICKER_ORDER
        assert key in sticker_engine.STICKER_SEMANTICS


def test_rage_sticker_probability_is_bounded():
    assert 0 < sticker_post_runtime.RAGE_POST_TEXT_TAG_CHANCE <= 0.20
