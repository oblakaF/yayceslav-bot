"""Lazily decays lifetime reputation back toward neutral when it's read.

There is no daily sweep job: `member_reputation` rows are only ever
touched when someone is active, so decay is applied on-read (wrapping
`reputation_runtime._state_sync`) instead of scanning the whole table on
a schedule that would cost CPU/IO on Railway's free tier for rows nobody
is currently looking at.
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime

import reputation_decay_engine
import reputation_engine


def _row_sync(bot_module, chat_id: int, user_id: int):
    with bot_module.get_db_connection() as connection:
        return connection.execute(
            "SELECT score, updated_at FROM member_reputation WHERE chat_id = ? AND user_id = ?",
            (int(chat_id), int(user_id)),
        ).fetchone()


def _current_time(bot_module) -> datetime:
    current = getattr(bot_module, "current_msk_datetime", None)
    if callable(current):
        return current()
    return datetime.utcnow()


def _apply_decay_sync(bot_module, chat_id: int, user_id: int) -> None:
    row = _row_sync(bot_module, chat_id, user_id)
    if row is None:
        return
    score, updated_at = row
    decayed = reputation_decay_engine.decayed_score(
        int(score or 0), updated_at, _current_time(bot_module)
    )
    if decayed == int(score or 0):
        return

    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            UPDATE member_reputation
            SET score = ?, last_delta = ?, last_reason = 'reputation_decay',
                updated_at = datetime('now')
            WHERE chat_id = ? AND user_id = ?
            """,
            (
                reputation_engine.clamp_score(decayed),
                decayed - int(score or 0),
                int(chat_id),
                int(user_id),
            ),
        )
        connection.commit()


def _patch_state_sync(reputation_runtime_module) -> None:
    if getattr(reputation_runtime_module, "_yayceslav_reputation_decay_patch", False):
        return
    original = reputation_runtime_module._state_sync

    @functools.wraps(original)
    def wrapped(bot_module, chat_id, user_id):
        try:
            _apply_decay_sync(bot_module, chat_id, user_id)
        except Exception:
            logging.exception(
                "Reputation decay: failed to apply for chat=%s user=%s", chat_id, user_id
            )
        return original(bot_module, chat_id, user_id)

    reputation_runtime_module._state_sync = wrapped
    reputation_runtime_module._yayceslav_reputation_decay_patch = True


def _prepare() -> None:
    import reputation_runtime

    _patch_state_sync(reputation_runtime)
