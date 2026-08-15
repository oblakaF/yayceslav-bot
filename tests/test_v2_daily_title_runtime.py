import bot


def _seed_member(chat_id, user_id):
    with bot.get_db_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, 'group')",
            (chat_id,),
        )
        connection.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_member_profiles (
                chat_id, user_id, current_display_name
            ) VALUES (?, ?, ?)
            """,
            (chat_id, user_id, f"user-{user_id}"),
        )
        connection.commit()


def test_daily_assignment_is_atomic_and_persistent(tmp_path, monkeypatch):
    db_path = tmp_path / "daily-title.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    _seed_member(-1001, 11)
    assert bot.try_assign_daily_title_sync(-1001, "2026-08-15", 11, "Воевода споров")
    assert not bot.try_assign_daily_title_sync(-1001, "2026-08-15", 11, "Другой титул")
    saved = bot.get_daily_title_assignment_sync(-1001, "2026-08-15")
    assert saved is not None
    assert saved["user_id"] == 11
    assert saved["title"] == "Воевода споров"


def test_daily_assignment_updates_current_member_title(tmp_path, monkeypatch):
    db_path = tmp_path / "daily-title-member.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    _seed_member(-1002, 12)
    assert bot.try_assign_daily_title_sync(-1002, "2026-08-15", 12, "Князь тестов")
    profile = bot.get_member_profile_sync(-1002, 12)
    assert profile is not None
    assert profile["current_title"] == "Князь тестов"


def test_same_chat_can_receive_new_title_next_day(tmp_path, monkeypatch):
    db_path = tmp_path / "daily-title-next-day.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    _seed_member(-1003, 13)
    assert bot.try_assign_daily_title_sync(-1003, "2026-08-15", 13, "Первый")
    assert bot.try_assign_daily_title_sync(-1003, "2026-08-16", 13, "Второй")


def test_two_different_users_cannot_receive_two_titles_same_day(tmp_path, monkeypatch):
    db_path = tmp_path / "daily-title-race.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    _seed_member(-1004, 14)
    _seed_member(-1004, 15)
    assert bot.try_assign_daily_title_sync(-1004, "2026-08-15", 14, "Первый")
    assert not bot.try_assign_daily_title_sync(-1004, "2026-08-15", 15, "Второй")
    saved = bot.get_daily_title_assignment_sync(-1004, "2026-08-15")
    assert saved["user_id"] == 14
