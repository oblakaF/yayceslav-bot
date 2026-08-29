from __future__ import annotations

import asyncio
import random
import re
import sys
from typing import Any

import social_engine
from telegram.constants import ChatType
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, MessageHandler, filters


_PREPARED_APPLICATION_IDS: set[int] = set()

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+", re.UNICODE)

_WORD_STOPWORDS = {
    "это", "как", "что", "чтобы", "когда", "где", "куда", "откуда", "почему",
    "зачем", "кто", "кого", "кому", "чем", "чего", "какой", "какая", "какие",
    "так", "там", "тут", "здесь", "вот", "уже", "еще", "ещё", "просто", "вообще",
    "сейчас", "сегодня", "вчера", "завтра", "потом", "теперь", "тогда", "очень",
    "тоже", "также", "снова", "опять",
    "можно", "надо", "нужно", "будет", "было", "были", "есть", "нет", "да",
    "ну", "ага", "или", "либо", "если", "для", "про", "при", "без", "под",
    "над", "между", "через", "после", "перед", "из", "от", "до", "по", "на",
    "в", "во", "за", "с", "со", "к", "ко", "у", "и", "а", "но", "же", "бы",
    "я", "ты", "он", "она", "оно", "мы", "вы", "они", "меня", "тебя", "его",
    "ее", "её", "нас", "вас", "их", "мне", "тебе", "ему", "ей", "им", "мой",
    "моя", "моё", "мои", "твой", "твоя", "твои", "наш", "ваш", "свой", "сам",
    "сама", "сами", "этот", "эта", "эти", "тот", "та", "те", "такой", "такая",
    "больше", "меньше", "хорошо", "плохо", "нормально", "короче", "ладно",
    "яйцеслав", "бот", "бобер", "бобр",
}

_THEME_NOISE = _WORD_STOPWORDS | {
    "моду", "одобряет", "одобряю", "одобрил", "сказал", "сказала", "говорит",
    "говорю", "ответил", "ответила", "пишет", "пишу", "написал", "написала",
    "делает", "сделал", "сделай", "видит", "вижу", "знает", "знаю", "думает",
    "думаю", "хочет", "хочу", "может", "могут", "буду", "будешь", "давай",
    "окей", "ок", "норм", "правильно", "реально", "тип", "типа",
    "ответ", "ответа", "ответы", "вопрос", "вопроса", "вопросы", "проверил",
    "проверила", "проверь", "починил", "починила", "почини", "кажется", "вроде",
    "сделано", "получилось", "стороны", "другой", "другая", "другие", "всех",
}


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _normalize_word(word: str) -> str:
    return (word or "").strip().lower().replace("ё", "е")


def _display_word_ok(word: str) -> bool:
    normalized = _normalize_word(word)
    if len(normalized) < 3:
        return False
    if normalized in _WORD_STOPWORDS:
        return False
    if normalized.isdigit():
        return False
    return True


def _theme_ok(term: str) -> bool:
    normalized = _normalize_word(term)
    if not normalized or len(normalized) < 3:
        return False
    if normalized in _THEME_NOISE:
        return False
    words = [_normalize_word(w) for w in _WORD_RE.findall(normalized)]
    if not words:
        return False
    return all(w not in _THEME_NOISE and len(w) >= 3 for w in words)


def _current_month(bot_module) -> str:
    now = bot_module.current_msk_datetime()
    return f"{now.year:04d}-{now.month:02d}"


def _initialize_tables(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_word_counts (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_id, word)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_word_counts_rank
            ON member_word_counts(chat_id, user_id, occurrences DESC, last_seen DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_word_counts_monthly (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                word TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 0,
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_id, month, word)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_word_counts_monthly_rank
            ON member_word_counts_monthly(chat_id, user_id, month, occurrences DESC, last_seen DESC)
            """
        )
        connection.commit()


def _record_words_sync(bot_module, chat_id: int, user_id: int, text: str) -> None:
    words = [_normalize_word(word) for word in _WORD_RE.findall(text or "")]
    words = [word for word in words if _display_word_ok(word)]
    if not words:
        return

    month = _current_month(bot_module)
    with bot_module.get_db_connection() as connection:
        for word in words:
            connection.execute(
                """
                INSERT INTO member_word_counts(chat_id, user_id, word, occurrences)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(chat_id, user_id, word) DO UPDATE SET
                    occurrences = occurrences + 1,
                    last_seen = datetime('now')
                """,
                (chat_id, user_id, word),
            )
            connection.execute(
                """
                INSERT INTO member_word_counts_monthly(chat_id, user_id, month, word, occurrences)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(chat_id, user_id, month, word) DO UPDATE SET
                    occurrences = occurrences + 1,
                    last_seen = datetime('now')
                """,
                (chat_id, user_id, month, word),
            )

        connection.execute(
            """
            DELETE FROM member_word_counts
            WHERE chat_id = ? AND user_id = ?
              AND occurrences = 1
              AND last_seen < datetime('now', '-90 days')
            """,
            (chat_id, user_id),
        )
        # Keep only a small rolling history of monthly counters. The dossier only
        # reads the current month, so this is deliberately bounded.
        connection.execute(
            """
            DELETE FROM member_word_counts_monthly
            WHERE last_seen < datetime('now', '-190 days')
            """
        )
        connection.commit()


def _favorite_word_sync(bot_module, chat_id: int, user_id: int):
    month = _current_month(bot_module)
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT word, occurrences
            FROM member_word_counts_monthly
            WHERE chat_id = ? AND user_id = ? AND month = ?
              AND occurrences >= 2
            ORDER BY occurrences DESC, last_seen DESC, word ASC
            LIMIT 20
            """,
            (chat_id, user_id, month),
        ).fetchall()
    for word, count in rows:
        if _display_word_ok(str(word)):
            return str(word), int(count)
    return None, 0


def _themes_sync(bot_module, chat_id: int, user_id: int) -> list[str]:
    month = _current_month(bot_module)
    with bot_module.get_db_connection() as connection:
        try:
            rows = connection.execute(
                """
                SELECT word, occurrences
                FROM member_word_counts_monthly
                WHERE chat_id = ? AND user_id = ? AND month = ?
                  AND occurrences >= 4
                ORDER BY occurrences DESC, last_seen DESC, word ASC
                LIMIT 40
                """,
                (chat_id, user_id, month),
            ).fetchall()
        except Exception:
            rows = []

    result: list[str] = []
    for word, _count in rows:
        clean = str(word).strip()
        if not _theme_ok(clean):
            continue
        result.append(clean)
        if len(result) >= 3:
            break
    return result


def _contains(themes: list[str], *stems: str) -> bool:
    text = " ".join(_normalize_word(item) for item in themes)
    return any(stem in text for stem in stems)


def topical_verdict(themes: list[str], *, fallback_level: int = 0, rng=random) -> str:
    if _contains(themes, "милф") and _contains(themes, "steam", "стим"):
        return "Любитель милф и цифровых страданий."
    if _contains(themes, "милф"):
        return rng.choice((
            "Любитель милф. Или сама милфа — следствие разбирается.",
            "Милфолог-любитель.",
            "По милфам специалист, по остальному уточняется.",
        ))
    if _contains(themes, "steam", "стим"):
        return rng.choice((
            "Житель Steam с временной пропиской в реальности.",
            "Цифровой дачник Steam.",
        ))
    if _contains(themes, "дота", "dota", "кс", "counter", "игр"):
        return "Игровой отдел дивана."
    if _contains(themes, "пив", "водк", "вино", "бух", "алко"):
        return "Пивной аналитик широкого профиля."
    if _contains(themes, "код", "python", "питон", "github", "гитхаб"):
        return "Чинит то, что сам же открыл в редакторе."
    if themes:
        topic = themes[0]
        return rng.choice((
            f"Специалист по теме «{topic}». Остальное факультативно.",
            f"Живёт где-то рядом с темой «{topic}».",
        ))

    if fallback_level >= 4:
        return "Несущая конструкция этого дурдома."
    if fallback_level >= 3:
        return "Старожил. Уже знает, где тут скрипит чат."
    if fallback_level >= 2:
        return "Местный. Уходить явно не собирается."
    if fallback_level >= 1:
        return "Осваивается. Компромат копится."
    return "Пока человек-загадка. Досье худеет."


async def _observe_words(update, context) -> None:
    del context
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        not chat
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or not user
        or user.is_bot
        or not message
        or not getattr(message, "text", None)
    ):
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    await asyncio.to_thread(_record_words_sync, bot_module, chat.id, user.id, message.text)


async def _whoami_v3(update, context) -> None:
    """Legacy renderer kept for compatibility/tests; v4 owns /whoami runtime."""
    del context
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if not message or not chat or not user:
        raise ApplicationHandlerStop

    bot_module = _find_bot_module()
    if bot_module is None:
        raise ApplicationHandlerStop

    profile = await bot_module.get_member_profile(chat.id, user.id)
    if profile is None:
        await message.reply_text("Досье пустое. Даже клевету пока не на что опереть.")
        raise ApplicationHandlerStop

    total = int(profile.get("total_messages", 0) or 0)
    chat_level = social_engine.chat_level_from_messages(total)
    relationship_level = social_engine.relationship_level_from_profile(profile)
    insults = int(profile.get("insults_to_bot", 0) or 0)
    relationship = social_engine.relationship_status_label(
        relationship_level,
        insults_to_bot=insults,
    )

    favorite_word, favorite_count = await asyncio.to_thread(
        _favorite_word_sync, bot_module, chat.id, user.id
    )
    themes = await asyncio.to_thread(_themes_sync, bot_module, chat.id, user.id)

    name = profile.get("current_display_name") or user.full_name or user.username or str(user.id)
    title = profile.get("current_title") or "пока без регалий"

    lines = [
        "🥚 ДОСЬЕ ЯЙЦЕСЛАВА",
        str(name),
        f"🤝 Кто Яйцеславу: {relationship}",
        f"🏅 Титул: {title}",
        f"💬 Сообщений: {total}",
        f"🏚 Уровень в чате: {chat_level}/4 — {social_engine.chat_level_label(chat_level)}",
    ]

    if favorite_word:
        lines.append(f"🗣 Любимое слово: «{favorite_word}» — {favorite_count} раз")
    else:
        lines.append("🗣 Любимое слово: ещё не определилось")

    if themes:
        lines.append("👀 Видит вокруг: " + ", ".join(themes))

    lines.append("🎯 Вердикт: " + topical_verdict(themes, fallback_level=chat_level))

    await message.reply_text("\n".join(lines))
    raise ApplicationHandlerStop


def _prepare_application(application: Application) -> None:
    """Initialize v3 data collectors only; v4 is the sole /whoami renderer."""
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return

    _initialize_tables(bot_module)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_words),
        group=6,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
