import bot


def test_get_week_date_range_spans_seven_days():
    start, end = bot.get_week_date_range("2026-08-09")
    assert start == "2026-08-03"
    assert end == "2026-08-09"


def test_build_text_activity_deltas_counts_question_and_link():
    deltas = bot.build_text_activity_deltas(
        "смотри вот ссылка https://example.com, работает?"
    )
    assert deltas["messages"] == 1
    assert deltas["questions"] == 1
    assert deltas["links"] == 1


def test_build_text_activity_deltas_marks_reply_to_bot():
    deltas = bot.build_text_activity_deltas("привет", is_reply_to_bot=True)
    assert deltas["replies_to_bot"] == 1


def test_week_time_regex_accepts_valid_and_rejects_invalid():
    assert bot._WEEK_TIME_RE.match("21:00")
    assert bot._WEEK_TIME_RE.match("00:00")
    assert bot._WEEK_TIME_RE.match("23:59")
    assert bot._WEEK_TIME_RE.match("24:00") is None
    assert bot._WEEK_TIME_RE.match("9:00") is None


def test_weekday_names_cover_russian_and_english():
    assert bot.WEEKDAY_NAMES_RU["воскресенье"] == 6
    assert bot.WEEKDAY_NAMES_RU["sunday"] == 6
    assert bot.WEEKDAY_NAMES_RU["понедельник"] == 0


def test_increment_chat_activity_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "activity_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id, user_id, date_str = 501, 601, "2026-08-02"

    bot.increment_chat_activity_sync(
        chat_id, user_id, "group", date_str, messages=1, text_characters=10
    )
    bot.increment_chat_activity_sync(
        chat_id, user_id, "group", date_str, messages=1, text_characters=5
    )

    weekly = bot.get_weekly_activity_sync(chat_id, date_str, date_str)

    assert len(weekly) == 1
    assert weekly[0]["user_id"] == user_id
    assert weekly[0]["messages"] == 2
    assert weekly[0]["text_characters"] == 15


def test_increment_chat_activity_rejects_unknown_column(tmp_path, monkeypatch):
    db_path = tmp_path / "activity_reject.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    try:
        bot.increment_chat_activity_sync(
            1, 1, "group", "2026-08-02", not_a_real_column=1
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown activity column")


def test_weekly_report_schedule_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "schedule_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 701
    bot.update_chat_setting_sync(chat_id, "weekly_report_enabled", True, "group")
    bot.update_chat_setting_sync(chat_id, "weekly_report_weekday", 6, "group")
    bot.update_chat_setting_sync(chat_id, "weekly_report_time", "21:00", "group")

    chats = bot.get_weekly_report_chats_sync()
    assert len(chats) == 1
    assert chats[0]["chat_id"] == chat_id
    assert chats[0]["weekday"] == 6
    assert chats[0]["time"] == "21:00"
    assert chats[0]["last_sent_date"] is None

    bot.mark_weekly_report_sent_sync(chat_id)
    chats = bot.get_weekly_report_chats_sync()
    assert chats[0]["last_sent_date"] == bot.current_msk_date_str()


def test_weekly_report_schedule_defaults_match_project_decision(tmp_path, monkeypatch):
    db_path = tmp_path / "schedule_defaults.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 702
    settings = bot.get_chat_settings_sync(chat_id, "group")

    # Defaults should be Sunday 21:00 MSK per the explicit product decision,
    # even before anyone runs /week_time.
    with bot.get_db_connection() as connection:
        row = connection.execute(
            "SELECT weekly_report_weekday, weekly_report_time "
            "FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()

    assert row[0] == 6
    assert row[1] == "21:00"
    assert settings["hard_mode_enabled"] is True
