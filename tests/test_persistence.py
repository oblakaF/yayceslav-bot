import time

import bot


def test_get_db_connection_sets_wal_and_foreign_keys(tmp_path):
    db_path = tmp_path / "pragma_test.db"
    connection = bot.get_db_connection(db_path)
    try:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        assert str(journal_mode).lower() == "wal"
        assert foreign_keys == 1
    finally:
        connection.close()


def test_chat_settings_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "chat_settings_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 555

    defaults = bot.get_chat_settings_sync(chat_id, "group")
    assert defaults == bot.DEFAULT_CHAT_SETTINGS

    bot.update_chat_setting_sync(chat_id, "hard_mode_enabled", False, "group")
    bot.update_chat_setting_sync(chat_id, "hard_level", "chaos", "group")

    updated = bot.get_chat_settings_sync(chat_id, "group")
    assert updated["hard_mode_enabled"] is False
    assert updated["hard_level"] == "chaos"
    assert (
        updated["reaction_chance"]
        == bot.DEFAULT_CHAT_SETTINGS["reaction_chance"]
    )


def test_chat_settings_persist_across_simulated_restart(tmp_path, monkeypatch):
    db_path = tmp_path / "restart_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 777
    bot.update_chat_setting_sync(chat_id, "hard_mode_enabled", False, "group")

    # Новое соединение к тому же файлу — как после рестарта Railway.
    reloaded = bot.get_chat_settings_sync(chat_id, "group")
    assert reloaded["hard_mode_enabled"] is False


def test_update_chat_setting_rejects_unknown_column(tmp_path, monkeypatch):
    db_path = tmp_path / "reject_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    try:
        bot.update_chat_setting_sync(1, "not_a_real_setting", "x")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown chat setting")


def test_make_safe_filename_differs_across_chats_with_same_message_id():
    name_a = bot.make_safe_filename("report.pdf", message_id=42, chat_id=1)
    name_b = bot.make_safe_filename("report.pdf", message_id=42, chat_id=2)
    assert name_a != name_b


def test_make_safe_filename_differs_on_repeated_calls():
    first = bot.make_safe_filename("report.pdf", message_id=42, chat_id=1)
    second = bot.make_safe_filename("report.pdf", message_id=42, chat_id=1)
    assert first != second


def test_cleanup_in_memory_state_removes_stale_keys_only():
    bot.REQUEST_TIMES.clear()
    bot.LAST_LIMIT_WARNING.clear()

    stale_key = (111, "general")
    fresh_key = (222, "general")

    bot.REQUEST_TIMES[stale_key].append(time.monotonic() - 999_999)
    bot.REQUEST_TIMES[fresh_key].append(time.monotonic())

    bot.LAST_LIMIT_WARNING[stale_key] = time.monotonic() - 999_999
    bot.LAST_LIMIT_WARNING[fresh_key] = time.monotonic()

    removed = bot.cleanup_in_memory_state(max_age_seconds=10)

    assert stale_key not in bot.REQUEST_TIMES
    assert fresh_key in bot.REQUEST_TIMES
    assert stale_key not in bot.LAST_LIMIT_WARNING
    assert fresh_key in bot.LAST_LIMIT_WARNING
    assert removed["request_time_keys"] == 1
    assert removed["warning_keys"] == 1


def test_cleanup_in_memory_state_removes_empty_group_memory_ids():
    bot.GROUP_MEMORY.clear()

    old_chat_id = 9001
    bot.GROUP_MEMORY[old_chat_id].append(
        (time.monotonic() - 999_999, "user", "Тест", "старое сообщение")
    )

    removed = bot.cleanup_in_memory_state(max_age_seconds=10)

    assert old_chat_id not in bot.GROUP_MEMORY
    assert removed["memory_ids"] >= 1
