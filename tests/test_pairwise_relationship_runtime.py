import asyncio
import sqlite3
from types import SimpleNamespace

from telegram.ext import Application, MessageHandler

import pairwise_relationship_runtime as pairwise


def _db_bot(tmp_path):
    path = tmp_path / "pairwise.db"

    def get_db_connection():
        return sqlite3.connect(path)

    return SimpleNamespace(get_db_connection=get_db_connection)


def _update(
    text,
    replier_id=20,
    replied_to_id=30,
    reply_is_bot=False,
    chat_id=-100,
    chat_type="group",
):
    reply_message = None
    if replied_to_id is not None:
        reply_message = SimpleNamespace(
            from_user=SimpleNamespace(id=replied_to_id, is_bot=reply_is_bot)
        )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=replier_id, is_bot=False),
        effective_message=SimpleNamespace(text=text, reply_to_message=reply_message),
    )


def test_reply_between_two_members_is_recorded(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(pairwise._observe_pairwise(_update("привет"), None))
    state = pairwise._pair_state_sync(bot, -100, 20, 30)
    assert state == {"reply_count": 1, "hostile_count": 0, "positive_count": 0}


def test_a_to_b_and_b_to_a_normalize_to_same_row(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(
        pairwise._observe_pairwise(
            _update("привет", replier_id=20, replied_to_id=30), None
        )
    )
    asyncio.run(
        pairwise._observe_pairwise(
            _update("привет", replier_id=30, replied_to_id=20), None
        )
    )
    assert pairwise._pair_state_sync(bot, -100, 20, 30)["reply_count"] == 2
    assert pairwise._pair_state_sync(bot, -100, 30, 20)["reply_count"] == 2


def test_hostile_reply_increments_hostile_count(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(pairwise._observe_pairwise(_update("ты мудак"), None))
    state = pairwise._pair_state_sync(bot, -100, 20, 30)
    assert state == {"reply_count": 1, "hostile_count": 1, "positive_count": 0}


def test_positive_reply_increments_positive_count(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(pairwise._observe_pairwise(_update("спасибо большое"), None))
    state = pairwise._pair_state_sync(bot, -100, 20, 30)
    assert state == {"reply_count": 1, "hostile_count": 0, "positive_count": 1}


def test_self_reply_is_ignored(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(
        pairwise._observe_pairwise(
            _update("привет", replier_id=20, replied_to_id=20), None
        )
    )
    assert pairwise._pair_state_sync(bot, -100, 20, 20)["reply_count"] == 0


def test_reply_to_bot_is_ignored(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(
        pairwise._observe_pairwise(
            _update("привет", replier_id=20, replied_to_id=999, reply_is_bot=True), None
        )
    )
    assert pairwise._pair_state_sync(bot, -100, 20, 999)["reply_count"] == 0


def test_non_reply_message_is_ignored(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(pairwise._observe_pairwise(_update("привет всем", replied_to_id=None), None))
    with bot.get_db_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM member_pair_interactions"
        ).fetchone()[0]
    assert count == 0


def test_private_chat_is_ignored(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    asyncio.run(pairwise._observe_pairwise(_update("привет", chat_type="private"), None))
    with bot.get_db_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM member_pair_interactions"
        ).fetchone()[0]
    assert count == 0


def test_ttl_sweep_removes_stale_pairs(tmp_path):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)

    pairwise._record_pair_interaction_sync(bot, -100, 1, 2, hostile=False, positive=False)
    with bot.get_db_connection() as connection:
        connection.execute(
            "UPDATE member_pair_interactions SET last_interaction_at = datetime('now', ?)",
            (f"-{pairwise.PAIR_INTERACTION_TTL_DAYS + 1} days",),
        )
        connection.commit()

    pairwise._record_pair_interaction_sync(bot, -100, 3, 4, hostile=False, positive=False)
    with bot.get_db_connection() as connection:
        pairs = connection.execute(
            "SELECT user_a_id, user_b_id FROM member_pair_interactions"
        ).fetchall()
    assert pairs == [(3, 4)]


def test_cap_sweep_keeps_only_most_recent_pairs(tmp_path):
    bot = _db_bot(tmp_path)
    pairwise._initialize_table(bot)

    total = pairwise.MAX_PAIR_ROWS_PER_CHAT + 3
    for i in range(total):
        pairwise._record_pair_interaction_sync(bot, -100, i, i + 1000, hostile=False, positive=False)

    with bot.get_db_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM member_pair_interactions WHERE chat_id = -100"
        ).fetchone()[0]
    assert count == pairwise.MAX_PAIR_ROWS_PER_CHAT


def test_prepare_registers_group13_once(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    monkeypatch.setattr(pairwise, "_find_bot_module", lambda: bot)

    application = Application.builder().token("123456:TESTTOKEN").build()
    pairwise._PREPARED_APPLICATION_IDS.discard(id(application))
    pairwise._prepare_application(application)
    pairwise._prepare_application(application)

    handlers = application.handlers.get(13, ())
    assert len(handlers) == 1
    assert isinstance(handlers[0], MessageHandler)
    assert handlers[0].callback is pairwise._observe_pairwise
