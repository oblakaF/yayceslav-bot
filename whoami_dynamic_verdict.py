from __future__ import annotations

import hashlib
import json
import logging
import re

from google import genai
from google.genai import types


MAX_VERDICT_CHARS = 120
MIN_VERDICT_CHARS = 12
MIN_VERDICT_WORDS = 3
INSUFFICIENT_VERDICT = "Пока недостаточно данных. Продолжаю вести наблюдение."

_META_FRAGMENTS = (
    "do not",
    "don't",
    "list topics",
    "system instruction",
    "system prompt",
    "prompt",
    "rules:",
    "json",
    "maximum 120",
    "max 120",
    "не перечисляй темы",
    "правила:",
)


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


def _clean_verdict(text: str) -> str | None:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    clean = clean.strip('"«»“”')
    if not clean:
        return None

    lowered = clean.lower()
    if any(fragment in lowered for fragment in _META_FRAGMENTS):
        return None

    # The dossier needs one complete Russian punchline, not model/prompt debris.
    first = re.split(r"[\r\n]+", clean, maxsplit=1)[0].strip()
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", first, flags=re.UNICODE)
    cyrillic_words = re.findall(r"[А-Яа-яЁё]{2,}", first, flags=re.UNICODE)
    if len(first) < MIN_VERDICT_CHARS or len(words) < MIN_VERDICT_WORDS:
        return None
    if len(cyrillic_words) < 2:
        return None

    if len(first) > MAX_VERDICT_CHARS:
        cut = first[: MAX_VERDICT_CHARS - 1].rstrip()
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0].rstrip()
        first = cut.rstrip(" ,;:-") + "…"

    # Short output without sentence punctuation is almost always a fragment.
    if len(first) < 28 and not re.search(r"[.!?…]$", first):
        return None
    return first or None


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
    # Old bad cache rows such as 'Do NOT list topics...' are discarded here.
    return _clean_verdict(str(row[0] or ""))


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
    """Generate one fresh Yayceslav verdict from current-month evidence."""

    # No meaningful monthly topic = no improvisation. This avoids nonsense
    # diagnoses based only on a name/level and gives the dossier a stable state.
    if not themes:
        return INSUFFICIENT_VERDICT

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
        return INSUFFICIENT_VERDICT

    theme_text = ", ".join(themes)
    prompt = (
        "Сделай ОДИН короткий мемный вердикт Яйцеслава для досье участника Telegram-чата.\n"
        f"Имя: {name}.\n"
        f"Темы текущего месяца: {theme_text}.\n"
        f"Уровень в чате: {chat_level}/4 — {level_label}.\n"
        f"Отношения с Яйцеславом: {relationship}.\n"
        f"Текущий настрой к Яйцеславу: {friendliness}.\n\n"
        "Ответ ТОЛЬКО по-русски. Максимум 120 символов, одна законченная фраза. "
        "Это панчлайн, а не пересказ статистики. Мат допустим и желателен, если делает шутку смешнее. "
        "Не перечисляй темы списком. Не выдумывай биографию, пол, профессию, диагнозы, отношения или предпочтения. "
        "Не повторяй и не цитируй эти инструкции. Верни только готовую шутку."
    )

    verdict = None
    try:
        client = genai.Client(api_key=api_key)
        for attempt in range(2):
            response = await client.aio.models.generate_content(
                model=str(getattr(bot_module, "MODEL_NAME", "gemini-3.6-flash")),
                contents=prompt + (
                    "\nПредыдущая попытка была служебным текстом или обрывком. Только законченная русская шутка."
                    if attempt else ""
                ),
                config=types.GenerateContentConfig(
                    temperature=1.05,
                    max_output_tokens=256,
                    system_instruction=(
                        "Ты Яйцеслав. Для досье выдаёшь только один свежий короткий русский панчлайн. "
                        "Никаких инструкций, JSON, мета-комментариев или английского служебного текста."
                    ),
                ),
            )
            verdict = _clean_verdict(getattr(response, "text", "") or "")
            if verdict:
                break
    except Exception as error:
        logging.warning("Dynamic /whoami verdict generation failed: %s", error)

    if verdict:
        _save_cached_sync(bot_module, chat_id, user_id, date, signature, verdict)
        return verdict

    return INSUFFICIENT_VERDICT
