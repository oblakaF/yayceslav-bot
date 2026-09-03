"""Privacy-bounded live latency/route diagnostics for Yayceslav.

The runtime records technical metadata only: chat id/type, route, elapsed times,
provider call/cache/fallback counters and a bounded error kind. It never stores
message text, model output, provider payloads, API keys or user ids.

Instrumentation is passive and adds no provider/model calls. A private owner-only
``/diag`` command summarizes recent rows from the existing SQLite volume.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from telegram.ext import Application, CommandHandler


RETENTION_DAYS = 14
MAX_ROWS = 10_000
REPORT_DAYS = 3
MAX_ERROR_CHARS = 80
_INSTALLED = False
_PREPARED_APPLICATION_IDS: set[int] = set()


@dataclass(frozen=True)
class DiagnosticSession:
    started_at: float
    chat_id: int
    chat_type: str
    route: str = "normal"
    model_ms: float = 0.0
    provider_ms: float = 0.0
    provider_calls: int = 0
    cache_hits: int = 0
    fallback: bool = False
    error_kind: str = ""


_SESSION: contextvars.ContextVar[DiagnosticSession | None] = contextvars.ContextVar(
    "yayceslav_live_diagnostic_session", default=None
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _clean_error(value: Any) -> str:
    text = type(value).__name__ if isinstance(value, BaseException) else str(value or "")
    return " ".join(text.split())[:MAX_ERROR_CHARS]


def _initialize_table(bot_module: Any) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_diagnostics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                chat_type TEXT NOT NULL DEFAULT '',
                route TEXT NOT NULL,
                total_ms REAL NOT NULL DEFAULT 0,
                model_ms REAL NOT NULL DEFAULT 0,
                provider_ms REAL NOT NULL DEFAULT 0,
                provider_calls INTEGER NOT NULL DEFAULT 0,
                cache_hits INTEGER NOT NULL DEFAULT 0,
                fallback INTEGER NOT NULL DEFAULT 0,
                error_kind TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_live_diagnostics_created
            ON live_diagnostics_events(created_at, id)
            """
        )
        connection.commit()


def _cleanup_sync(bot_module: Any) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            "DELETE FROM live_diagnostics_events WHERE created_at < datetime('now', ?)",
            (f"-{RETENTION_DAYS} days",),
        )
        stale = connection.execute(
            """
            SELECT id FROM live_diagnostics_events
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET ?
            """,
            (MAX_ROWS,),
        ).fetchall()
        if stale:
            connection.executemany(
                "DELETE FROM live_diagnostics_events WHERE id = ?",
                [(int(row[0]),) for row in stale],
            )
        connection.commit()


def _persist_sync(bot_module: Any, session: DiagnosticSession, *, total_ms: float) -> None:
    try:
        with bot_module.get_db_connection() as connection:
            connection.execute(
                """
                INSERT INTO live_diagnostics_events(
                    chat_id, chat_type, route, total_ms, model_ms, provider_ms,
                    provider_calls, cache_hits, fallback, error_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(session.chat_id),
                    str(session.chat_type or "")[:24],
                    str(session.route or "normal")[:32],
                    max(0.0, float(total_ms)),
                    max(0.0, float(session.model_ms)),
                    max(0.0, float(session.provider_ms)),
                    max(0, int(session.provider_calls)),
                    max(0, int(session.cache_hits)),
                    1 if session.fallback else 0,
                    _clean_error(session.error_kind),
                ),
            )
            connection.commit()
        if int(time.monotonic()) % 97 == 0:
            _cleanup_sync(bot_module)
    except Exception as error:
        logging.info("Live diagnostics persistence skipped: %s", error)


def _extract_chat(update: Any) -> tuple[int, str]:
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return 0, ""
    try:
        chat_id = int(getattr(chat, "id", 0) or 0)
    except (TypeError, ValueError):
        chat_id = 0
    return chat_id, str(getattr(chat, "type", "") or "")


def _start_from_ids(chat_id: Any, chat_type: Any, *, route: str = "normal") -> None:
    try:
        numeric_chat_id = int(chat_id or 0)
    except (TypeError, ValueError):
        numeric_chat_id = 0
    if numeric_chat_id and _SESSION.get() is None:
        _SESSION.set(
            DiagnosticSession(
                started_at=time.monotonic(),
                chat_id=numeric_chat_id,
                chat_type=str(chat_type or ""),
                route=str(route or "normal"),
            )
        )


def start_request(update: Any, *, route: str = "normal") -> None:
    bot_module = _find_bot_module()
    previous = _SESSION.get()
    if previous is not None and bot_module is not None:
        previous = replace(previous, fallback=True)
        _persist_sync(bot_module, previous, total_ms=(time.monotonic() - previous.started_at) * 1000.0)
    chat_id, chat_type = _extract_chat(update)
    if chat_id:
        _SESSION.set(
            DiagnosticSession(
                started_at=time.monotonic(),
                chat_id=chat_id,
                chat_type=chat_type,
                route=str(route or "normal"),
            )
        )


def mark_route(route: str) -> None:
    session = _SESSION.get()
    if session is not None:
        _SESSION.set(replace(session, route=str(route or session.route)[:32]))


def mark_fallback(value: bool = True) -> None:
    session = _SESSION.get()
    if session is not None:
        _SESSION.set(replace(session, fallback=bool(value)))


def mark_error(error: Any) -> None:
    session = _SESSION.get()
    if session is not None:
        _SESSION.set(replace(session, error_kind=_clean_error(error)))


def add_model_ms(elapsed_ms: float) -> None:
    session = _SESSION.get()
    if session is not None:
        _SESSION.set(replace(session, model_ms=session.model_ms + max(0.0, float(elapsed_ms))))


def add_provider_ms(elapsed_ms: float, *, empty: bool = False, error: Any = None) -> None:
    session = _SESSION.get()
    if session is None:
        return
    _SESSION.set(
        replace(
            session,
            provider_ms=session.provider_ms + max(0.0, float(elapsed_ms)),
            provider_calls=session.provider_calls + 1,
            fallback=session.fallback or bool(empty),
            error_kind=_clean_error(error) if error is not None else session.error_kind,
        )
    )


def add_cache_hit() -> None:
    session = _SESSION.get()
    if session is not None:
        _SESSION.set(replace(session, cache_hits=session.cache_hits + 1))


def finish_request() -> None:
    session = _SESSION.get()
    if session is None:
        return
    _SESSION.set(None)
    bot_module = _find_bot_module()
    if bot_module is not None:
        _persist_sync(bot_module, session, total_ms=(time.monotonic() - session.started_at) * 1000.0)


def _infer_route_from_contents(contents: Any) -> str:
    if isinstance(contents, (list, tuple)):
        text = "\n".join(str(item) for item in contents)
    else:
        text = str(contents or "")
    lowered = text.lower()
    if "результаты поиска:" in lowered:
        return "search"
    if "[голосовое:" in lowered or "голосовое сообщение" in lowered or "voice message" in lowered:
        return "voice"
    return ""


def _patch_bot_hot_path(bot_module: Any) -> None:
    prepare = getattr(bot_module, "prepare_request_text", None)
    if callable(prepare) and not getattr(prepare, "_yayceslav_live_diag", False):
        @functools.wraps(prepare)
        async def prepare_with_diag(*args: Any, **kwargs: Any):
            result = await prepare(*args, **kwargs)
            if result is not None:
                update = kwargs.get("update") or (args[0] if args else None)
                start_request(update, route="normal")
            return result

        prepare_with_diag._yayceslav_live_diag = True
        bot_module.prepare_request_text = prepare_with_diag

    ask = getattr(bot_module, "ask_gemini", None)
    if callable(ask) and not getattr(ask, "_yayceslav_live_diag", False):
        @functools.wraps(ask)
        async def ask_with_diag(*args: Any, **kwargs: Any):
            contents = kwargs.get("contents") if "contents" in kwargs else (args[0] if args else "")
            inferred = _infer_route_from_contents(contents)
            _start_from_ids(
                kwargs.get("chat_id"),
                kwargs.get("chat_type"),
                route=inferred or "normal",
            )
            if inferred:
                mark_route(inferred)
            started = time.monotonic()
            try:
                return await ask(*args, **kwargs)
            except Exception as error:
                mark_error(error)
                raise
            finally:
                if _SESSION.get() is not None:
                    add_model_ms((time.monotonic() - started) * 1000.0)

        ask_with_diag._yayceslav_live_diag = True
        bot_module.ask_gemini = ask_with_diag

    send = getattr(bot_module, "send_answer", None)
    if callable(send) and not getattr(send, "_yayceslav_live_diag", False):
        @functools.wraps(send)
        async def send_with_diag(*args: Any, **kwargs: Any):
            try:
                return await send(*args, **kwargs)
            except Exception as error:
                mark_error(error)
                raise
            finally:
                finish_request()

        send_with_diag._yayceslav_live_diag = True
        bot_module.send_answer = send_with_diag


def _wrap_classifier(module: Any, function_name: str, route: str) -> None:
    original: Callable[..., str] | None = getattr(module, function_name, None)
    if not callable(original) or getattr(original, "_yayceslav_live_diag", False):
        return

    @functools.wraps(original)
    def wrapped(*args: Any, **kwargs: Any):
        result = original(*args, **kwargs)
        if result:
            mark_route(route)
        return result

    wrapped._yayceslav_live_diag = True
    setattr(module, function_name, wrapped)


def _wrap_cache_get(module: Any) -> None:
    original = getattr(module, "_cache_get", None)
    if not callable(original) or getattr(original, "_yayceslav_live_diag", False):
        return

    @functools.wraps(original)
    def wrapped(*args: Any, **kwargs: Any):
        result = original(*args, **kwargs)
        if result is not None:
            add_cache_hit()
        return result

    wrapped._yayceslav_live_diag = True
    module._cache_get = wrapped


def _wrap_provider(module: Any, function_name: str) -> None:
    original = getattr(module, function_name, None)
    if not callable(original) or getattr(original, "_yayceslav_live_diag", False):
        return

    @functools.wraps(original)
    async def wrapped(*args: Any, **kwargs: Any):
        started = time.monotonic()
        try:
            result = await original(*args, **kwargs)
        except Exception as error:
            add_provider_ms((time.monotonic() - started) * 1000.0, error=error)
            raise
        add_provider_ms((time.monotonic() - started) * 1000.0, empty=result is None)
        return result

    wrapped._yayceslav_live_diag = True
    setattr(module, function_name, wrapped)


def _patch_specialists() -> None:
    try:
        import book_recommendation_runtime as books
        import game_recommendation_runtime as games
        import movie_recommendation_runtime as movies
        import music_recommendation_runtime as music
    except Exception as error:
        logging.info("Live diagnostics specialist patch skipped: %s", error)
        return

    for module, classifier, route, provider in (
        (music, "classify_recommendation_intent", "music", "_listenbrainz_get"),
        (books, "classify_book_recommendation_intent", "books", "_openlibrary_get"),
        (movies, "classify_movie_recommendation_intent", "movies", "_tmdb_get"),
        (games, "classify_game_recommendation_intent", "games", "_rawg_get"),
    ):
        _wrap_classifier(module, classifier, route)
        _wrap_cache_get(module)
        _wrap_provider(module, provider)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return float(ordered[index])


def summarize_sync(bot_module: Any, *, days: int = REPORT_DAYS) -> str:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT route, total_ms, model_ms, provider_ms, provider_calls,
                   cache_hits, fallback, error_kind
            FROM live_diagnostics_events
            WHERE created_at >= datetime('now', ?)
            ORDER BY id
            """,
            (f"-{max(1, int(days))} days",),
        ).fetchall()
    if not rows:
        return f"Live diagnostics: за последние {days} дн. данных пока нет."

    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row[0] or "normal"), []).append(row)

    lines = [f"Live diagnostics · {days} дн. · {len(rows)} ответов/попыток"]
    for route in sorted(grouped):
        items = grouped[route]
        total = [float(row[1] or 0.0) for row in items]
        provider = [float(row[3] or 0.0) for row in items]
        calls = sum(int(row[4] or 0) for row in items)
        hits = sum(int(row[5] or 0) for row in items)
        fallbacks = sum(int(row[6] or 0) for row in items)
        errors = sum(1 for row in items if str(row[7] or ""))
        lines.append(
            f"{route}: n={len(items)}, avg={sum(total)/len(total):.0f}ms, "
            f"p95={_percentile(total, 0.95):.0f}ms, provider_avg={sum(provider)/len(provider):.0f}ms, "
            f"fallback={fallbacks}, errors={errors}, cache={hits}/{calls}"
        )
    return "\n".join(lines)


def _owner_id() -> int:
    try:
        return int(str(os.getenv("BOT_OWNER_ID", "0") or "0").strip())
    except ValueError:
        return 0


async def _diag_command(update: Any, context: Any) -> None:
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if user is None or message is None or int(getattr(user, "id", 0) or 0) != _owner_id():
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    try:
        days = int(context.args[0]) if getattr(context, "args", None) else REPORT_DAYS
    except (TypeError, ValueError, IndexError):
        days = REPORT_DAYS
    days = max(1, min(days, RETENTION_DAYS))
    await message.reply_text(summarize_sync(bot_module, days=days))


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True
    _initialize_table(module)
    _patch_bot_hot_path(module)
    _patch_specialists()
    _INSTALLED = True
    logging.warning("Live diagnostics ready: route/latency/provider telemetry, no message content")
    return True


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    install()
    application.add_handler(CommandHandler("diag", _diag_command), group=-20)
    _PREPARED_APPLICATION_IDS.add(app_id)
