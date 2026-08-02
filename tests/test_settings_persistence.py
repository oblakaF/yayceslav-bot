import bot


def test_user_settings_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "test_stats.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    user_id = 987654321

    defaults = bot.get_user_settings_sync(user_id)
    assert defaults == bot.DEFAULT_USER_SETTINGS

    bot.update_user_setting_sync(user_id, "roughness", "high")
    bot.update_user_setting_sync(user_id, "voice_enabled", True)

    updated = bot.get_user_settings_sync(user_id)
    assert updated["roughness"] == "high"
    assert updated["voice_enabled"] is True
    assert updated["character"] == bot.DEFAULT_USER_SETTINGS["character"]


def test_update_user_setting_rejects_unknown_column(tmp_path, monkeypatch):
    db_path = tmp_path / "test_stats.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    try:
        bot.update_user_setting_sync(1, "not_a_real_setting", "x")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown setting name")


def test_voice_mode_currently_lives_only_in_memory_known_gap():
    """Documents the known bug (roadmap Phase 5): /voice_on and /voice_off
    write to context.user_data, not to the SQLite voice_enabled column, so
    it does not survive a restart. This test locks in today's behaviour so
    the Phase 5 fix has something concrete to flip."""

    class FakeContext:
        def __init__(self):
            self.user_data = {}

    context = FakeContext()
    assert bot.voice_mode_enabled(context) is False
    context.user_data["voice_mode"] = True
    assert bot.voice_mode_enabled(context) is True
