import bot


def test_very_long_message_reason():
    long_text = "а" * 600
    assert bot.detect_reaction_reason(long_text) == "very_long_message"


def test_one_word_reply_reason():
    assert bot.detect_reaction_reason("ясно") == "one_word_reply"


def test_all_caps_reason():
    assert bot.detect_reaction_reason("ЭТО ПРОСТО ОГОНЬ ТЕМА") == "all_caps"


def test_many_question_marks_reason():
    assert bot.detect_reaction_reason("ты вообще о чём???") == "many_question_marks"


def test_repeated_message_reason():
    reason = bot.detect_reaction_reason(
        "давайте закажем пиццу сегодня вечером",
        previous_group_text="давайте закажем пиццу сегодня вечером!",
    )
    assert reason == "repeated_message"


def test_good_question_reason():
    reason = bot.detect_reaction_reason(
        "как лучше организовать резервное копирование базы данных?"
    )
    assert reason == "good_question"


def test_no_reason_for_plain_statement():
    assert bot.detect_reaction_reason("сегодня обычный день") is None


def test_pick_reaction_emoji_matches_reason_pool():
    emoji = bot.pick_reaction_emoji("good_joke")
    assert emoji in bot.REACTION_REASON_EMOJIS["good_joke"]


def test_pick_reaction_emoji_falls_back_to_general_pool():
    emoji = bot.pick_reaction_emoji(None)
    assert emoji in bot.HARD_REACTION_EMOJIS


def test_hard_level_chances_cover_calm_normal_chaos():
    assert set(bot.HARD_LEVEL_CHANCES.keys()) == {"calm", "normal", "chaos"}
    assert (
        bot.HARD_LEVEL_CHANCES["calm"]["reaction_chance"]
        < bot.HARD_LEVEL_CHANCES["normal"]["reaction_chance"]
        < bot.HARD_LEVEL_CHANCES["chaos"]["reaction_chance"]
    )


def test_increment_chat_hard_stat_updates_counter_and_timestamp(tmp_path, monkeypatch):
    db_path = tmp_path / "hard_stats_test.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    chat_id = 4242

    bot.increment_chat_hard_stat_sync(chat_id, "reactions_count", "group")
    bot.increment_chat_hard_stat_sync(chat_id, "reactions_count", "group")
    bot.increment_chat_hard_stat_sync(chat_id, "trigger_replies_count", "group")

    settings = bot.get_chat_settings_sync(chat_id, "group")

    assert settings["reactions_count"] == 2
    assert settings["trigger_replies_count"] == 1
    assert settings["random_replies_count"] == 0
    assert settings["last_intervention_at"] is not None


def test_increment_chat_hard_stat_rejects_unknown_counter(tmp_path, monkeypatch):
    db_path = tmp_path / "hard_stats_reject.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()

    try:
        bot.increment_chat_hard_stat_sync(1, "not_a_real_counter")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown counter")
