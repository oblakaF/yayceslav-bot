import bot
import dialogue_followup_mode_patch as followup
import member_memory_safety_patch as safety
import member_profile_runtime as memory


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "memory-safety.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    memory._initialize_tables(bot)
    return db_path


def test_legacy_sensitive_term_is_purged(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    memory._upsert_member_sync(bot, -1001, 101, "Серёга", "serega")

    with bot.get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO member_callback_terms
                (chat_id, user_id, term, occurrences)
            VALUES (?, ?, ?, ?)
            """,
            (-1001, 101, "кредит банка", 3),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO member_callback_terms
                (chat_id, user_id, term, occurrences)
            VALUES (?, ?, ?, ?)
            """,
            (-1001, 101, "steam", 2),
        )
        connection.commit()

    assert safety._purge_unsafe_backfill(bot) == 1
    profile = memory._load_member_memory_sync(bot, -1001, 101)
    assert "кредит банка" not in profile["callback_terms"]
    assert "steam" in profile["callback_terms"]


def test_short_ping_pong_phrases_are_recognized_as_banter_followups():
    assert followup._BANTER_FOLLOWUP_RE.match("нет ты")
    assert followup._BANTER_FOLLOWUP_RE.match("Нет ты.")
    assert followup._BANTER_FOLLOWUP_RE.match("сам такой")
    assert followup._BANTER_FOLLOWUP_RE.match("ты сам")
    assert not followup._BANTER_FOLLOWUP_RE.match("да")
    assert not followup._BANTER_FOLLOWUP_RE.match("что такое интеграл?")
