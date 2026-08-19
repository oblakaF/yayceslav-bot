from datetime import datetime, timezone, timedelta

import monthly_report_timing_patch as timing
import monthly_social_runtime as monthly
import relationship_experience_runtime as relationship


MSK = timezone(timedelta(hours=3))


def test_last_calendar_day_handles_february_and_30_31_day_months():
    assert monthly.is_last_calendar_day(datetime(2026, 2, 28).date())
    assert not monthly.is_last_calendar_day(datetime(2026, 2, 27).date())
    assert monthly.is_last_calendar_day(datetime(2028, 2, 29).date())
    assert monthly.is_last_calendar_day(datetime(2026, 4, 30).date())
    assert monthly.is_last_calendar_day(datetime(2026, 8, 31).date())


def test_monthly_report_opens_at_1900_msk_on_last_day():
    assert timing._target_report_date(
        datetime(2026, 8, 31, 18, 59, tzinfo=MSK)
    ) is None
    assert timing._target_report_date(
        datetime(2026, 8, 31, 19, 0, tzinfo=MSK)
    ) == datetime(2026, 8, 31).date()


def test_first_day_catches_up_previous_month():
    assert timing._target_report_date(
        datetime(2026, 9, 1, 0, 5, tzinfo=MSK)
    ) == datetime(2026, 8, 31).date()


def test_level_four_is_only_unique_month_leader():
    assert relationship.chat_level_from_monthly_messages(554) == 3
    assert relationship.chat_level_from_monthly_messages(555) == 3
    assert relationship.chat_level_from_monthly_messages(555, is_month_leader=True) == 4
    assert relationship.chat_level_from_monthly_messages(1200, is_month_leader=False) == 3
