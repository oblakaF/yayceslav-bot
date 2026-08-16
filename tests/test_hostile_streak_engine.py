import hostile_streak_engine as streaks


def setup_function():
    streaks.reset()


def test_streak_escalates_on_third_and_fourth_then_cycles_back():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=10.0) == 2
    assert streaks.observe(1, 10, hostile=True, now=20.0) == 3
    assert streaks.observe(1, 10, hostile=True, now=30.0) == 4
    assert streaks.observe(1, 10, hostile=True, now=40.0) == 1


def test_non_hostile_turn_resets_same_users_streak():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=10.0) == 2
    assert streaks.observe(1, 10, hostile=False, now=20.0) == 0
    assert streaks.observe(1, 10, hostile=True, now=30.0) == 1


def test_streak_isolated_by_user_and_chat():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=5.0) == 2
    assert streaks.observe(1, 20, hostile=True, now=5.0) == 1
    assert streaks.observe(2, 10, hostile=True, now=5.0) == 1


def test_streak_expires_after_ten_minutes():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=599.0) == 2
    assert streaks.observe(1, 10, hostile=True, now=1200.0) == 1


def test_escalation_gate_only_third_and_fourth():
    assert not streaks.is_escalated(1)
    assert not streaks.is_escalated(2)
    assert streaks.is_escalated(3)
    assert streaks.is_escalated(4)
