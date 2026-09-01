"""Chat-local soft memory for Yayceslav's own hypothetical self-image.

Each Telegram chat gets an independent, revisable self-canon. The canon is not
an objective biography: it stores choices Yayceslav made about himself during
explicit imagination/role-play conversations so later conversations in the same
chat can stay internally consistent.

The same model turn emits a hidden machine marker when it establishes or revises
a durable self-choice. This runtime strips that marker before delivery, stores
validated traits in SQLite, and injects the current chat-local canon back into
future system instructions. No extra model call is introduced.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import re
import sys
from typing import Any

import imagination_runtime


_INSTALLED = False
MAX_ACTIVE_TRAITS = 24
MAX_HISTORY_ROWS_PER_CHAT = 96
MAX_TRAIT_VALUE_CHARS = 180
MAX_SOURCE_EXCERPT_CHARS = 260

# Broad enough to make a character, bounded enough to prevent key drift and an
# ever-growing DB. A value can be revised independently without resetting the
# rest of the local persona.
TRAIT_KEYS: tuple[str, ...] = (
    "embodiment",
    "ethnicity",
    "gender",
    "age_vibe",
    "height",
    "build",
    "face",
    "hair",
    "clothing",
    "voice",
    "origin",
    "residence",
    "profession",
    "lifestyle",
    "aesthetic",
    "favorite_food",
    "favorite_drink",
    "music",
    "hobbies",
    "transport",
    "pet",
    "values",
    "political_taste",
    "quirks",
)

TRAIT_LABELS = {
    "embodiment": "физическая форма",
    "ethnicity": "этничность/внешний тип",
    "gender": "пол/гендерный образ",
    "age_vibe": "возрастной образ",
    "height": "рост",
    "build": "телосложение",
    "face": "лицо/черты",
    "hair": "волосы",
    "clothing": "одежда/стиль",
    "voice": "голос",
    "origin": "происхождение",
    "residence": "где живёт",
    "profession": "профессия",
    "lifestyle": "образ жизни",
    "aesthetic": "эстетика",
    "favorite_food": "любимая еда",
    "favorite_drink": "любимый напиток",
    "music": "музыка",
    "hobbies": "увлечения",
    "transport": "транспорт",
    "pet": "питомец",
    "values": "ценности",
    "political_taste": "политический вкус в рамках фантазии",
    "quirks": "привычки/загоны",
}

_ALLOWED_TRAITS = frozenset(TRAIT_KEYS)
_CANON_CACHE: dict[tuple[int, int], dict[str, str]] = {}

# Marker is deliberately ugly and unique so ordinary prose is extremely
# unlikely to collide with it. It must be the final item in the model answer.
_CANON_MARKER_RE = re.compile(
    r"\s*\[\[YAY_SELF_CANON\s+(\{.*\})\s*\]\]\s*\Z",
    re.DOTALL,
)
_CANON_MARKER_BROAD_RE = re.compile(
    r"\s*\[\[YAY_SELF_CANON\b.*\]\]\s*\Z",
    re.DOTALL,
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "get_db_connection", None))
            and callable(getattr(module, "build_full_system_instruction", None))
            and callable(getattr(module, "ask_gemini", None))
        ):
            return module
    return None


def _bound_argument(func: Any, args: tuple[Any, ...], kwargs: dict[str, Any], name: str) -> Any:
    """Read a named argument through wrappers without hard-coded positions."""
    if name in kwargs:
        return kwargs[name]
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        return bound.arguments.get(name)
    except Exception:
        return None


def _cache_key(bot_module: Any, chat_id: int) -> tuple[int, int]:
    return (id(bot_module), int(chat_id))


def _normalize_value(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:MAX_TRAIT_VALUE_CHARS]


def sanitize_change_payload(payload: Any) -> tuple[dict[str, str], tuple[str, ...]]:
    """Accept only bounded, known self-trait keys from the hidden marker."""
    if not isinstance(payload, dict):
        return {}, ()

    raw_set = payload.get("set", {})
    raw_drop = payload.get("drop", [])
    updates: dict[str, str] = {}

    if isinstance(raw_set, dict):
        for key, value in raw_set.items():
            name = str(key or "").strip()
            if name not in _ALLOWED_TRAITS:
                continue
            normalized = _normalize_value(value)
            if normalized:
                updates[name] = normalized

    drops: list[str] = []
    if isinstance(raw_drop, (list, tuple)):
        for key in raw_drop:
            name = str(key or "").strip()
            if name in _ALLOWED_TRAITS and name not in drops:
                drops.append(name)

    return updates, tuple(drops)


def strip_and_parse_canon_marker(answer: str) -> tuple[str, dict[str, str], tuple[str, ...]]:
    """Remove the private marker and return validated changes."""
    text = str(answer or "")
    match = _CANON_MARKER_RE.search(text)
    if match is None:
        # Still hide a malformed marker instead of leaking implementation syntax
        # into Telegram. Invalid content is simply not persisted.
        broad = _CANON_MARKER_BROAD_RE.search(text)
        if broad is None:
            return text, {}, ()
        return text[: broad.start()].rstrip(), {}, ()

    clean = text[: match.start()].rstrip()
    try:
        payload = json.loads(match.group(1))
    except Exception:
        return clean, {}, ()
    updates, drops = sanitize_change_payload(payload)
    return clean, updates, drops


def load_canon_sync(bot_module: Any, chat_id: int) -> dict[str, str]:
    key = _cache_key(bot_module, chat_id)
    cached = _CANON_CACHE.get(key)
    if cached is not None:
        return dict(cached)

    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT trait_key, trait_value
            FROM chat_self_canon
            WHERE chat_id = ?
            """,
            (int(chat_id),),
        ).fetchall()

    canon = {
        str(trait_key): str(trait_value)
        for trait_key, trait_value in rows
        if str(trait_key) in _ALLOWED_TRAITS
    }
    _CANON_CACHE[key] = canon
    return dict(canon)


def _write_history(
    connection: Any,
    *,
    chat_id: int,
    trait_key: str,
    old_value: str | None,
    new_value: str | None,
    source_excerpt: str,
) -> None:
    connection.execute(
        """
        INSERT INTO chat_self_canon_history
            (chat_id, trait_key, old_value, new_value, source_excerpt)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(chat_id),
            trait_key,
            old_value,
            new_value,
            source_excerpt[:MAX_SOURCE_EXCERPT_CHARS],
        ),
    )


def apply_canon_changes_sync(
    bot_module: Any,
    chat_id: int,
    updates: dict[str, str],
    drops: tuple[str, ...] = (),
    source_excerpt: str = "",
) -> dict[str, str]:
    """Atomically revise only the mentioned traits and retain revision history."""
    updates, safe_drops = sanitize_change_payload({"set": updates, "drop": list(drops)})
    source = " ".join(str(source_excerpt or "").split()).strip()

    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            "SELECT trait_key, trait_value FROM chat_self_canon WHERE chat_id = ?",
            (int(chat_id),),
        ).fetchall()
        current = {str(key): str(value) for key, value in rows}

        for trait_key, new_value in updates.items():
            old_value = current.get(trait_key)
            if old_value == new_value:
                continue
            _write_history(
                connection,
                chat_id=chat_id,
                trait_key=trait_key,
                old_value=old_value,
                new_value=new_value,
                source_excerpt=source,
            )
            connection.execute(
                """
                INSERT INTO chat_self_canon
                    (chat_id, trait_key, trait_value, revision, updated_at)
                VALUES (?, ?, ?, 1, datetime('now'))
                ON CONFLICT(chat_id, trait_key) DO UPDATE SET
                    trait_value = excluded.trait_value,
                    revision = chat_self_canon.revision + 1,
                    updated_at = datetime('now')
                """,
                (int(chat_id), trait_key, new_value),
            )
            current[trait_key] = new_value

        for trait_key in safe_drops:
            old_value = current.get(trait_key)
            if old_value is None:
                continue
            _write_history(
                connection,
                chat_id=chat_id,
                trait_key=trait_key,
                old_value=old_value,
                new_value=None,
                source_excerpt=source,
            )
            connection.execute(
                "DELETE FROM chat_self_canon WHERE chat_id = ? AND trait_key = ?",
                (int(chat_id), trait_key),
            )
            current.pop(trait_key, None)

        history_rows = connection.execute(
            """
            SELECT id FROM chat_self_canon_history
            WHERE chat_id = ?
            ORDER BY changed_at DESC, id DESC
            """,
            (int(chat_id),),
        ).fetchall()
        stale_ids = [row[0] for row in history_rows[MAX_HISTORY_ROWS_PER_CHAT:]]
        if stale_ids:
            connection.executemany(
                "DELETE FROM chat_self_canon_history WHERE id = ?",
                [(row_id,) for row_id in stale_ids],
            )

        connection.commit()

    _CANON_CACHE[_cache_key(bot_module, chat_id)] = dict(current)
    return dict(current)


def _format_canon(canon: dict[str, str]) -> str:
    lines = []
    for key in TRAIT_KEYS:
        value = canon.get(key)
        if value:
            lines.append(f"- {TRAIT_LABELS[key]}: {value}")
    return "\n".join(lines)


def _canon_context_rule(canon: dict[str, str]) -> str:
    body = _format_canon(canon)
    if not body:
        return ""
    return f"""

CHAT-LOCAL SELF CANON — МЯГКАЯ ПАМЯТЬ ЯЙЦЕСЛАВА О СЕБЕ В ЭТОМ ЧАТЕ:
Это прошлые гипотетические выборы самого Яйцеслава, сложившиеся именно в этом
чате. В другом чате его образ может быть другим. Не перечисляй память без повода
и не называй её базой данных; просто сохраняй естественную непрерывность, когда
тема касается самого Яйцеслава.
{body}

Считай эти черты текущей версией персонажа, а не вечной истиной. Если новый
явный разговор-фантазия заставляет Яйцеслава действительно выбрать иначе, он
может пересмотреть отдельную черту; остальные черты не сбрасывай.
"""


_UPDATE_PROTOCOL = f"""

SELF-CANON UPDATE PROTOCOL — СКРЫТАЯ МАШИННАЯ ПАМЯТЬ:
Этот протокол применяется только внутри текущего imagination-сценария.
Если в СВОЁМ ответе ты действительно устанавливаешь или меняешь устойчивую
черту собственного образа/вкуса, после обычного текста добавь ОДНУ последнюю
строку строго такого вида:
[[YAY_SELF_CANON {{"set":{{"ethnicity":"японец","aesthetic":"минимализм и технологии"}},"drop":[]}}]]

Допустимые ключи (максимум {MAX_ACTIVE_TRAITS} активных черт):
{', '.join(TRAIT_KEYS)}

Правила записи:
- сохраняй только собственный относительно устойчивый выбор: «я бы был...»,
  «я бы выбрал для себя...», «мне бы нравилось...»;
- НЕ сохраняй навязанный пользователем факт, случайную шутку, временную роль
  «на один день», чужую характеристику или деталь, которую ты сам не выбрал;
- если новая явная фантазия меняет прежнюю черту, запиши новое значение под ТЕМ
  ЖЕ ключом — так память эволюционирует вместо размножения дублей;
- если явно отказался от прежней черты без замены, положи её ключ в `drop`;
- если ничего устойчивого не изменилось, маркер вообще не добавляй;
- сам маркер пользователю не объясняй и не обсуждай: runtime вырежет его до
  отправки сообщения.
"""


def _install_prompt_memory(bot_module: Any) -> None:
    original = getattr(bot_module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_self_canon_prompt", False):
        return

    @functools.wraps(original)
    def build_with_self_canon(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        chat_id = _bound_argument(original, args, kwargs, "chat_id")
        style_text = _bound_argument(original, args, kwargs, "style_text") or ""
        recent_messages = _bound_argument(original, args, kwargs, "recent_messages")

        if chat_id is not None:
            try:
                canon = load_canon_sync(bot_module, int(chat_id))
            except Exception as error:
                logging.warning("Self-canon load failed for chat %s: %s", chat_id, error)
                canon = {}
            if canon:
                instruction += _canon_context_rule(canon)

        direct = imagination_runtime.is_imagination_request(str(style_text or ""))
        followup = imagination_runtime.looks_like_imagination_followup(
            str(style_text or ""), recent_messages
        )
        if direct or followup:
            instruction += _UPDATE_PROTOCOL
        return instruction

    build_with_self_canon._yayceslav_self_canon_prompt = True
    bot_module.build_full_system_instruction = build_with_self_canon


def _install_answer_memory(bot_module: Any) -> None:
    original = getattr(bot_module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_self_canon_answer", False):
        return

    @functools.wraps(original)
    async def ask_with_self_canon(*args: Any, **kwargs: Any):
        answer = await original(*args, **kwargs)
        clean, updates, drops = strip_and_parse_canon_marker(str(answer or ""))
        chat_id = _bound_argument(original, args, kwargs, "chat_id")

        if chat_id is not None and (updates or drops):
            try:
                await asyncio.to_thread(
                    apply_canon_changes_sync,
                    bot_module,
                    int(chat_id),
                    updates,
                    drops,
                    clean,
                )
            except Exception as error:
                # Memory must never make a valid user reply fail.
                logging.warning("Self-canon write failed for chat %s: %s", chat_id, error)
        return clean

    ask_with_self_canon._yayceslav_self_canon_answer = True
    bot_module.ask_gemini = ask_with_self_canon


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _install_prompt_memory(module)
    _install_answer_memory(module)
    _INSTALLED = True
    logging.warning(
        "Self-canon memory ready: chat-local, up to %s revisable traits + history",
        MAX_ACTIVE_TRAITS,
    )
    return True
