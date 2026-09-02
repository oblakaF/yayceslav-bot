"""Rare, evidence-grounded self-development for Yayceslav.

This layer gives low/medium-inertia preferences a chance to evolve naturally
without adding another model call. It only opens a development window on
self-reflective turns, after enough of Yayceslav's own prior statements exist
across multiple days, and after a long cooldown. A separate hidden marker is
used so this feature can enforce a narrow allowlist independently of the general
self-canon protocol.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import sys
from typing import Any

import imagination_runtime
import self_canon_runtime
import self_canon_v2_runtime


_INSTALLED = False
MIN_EVIDENCE_ROWS = 6
MIN_EVIDENCE_SPAN_DAYS = 7.0
EVENT_COOLDOWN_DAYS = 21
MAX_EVIDENCE_ROWS = 8
MAX_EVIDENCE_CHARS = 360

_ALLOWED_MEDIUM = frozenset({"lifestyle", "aesthetic", "clothing", "voice"})
_ALLOWED_TRAITS = frozenset(self_canon_v2_runtime.LOW_INERTIA) | _ALLOWED_MEDIUM

_REFLECTIVE_RE = re.compile(
    r"(?:"
    r"\b(?:что|кто|какой|какая|какие)\s+(?:тебе|ты|у\s+тебя)\b|"
    r"\b(?:тебе\s+нравится|ты\s+любишь|что\s+слушаешь|во\s+что\s+играешь|что\s+читаешь)\b|"
    r"\b(?:ты\s+изменился|как\s+ты\s+изменился|передумал|теперь\s+тебе|что\s+тебе\s+ближе)\b|"
    r"\b(?:what\s+do\s+you\s+like|what\s+are\s+you\s+into|have\s+you\s+changed)\b"
    r")",
    re.IGNORECASE,
)

_SELF_STATEMENT_RE = re.compile(
    r"(?:"
    r"\bмне\s+(?:нравится|нравятся|ближе|заходит|интересно|важнее)\b|"
    r"\bя\s+(?:люблю|предпочитаю|слушаю|играю|читаю|выбираю|ценю)\b|"
    r"\bя\s+бы\s+(?:выбрал|предпоч[её]л)\b|"
    r"\bi\s+(?:like|love|prefer|listen|play|read|value)\b"
    r")",
    re.IGNORECASE,
)

_MARKER_RE = re.compile(r"\s*\[\[YAY_SELF_DEVELOPMENT\s+(\{.*\})\s*\]\]\s*\Z", re.DOTALL)
_MARKER_BROAD_RE = re.compile(r"\s*\[\[YAY_SELF_DEVELOPMENT\b.*\]\]\s*\Z", re.DOTALL)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _initialize_table(bot_module: Any) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_self_development_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                trait_key TEXT NOT NULL,
                old_value TEXT NOT NULL DEFAULT '',
                new_value TEXT NOT NULL DEFAULT '',
                reason_excerpt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_self_development_chat_time
            ON chat_self_development_events(chat_id, created_at, id)
            """
        )
        connection.commit()


def _clean(value: Any, limit: int = MAX_EVIDENCE_CHARS) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _reflective_turn(style_text: Any) -> bool:
    return bool(_REFLECTIVE_RE.search(_clean(style_text, 1000)))


def _cooldown_ready(bot_module: Any, chat_id: int) -> bool:
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM chat_self_development_events
            WHERE chat_id = ?
              AND created_at >= datetime('now', ?)
            LIMIT 1
            """,
            (int(chat_id), f"-{EVENT_COOLDOWN_DAYS} days"),
        ).fetchone()
    return row is None


def _evidence_rows(bot_module: Any, chat_id: int) -> list[tuple[str, str]]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT content, created_at
            FROM chat_semantic_history
            WHERE chat_id = ?
              AND role = 'assistant'
              AND created_at >= datetime('now', '-30 days')
            ORDER BY created_at DESC, id DESC
            LIMIT 80
            """,
            (int(chat_id),),
        ).fetchall()

    filtered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for content, created_at in rows:
        text = _clean(content)
        if not text or not _SELF_STATEMENT_RE.search(text):
            continue
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        filtered.append((text, str(created_at or "")))
        if len(filtered) >= MAX_EVIDENCE_ROWS:
            break
    return filtered


def _evidence_is_mature(bot_module: Any, chat_id: int, rows: list[tuple[str, str]]) -> bool:
    if len(rows) < MIN_EVIDENCE_ROWS:
        return False
    dates = [created[:10] for _, created in rows if len(created) >= 10]
    if len(set(dates)) < 3:
        return False
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT julianday(MAX(created_at)) - julianday(MIN(created_at))
            FROM chat_semantic_history
            WHERE chat_id = ?
              AND role = 'assistant'
              AND created_at >= datetime('now', '-30 days')
            """,
            (int(chat_id),),
        ).fetchone()
    span = float((row or [0.0])[0] or 0.0)
    return span >= MIN_EVIDENCE_SPAN_DAYS


def _eligible_traits(bot_module: Any, chat_id: int) -> dict[str, str]:
    canon = self_canon_runtime.load_canon_sync(bot_module, int(chat_id))
    return {key: value for key, value in canon.items() if key in _ALLOWED_TRAITS and _clean(value)}


def development_context(bot_module: Any, chat_id: int, style_text: Any) -> str:
    """Return a bounded optional prompt block, or empty string when not eligible."""
    text = _clean(style_text, 1000)
    if not _reflective_turn(text):
        return ""
    # Explicit imagination/temporary-role conversations own their own canon
    # protocol and must never overlap with autonomous development.
    if imagination_runtime.is_imagination_request(text):
        return ""
    try:
        if not _cooldown_ready(bot_module, int(chat_id)):
            return ""
        traits = _eligible_traits(bot_module, int(chat_id))
        if not traits:
            return ""
        rows = _evidence_rows(bot_module, int(chat_id))
        if not _evidence_is_mature(bot_module, int(chat_id), rows):
            return ""
    except Exception as error:
        logging.warning("Self-development eligibility failed for chat %s: %s", chat_id, error)
        return ""

    trait_lines = [f"- {key}: {value}" for key, value in traits.items()]
    evidence_lines = [f"- [{created[:10]}] {text}" for text, created in reversed(rows)]
    allowed = ", ".join(sorted(_ALLOWED_TRAITS))
    return (
        "RARE SELF-DEVELOPMENT WINDOW — ОПЦИОНАЛЬНОЕ РАЗВИТИЕ ПЕРСОНАЖА:\n"
        "Это редкое окно, а не обязанность что-то менять. Сначала ответь на вопрос пользователя нормально. "
        "Только если нижняя история действительно показывает повторяющийся и устойчивый сдвиг в СОБСТВЕННЫХ вкусах Яйцеслава, "
        "можно естественно заметить это в видимом ответе. Не выводи изменение из одного сообщения и не подстраивай личность под пользователя.\n\n"
        "Разрешены только низко-/частично средне-инерционные черты. Высокоинерционные черты здесь менять запрещено.\n"
        f"Разрешённые ключи: {allowed}\n"
        "За один event меняй максимум ОДНУ черту. Для low-inertia вкусов предпочитай расширение старого вкуса, а не стирание. "
        "Если меняешь уже заполненную черту, в обычном тексте обязательно сформулируй пересмотр И причину: например, "
        "«раньше я чаще выбирал X, теперь тянет к X + Y, потому что ...».\n"
        "Только после такого видимого объяснения добавь последней строкой скрытый маркер:\n"
        "[[YAY_SELF_DEVELOPMENT {\"set\":{\"music\":\"старое + новое\"}}]]\n"
        "Если доказательств устойчивого изменения недостаточно — НЕ добавляй маркер и ничего не меняй.\n\n"
        "ТЕКУЩИЕ РАЗРЕШЁННЫЕ ЧЕРТЫ:\n"
        + "\n".join(trait_lines)
        + "\n\nСОБСТВЕННЫЕ ПРОШЛЫЕ ВЫСКАЗЫВАНИЯ ЯЙЦЕСЛАВА:\n"
        + "\n".join(evidence_lines)
    )


def _sanitize_marker(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("set"), dict):
        return {}
    result: dict[str, str] = {}
    for key, value in payload["set"].items():
        name = str(key or "").strip()
        text = _clean(value, self_canon_runtime.MAX_TRAIT_VALUE_CHARS)
        if name in _ALLOWED_TRAITS and text:
            result[name] = text
        if result:
            break
    return result


def strip_and_parse_marker(answer: str) -> tuple[str, dict[str, str]]:
    text = str(answer or "")
    match = _MARKER_RE.search(text)
    if match is None:
        broad = _MARKER_BROAD_RE.search(text)
        if broad is None:
            return text, {}
        return text[: broad.start()].rstrip(), {}
    clean = text[: match.start()].rstrip()
    try:
        payload = json.loads(match.group(1))
    except Exception:
        return clean, {}
    return clean, _sanitize_marker(payload)


def _record_event(bot_module: Any, chat_id: int, trait_key: str, old_value: str, new_value: str, reason: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_self_development_events
                (chat_id, trait_key, old_value, new_value, reason_excerpt)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(chat_id), trait_key, _clean(old_value, 180), _clean(new_value, 180), _clean(reason, 360)),
        )
        connection.commit()


def _install_prompt(bot_module: Any) -> None:
    original = getattr(bot_module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_self_development_prompt", False):
        return

    @functools.wraps(original)
    def build_with_development(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        chat_id = self_canon_runtime._bound_argument(original, args, kwargs, "chat_id")
        style_text = self_canon_runtime._bound_argument(original, args, kwargs, "style_text") or ""
        if chat_id is None:
            return instruction
        block = development_context(bot_module, int(chat_id), style_text)
        if block:
            instruction += "\n\n" + block
        return instruction

    build_with_development._yayceslav_self_development_prompt = True
    bot_module.build_full_system_instruction = build_with_development


def _install_answer(bot_module: Any) -> None:
    original = getattr(bot_module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_self_development_answer", False):
        return

    @functools.wraps(original)
    async def ask_with_development(*args: Any, **kwargs: Any):
        answer = await original(*args, **kwargs)
        clean, updates = strip_and_parse_marker(str(answer or ""))
        chat_id = self_canon_runtime._bound_argument(original, args, kwargs, "chat_id")
        if chat_id is None or not updates:
            return clean
        try:
            before = self_canon_runtime.load_canon_sync(bot_module, int(chat_id))
            after = self_canon_runtime.apply_canon_changes_sync(
                bot_module,
                int(chat_id),
                updates,
                (),
                clean,
            )
            for trait_key, new_value in updates.items():
                old_value = before.get(trait_key, "")
                if after.get(trait_key) == new_value and old_value != new_value:
                    _record_event(bot_module, int(chat_id), trait_key, old_value, new_value, clean)
                    logging.info("Rare self-development event chat=%s trait=%s", chat_id, trait_key)
                    break
        except Exception as error:
            logging.warning("Self-development write failed for chat %s: %s", chat_id, error)
        return clean

    ask_with_development._yayceslav_self_development_answer = True
    bot_module.ask_gemini = ask_with_development


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True
    try:
        _initialize_table(module)
    except Exception as error:
        logging.warning("Self-development table init failed: %s", error)
        return False
    _install_prompt(module)
    _install_answer(module)
    _INSTALLED = True
    logging.warning(
        "Rare self-development ready: %s-day cooldown, %s-day evidence span, no extra model call",
        EVENT_COOLDOWN_DAYS,
        int(MIN_EVIDENCE_SPAN_DAYS),
    )
    return True
