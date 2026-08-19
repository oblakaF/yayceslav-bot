import asyncio
from datetime import datetime, timezone, timedelta

from telegram.ext import Application, MessageHandler

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
    assert monthly._target_report_date(
        datetime(2026, 8, 31, 18, 59, tzinfo=MSK)
    ) is None
    assert monthly._target_report_date(
        datetime(2026, 8, 31, 19, 0, tzinfo=MSK)
    ) == datetime(2026, 8, 31).date()


def test_first_day_catches_up_previous_month():
    assert monthly._target_report_date(
        datetime(2026, 9, 1, 0, 5, tzinfo=MSK)
    ) == datetime(2026, 8, 31).date()


def test_level_four_is_only_unique_month_leader():
    assert relationship.chat_level_from_monthly_messages(554) == 3
    assert relationship.chat_level_from_monthly_messages(555) == 3
    assert relationship.chat_level_from_monthly_messages(555, is_month_leader=True) == 4
    assert relationship.chat_level_from_monthly_messages(1200, is_month_leader=False) == 3


def test_scheduler_keeps_daily_titles_before_monthly_report(monkeypatch):
    calls = []

    class FakeBotModule:
        _yayceslav_monthly_report_patch = False

        async def run_due_daily_titles(self, application):
            del application
            calls.append("daily")

    fake = FakeBotModule()

    async def fake_monthly_report(application):
        del application
        calls.append("monthly")

    monkeypatch.setattr(monthly, "run_monthly_report_if_due", fake_monthly_report)

    monthly._patch_scheduler(fake)
    wrapped = fake.run_due_daily_titles
    monthly._patch_scheduler(fake)

    assert fake.run_due_daily_titles is wrapped
    asyncio.run(fake.run_due_daily_titles(object()))
    assert calls == ["daily", "monthly"]


def test_prepare_application_registers_once(monkeypatch):
    class FakeBotModule:
        _yayceslav_monthly_report_patch = False

        async def run_due_daily_titles(self, application):
            del application

    fake = FakeBotModule()
    init_calls = []
    monkeypatch.setattr(monthly, "_find_bot_module", lambda: fake)
    monkeypatch.setattr(monthly, "_initialize_tables", lambda bot: init_calls.append(bot))

    application = Application.builder().token("123456:TESTTOKEN").build()
    monthly._PREPARED_APPLICATION_IDS.discard(id(application))
    monthly._prepare_application(application)
    monthly._prepare_application(application)

    assert init_calls == [fake]
    handlers = application.handlers.get(8, ())
    assert len(handlers) == 1
    assert isinstance(handlers[0], MessageHandler)
    assert handlers[0].callback is monthly._observe_monthly_social
    assert not hasattr(monthly, "install_runtime_hook")
