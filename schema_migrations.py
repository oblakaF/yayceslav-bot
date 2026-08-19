"""Versioned, transactional SQLite schema migrations for Yayceslav V2.

The migration registry starts with a NO-OP baseline. Existing production tables
are not renamed, dropped or rewritten by this module. Future consolidation must
be expressed as explicit numbered migrations and covered by migration tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


MigrationFn = Callable[[object], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFn


def _baseline_v2(_connection) -> None:
    """Take the existing V2 schema under version control without changing it."""
    return None


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline_v2_existing_schema", _baseline_v2),
)


def _validate_registry() -> None:
    versions = [migration.version for migration in MIGRATIONS]
    if versions != sorted(versions):
        raise RuntimeError("Schema migrations must be ordered by version")
    if len(versions) != len(set(versions)):
        raise RuntimeError("Duplicate schema migration version")
    if versions and versions[0] != 1:
        raise RuntimeError("Schema migrations must start at version 1")
    for expected, actual in enumerate(versions, start=1):
        if expected != actual:
            raise RuntimeError(
                f"Schema migration gap: expected version {expected}, got {actual}"
            )


def _ensure_registry_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def applied_versions(connection) -> dict[int, str]:
    _ensure_registry_table(connection)
    rows = connection.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {int(version): str(name) for version, name in rows}


def run_pending(bot_module) -> tuple[int, ...]:
    """Apply all pending migrations in one transaction.

    The bot's shared get_db_connection() factory supplies WAL/foreign_keys and
    rollback-on-exception semantics. No migration may call commit() itself.
    """
    _validate_registry()
    applied_now: list[int] = []

    with bot_module.get_db_connection() as connection:
        _ensure_registry_table(connection)
        existing = applied_versions(connection)

        for migration in MIGRATIONS:
            if migration.version in existing:
                if existing[migration.version] != migration.name:
                    raise RuntimeError(
                        "Migration version/name mismatch: "
                        f"v{migration.version} DB={existing[migration.version]!r} "
                        f"code={migration.name!r}"
                    )
                continue

            migration.apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            applied_now.append(migration.version)

    return tuple(applied_now)
