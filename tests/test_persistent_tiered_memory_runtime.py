import asyncio
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace

import chat_digest_runtime
import episodic_memory_runtime
import persistent_tiered_memory_runtime as memory


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def _module(tmp_path: Path):
    db_path = tmp_path / "memory.db"
    group_memory = defaultdict(deque)
    private_memory = defaultdict(deque)

    def get_db_connection():
        return sqlite3.connect(db_path, factory=ClosingConnection)

    def remember_message(store, memory_id, role, text, ttl, cap, author=None):
        store[int(memory_id)].append((role, text, author))
        while len(store[int(memory_id)]) > int(cap):
            store[int(memory_id)].popleft()

    async def ask_gemini(contents, *args, **kwargs):
        return {"contents": contents, "kwargs": kwargs}

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        GROUP_MEMORY=group_memory,
        PRIVATE_MEMORY=private_memory,
        GROUP_MEMORY_SECONDS=900,
        PRIVATE_MEMORY_SECONDS=900,
        GROUP_MEMORY_MAX_MESSAGES=30,
        PRIVATE_MEMORY_MAX_MESSAGES=40,
        remember_message=remember_message,
        ask_gemini=ask_gemini,
    )


def setup_function():
    memory._WRITE_COUNTS.clear()


def test_install_raises_ram_and_existing_long_memory_limits(tmp_path, monkeypatch):
    module = _module(tmp_path)
    monkeypatch.setattr(memory, "_INSTALLED", False)

    assert memory.install(module) is True
    assert module.GROUP_MEMORY_SECONDS == 2 * 60 * 60
    assert module.PRIVATE_MEMORY_SECONDS == 2 * 60 * 60
    assert module.GROUP_MEMORY_MAX_MESSAGES == 60
    assert module.PRIVATE_MEMORY_MAX_MESSAGES == 60
    assert chat_digest_runtime.DIGEST_TTL_DAYS == 90
    assert chat_digest_runtime.MAX_DIGESTS_PER_CHAT == 120
    assert episodic_memory_runtime.EPISODIC_NOTE_TTL_DAYS == 365
    assert episodic_memory_runtime.MAX_EPISODIC_NOTES_PER_MEMBER == 80


def test_group_memory_persists_semantic_voice_and_video_note(tmp_path):
    module = _module(tmp_path)
    memory._initialize_tables(module)
    memory._patch_group_memory_persistence(module)

    module.remember_message(
        module.GROUP_MEMORY,
        -100,
        "user",
        "[Голосовое: я в субботу беру Volvo XC60]",
        7200,
        60,
        "Серега",
    )
    module.remember_message(
        module.GROUP_MEMORY,
        -100,
        "user",
        "[Видео-кружок: видно: красная машина; сказано: вот этот цвет норм?]",
        7200,
        60,
        "Серега",
    )

    with module.get_db_connection() as connection:
        rows = connection.execute(
            "SELECT role, author, modality, content FROM chat_semantic_history ORDER BY id"
        ).fetchall()

    assert rows[0][0:3] == ("user", "Серега", "voice")
    assert "Volvo XC60" in rows[0][3]
    assert rows[1][2] == "video_note"
    assert "красная машина" in rows[1][3]


def test_generic_voice_placeholder_is_not_durable(tmp_path):
    module = _module(tmp_path)
    memory._initialize_tables(module)
    memory._store_turn_sync(
        module,
        -100,
        "user",
        "Серега",
        "[Пользователь отправил голосовое сообщение]",
    )
    with module.get_db_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM chat_semantic_history").fetchone()[0]
    assert count == 0


def test_fts_retrieval_finds_relevant_old_topic(tmp_path):
    module = _module(tmp_path)
    memory._initialize_tables(module)
    memory._store_turn_sync(module, -100, "user", "Серега", "В субботу беру Volvo XC60, думаю про темно-синий цвет")
    memory._store_turn_sync(module, -100, "user", "Паша", "Сегодня заказал себе новую клавиатуру Keychron")
    with module.get_db_connection() as connection:
        connection.execute("UPDATE chat_semantic_history SET created_at = datetime('now', '-1 day')")
        connection.commit()

    rows = memory._retrieve_relevant_sync(module, -100, "ну что думаешь про цвет Volvo?", 6)

    assert rows
    assert any("Volvo XC60" in row["content"] for row in rows)
    assert not any("Keychron" in row["content"] for row in rows)


def test_retrieval_appends_secondary_memory_without_replacing_recent_context(tmp_path):
    module = _module(tmp_path)
    memory._initialize_tables(module)
    memory._store_turn_sync(module, -100, "user", "Серега", "Я собираюсь брать Volvo XC60 темно-синего цвета")
    with module.get_db_connection() as connection:
        connection.execute("UPDATE chat_semantic_history SET created_at = datetime('now', '-1 day')")
        connection.commit()

    memory._patch_retrieval(module)
    result = asyncio.run(
        module.ask_gemini(
            "а что думаешь про Volvo?",
            chat_id=-100,
            chat_type="supergroup",
            recent_messages=["RECENT: мы только что говорили про страховку"],
        )
    )

    recent = result["kwargs"]["recent_messages"]
    assert recent[0].startswith("RECENT:")
    assert any("LONG-TERM RELEVANT MEMORY" in line for line in recent)
    assert any("Volvo XC60" in line for line in recent)


def test_cleanup_enforces_ttl_and_row_cap(tmp_path, monkeypatch):
    module = _module(tmp_path)
    memory._initialize_tables(module)
    monkeypatch.setattr(memory, "PERSISTENT_MAX_ROWS_PER_CHAT", 3)
    for index in range(5):
        memory._store_turn_sync(module, -100, "user", "Серега", f"сообщение номер {index}")
    memory._store_turn_sync(module, -200, "user", "Другой", "чужой чат не трогаем")
    with module.get_db_connection() as connection:
        connection.execute(
            "UPDATE chat_semantic_history SET created_at = datetime('now', '-40 days') WHERE content = 'сообщение номер 0'"
        )
        connection.commit()

    memory._cleanup_chat_sync(module, -100)

    with module.get_db_connection() as connection:
        own = connection.execute(
            "SELECT content FROM chat_semantic_history WHERE chat_id = -100 ORDER BY id"
        ).fetchall()
        other = connection.execute(
            "SELECT content FROM chat_semantic_history WHERE chat_id = -200"
        ).fetchall()
    assert len(own) == 3
    assert "сообщение номер 0" not in {row[0] for row in own}
    assert other == [("чужой чат не трогаем",)]


def test_query_terms_are_bounded_and_drop_common_prompt_noise():
    terms = memory._query_terms(
        "Ниже история группы. Новое сообщение пользователя: что думаешь про Volvo XC60 и темно-синий цвет?"
    )
    assert "пользователя" not in terms
    assert "группы" not in terms
    assert "volvo" in terms
    assert "xc60" in terms
    assert len(terms) <= memory.RETRIEVAL_MAX_QUERY_TERMS
