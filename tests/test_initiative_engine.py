import random

import initiative_engine as initiative


def test_every_mood_key_has_a_pool_with_enough_variety():
    for key in ("раздражённый", "благодушный", "циничный", "энергичный", "уставший",
                "подозрительный", "мемный", "нейтральный", "generic"):
        assert key in initiative.INITIATIVE_LINE_POOL
        assert len(initiative.INITIATIVE_LINE_POOL[key]) >= 5


def test_no_duplicate_lines_within_a_pool():
    for key, pool in initiative.INITIATIVE_LINE_POOL.items():
        assert len(pool) == len(set(pool)), f"duplicate line in pool {key!r}"


def test_unknown_mood_falls_back_to_generic():
    rng = random.Random(1)
    line = initiative.pick_initiative_line("не существует", rng)
    assert line in initiative.INITIATIVE_LINE_POOL["generic"]


def test_none_mood_falls_back_to_generic():
    rng = random.Random(1)
    line = initiative.pick_initiative_line(None, rng)
    assert line in initiative.INITIATIVE_LINE_POOL["generic"]


def test_known_mood_draws_from_its_own_pool():
    rng = random.Random(1)
    line = initiative.pick_initiative_line("энергичный", rng)
    assert line in initiative.INITIATIVE_LINE_POOL["энергичный"]


def test_pick_is_deterministic_for_a_seeded_rng():
    a = initiative.pick_initiative_line("мемный", random.Random(3))
    b = initiative.pick_initiative_line("мемный", random.Random(3))
    assert a == b
