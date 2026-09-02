import sqlite3
from pathlib import Path
from types import SimpleNamespace

import chat_digest_runtime
import episodic_memory_runtime


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def _module(tmp_path: Path):
    db_path = tmp_path / "cleanup.db"

    def get_db_connection():
        return sqlite3.connect(db_path, factory=ClosingConnection)

    return SimpleNamespace(get_db_connection=get_db_connection)


def test_episodic_default_limit_is_read_at_call_time(tmp_path, monkeypatch):
    module = _module(tmp_path)
    episodic_memory_runtime._initialize_table(module)
    for index in range(10):
        episodic_memory_runtime._record_episodic_note_sync(
            module,
            -100,
            42,
            f"эпизод {index}",
            5,
            "test",
        )

    monkeypatch.setattr(episodic_memory_runtime, "EPISODIC_PROFILE_NOTES", 8)
    rows = episodic_memory_runtime._load_episodic_notes_sync(module, -100, 42)

    assert len(rows) == 8
    assert rows[0] == "эпизод 9"


def test_digest_default_limit_is_read_at_call_time(tmp_path, monkeypatch):
    module = _module(tmp_path)
    chat_digest_runtime._initialize_table(module)
    for index in range(10):
        chat_digest_runtime._store_digest_sync(module, -100, f"сводка {index}")

    monkeypatch.setattr(chat_digest_runtime, "DIGESTS_FOR_RECAP", 6)
    rows = chat_digest_runtime._load_digests_sync(module, -100)

    assert len(rows) == 6
    assert rows[-1] == "сводка 9"


def test_explicit_limits_still_override_runtime_defaults(tmp_path, monkeypatch):
    module = _module(tmp_path)
    episodic_memory_runtime._initialize_table(module)
    chat_digest_runtime._initialize_table(module)

    for index in range(5):
        episodic_memory_runtime._record_episodic_note_sync(
            module,
            -100,
            42,
            f"эпизод {index}",
            5,
            "test",
        )
        chat_digest_runtime._store_digest_sync(module, -100, f"сводка {index}")

    monkeypatch.setattr(episodic_memory_runtime, "EPISODIC_PROFILE_NOTES", 8)
    monkeypatch.setattr(chat_digest_runtime, "DIGESTS_FOR_RECAP", 6)

    assert len(episodic_memory_runtime._load_episodic_notes_sync(module, -100, 42, 2)) == 2
    assert len(chat_digest_runtime._load_digests_sync(module, -100, 3)) == 3
