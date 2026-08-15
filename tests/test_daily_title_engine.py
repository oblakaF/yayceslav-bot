from datetime import datetime, timezone, timedelta

import daily_title_engine


class FirstChoice:
    @staticmethod
    def choice(seq):
        return seq[0]


def test_assignment_window_opens_at_18_msk():
    tz = timezone(timedelta(hours=3))
    assert not daily_title_engine.is_assignment_window_open(
        datetime(2026, 8, 15, 17, 59, tzinfo=tz)
    )
    assert daily_title_engine.is_assignment_window_open(
        datetime(2026, 8, 15, 18, 0, tzinfo=tz)
    )


def test_only_users_with_messages_today_are_candidates():
    activity = [
        {"user_id": 1, "messages": 5},
        {"user_id": 2, "messages": 0},
        {"user_id": 3, "messages": 2},
    ]
    members = [
        {"user_id": 1, "current_display_name": "А", "current_title": "Старый"},
        {"user_id": 2, "current_display_name": "Б", "current_title": None},
        {"user_id": 3, "current_display_name": "В", "current_title": None},
    ]
    candidates = daily_title_engine.build_candidates(activity, members)
    assert [c.user_id for c in candidates] == [1, 3]
    assert candidates[0].previous_title == "Старый"


def test_activity_amount_does_not_weight_random_choice():
    candidates = [
        daily_title_engine.DailyTitleCandidate(1, 100, "А"),
        daily_title_engine.DailyTitleCandidate(2, 1, "Б"),
    ]
    chosen = daily_title_engine.choose_candidate(candidates, rng=FirstChoice())
    assert chosen is candidates[0]


def test_no_active_users_means_no_title():
    assert daily_title_engine.choose_candidate([], rng=FirstChoice()) is None


def test_message_is_short_and_contains_name_and_title():
    text = daily_title_engine.format_daily_title_message("Вася", "Воевода споров")
    assert "Вася" in text
    assert "Воевода споров" in text
    assert len(text) < 220
