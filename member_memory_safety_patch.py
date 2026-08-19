from __future__ import annotations

import logging

import member_profile_runtime as runtime


_ORIGINAL_INITIALIZE_TABLES = runtime._initialize_tables
_PATCHED = False


def _purge_unsafe_backfill(bot_module) -> int:
    """Apply the same safety gate to legacy chat-native rows as to new messages."""
    removed = 0
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT chat_id, user_id, term
            FROM member_callback_terms
            """
        ).fetchall()
        unsafe = [
            (int(chat_id), int(user_id), str(term))
            for chat_id, user_id, term in rows
            if not runtime._safe_callback_term(str(term))
        ]
        if unsafe:
            connection.executemany(
                """
                DELETE FROM member_callback_terms
                WHERE chat_id = ? AND user_id = ? AND term = ?
                """,
                unsafe,
            )
            connection.commit()
            removed = len(unsafe)
    return removed


def _safe_initialize_tables(bot_module) -> None:
    _ORIGINAL_INITIALIZE_TABLES(bot_module)
    try:
        removed = _purge_unsafe_backfill(bot_module)
        if removed:
            logging.info("Member memory safety purge removed %s legacy terms", removed)
    except Exception as error:
        logging.warning("Member memory safety purge failed: %s", error)


def install() -> None:
    global _PATCHED
    if _PATCHED:
        return
    runtime._initialize_tables = _safe_initialize_tables
    _PATCHED = True


install()
