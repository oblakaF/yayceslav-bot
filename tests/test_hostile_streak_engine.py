import hostile_streak_engine as streaks


def setup_function():
    streaks.reset()


def test_streak_escalates_from_second_attack_and_saturates():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=10.0) == 2
    assert streaks.observe(1, 10, hostile=True, now=20.0) == 3
    assert streaks.observe(1, 10, hostile=True, now=30.0) == 4
    assert streaks.observe(1, 10, hostile=True, now=40.0) == 4


def test_non_hostile_turn_does_not_erase_hot_conflict():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=10.0) == 2
    assert streaks.observe(1, 10, hostile=False, now=20.0) == 2
    assert streaks.current(1, 10, now=21.0) == 2
    assert streaks.observe(1, 10, hostile=True, now=30.0) == 3


def test_explicit_reset_cools_conflict():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=10.0) == 2
    streaks.reset(1, 10)
    assert streaks.current(1, 10, now=20.0) == 0
    assert streaks.observe(1, 10, hostile=True, now=30.0) == 1


def test_streak_isolated_by_user_and_chat():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=5.0) == 2
    assert streaks.observe(1, 20, hostile=True, now=5.0) == 1
    assert streaks.observe(2, 10, hostile=True, now=5.0) == 1


def test_streak_expires_after_ten_minutes_from_last_attack():
    assert streaks.observe(1, 10, hostile=True, now=0.0) == 1
    assert streaks.observe(1, 10, hostile=True, now=599.0) == 2
    # A neutral turn sees the heat but does not extend its TTL.
    assert streaks.observe(1, 10, hostile=False, now=700.0) == 2
    assert streaks.current(1, 10, now=1200.0) == 0
    assert streaks.observe(1, 10, hostile=True, now=1200.0) == 1


def test_escalation_gate_starts_on_second_attack():
    assert not streaks.is_escalated(1)
    assert streaks.is_escalated(2)
    assert streaks.is_escalated(3)
    assert streaks.is_escalated(4)
