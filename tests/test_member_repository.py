from datetime import datetime, timedelta, timezone

import bot
import member_profile_runtime as member_runtime
import member_repository


MSK = timezone(timedelta(hours=3))


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "member-repository.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    member_runtime._initialize_tables(bot)
    return db_path


def test_repository_filters_members_and_preserves_daily_title_fields(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 19, 19, 0, tzinfo=MSK),
    )

    chat_id = -1009001
    active_id = 101
    left_id = 102
    bot_id = 103

    member_runtime._upsert_member_sync(
        bot,
        chat_id,
        active_id,
        "Серёга",
        "serega",
        is_active=True,
        is_bot=False,
        chat_type="group",
    )
    member_runtime._upsert_member_sync(
        bot,
        chat_id,
        left_id,
        "Ушедший",
        "left_user",
        is_active=False,
        is_bot=False,
        chat_type="group",
    )
    member_runtime._upsert_member_sync(
        bot,
        chat_id,
        bot_id,
        "Служебный бот",
        "helper_bot",
        is_active=True,
        is_bot=True,
        chat_type="group",
    )

    with bot.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE chat_member_profiles
            SET total_messages = 77,
                current_title = 'Кемпер подъезда'
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, active_id),
        )
        connection.executemany(
            """
            INSERT INTO chat_activity_daily(chat_id, user_id, date, messages)
            VALUES (?, ?, ?, ?)
            """,
            (
                (chat_id, active_id, "2026-08-14", 2),
                (chat_id, active_id, "2026-08-18", 3),
                (chat_id, active_id, "2026-08-19", 4),
                # Outside the seven-day title window and must not be counted.
                (chat_id, active_id, "2026-08-10", 50),
                # Inactive/bot rows must not make them title candidates.
                (chat_id, left_id, "2026-08-19", 10),
                (chat_id, bot_id, "2026-08-19", 10),
            ),
        )
        connection.commit()

    assert member_repository.known_active_group_chat_ids(bot) == [chat_id]
    assert member_repository.known_content_group_chat_ids(bot) == [chat_id]

    candidates = member_repository.daily_title_candidates(
        bot,
        chat_id,
        "2026-08-19",
    )
    assert candidates == [
        {
            "user_id": active_id,
            "display_name": "Серёга",
            "total_messages": 77,
            "previous_title": "Кемпер подъезда",
            "week_messages": 9,
        }
    ]

    assert member_repository.display_name(bot, chat_id, active_id) == "Серёга"


def test_daily_content_chat_discovery_falls_back_to_chats_table(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    group_id = -1009101
    supergroup_id = -1009102
    private_id = 9103

    with bot.get_db_connection() as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO chats(chat_id, chat_type) VALUES (?, ?)",
            (
                (group_id, "group"),
                (supergroup_id, "supergroup"),
                (private_id, "private"),
            ),
        )
        # Simulate an older/partially initialized DB where the registry is not
        # available. Daily content historically falls back to chats in this case.
        connection.execute("DROP TABLE chat_membership_registry")
        connection.commit()

    # SQL uses ORDER BY chat_id ASC; Telegram group IDs are negative, so the
    # numerically smaller (more negative) ID appears first.
    assert member_repository.known_content_group_chat_ids(bot) == sorted(
        [group_id, supergroup_id]
    )


def test_display_name_has_stable_fallback_for_unknown_member(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    assert member_repository.display_name(bot, -1009999, 4242) == "участник 4242"
