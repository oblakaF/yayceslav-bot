import asyncio
import sqlite3
from types import SimpleNamespace

import episodic_memory_runtime as episodic


def _db_bot(tmp_path):
    path = tmp_path / "episodic.db"

    def get_db_connection():
        return sqlite3.connect(path)

    async def get_member_profile(chat_id, user_id):
        return {"user_id": user_id}

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        get_member_profile_sync=lambda chat_id, user_id: {"user_id": user_id},
        get_member_profile=get_member_profile,
        detect_conversation_mode=lambda text: "hostile" if "нахуй" in str(text) else "normal",
    )


def _update(text: str):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, type="group"),
        effective_user=SimpleNamespace(id=20, is_bot=False),
        effective_message=SimpleNamespace(text=text, reply_to_message=None),
    )


def _context():
    return SimpleNamespace(bot=SimpleNamespace(id=999, username="yayceslav_bot"))


def test_record_and_load_note(tmp_path):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)

    episodic._record_episodic_note_sync(bot, -100, 20, "долбоёб яйцеслав", -8, "negative")
    notes = episodic._load_episodic_notes_sync(bot, -100, 20)
    assert notes == ["долбоёб яйцеслав"]


def test_excerpt_is_truncated(tmp_path):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)

    long_text = "а" * 300
    episodic._record_episodic_note_sync(bot, -100, 20, long_text, 9, "positive")
    notes = episodic._load_episodic_notes_sync(bot, -100, 20)
    assert len(notes[0]) == episodic.EPISODIC_EXCERPT_MAX_CHARS


def test_ttl_sweep_deletes_old_notes(tmp_path):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)

    episodic._record_episodic_note_sync(bot, -100, 20, "старая запись", -9, "negative")
    with bot.get_db_connection() as connection:
        connection.execute(
            "UPDATE member_episodic_notes SET created_at = datetime('now', ?)",
            (f"-{episodic.EPISODIC_NOTE_TTL_DAYS + 1} days",),
        )
        connection.commit()

    episodic._record_episodic_note_sync(bot, -100, 20, "новая запись", 9, "positive")
    notes = episodic._load_episodic_notes_sync(bot, -100, 20, limit=10)
    assert notes == ["новая запись"]


def test_cap_sweep_keeps_only_most_recent(tmp_path):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)

    total = episodic.MAX_EPISODIC_NOTES_PER_MEMBER + 3
    for i in range(total):
        episodic._record_episodic_note_sync(bot, -100, 20, f"note {i}", 9, "positive")

    with bot.get_db_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM member_episodic_notes WHERE chat_id = -100 AND user_id = 20"
        ).fetchone()[0]
    assert count == episodic.MAX_EPISODIC_NOTES_PER_MEMBER

    notes = episodic._load_episodic_notes_sync(bot, -100, 20, limit=1)
    assert notes == [f"note {total - 1}"]


def test_observer_ignores_small_delta(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)
    monkeypatch.setattr(episodic, "_find_bot_module", lambda: bot)

    asyncio.run(episodic._observe_episodic(_update("яйцеслав спс"), _context()))
    assert episodic._load_episodic_notes_sync(bot, -100, 20) == []


def test_observer_records_notable_negative_moment(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)
    monkeypatch.setattr(episodic, "_find_bot_module", lambda: bot)

    asyncio.run(episodic._observe_episodic(_update("яйцеслав ты долбоёб"), _context()))
    notes = episodic._load_episodic_notes_sync(bot, -100, 20)
    assert notes == ["яйцеслав ты долбоёб"]


def test_observer_ignores_undirected_hostility(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)
    monkeypatch.setattr(episodic, "_find_bot_module", lambda: bot)

    asyncio.run(episodic._observe_episodic(_update("он долбоёб"), _context()))
    assert episodic._load_episodic_notes_sync(bot, -100, 20) == []


def test_profile_enrichment_adds_episodic_notes_sync(tmp_path):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)
    episodic._record_episodic_note_sync(bot, -100, 20, "яйцеслав ты долбоёб", -8, "negative")

    episodic._augment_profile_functions(bot)
    profile = bot.get_member_profile_sync(-100, 20)
    assert profile["episodic_notes"] == ["яйцеслав ты долбоёб"]


def test_profile_enrichment_adds_episodic_notes_async(tmp_path):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)
    episodic._record_episodic_note_sync(bot, -100, 20, "яйцеслав ты долбоёб", -8, "negative")

    episodic._augment_profile_functions(bot)
    profile = asyncio.run(bot.get_member_profile(-100, 20))
    assert profile["episodic_notes"] == ["яйцеслав ты долбоёб"]


def test_augment_profile_functions_is_idempotent(tmp_path):
    bot = _db_bot(tmp_path)
    episodic._initialize_table(bot)

    episodic._augment_profile_functions(bot)
    wrapped_once = bot.get_member_profile_sync
    episodic._augment_profile_functions(bot)
    assert bot.get_member_profile_sync is wrapped_once
