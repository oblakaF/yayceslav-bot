from datetime import datetime, timedelta, timezone

from telegram.ext import Application, ChatMemberHandler, CommandHandler, MessageHandler

import bot
import member_profile_runtime as memory
import monthly_memory_scope_patch as monthly_memory


MSK = timezone(timedelta(hours=3))


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "member-memory.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    memory._initialize_tables(bot)
    monthly_memory._profile_init_monthly(bot)
    return db_path


def test_monthly_runtime_creates_only_live_word_count_table(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    with bot.get_db_connection() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "member_word_counts_monthly" in names
    assert "member_word_counts" not in names


def test_personal_callback_memory_rotates_per_user(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    memory._upsert_member_sync(bot, -1001, 101, "Серёга", "serega")

    memory._record_member_terms_sync(bot, -1001, 101, "steam")
    memory._record_member_terms_sync(bot, -1001, 101, "steam")

    profile = memory._load_member_memory_sync(bot, -1001, 101)
    assert "steam" in profile["callback_terms"]

    memory.reserve_callback_term(-1001, 101, "steam")
    rotated = memory._load_member_memory_sync(bot, -1001, 101)
    assert "steam" not in rotated["callback_terms"]


def test_favorite_word_is_calendar_month_and_per_user(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 19, 19, 0, tzinfo=MSK),
    )

    monthly_memory._record_words_monthly(bot, -1001, 101, "steam steam steam")
    monthly_memory._record_words_monthly(bot, -1001, 102, "гараж гараж")

    assert monthly_memory._favorite_word_monthly(bot, -1001, 101) == ("steam", 3)
    assert monthly_memory._favorite_word_monthly(bot, -1001, 102) == ("гараж", 2)


def test_monthly_themes_require_recurring_evidence_and_rank_by_count(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 19, 19, 0, tzinfo=MSK),
    )

    chat_id = -1003
    user_id = 103
    memory._upsert_member_sync(bot, chat_id, user_id, "Тематик", "themes")
    with bot.get_db_connection() as connection:
        connection.executemany(
            """
            INSERT INTO member_callback_terms
                (chat_id, user_id, term, occurrences, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (chat_id, user_id, "steam", 5, "2026-08-02", "2026-08-18"),
                (chat_id, user_id, "гараж машина", 2, "2026-08-03", "2026-08-19"),
                # One-word topic with only two mentions is deliberately weak.
                (chat_id, user_id, "милфы", 2, "2026-08-04", "2026-08-19"),
                # One-off noise cannot become a dossier theme just for recency.
                (chat_id, user_id, "новинка", 1, "2026-08-19", "2026-08-19"),
            ),
        )
        connection.commit()

    assert monthly_memory._themes_monthly(bot, chat_id, user_id) == [
        "steam",
        "гараж машина",
    ]


def test_sensitive_topics_are_not_auto_stored(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    memory._upsert_member_sync(bot, -1002, 102, "Вася", "vasya")
    memory._record_member_terms_sync(bot, -1002, 102, "зарплата банк кредит")
    profile = memory._load_member_memory_sync(bot, -1002, 102)
    assert not profile["callback_terms"]


def test_silent_candidates_include_week_silent_and_never_spoke(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 19, 19, 0, tzinfo=MSK),
    )

    chat_id = -2001
    memory._upsert_member_sync(bot, chat_id, 201, "Активный", "active")
    memory._upsert_member_sync(bot, chat_id, 202, "Молчун", "silent")
    memory._upsert_member_sync(bot, chat_id, 203, "Никогда", "never")

    with bot.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE chat_member_profiles
            SET total_messages = 20
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, 202),
        )
        connection.execute(
            """
            INSERT INTO chat_activity_daily (chat_id, user_id, date, messages)
            VALUES (?, ?, ?, 3)
            """,
            (chat_id, 201, "2026-08-19"),
        )
        connection.commit()

    candidates = memory._silent_candidate_rows_sync(
        bot, chat_id, "2026-08-19"
    )
    by_id = {item["user_id"]: item for item in candidates}

    assert 201 not in by_id
    assert by_id[202]["total_messages"] == 20
    assert by_id[203]["total_messages"] == 0


def test_silent_title_is_one_per_chat_per_day(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -3001
    memory._upsert_member_sync(bot, chat_id, 301, "Молчун", "silent")

    assert memory._save_silent_assignment_sync(
        bot, chat_id, "2026-08-19", 301, "Куколд-наблюдатель", "silent_week"
    )
    assert not memory._save_silent_assignment_sync(
        bot, chat_id, "2026-08-19", 301, "NPC в режиме AFK", "silent_week"
    )

    saved = memory._silent_assignment_sync(bot, chat_id, "2026-08-19")
    assert saved["title"] == "Куколд-наблюдатель"


def test_prepare_application_registers_member_observers_once(monkeypatch):
    fake_bot_module = object()
    calls = []
    monkeypatch.setattr(memory, "_find_bot_module", lambda: fake_bot_module)
    monkeypatch.setattr(memory, "_initialize_tables", lambda bot: calls.append(("init", bot)))
    monkeypatch.setattr(memory, "_augment_profile_functions", lambda bot: calls.append(("augment", bot)))
    monkeypatch.setattr(memory, "_patch_daily_title_scheduler", lambda bot: calls.append(("scheduler", bot)))

    application = Application.builder().token("123456:TESTTOKEN").build()
    memory._PREPARED_APPLICATION_IDS.discard(id(application))
    memory._prepare_application(application)
    memory._prepare_application(application)

    assert calls == [
        ("init", fake_bot_module),
        ("augment", fake_bot_module),
        ("scheduler", fake_bot_module),
    ]

    whoami_handlers = application.handlers.get(-10, ())
    assert len(whoami_handlers) == 1
    assert isinstance(whoami_handlers[0], CommandHandler)
    assert whoami_handlers[0].callback is memory._whoami_v2

    membership_handlers = application.handlers.get(-9, ())
    assert len(membership_handlers) == 2
    assert any(
        isinstance(handler, ChatMemberHandler) and handler.callback is memory._observe_chat_member
        for handler in membership_handlers
    )
    assert any(
        isinstance(handler, MessageHandler) and handler.callback is memory._observe_service_members
        for handler in membership_handlers
    )

    text_handlers = application.handlers.get(5, ())
    assert len(text_handlers) == 1
    assert isinstance(text_handlers[0], MessageHandler)
    assert text_handlers[0].callback is memory._observe_text
