import random

import daily_mood_engine as mood


def test_pool_covers_all_keys_over_many_draws():
    rng = random.Random(7)
    drawn = {mood.pick_mood_key(rng) for _ in range(500)}
    assert drawn == set(key for key, _ in mood.MOOD_POOL)


def test_pick_is_deterministic_for_a_seeded_rng():
    assert mood.pick_mood_key(random.Random(1)) == mood.pick_mood_key(random.Random(1))


def test_instruction_text_matches_key():
    for key, text in mood.MOOD_POOL:
        assert mood.mood_instruction(key) == text


def test_unknown_key_falls_back_to_neutral():
    assert mood.mood_instruction("не существует") == mood.mood_instruction("нейтральный")
