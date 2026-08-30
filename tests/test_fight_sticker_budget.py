import fight_sticker_budget as budget


def setup_function():
    budget.reset()


def test_fight_budget_allows_two_visual_beats():
    assert budget.allowed(-100, 7, 100.0)
    budget.record(-100, 7, 100.0)
    assert not budget.allowed(-100, 7, 120.0)
    second = 100.0 + budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0
    assert budget.allowed(-100, 7, second)
    budget.record(-100, 7, second)
    assert budget.count(-100, 7, second) == 2
    assert budget.chat_count(-100, second) == 2
    assert not budget.allowed(-100, 7, second + 300.0)


def test_budget_is_scoped_per_target_before_chat_cap_is_exhausted():
    budget.record(-100, 7, 100.0)
    later = 100.0 + budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0
    assert budget.allowed(-100, 8, later)
    assert budget.count(-100, 8, later) == 0


def test_chat_wide_cap_prevents_parallel_fights_from_spamming():
    budget.record(-100, 7, 100.0)
    second = 100.0 + budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0
    budget.record(-100, 8, second)
    later = second + budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0

    assert budget.chat_count(-100, later) == 2
    assert not budget.allowed(-100, 7, later)
    assert not budget.allowed(-100, 8, later)
    assert not budget.allowed(-100, 9, later)


def test_session_expiry_resets_budget():
    budget.record(-100, 7, 100.0)
    budget.record(-100, 7, 200.0)
    later = 200.0 + budget.FIGHT_STICKER_SESSION_SECONDS + 1.0
    assert budget.count(-100, 7, later) == 0
    assert budget.chat_count(-100, later) == 0
    assert budget.allowed(-100, 7, later)


def test_chance_decreases_after_first_sticker():
    first = budget.chance(-100, 7, 100.0)
    budget.record(-100, 7, 100.0)
    second = budget.chance(-100, 7, 200.0)
    budget.record(-100, 7, 200.0)
    exhausted = budget.chance(-100, 7, 300.0)
    assert first > second > exhausted
    assert exhausted == 0.0
