import bot


def _activity(user_id, **kwargs):
    entry = {
        "user_id": user_id,
        "messages": 0,
        "text_characters": 0,
        "voice_messages": 0,
        "voice_duration_seconds": 0,
        "photos": 0,
        "videos": 0,
        "stickers": 0,
        "documents": 0,
        "replies": 0,
        "replies_to_bot": 0,
        "commands": 0,
        "night_messages": 0,
        "questions": 0,
        "links": 0,
        "edited_messages": 0,
    }
    entry.update(kwargs)
    return entry


def test_chat_leader_picks_the_highest_message_count():
    weekly = [
        _activity(1, messages=10),
        _activity(2, messages=25),
        _activity(3, messages=5),
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert awards["chat_leader"] == 2


def test_no_award_when_everyone_is_at_zero():
    weekly = [_activity(1), _activity(2)]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert "chat_leader" not in awards
    assert "voice_leader" not in awards


def test_one_word_sage_requires_minimum_messages():
    weekly = [
        # Both below the 5-message minimum -- nobody should qualify.
        _activity(1, messages=2, text_characters=2),
        _activity(2, messages=3, text_characters=6),
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert "one_word_sage" not in awards


def test_one_word_sage_picks_shortest_average_length():
    weekly = [
        _activity(1, messages=10, text_characters=20),  # avg 2
        _activity(2, messages=10, text_characters=500),  # avg 50
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert awards["one_word_sage"] == 1


def test_silent_observer_only_for_previously_active_member():
    weekly = [_activity(1, messages=5)]
    known_members = [
        {"user_id": 1, "total_messages": 50},
        {"user_id": 2, "total_messages": 30},  # known, active before, silent now
        {"user_id": 3, "total_messages": 0},  # never posted -- not eligible
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members))
    assert awards["silent_observer"] == 2


def test_no_silent_observer_when_everyone_known_is_active():
    weekly = [_activity(1, messages=5)]
    known_members = [{"user_id": 1, "total_messages": 50}]
    awards = dict(bot.compute_weekly_awards(weekly, known_members))
    assert "silent_observer" not in awards


def test_format_awards_message_handles_empty_list():
    message = bot.format_awards_message([], {})
    assert "маловато" in message


def test_format_awards_message_includes_display_name():
    message = bot.format_awards_message(
        [("chat_leader", 1)], {1: "Тестовый Герой"}
    )
    assert "Тестовый Герой" in message
    assert "Срун чата" in message


def test_get_or_create_weekly_awards_locks_in_first_choice(tmp_path, monkeypatch):
    """
    Regression for the bug where silent_observer (and any other
    award using random.choice) could return a different winner on
    every call within the same week. The first computed winner must
    stick even if a later call's local randomness would have picked
    someone else.
    """

    db_path = tmp_path / "awards_lock.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 9001
    week_start = "2026-08-03"
    weekly = [_activity(1, messages=5)]
    known_members = [
        {"user_id": 1, "total_messages": 5},
        {"user_id": 2, "total_messages": 20},  # silent this week
        {"user_id": 3, "total_messages": 15},  # silent this week
    ]

    monkeypatch.setattr(bot.random, "choice", lambda seq: seq[0])
    first = dict(
        bot.get_or_create_weekly_awards_sync(
            chat_id, week_start, weekly, known_members
        )
    )

    monkeypatch.setattr(bot.random, "choice", lambda seq: seq[-1])
    second = dict(
        bot.get_or_create_weekly_awards_sync(
            chat_id, week_start, weekly, known_members
        )
    )

    assert first["silent_observer"] == second["silent_observer"]


def test_get_or_create_weekly_awards_scoped_per_week(tmp_path, monkeypatch):
    db_path = tmp_path / "awards_per_week.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 9002
    weekly = [_activity(1, messages=10), _activity(2, messages=3)]
    known_members = [
        {"user_id": 1, "total_messages": 10},
        {"user_id": 2, "total_messages": 3},
    ]

    bot.get_or_create_weekly_awards_sync(
        chat_id, "2026-08-03", weekly, known_members
    )
    bot.get_or_create_weekly_awards_sync(
        chat_id, "2026-08-10", weekly, known_members
    )

    with bot.get_db_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM weekly_award_winners WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()[0]

    # chat_leader is stored once per week -- two distinct weeks means
    # at least two rows for the same award_key, not a single shared one.
    assert count >= 2


def test_time_str_to_minutes():
    assert bot._time_str_to_minutes("00:00") == 0
    assert bot._time_str_to_minutes("21:00") == 21 * 60
    assert bot._time_str_to_minutes("23:59") == 23 * 60 + 59


class _FakeBot:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.sent_messages = []

    async def send_message(self, chat_id, text):
        if self.should_fail:
            raise RuntimeError("boom")
        self.sent_messages.append((chat_id, text))


class _FakeApplication:
    def __init__(self, should_fail=False):
        self.bot = _FakeBot(should_fail=should_fail)


async def _fake_ask_gemini(*args, **kwargs):
    """Avoids a real (and, with a fake API key, always-failing-with-
    retries) network call to Gemini for the report "verdict" line —
    these tests only care about the send/mark-sent bookkeeping."""

    return "Тестовый вердикт недели."


def test_run_due_weekly_reports_marks_sent_only_on_success(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(bot, "ask_gemini", _fake_ask_gemini)

    db_path = tmp_path / "auto_report_success.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 9101
    bot.update_chat_setting_sync(chat_id, "weekly_report_enabled", True, "group")

    now = bot.current_msk_datetime()
    bot.update_chat_setting_sync(
        chat_id, "weekly_report_weekday", now.weekday(), "group"
    )
    bot.update_chat_setting_sync(
        chat_id, "weekly_report_time", now.strftime("%H:%M"), "group"
    )

    # Give it something to report so build_weekly_report_text has data.
    bot.increment_chat_activity_sync(
        chat_id, 1, "group", bot.current_msk_date_str(), messages=3
    )

    application = _FakeApplication(should_fail=False)
    asyncio.run(bot.run_due_weekly_reports(application))

    assert len(application.bot.sent_messages) == 1

    chats = bot.get_weekly_report_chats_sync()
    sent_entry = next(c for c in chats if c["chat_id"] == chat_id)
    assert sent_entry["last_sent_date"] == bot.current_msk_date_str()


def test_run_due_weekly_reports_does_not_mark_sent_on_failure(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(bot, "ask_gemini", _fake_ask_gemini)

    db_path = tmp_path / "auto_report_failure.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 9102
    bot.update_chat_setting_sync(chat_id, "weekly_report_enabled", True, "group")

    now = bot.current_msk_datetime()
    bot.update_chat_setting_sync(
        chat_id, "weekly_report_weekday", now.weekday(), "group"
    )
    bot.update_chat_setting_sync(
        chat_id, "weekly_report_time", now.strftime("%H:%M"), "group"
    )
    bot.increment_chat_activity_sync(
        chat_id, 1, "group", bot.current_msk_date_str(), messages=3
    )

    application = _FakeApplication(should_fail=True)
    asyncio.run(bot.run_due_weekly_reports(application))

    chats = bot.get_weekly_report_chats_sync()
    sent_entry = next(c for c in chats if c["chat_id"] == chat_id)
    assert sent_entry["last_sent_date"] is None


def test_run_due_weekly_reports_retries_next_minute_after_failure(tmp_path, monkeypatch):
    """
    A failed send at the scheduled minute must still be eligible one
    minute later on the same day -- not skipped until next week.
    """

    import asyncio

    monkeypatch.setattr(bot, "ask_gemini", _fake_ask_gemini)

    db_path = tmp_path / "auto_report_retry.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 9103
    now = bot.current_msk_datetime()
    bot.update_chat_setting_sync(chat_id, "weekly_report_enabled", True, "group")
    bot.update_chat_setting_sync(
        chat_id, "weekly_report_weekday", now.weekday(), "group"
    )
    # Schedule it a minute in the past so "now" is already past due.
    scheduled_minutes = now.hour * 60 + now.minute - 1
    scheduled_time = f"{scheduled_minutes // 60:02d}:{scheduled_minutes % 60:02d}"
    bot.update_chat_setting_sync(
        chat_id, "weekly_report_time", scheduled_time, "group"
    )
    bot.increment_chat_activity_sync(
        chat_id, 1, "group", bot.current_msk_date_str(), messages=3
    )

    failing_application = _FakeApplication(should_fail=True)
    asyncio.run(bot.run_due_weekly_reports(failing_application))

    working_application = _FakeApplication(should_fail=False)
    asyncio.run(bot.run_due_weekly_reports(working_application))

    assert len(working_application.bot.sent_messages) == 1
