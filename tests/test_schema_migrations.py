import sqlite3

import bot
import schema_migrations as migrations


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "migrations.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    return db_path


def test_migrations_are_non_destructive_and_idempotent(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)

    with bot.get_db_connection() as connection:
        before = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert migrations.run_pending(bot) == (1, 2)
    assert migrations.run_pending(bot) == ()

    with bot.get_db_connection() as connection:
        after = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        applied = migrations.applied_versions(connection)

    assert before <= after
    assert {
        "schema_migrations",
        "chat_self_canon",
        "chat_self_canon_history",
    } <= after
    assert applied == {
        1: "baseline_v2_existing_schema",
        2: "chat_local_self_canon",
    }


def test_migration_name_mismatch_fails_closed(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    migrations.run_pending(bot)

    with bot.get_db_connection() as connection:
        connection.execute(
            "UPDATE schema_migrations SET name = 'wrong-name' WHERE version = 1"
        )
        connection.commit()

    try:
        migrations.run_pending(bot)
    except RuntimeError as error:
        assert "version/name mismatch" in str(error)
    else:
        raise AssertionError("migration name mismatch must fail closed")


def test_failed_future_migration_rolls_back_version_and_schema(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)

    def failing(connection):
        connection.execute("CREATE TABLE should_rollback(value INTEGER)")
        raise RuntimeError("boom")

    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        (
            migrations.Migration(1, "baseline_v2_existing_schema", migrations._baseline_v2),
            migrations.Migration(2, "chat_local_self_canon", migrations._chat_self_canon_v2),
            migrations.Migration(3, "failing_test_migration", failing),
        ),
    )

    try:
        migrations.run_pending(bot)
    except RuntimeError as error:
        assert str(error) == "boom"
    else:
        raise AssertionError("failing migration must propagate")

    with sqlite3.connect(bot.STATS_DB_PATH) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        applied = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert "should_rollback" not in tables
    assert "chat_self_canon" not in tables
    assert applied == []
