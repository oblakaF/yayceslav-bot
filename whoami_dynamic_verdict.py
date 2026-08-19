from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types


MAX_VERDICT_CHARS = 120


def _signature_payload(
    *,
    month: str,
    themes: list[str],
    chat_level: int,
    relationship: str,
    friendliness: str,
) -> str:
    payload = {
        "month": month,
        "themes": list(themes),
        "chat_level": int(chat_level),
        "relationship": str(relationship),
        "friendliness": str(friendliness),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _initialize_cache(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS whoami_verdict_cache (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                input_signature TEXT NOT NULL,
                verdict TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_id, date)
            )
            """
        )
        connection.commit()


def _load_cached_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    date: str,
    signature: str,
) -> str | None:
    _initialize_cache(bot_module)
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT verdict, input_signature
            FROM whoami_verdict_cache
            WHERE chat_id = ? AND user_id = ? AND date = ?
            """,
            (chat_id, user_id, date),
        ).fetchone()
    if not row or str(row[1]) != signature:
        return None
    verdict = str(row[0] or "").strip()
    return verdict or None


def _save_cached_sync(
    bot_module,
    chat_id: int,
    user_id: int,
    date: str,
    signature: str,
    verdict: str,
) -> None:
    _initialize_cache(bot_module)
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO whoami_verdict_cache
                (chat_id, user_id, date, input_signature, verdict)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                input_signature = excluded.input_signature,
                verdict = excluded.verdict,
                created_at = datetime('now')
            """,
            (chat_id, user_id, date, signature, verdict),
        )
        connection.commit()


def _clean_verdict(text: str) -> str | None:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    clean = clean.strip('"«»“”')
    if not clean:
        return None

    # The dossier needs one punchline, not a mini monologue.
    first = re.split(r"[\r\n]+", clean, maxsplit=1)[0].strip()
    if len(first) > MAX_VERDICT_CHARS:
        cut = first[: MAX_VERDICT_CHARS - 1].rstrip()
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0].rstrip()
        first = cut.rstrip(" ,;:-") + "…"
    return first or None


async def generate_verdict(
    bot_module,
    *,
    chat_id: int,
    user_id: int,
    name: str,
    themes: list[str],
    chat_level: int,
    level_label: str,
    relationship: str,
    friendliness: str,
) -> str | None:
    """Generate one fresh Yayceslav verdict from current-month evidence.

    There are deliberately no topic->joke templates here. Gemini receives only
    the current monthly themes and social state, then writes a new punchline.
    """

    now = bot_module.current_msk_datetime()
    date = now.date().isoformat()
    month = f"{now.year:04d}-{now.month:02d}"
    signature = _signature_payload(
        month=month,
        themes=themes,
        chat_level=chat_level,
        relationship=relationship,
        friendliness=friendliness,
    )

    cached = _load_cached_sync(bot_module, chat_id, user_id, date, signature)
    if cached:
        return cached

    api_key = str(getattr(bot_module, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None

    theme_text = ", ".join(themes) if themes else "устойчивые темы пока не набрались"
    prompt = (
        "Сделай ОДИН короткий мемный вердикт Яйцеслава для досье участника Telegram-чата.\n"
        f"Имя: {name}.\n"
        f"Темы текущего месяца: {theme_text}.\n"
        f"Уровень в чате: {chat_level}/4 — {level_label}.\n"
        f"Отношения с Яйцеславом: {relationship}.\n"
        f"Текущий настрой к Яйцеславу: {friendliness}.\n\n"
        "Правила: максимум 120 символов, одна фраза, без заголовка и без кавычек. "
        "Это должен быть панчлайн, а не описание статистики. Мат разрешён и желателен, "
        "только если реально делает шутку смешнее. Не перечисляй темы через запятую. "
        "Не используй заготовки и не повторяй формулировки из входа. "
        "Не выдумывай биографические факты, пол, профессию, диагнозы, отношения или предпочтения: "
        "шути только из данных выше. Если тема вроде «милфы» — это лишь тема сообщений, не вывод о личности."
    )

    try:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=str(getattr(bot_module, "MODEL_NAME", "gemini-3.6-flash")),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=1.15,
                max_output_tokens=96,
                system_instruction=(
                    "Ты Яйцеслав: живой, мемный, острый персонаж Telegram-чата. "
                    "Для досье выдаёшь только один свежий короткий панчлайн."
                ),
            ),
        )
        verdict = _clean_verdict(getattr(response, "text", "") or "")
    except Exception as error:
        logging.warning("Dynamic /whoami verdict generation failed: %s", error)
        return None

    if verdict:
        _save_cached_sync(bot_module, chat_id, user_id, date, signature, verdict)
    return verdict
