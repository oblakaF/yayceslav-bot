"""Read-only member repository for the current transitional V2 schema.

The bot still has two membership/profile tables. This module centralizes the
JOIN contract so feature modules do not each embed knowledge of both schemas.
It intentionally performs no writes and no migrations.
"""

from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Any


def known_active_group_chat_ids(bot_module) -> list[int]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT r.chat_id
            FROM chat_membership_registry AS r
            JOIN chats AS c ON c.chat_id = r.chat_id
            WHERE r.is_active = 1
              AND r.is_bot = 0
              AND c.chat_type IN ('group', 'supergroup', 'ChatType.GROUP', 'ChatType.SUPERGROUP')
            ORDER BY r.chat_id
            """
        ).fetchall()
    return [int(row[0]) for row in rows]


def known_content_group_chat_ids(bot_module) -> list[int]:
    """Preserve daily-content discovery including its legacy chats fallback.

    Current production databases normally have chat_membership_registry. Older
    or partially initialized databases may not, so daily content historically
    falls back to the chats table. Keep that behavior centralized here.
    """
    with bot_module.get_db_connection() as connection:
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT chat_id
                FROM chat_membership_registry
                WHERE is_active = 1 AND is_bot = 0
                ORDER BY chat_id
                """
            ).fetchall()
        except Exception:
            rows = connection.execute(
                """
                SELECT DISTINCT chat_id
                FROM chats
                WHERE chat_type IN ('group', 'supergroup')
                ORDER BY chat_id
                """
            ).fetchall()
    return [int(row[0]) for row in rows]


def display_name(bot_module, chat_id: int, user_id: int) -> str:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(NULLIF(r.display_name, ''), p.current_display_name, '')
            FROM chat_membership_registry AS r
            LEFT JOIN chat_member_profiles AS p
              ON p.chat_id = r.chat_id AND p.user_id = r.user_id
            WHERE r.chat_id = ? AND r.user_id = ?
            """,
            (chat_id, user_id),
        ).fetchone()
    return str((row[0] if row else None) or f"участник {user_id}")


def daily_title_candidates(
    bot_module,
    chat_id: int,
    current_date: str,
) -> list[dict[str, Any]]:
    """All active human members plus 7-day activity needed by daily titles."""
    end = date_type.fromisoformat(current_date)
    start_date = (end - timedelta(days=6)).isoformat()

    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                r.user_id,
                COALESCE(NULLIF(r.display_name, ''), p.current_display_name, ''),
                COALESCE(p.total_messages, 0),
                p.current_title,
                COALESCE(SUM(a.messages), 0) AS week_messages
            FROM chat_membership_registry AS r
            LEFT JOIN chat_member_profiles AS p
              ON p.chat_id = r.chat_id AND p.user_id = r.user_id
            LEFT JOIN chat_activity_daily AS a
              ON a.chat_id = r.chat_id
             AND a.user_id = r.user_id
             AND a.date BETWEEN ? AND ?
            WHERE r.chat_id = ?
              AND r.is_active = 1
              AND r.is_bot = 0
            GROUP BY r.user_id, r.display_name, p.current_display_name,
                     p.total_messages, p.current_title
            ORDER BY r.user_id
            """,
            (start_date, current_date, chat_id),
        ).fetchall()

    return [
        {
            "user_id": int(row[0]),
            "display_name": str(row[1] or f"участник {row[0]}"),
            "total_messages": int(row[2] or 0),
            "previous_title": (str(row[3]) if row[3] else None),
            "week_messages": int(row[4] or 0),
        }
        for row in rows
    ]
