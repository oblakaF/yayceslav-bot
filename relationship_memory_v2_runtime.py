"""Bounded social/relationship continuity for group members.

This layer stores social interaction markers, not raw messages or inferred
personality traits.  It reuses the existing safe member callback-term memory for
specific recurring topics and existing relationship/profile counters for coarse
history.  Current-turn behavior always has priority over old relationship state.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import re
import sys
from typing import Any, Mapping

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters


_INSTALLED = False
_PREPARED_APPLICATION_IDS: set[int] = set()
MARKER_TTL_DAYS = 365
MAX_MARKERS_PER_MEMBER = 12
MIN_MARKER_OCCURRENCES_FOR_PROMPT = 1

_ALLOWED_MARKERS = frozenset(
    {
        "banter",
        "correction",
        "apology",
        "gratitude",
        "disagreement",
        "reconciliation",
    }
)

_APOLOGY_RE = re.compile(r"\b(?:извини|извиняюсь|прости|сорян|сори|виноват)\b", re.I)
_GRATITUDE_RE = re.compile(r"\b(?:спасибо|благодарю|спс|пасиб)\b", re.I)
_CORRECTION_RE = re.compile(
    r"\b(?:неверно|неправильно|ошиб(?:ся|ка)|ты\s+ошибся|нет,?\s+не\s+так|"
    r"поправ(?:ь|лю|ка)|я\s+имел\s+в\s+виду)\b",
    re.I,
)
_DISAGREEMENT_RE = re.compile(
    r"\b(?:не\s+согласен|не\s+согласна|спорю|неправда|чушь|ерунда|не\s+верю)\b",
    re.I,
)
_RECONCILIATION_RE = re.compile(r"\b(?:мир|ладно,?\s+проехали|замяли|без\s+обид)\b", re.I)
_BANTER_RE = re.compile(
    r"(?:\b(?:ахах|хаха|лол|кек|ор(?:у|нул)|угар|рофл|шутк)\w*\b|[😂🤣]{1,})",
    re.I,
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "get_db_connection", None))
            and callable(getattr(module, "build_full_system_instruction", None))
        ):
            return module
    return None


def _initialize_table(bot_module: Any) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_relationship_markers (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                marker TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at TEXT,
                PRIMARY KEY (chat_id, user_id, marker)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_relationship_markers_recent
            ON member_relationship_markers(chat_id, user_id, last_seen_at)
            """
        )
        connection.commit()


def classify_social_markers(text: str, *, replying_to_bot: bool) -> tuple[str, ...]:
    """Return conservative marker types; never return raw text or topics."""
    value = str(text or "").strip()
    if not value or not replying_to_bot:
        return ()

    markers: list[str] = []
    checks = (
        ("apology", _APOLOGY_RE),
        ("gratitude", _GRATITUDE_RE),
        ("correction", _CORRECTION_RE),
        ("disagreement", _DISAGREEMENT_RE),
        ("reconciliation", _RECONCILIATION_RE),
        ("banter", _BANTER_RE),
    )
    for name, pattern in checks:
        if pattern.search(value):
            markers.append(name)
    return tuple(markers)


def _record_markers_sync(
    bot_module: Any,
    chat_id: int,
    user_id: int,
    markers: tuple[str, ...],
) -> None:
    safe = tuple(dict.fromkeys(marker for marker in markers if marker in _ALLOWED_MARKERS))
    if not safe:
        return
    with bot_module.get_db_connection() as connection:
        for marker in safe:
            connection.execute(
                """
                INSERT INTO member_relationship_markers
                    (chat_id, user_id, marker, occurrences)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(chat_id, user_id, marker) DO UPDATE SET
                    occurrences = occurrences + 1,
                    last_seen_at = datetime('now')
                """,
                (int(chat_id), int(user_id), marker),
            )
        connection.execute(
            """
            DELETE FROM member_relationship_markers
            WHERE chat_id = ? AND user_id = ?
              AND last_seen_at < datetime('now', ?)
            """,
            (int(chat_id), int(user_id), f"-{MARKER_TTL_DAYS} days"),
        )
        rows = connection.execute(
            """
            SELECT marker FROM member_relationship_markers
            WHERE chat_id = ? AND user_id = ?
            ORDER BY last_seen_at DESC, occurrences DESC
            """,
            (int(chat_id), int(user_id)),
        ).fetchall()
        for (marker,) in rows[MAX_MARKERS_PER_MEMBER:]:
            connection.execute(
                """
                DELETE FROM member_relationship_markers
                WHERE chat_id = ? AND user_id = ? AND marker = ?
                """,
                (int(chat_id), int(user_id), marker),
            )
        connection.commit()


def _load_markers_sync(bot_module: Any, chat_id: int, user_id: int) -> dict[str, int]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT marker, occurrences
            FROM member_relationship_markers
            WHERE chat_id = ? AND user_id = ?
              AND last_seen_at >= datetime('now', ?)
            ORDER BY occurrences DESC, last_seen_at DESC
            """,
            (int(chat_id), int(user_id), f"-{MARKER_TTL_DAYS} days"),
        ).fetchall()
    return {
        str(marker): int(count or 0)
        for marker, count in rows
        if str(marker) in _ALLOWED_MARKERS and int(count or 0) >= MIN_MARKER_OCCURRENCES_FOR_PROMPT
    }


def _safe_profile_sync(bot_module: Any, chat_id: int, user_id: int) -> Mapping[str, Any]:
    getter = getattr(bot_module, "get_member_profile_sync", None)
    if not callable(getter):
        return {}
    try:
        return getter(int(chat_id), int(user_id)) or {}
    except Exception as error:
        logging.debug("Relationship v2 profile read failed: %s", error)
        return {}


def build_relationship_snapshot(
    profile: Mapping[str, Any],
    markers: Mapping[str, int],
) -> str:
    """Serialize only bounded observable relationship evidence."""
    lines: list[str] = []

    total = int(profile.get("total_messages", 0) or 0)
    replies = int(profile.get("replies_to_bot", 0) or 0)
    insults = int(profile.get("insults_to_bot", 0) or 0)
    relationship_level = int(profile.get("relationship_level", 0) or 0)

    if total or replies or insults or relationship_level:
        lines.append(
            f"observed totals: messages={total}; replies_to_yayceslav={replies}; "
            f"insults_to_yayceslav={insults}; relationship_level={relationship_level}"
        )

    marker_labels = {
        "banter": "mutual banter/laughter",
        "correction": "user corrected Yayceslav",
        "apology": "user apologized",
        "gratitude": "user thanked Yayceslav",
        "disagreement": "explicit disagreement",
        "reconciliation": "reconciliation/de-escalation",
    }
    marker_bits = [
        f"{marker_labels[key]} x{int(markers[key])}"
        for key in marker_labels
        if int(markers.get(key, 0) or 0) > 0
    ]
    if marker_bits:
        lines.append("relationship events: " + "; ".join(marker_bits))

    topics = [
        str(item).strip()
        for item in (profile.get("callback_terms") or ())
        if str(item).strip()
    ][:5]
    if topics:
        lines.append(
            "safe recurring/recent callback topics actually used by this member: "
            + ", ".join(topics)
        )

    return "\n".join(lines)


def build_relationship_instruction(snapshot: str) -> str:
    if not snapshot.strip():
        return ""
    return f"""

RELATIONSHIP MEMORY V2 — CHAT-LOCAL HISTORY WITH THE CURRENT SENDER:
{snapshot}

RULES:
- This is relationship continuity, NOT a personality diagnosis and NOT a list of immutable traits.
- Current message and current tone override old history. Old conflict never authorizes attacking a neutral turn.
- A correction means Yayceslav may remember that he was corrected; if relevant, acknowledge it naturally instead of pretending infallibility.
- Apologies/reconciliation soften old conflict. Do not keep punishing someone after reconciliation.
- Banter history may justify a slightly more familiar joke, but only when the current turn is playful.
- Callback topics are words/topics this member actually used; they are NOT automatically preferences, professions, beliefs, or personal facts.
- Use callbacks sparsely. Never mechanically recite counts, database fields, or say you have a dossier.
- Do not infer or mention health, finances, politics, religion, sexuality, ethnicity, criminal history, or other sensitive characteristics from this memory.
- Never leak relationship memory across chats or users.
""".rstrip()


def _bound_argument(original: Any, args: tuple[Any, ...], kwargs: dict[str, Any], name: str) -> Any:
    if name in kwargs:
        return kwargs[name]
    try:
        bound = inspect.signature(original).bind_partial(*args, **kwargs)
        return bound.arguments.get(name)
    except Exception:
        return None


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _initialize_table(module)
    original = module.build_full_system_instruction
    if getattr(original, "_yayceslav_relationship_memory_v2", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def build_with_relationship_memory(*args: Any, **kwargs: Any) -> str:
        instruction = original(*args, **kwargs)
        chat_id = _bound_argument(original, args, kwargs, "chat_id")
        user_id = _bound_argument(original, args, kwargs, "user_id")
        chat_type = str(_bound_argument(original, args, kwargs, "chat_type") or "")
        if chat_id is None or user_id is None:
            return instruction
        if "group" not in chat_type.lower() and "supergroup" not in chat_type.lower():
            return instruction
        try:
            profile = _safe_profile_sync(module, int(chat_id), int(user_id))
            markers = _load_markers_sync(module, int(chat_id), int(user_id))
            snapshot = build_relationship_snapshot(profile, markers)
        except Exception as error:
            logging.debug("Relationship v2 prompt read failed: %s", error)
            return instruction
        return instruction + build_relationship_instruction(snapshot)

    build_with_relationship_memory._yayceslav_relationship_memory_v2 = True
    module.build_full_system_instruction = build_with_relationship_memory
    module._yayceslav_relationship_memory_v2_installed = True
    _INSTALLED = True
    logging.warning(
        "Relationship memory v2 ready: bounded social markers + safe member callbacks, %s-day TTL",
        MARKER_TTL_DAYS,
    )
    return True


async def _observe_relationship_markers(update: Any, context: Any) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        chat is None
        or user is None
        or getattr(user, "is_bot", False)
        or message is None
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or not getattr(message, "text", None)
    ):
        return

    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None)
    bot = getattr(context, "bot", None)
    bot_id = getattr(bot, "id", None)
    replying_to_bot = bool(reply_user is not None and bot_id is not None and int(reply_user.id) == int(bot_id))
    markers = classify_social_markers(str(message.text or ""), replying_to_bot=replying_to_bot)
    if not markers:
        return

    module = _find_bot_module()
    if module is None:
        return
    await asyncio.to_thread(
        _record_markers_sync,
        module,
        int(chat.id),
        int(user.id),
        markers,
    )


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    if not install():
        logging.warning("Relationship memory v2: bot module not ready")
        return
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_relationship_markers),
        group=14,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
