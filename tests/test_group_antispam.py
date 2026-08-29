from datetime import datetime, timedelta, timezone

import bot


def _reset_chat(chat_id: int) -> None:
    bot.GROUP_RANDOM_REPLY_TIMES.pop(chat_id, None)
    bot.GROUP_IGNORED_STREAK.pop(chat_id, None)
    bot.GROUP_LAST_SERIOUS_AT.pop(chat_id, None)


def _force_daytime(monkeypatch) -> None:
    # These tests exercise the interval/window/serious/ignore logic,
    # not the time-of-day gate -- pin it so a real midnight run
    # doesn't make them flaky.
    monkeypatch.setattr(bot, "is_quiet_hours_msk", lambda: False)


def test_quiet_hours_detects_night():
    fixed = datetime(2026, 1, 1, 3, 0, tzinfo=timezone(timedelta(hours=3)))

    class FakeDatetime:
        @staticmethod
        def now(tz=None):
            return fixed

    original = bot.datetime
    bot.datetime = FakeDatetime
    try:
        assert bot.is_quiet_hours_msk() is True
    finally:
        bot.datetime = original


def test_quiet_hours_false_during_day():
    fixed = datetime(2026, 1, 1, 14, 0, tzinfo=timezone(timedelta(hours=3)))

    class FakeDatetime:
        @staticmethod
        def now(tz=None):
            return fixed

    original = bot.datetime
    bot.datetime = FakeDatetime
    try:
        assert bot.is_quiet_hours_msk() is False
    finally:
        bot.datetime = original


def test_group_random_reply_respects_min_interval(monkeypatch):
    _force_daytime(monkeypatch)
    chat_id = 555001
    _reset_chat(chat_id)

    now = 10_000.0
    assert bot.group_random_reply_allowed(chat_id, now) is True
    bot.record_group_random_reply(chat_id, now)

    assert bot.group_random_reply_allowed(chat_id, now + 10) is False
    assert (
        bot.group_random_reply_allowed(
            chat_id, now + bot.GROUP_RANDOM_REPLY_MIN_INTERVAL + 1
        )
        is True
    )


def test_group_random_reply_respects_window_cap(monkeypatch):
    _force_daytime(monkeypatch)
    chat_id = 555002
    _reset_chat(chat_id)

    now = 20_000.0
    for _ in range(bot.GROUP_RANDOM_REPLY_MAX_PER_WINDOW):
        assert bot.group_random_reply_allowed(chat_id, now) is True
        bot.record_group_random_reply(chat_id, now)
        # Reset the ignored-streak between sends so this loop tests
        # the window cap in isolation, not the (stricter) streak limit.
        bot.register_group_engagement(chat_id)
        now += bot.GROUP_RANDOM_REPLY_MIN_INTERVAL + 1

    assert bot.group_random_reply_allowed(chat_id, now) is False


def test_group_random_reply_blocked_after_serious_topic(monkeypatch):
    _force_daytime(monkeypatch)
    chat_id = 555003
    _reset_chat(chat_id)

    now = 30_000.0
    bot.GROUP_LAST_SERIOUS_AT[chat_id] = now

    assert bot.group_random_reply_allowed(chat_id, now + 60) is False
    assert (
        bot.group_random_reply_allowed(
            chat_id, now + bot.SERIOUS_TOPIC_HUMOR_COOLDOWN + 1
        )
        is True
    )


def test_group_random_reply_blocked_after_two_ignored_then_reset(monkeypatch):
    _force_daytime(monkeypatch)
    chat_id = 555004
    _reset_chat(chat_id)

    now = 40_000.0
    bot.record_group_random_reply(chat_id, now)
    now += bot.GROUP_RANDOM_REPLY_MIN_INTERVAL + 1
    bot.record_group_random_reply(chat_id, now)
    now += bot.GROUP_RANDOM_REPLY_MIN_INTERVAL + 1

    assert bot.group_random_reply_allowed(chat_id, now) is False

    bot.register_group_engagement(chat_id)
    assert bot.group_random_reply_allowed(chat_id, now) is True


def test_cleanup_in_memory_state_prunes_antispam_dicts():
    bot.GROUP_RANDOM_REPLY_TIMES.clear()
    bot.GROUP_IGNORED_STREAK.clear()
    bot.GROUP_LAST_SERIOUS_AT.clear()
    bot.TRIGGER_REPLY_LAST_BY_USER.clear()

    import time

    stale_chat = 9101
    fresh_chat = 9102
    stale_user_key = (9101, 1)

    bot.GROUP_RANDOM_REPLY_TIMES[stale_chat].append(time.monotonic() - 999_999)
    bot.GROUP_IGNORED_STREAK[stale_chat] = 1
    bot.GROUP_RANDOM_REPLY_TIMES[fresh_chat].append(time.monotonic())

    bot.GROUP_LAST_SERIOUS_AT[stale_chat] = time.monotonic() - 999_999
    bot.TRIGGER_REPLY_LAST_BY_USER[stale_user_key] = time.monotonic() - 999_999

    removed = bot.cleanup_in_memory_state(max_age_seconds=10)

    assert stale_chat not in bot.GROUP_RANDOM_REPLY_TIMES
    assert stale_chat not in bot.GROUP_IGNORED_STREAK
    assert fresh_chat in bot.GROUP_RANDOM_REPLY_TIMES
    assert stale_chat not in bot.GROUP_LAST_SERIOUS_AT
    assert stale_user_key not in bot.TRIGGER_REPLY_LAST_BY_USER
    assert removed["random_reply_chats"] == 1
    assert removed["serious_chats"] == 1
    assert removed["trigger_user_keys"] == 1
