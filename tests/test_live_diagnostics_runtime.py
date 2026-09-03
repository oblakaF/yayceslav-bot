import sqlite3
from types import SimpleNamespace

import live_diagnostics_runtime as diag


class FakeBot:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")

    def get_db_connection(self):
        return self.connection


def setup_function():
    diag._SESSION.set(None)


def _update(chat_id=-100, chat_type="supergroup"):
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id, type=chat_type))


def test_schema_contains_only_technical_fields():
    bot = FakeBot()
    diag._initialize_table(bot)
    columns = [row[1] for row in bot.connection.execute("PRAGMA table_info(live_diagnostics_events)")]
    assert "route" in columns
    assert "total_ms" in columns
    assert "provider_ms" in columns
    assert "cache_hits" in columns
    assert "fallback" in columns
    assert "message_text" not in columns
    assert "response_text" not in columns
    assert "user_id" not in columns
    assert "api_key" not in columns


def test_request_records_route_latency_provider_cache_and_fallback(monkeypatch):
    bot = FakeBot()
    diag._initialize_table(bot)
    monkeypatch.setattr(diag, "_find_bot_module", lambda: bot)

    diag.start_request(_update(), route="normal")
    diag.mark_route("games")
    diag.add_provider_ms(125.0)
    diag.add_cache_hit()
    diag.add_model_ms(230.0)
    diag.mark_fallback(True)
    diag.finish_request()

    row = bot.connection.execute(
        "SELECT chat_id, route, model_ms, provider_ms, provider_calls, cache_hits, fallback FROM live_diagnostics_events"
    ).fetchone()
    assert row[0] == -100
    assert row[1] == "games"
    assert row[2] == 230.0
    assert row[3] == 125.0
    assert row[4] == 1
    assert row[5] == 1
    assert row[6] == 1


def test_starting_normal_route_flushes_failed_specialist_attempt(monkeypatch):
    bot = FakeBot()
    diag._initialize_table(bot)
    monkeypatch.setattr(diag, "_find_bot_module", lambda: bot)

    diag.start_request(_update(), route="games")
    diag.add_provider_ms(10.0, empty=True)
    diag.start_request(_update(), route="normal")
    diag.finish_request()

    rows = bot.connection.execute(
        "SELECT route, fallback FROM live_diagnostics_events ORDER BY id"
    ).fetchall()
    assert rows == [("games", 1), ("normal", 0)]


def test_route_inference_distinguishes_search_and_voice_without_payload_storage():
    assert diag._infer_route_from_contents("Результаты поиска:\n1. example") == "search"
    assert diag._infer_route_from_contents("[Голосовое: привет]") == "voice"
    assert diag._infer_route_from_contents("обычный вопрос") == ""


def test_summary_reports_aggregate_not_message_content():
    bot = FakeBot()
    diag._initialize_table(bot)
    bot.connection.executemany(
        """
        INSERT INTO live_diagnostics_events(
            chat_id, chat_type, route, total_ms, model_ms, provider_ms,
            provider_calls, cache_hits, fallback, error_kind
        ) VALUES (-100, 'supergroup', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("games", 1000.0, 300.0, 500.0, 2, 1, 0, ""),
            ("games", 2000.0, 500.0, 900.0, 3, 0, 1, "TimeoutError"),
            ("normal", 400.0, 350.0, 0.0, 0, 0, 0, ""),
        ],
    )
    bot.connection.commit()
    report = diag.summarize_sync(bot, days=3)
    assert "games: n=2" in report
    assert "normal: n=1" in report
    assert "fallback=1" in report
    assert "errors=1" in report
    assert "cache=1/5" in report


def test_retention_and_row_cap_are_bounded(monkeypatch):
    bot = FakeBot()
    diag._initialize_table(bot)
    monkeypatch.setattr(diag, "MAX_ROWS", 2)
    bot.connection.executemany(
        "INSERT INTO live_diagnostics_events(chat_id, route, total_ms) VALUES (-100, 'normal', ?)",
        [(1.0,), (2.0,), (3.0,)],
    )
    bot.connection.commit()
    diag._cleanup_sync(bot)
    count = bot.connection.execute("SELECT COUNT(*) FROM live_diagnostics_events").fetchone()[0]
    assert count == 2
