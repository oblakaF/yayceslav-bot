from __future__ import annotations

import re

import whoami_profile_v3_runtime as profile_runtime


_PATCHED = False

_TOPIC_NOISE = profile_runtime._THEME_NOISE | {
    "ответ", "ответа", "ответы", "ответом", "ответить", "отвечать",
    "сторона", "стороны", "другой", "другая", "другие", "другое",
    "всех", "всем", "всего", "всякий", "всякое", "всякие",
    "вроде", "кажется", "похоже", "смысл", "вопрос", "вопросы",
    "сообщение", "сообщения", "слово", "слова", "текст", "текста",
    "человек", "люди", "дело", "дела", "штука", "штуки",
    "раз", "раза", "разом", "место", "места", "время", "разговор",
    "говорил", "говорила", "говорили", "сказать", "скажи", "сказали",
    "проверил", "проверила", "проверили", "проверить", "проверь",
    "починил", "починила", "починили", "починить", "сделано",
    "получилось", "получается", "получится", "работает", "работал",
    "работала", "работали", "понял", "поняла", "понятно",
    "нравится", "хочется", "нормальный", "нормальная", "нормальные",
}

_TOKEN_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9+_.#-]{2,31}$")


def _topic_word_ok(term: str) -> bool:
    clean = str(term or "").strip()
    norm = profile_runtime._normalize_word(clean)
    if not clean or not _TOKEN_RE.fullmatch(clean):
        return False
    if " " in clean:
        return False
    if norm in _TOPIC_NOISE:
        return False
    if not profile_runtime._theme_ok(clean):
        return False
    if norm.isdigit():
        return False
    return True


def _themes_monthly_ranked(bot_module, chat_id: int, user_id: int) -> list[str]:
    """Return true calendar-month subjects from the dedicated monthly table."""

    month = profile_runtime._current_month(bot_module)
    with bot_module.get_db_connection() as connection:
        try:
            rows = connection.execute(
                """
                SELECT word, occurrences, last_seen
                FROM member_word_counts_monthly
                WHERE chat_id = ? AND user_id = ? AND month = ?
                  AND occurrences >= 4
                ORDER BY occurrences DESC, last_seen DESC, word ASC
                LIMIT 100
                """,
                (chat_id, user_id, month),
            ).fetchall()
        except Exception:
            rows = []

    candidates: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for word, occurrences, _last_seen in rows:
        clean = str(word or "").strip()
        norm = profile_runtime._normalize_word(clean)
        if norm in seen or not _topic_word_ok(clean):
            continue
        seen.add(norm)
        candidates.append((int(occurrences or 0), clean, norm))

    candidates.sort(key=lambda item: (-item[0], item[1].lower()))
    return [item[1] for item in candidates[:3]]


def install() -> None:
    global _PATCHED
    if _PATCHED:
        return
    profile_runtime._themes_sync = _themes_monthly_ranked
    _PATCHED = True


install()
