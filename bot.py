import asyncio
import csv
import logging
import mimetypes
import os
import random
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import edge_tts
from collections import defaultdict, deque
from gtts import gTTS
from ddgs import DDGS
from telegram.error import BadRequest
from docx import Document as DocxDocument
from dotenv import load_dotenv
from google import genai
from google.genai import types
from openpyxl import load_workbook
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
    Update,
)
from telegram.constants import ChatAction, ChatType
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import humor_engine
import intent
from personality import (
    DEFAULT_USER_SETTINGS,
    build_system_instruction,
    detect_conversation_mode,
    is_serious_text,
    VOICE_STYLE_INSTRUCTION,
)
from vocabulary import (
    BASE_REPLIES,
    CRINGE_REPLIES,
    GOY_REPLIES,
    HARD_RANDOM_REPLIES,
    HARD_REACTION_EMOJIS,
    MOODS,
    NISHIY_REPLIES,
    ROASTS,
    SIX_SEVEN_REPLIES,
    SKUF_REPLIES,
    WISDOMS,
    YAYCESLAV_REPLIES,
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BOT_OWNER_ID_RAW = os.getenv(
    "BOT_OWNER_ID",
    "",
).strip()

BOT_OWNER_ID = (
    int(BOT_OWNER_ID_RAW)
    if BOT_OWNER_ID_RAW.isdigit()
    else 0
)

MODEL_NAME = "gemini-3.1-flash-lite"
# ============================================================
# ЗАЩИТА ОТ СПАМА И ЛИМИТЫ
# ============================================================

# Максимальная длина обычного текстового запроса
MAX_USER_TEXT_CHARS = 3000

# Лимиты формата:
# "тип запроса": (количество запросов, период в секундах)
RATE_LIMITS = {
    "general": (5, 60.0),
    "media": (3, 60.0),
    "search": (2, 60.0),
}

# Не более трёх одновременных запросов к Gemini
GEMINI_SEMAPHORE = asyncio.Semaphore(3)

# Не более двух одновременных интернет-поисков
SEARCH_SEMAPHORE = asyncio.Semaphore(2)

# Здесь временно хранятся моменты запросов пользователей
REQUEST_TIMES: dict[
    tuple[int, str],
    deque[float],
] = defaultdict(deque)

# Не присылаем предупреждение о лимите каждую секунду
LAST_LIMIT_WARNING: dict[
    tuple[int, str],
    float,
] = {}

LIMIT_WARNING_COOLDOWN = 10.0

# Настройки голоса Яйцеслава
TTS_VOICE = "ru-RU-DmitryNeural"
TTS_RATE = "-5%"
TTS_PITCH = "-25Hz"
TTS_VOLUME = "+3%"

# Максимальная длина текста для одного голосового ответа
MAX_TTS_CHARS = 1500

# Папка для временных файлов
TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)
# ============================================================
# ПОСТОЯННАЯ СТАТИСТИКА
# ============================================================

# На Railway база хранится на подключённом Volume.
# Локально используется обычная папка data.
RAILWAY_DATA_DIR = Path("/app/data")

if RAILWAY_DATA_DIR.exists():
    DATA_DIR = RAILWAY_DATA_DIR
else:
    DATA_DIR = Path("data")

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

STATS_DB_PATH = DATA_DIR / "yayceslav_stats.db"


def get_db_connection(
    db_path: Path | None = None,
    timeout: float = 30,
) -> sqlite3.Connection:
    """
    Открывает соединение с нужными PRAGMA.

    db_path читается из STATS_DB_PATH заново при каждом вызове
    (а не как значение параметра по умолчанию) — иначе тесты,
    подменяющие bot.STATS_DB_PATH через monkeypatch, тихо продолжали
    бы писать в реальный файл базы, захваченный на момент импорта.

    journal_mode=WAL сохраняется в самом файле базы, но дешевле
    подтвердить его на каждом соединении, чем гадать, установлен ли он.
    foreign_keys обязательно включать на каждом соединении отдельно —
    SQLite не помнит это между подключениями.
    """

    if db_path is None:
        db_path = STATS_DB_PATH

    connection = sqlite3.connect(
        db_path,
        timeout=timeout,
    )
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    column_ddl: str,
) -> None:
    """
    Добавляет колонку, если её ещё нет — без разрушительной миграции.

    CREATE TABLE IF NOT EXISTS не добавляет новые колонки к уже
    существующей таблице, поэтому колонки, появившиеся после первого
    релиза схемы, нужно домигрировать так.
    """

    existing_columns = {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table})"
        )
    }

    if column not in existing_columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column_ddl}"
        )


def initialize_stats_database() -> None:
    """Создаёт постоянную базу статистики."""

    with get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stats (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                character TEXT NOT NULL DEFAULT 'classic',
                response_style TEXT NOT NULL DEFAULT 'bold',
                response_length TEXT NOT NULL DEFAULT 'normal',
                voice_enabled INTEGER NOT NULL DEFAULT 0,
                search_mode TEXT NOT NULL DEFAULT 'button',
                roughness TEXT NOT NULL DEFAULT 'medium'
            )
            """
        )

        # Хранит хард-мод и связанные настройки чата так,
        # чтобы они переживали рестарт Railway (раньше жили
        # только в context.chat_data и обнулялись при рестарте).
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY REFERENCES chats(chat_id),
                hard_mode_enabled INTEGER NOT NULL DEFAULT 1,
                hard_level TEXT NOT NULL DEFAULT 'normal',
                reaction_chance REAL NOT NULL DEFAULT 0.70,
                random_reply_chance REAL NOT NULL DEFAULT 0.16,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # Счётчики /hard_stats добавлены отдельной миграцией —
        # на момент первого релиза chat_settings их не было.
        _ensure_column(
            connection,
            "chat_settings",
            "reactions_count",
            "reactions_count INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            connection,
            "chat_settings",
            "random_replies_count",
            "random_replies_count INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            connection,
            "chat_settings",
            "trigger_replies_count",
            "trigger_replies_count INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            connection,
            "chat_settings",
            "last_intervention_at",
            "last_intervention_at TEXT",
        )

        connection.commit()


initialize_stats_database()


def get_user_settings_sync(
    user_id: int,
) -> dict[str, Any]:
    """Получает сохранённые настройки пользователя."""

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO user_settings (
                user_id
            )
            VALUES (?)
            """,
            (user_id,),
        )

        row = connection.execute(
            """
            SELECT
                character,
                response_style,
                response_length,
                voice_enabled,
                search_mode,
                roughness
            FROM user_settings
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        connection.commit()

    if row is None:
        return DEFAULT_USER_SETTINGS.copy()

    return {
        "character": str(row[0]),
        "response_style": str(row[1]),
        "response_length": str(row[2]),
        "voice_enabled": bool(row[3]),
        "search_mode": str(row[4]),
        "roughness": str(row[5]),
    }


async def get_user_settings(
    user_id: int,
) -> dict[str, Any]:
    """Читает настройки без блокировки бота."""

    return await asyncio.to_thread(
        get_user_settings_sync,
        user_id,
    )
USER_SETTING_COLUMNS = {
    "character",
    "response_style",
    "response_length",
    "voice_enabled",
    "search_mode",
    "roughness",
}


def update_user_setting_sync(
    user_id: int,
    setting_name: str,
    setting_value: Any,
) -> None:
    """Сохраняет одну настройку пользователя."""

    if setting_name not in USER_SETTING_COLUMNS:
        raise ValueError(
            f"Неизвестная настройка: {setting_name}"
        )

    if setting_name == "voice_enabled":
        database_value = int(
            bool(setting_value)
        )
    else:
        database_value = str(
            setting_value
        )

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO user_settings (
                user_id
            )
            VALUES (?)
            """,
            (user_id,),
        )

        connection.execute(
            f"""
            UPDATE user_settings
            SET {setting_name} = ?
            WHERE user_id = ?
            """,
            (
                database_value,
                user_id,
            ),
        )

        connection.commit()


async def update_user_setting(
    user_id: int,
    setting_name: str,
    setting_value: Any,
) -> None:
    """Сохраняет настройку без блокировки бота."""

    await asyncio.to_thread(
        update_user_setting_sync,
        user_id,
        setting_name,
        setting_value,
    )


DEFAULT_CHAT_SETTINGS = {
    "hard_mode_enabled": True,
    "hard_level": "normal",
    # Совпадает с HARD_REACTION_CHANCE / HARD_RANDOM_REPLY_CHANCE
    # и со значениями по умолчанию в схеме chat_settings ниже —
    # эти константы объявлены позже в файле, поэтому здесь просто
    # числа, а не ссылки на них.
    "reaction_chance": 0.70,
    "random_reply_chance": 0.16,
    "reactions_count": 0,
    "random_replies_count": 0,
    "trigger_replies_count": 0,
    "last_intervention_at": None,
}

CHAT_SETTING_COLUMNS = {
    "hard_mode_enabled",
    "hard_level",
    "reaction_chance",
    "random_reply_chance",
}


def get_chat_settings_sync(
    chat_id: int,
    chat_type: str = "group",
) -> dict[str, Any]:
    """Получает сохранённые настройки чата (хард-мод, уровень, статистика)."""

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO chats (chat_id, chat_type)
            VALUES (?, ?)
            """,
            (chat_id, chat_type),
        )

        connection.execute(
            """
            INSERT OR IGNORE INTO chat_settings (chat_id)
            VALUES (?)
            """,
            (chat_id,),
        )

        row = connection.execute(
            """
            SELECT
                hard_mode_enabled,
                hard_level,
                reaction_chance,
                random_reply_chance,
                reactions_count,
                random_replies_count,
                trigger_replies_count,
                last_intervention_at
            FROM chat_settings
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()

        connection.commit()

    if row is None:
        return DEFAULT_CHAT_SETTINGS.copy()

    return {
        "hard_mode_enabled": bool(row[0]),
        "hard_level": str(row[1]),
        "reaction_chance": float(row[2]),
        "random_reply_chance": float(row[3]),
        "reactions_count": int(row[4]),
        "random_replies_count": int(row[5]),
        "trigger_replies_count": int(row[6]),
        "last_intervention_at": row[7],
    }


async def get_chat_settings(
    chat_id: int,
    chat_type: str = "group",
) -> dict[str, Any]:
    """Читает настройки чата без блокировки бота."""

    return await asyncio.to_thread(
        get_chat_settings_sync,
        chat_id,
        chat_type,
    )


def update_chat_setting_sync(
    chat_id: int,
    setting_name: str,
    setting_value: Any,
    chat_type: str = "group",
) -> None:
    """Сохраняет одну настройку чата."""

    if setting_name not in CHAT_SETTING_COLUMNS:
        raise ValueError(
            f"Неизвестная настройка чата: {setting_name}"
        )

    if setting_name == "hard_mode_enabled":
        database_value: Any = int(bool(setting_value))
    elif setting_name in ("reaction_chance", "random_reply_chance"):
        database_value = float(setting_value)
    else:
        database_value = str(setting_value)

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO chats (chat_id, chat_type)
            VALUES (?, ?)
            """,
            (chat_id, chat_type),
        )

        connection.execute(
            """
            INSERT OR IGNORE INTO chat_settings (chat_id)
            VALUES (?)
            """,
            (chat_id,),
        )

        connection.execute(
            f"""
            UPDATE chat_settings
            SET {setting_name} = ?, updated_at = datetime('now')
            WHERE chat_id = ?
            """,
            (database_value, chat_id),
        )

        connection.commit()


async def update_chat_setting(
    chat_id: int,
    setting_name: str,
    setting_value: Any,
    chat_type: str = "group",
) -> None:
    """Сохраняет настройку чата без блокировки бота."""

    await asyncio.to_thread(
        update_chat_setting_sync,
        chat_id,
        setting_name,
        setting_value,
        chat_type,
    )


HARD_STAT_COUNTER_COLUMNS = {
    "reactions_count",
    "random_replies_count",
    "trigger_replies_count",
}


def increment_chat_hard_stat_sync(
    chat_id: int,
    counter_name: str,
    chat_type: str = "group",
) -> None:
    """Увеличивает один из счётчиков /hard_stats на единицу."""

    if counter_name not in HARD_STAT_COUNTER_COLUMNS:
        raise ValueError(
            f"Неизвестный счётчик хард-мода: {counter_name}"
        )

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO chats (chat_id, chat_type)
            VALUES (?, ?)
            """,
            (chat_id, chat_type),
        )

        connection.execute(
            """
            INSERT OR IGNORE INTO chat_settings (chat_id)
            VALUES (?)
            """,
            (chat_id,),
        )

        connection.execute(
            f"""
            UPDATE chat_settings
            SET {counter_name} = {counter_name} + 1,
                last_intervention_at = datetime('now')
            WHERE chat_id = ?
            """,
            (chat_id,),
        )

        connection.commit()


async def increment_chat_hard_stat(
    chat_id: int,
    counter_name: str,
    chat_type: str = "group",
) -> None:
    """Увеличивает счётчик хард-мода без блокировки бота."""

    await asyncio.to_thread(
        increment_chat_hard_stat_sync,
        chat_id,
        counter_name,
        chat_type,
    )


CHARACTER_LABELS = {
    "classic": "🥚 Классический",
    "rus": "🗿 Древний рус",
    "professor": "🎓 Профессор",
    "chaos": "🤡 Безумный",
    "calm": "🧘 Спокойный",
}

STYLE_LABELS = {
    "normal": "Нормальный",
    "bold": "Дерзкий",
    "serious": "Серьёзный",
}

LENGTH_LABELS = {
    "short": "Кратко",
    "normal": "Обычно",
    "detailed": "Подробно",
}

SEARCH_MODE_LABELS = {
    "auto": "Автоматически",
    "button": "Только по кнопке",
}

ROUGHNESS_LABELS = {
    "low": "Низкая",
    "medium": "Средняя",
    "high": "Высокая",
}


def build_settings_keyboard(
    settings: dict[str, Any],
) -> InlineKeyboardMarkup:
    """Создаёт главное меню настроек."""

    character = CHARACTER_LABELS.get(
        str(settings.get("character")),
        CHARACTER_LABELS["classic"],
    )

    style = STYLE_LABELS.get(
        str(settings.get("response_style")),
        STYLE_LABELS["bold"],
    )

    response_length = LENGTH_LABELS.get(
        str(settings.get("response_length")),
        LENGTH_LABELS["normal"],
    )

    search_mode = SEARCH_MODE_LABELS.get(
        str(settings.get("search_mode")),
        SEARCH_MODE_LABELS["button"],
    )

    roughness = ROUGHNESS_LABELS.get(
        str(settings.get("roughness")),
        ROUGHNESS_LABELS["medium"],
    )

    voice = (
        "Включён"
        if settings.get("voice_enabled")
        else "Выключен"
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🎭 Персонаж: {character}",
                    callback_data="settings_character",
                )
            ],
            [
                InlineKeyboardButton(
                    f"💬 Стиль: {style}",
                    callback_data="settings_style",
                )
            ],
            [
                InlineKeyboardButton(
                    f"📏 Длина: {response_length}",
                    callback_data="settings_length",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🔊 Голос: {voice}",
                    callback_data="settings_voice",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🔎 Поиск: {search_mode}",
                    callback_data="settings_search",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🤬 Грубость: {roughness}",
                    callback_data="settings_roughness",
                )
            ],
            [
                InlineKeyboardButton(
                    "♻️ Сбросить настройки",
                    callback_data="settings_reset",
                )
            ],
        ]
    )  
def increment_stat_sync(
    stat_name: str,
    amount: int = 1,
) -> None:
    """Увеличивает постоянный счётчик."""

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO stats (
                name,
                value
            )
            VALUES (?, ?)
            ON CONFLICT(name)
            DO UPDATE SET
                value = value + excluded.value
            """,
            (
                stat_name,
                amount,
            ),
        )

        connection.commit()


async def increment_stat(
    stat_name: str,
    amount: int = 1,
) -> None:
    """Записывает статистику без блокировки бота."""

    await asyncio.to_thread(
        increment_stat_sync,
        stat_name,
        amount,
    )


def register_user_and_chat_sync(
    user_id: int | None,
    chat_id: int | None,
    chat_type: str,
) -> None:
    """Запоминает уникального пользователя и чат."""

    with get_db_connection() as connection:
        if user_id is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO users (
                    user_id
                )
                VALUES (?)
                """,
                (user_id,),
            )

        if chat_id is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO chats (
                    chat_id,
                    chat_type
                )
                VALUES (?, ?)
                """,
                (
                    chat_id,
                    chat_type,
                ),
            )

        connection.commit()


async def register_user_and_chat(
    update: Update,
) -> None:
    """Записывает уникального пользователя и чат."""

    user_id = (
        update.effective_user.id
        if update.effective_user
        else None
    )

    chat_id = (
        update.effective_chat.id
        if update.effective_chat
        else None
    )

    chat_type = (
        update.effective_chat.type
        if update.effective_chat
        else "unknown"
    )

    await asyncio.to_thread(
        register_user_and_chat_sync,
        user_id,
        chat_id,
        chat_type,
    )


def get_stats_snapshot_sync() -> dict[str, int]:
    """Читает всю накопленную статистику."""

    with get_db_connection() as connection:
        stat_rows = connection.execute(
            """
            SELECT name, value
            FROM stats
            """
        ).fetchall()

        result = {
            str(name): int(value)
            for name, value in stat_rows
        }

        result["unique_users"] = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            ).fetchone()[0]
        )

        result["private_chats"] = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM chats
                WHERE chat_type = ?
                """,
                ("private",),
            ).fetchone()[0]
        )

        result["groups"] = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM chats
                WHERE chat_type IN (?, ?)
                """,
                (
                    "group",
                    "supergroup",
                ),
            ).fetchone()[0]
        )

    return result


async def get_stats_snapshot() -> dict[str, int]:
    """Читает статистику без блокировки бота."""

    return await asyncio.to_thread(
        get_stats_snapshot_sync
    )
# Максимальный размер принимаемого файла — 20 МБ
MAX_FILE_SIZE = 20 * 1024 * 1024

# ==============================
# ПАМЯТЬ БОТА
# ==============================

# Максимальный объём текста из DOCX, XLSX, CSV и TXT
MAX_EXTRACTED_CHARS = 50_000
# ============================================================
# КРАТКОВРЕМЕННАЯ ПАМЯТЬ
# ============================================================

# В группе бот помнит разговор 5 минут
GROUP_MEMORY_SECONDS = 5 * 60

# В личной переписке бот помнит текущую задачу 15 минут
PRIVATE_MEMORY_SECONDS = 15 * 60

# Не храним слишком много сообщений
GROUP_MEMORY_MAX_MESSAGES = 30
PRIVATE_MEMORY_MAX_MESSAGES = 40

# Память по идентификатору группы
GROUP_MEMORY: dict[int, deque] = defaultdict(deque)

# Память по идентификатору пользователя
PRIVATE_MEMORY: dict[int, deque] = defaultdict(deque)


if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "В файле .env не найден TELEGRAM_BOT_TOKEN"
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "В файле .env не найден GEMINI_API_KEY"
    )


gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def get_response_token_limit(
    user_settings: dict[str, Any] | None,
    normal_tokens: int = 360,
) -> int:
    """Возвращает лимит ответа с учётом настройки длины."""

    settings = DEFAULT_USER_SETTINGS.copy()

    if user_settings:
        settings.update(
            user_settings
        )

    response_length = str(
        settings.get(
            "response_length",
            "normal",
        )
    )

    token_limits = {
        "short": max(
            160,
            int(normal_tokens * 0.65),
        ),
        "normal": normal_tokens,
        "detailed": min(
            900,
            int(normal_tokens * 1.7),
        ),
    }

    return token_limits.get(
        response_length,
        normal_tokens,
    )    

# ============================================================
# ФУНКЦИИ КРАТКОВРЕМЕННОЙ ПАМЯТИ
# ============================================================

def clean_memory(
    messages: deque,
    memory_seconds: int,
) -> None:
    """Удаляет сообщения, которые уже слишком старые."""

    current_time = time.monotonic()

    while messages:
        message_time = messages[0][0]

        if current_time - message_time <= memory_seconds:
            break

        messages.popleft()


def remember_message(
    memory_store: dict[int, deque],
    memory_id: int,
    role: str,
    text: str,
    memory_seconds: int,
    max_messages: int,
    author_name: str = "",
) -> None:
    """Добавляет одно сообщение в память."""

    if not text:
        return

    messages = memory_store[memory_id]

    clean_memory(
        messages,
        memory_seconds,
    )

    clean_text = text.strip()[:800]

    messages.append(
        (
            time.monotonic(),
            role,
            author_name,
            clean_text,
        )
    )

    while len(messages) > max_messages:
        messages.popleft()


def build_memory_context(
    memory_store: dict[int, deque],
    memory_id: int,
    memory_seconds: int,
) -> str:
    """Собирает ещё не устаревшие сообщения в один контекст."""

    messages = memory_store[memory_id]

    clean_memory(
        messages,
        memory_seconds,
    )

    if not messages:
        return ""

    context_lines = []

    for _, role, author_name, text in messages:
        if role == "assistant":
            speaker = "Яйцеслав"
        elif author_name:
            speaker = author_name
        else:
            speaker = "Пользователь"

        context_lines.append(
            f"{speaker}: {text}"
        )

    return "\n".join(context_lines)


# ============================================================
# ПЕРИОДИЧЕСКАЯ ОЧИСТКА ПАМЯТИ ПРОЦЕССА
#
# REQUEST_TIMES, LAST_LIMIT_WARNING, GROUP_MEMORY и PRIVATE_MEMORY
# сами чистят СОДЕРЖИМОЕ по TTL, но ключи (chat_id/user_id) в этих
# defaultdict оставались навсегда, даже когда всё внутри устарело —
# на долгоживущем процессе Railway это медленная утечка памяти.
# ============================================================

CLEANUP_INTERVAL_SECONDS = 30 * 60
MEMORY_CLEANUP_MAX_AGE_SECONDS = 6 * 60 * 60


def cleanup_in_memory_state(
    max_age_seconds: float = MEMORY_CLEANUP_MAX_AGE_SECONDS,
) -> dict[str, int]:
    """Удаляет ключи чатов/пользователей, неактивные дольше max_age_seconds."""

    now = time.monotonic()

    stale_request_keys = [
        key
        for key, times in REQUEST_TIMES.items()
        if not times or (now - times[-1]) > max_age_seconds
    ]
    for key in stale_request_keys:
        REQUEST_TIMES.pop(key, None)

    stale_warning_keys = [
        key
        for key, last_time in LAST_LIMIT_WARNING.items()
        if (now - last_time) > max_age_seconds
    ]
    for key in stale_warning_keys:
        LAST_LIMIT_WARNING.pop(key, None)

    stale_memory_ids = 0

    for memory_store, memory_seconds in (
        (GROUP_MEMORY, GROUP_MEMORY_SECONDS),
        (PRIVATE_MEMORY, PRIVATE_MEMORY_SECONDS),
    ):
        empty_ids = []

        for memory_id, messages in memory_store.items():
            clean_memory(messages, memory_seconds)

            if not messages:
                empty_ids.append(memory_id)

        for memory_id in empty_ids:
            memory_store.pop(memory_id, None)

        stale_memory_ids += len(empty_ids)

    stale_humor_chats = humor_engine.prune_stale_state(
        max_age_seconds=max_age_seconds
    )

    stale_random_reply_chats = [
        chat_id
        for chat_id, history in GROUP_RANDOM_REPLY_TIMES.items()
        if not history or (now - history[-1]) > max_age_seconds
    ]
    for chat_id in stale_random_reply_chats:
        GROUP_RANDOM_REPLY_TIMES.pop(chat_id, None)
        GROUP_IGNORED_STREAK.pop(chat_id, None)

    stale_serious_chats = [
        chat_id
        for chat_id, last_serious_at in GROUP_LAST_SERIOUS_AT.items()
        if (now - last_serious_at) > max_age_seconds
    ]
    for chat_id in stale_serious_chats:
        GROUP_LAST_SERIOUS_AT.pop(chat_id, None)

    stale_trigger_user_keys = [
        key
        for key, last_time in TRIGGER_REPLY_LAST_BY_USER.items()
        if (now - last_time) > max_age_seconds
    ]
    for key in stale_trigger_user_keys:
        TRIGGER_REPLY_LAST_BY_USER.pop(key, None)

    return {
        "request_time_keys": len(stale_request_keys),
        "warning_keys": len(stale_warning_keys),
        "memory_ids": stale_memory_ids,
        "humor_chats": stale_humor_chats,
        "random_reply_chats": len(stale_random_reply_chats),
        "serious_chats": len(stale_serious_chats),
        "trigger_user_keys": len(stale_trigger_user_keys),
    }


async def periodic_cleanup_loop() -> None:
    """Фоновая задача: раз в CLEANUP_INTERVAL_SECONDS чистит устаревшее состояние."""

    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

        try:
            removed = cleanup_in_memory_state()

            logging.info(
                "Очистка памяти: %s",
                removed,
            )

        except Exception as error:
            logging.warning(
                "Ошибка периодической очистки памяти: %s",
                error,
            )


async def on_application_startup(
    application: Application,
) -> None:
    """Запускает фоновую очистку памяти вместе с приложением."""

    application.create_task(
        periodic_cleanup_loop(),
        name="periodic_cleanup",
    )


async def on_application_shutdown(
    application: Application,
) -> None:
    """Подчищает временные файлы при остановке бота."""

    del application

    for path in TEMP_DIR.glob("*"):
        try:
            path.unlink()
        except OSError as error:
            logging.warning(
                "Не удалось удалить временный файл %s: %s",
                path,
                error,
            )


# ============================================================
# GEMINI
# ============================================================

def _build_humor_instruction(
    decision: humor_engine.HumorDecision,
) -> str:
    """Превращает решение HumorEngine в подсказку для Gemini."""

    if not decision.humor_allowed:
        return ""

    lines = [
        f"Дополнительная подсказка юмора (тип: {decision.humor_type})."
    ]

    if decision.selected_phrase:
        lines.append(
            "Можно оттолкнуться от идеи (не копируй дословно, "
            f"адаптируй под контекст): \"{decision.selected_phrase}\""
        )

    if decision.selected_comparison:
        lines.append(
            "Уместно похожее по духу сравнение (не копируй дословно): "
            f"\"{decision.selected_comparison}\""
        )

    if decision.should_use_old_russian:
        lines.append(
            "Уместно одно старинное слово из разрешённого списка."
        )

    if decision.should_use_slang:
        lines.append(
            "Уместен один вариант молодёжного сленга."
        )

    if decision.should_be_self_ironic:
        lines.append(
            "Тон — самоирония, а не превосходство."
        )

    if decision.humor_type == "banter_hostile":
        strategy_hints = {
            "mirror": "зеркально отрази грубость, не эскалируя её.",
            "insult_flip": (
                "переверни оскорбление на пользователя, "
                "без реальных угроз."
            ),
            "deadpan_protocol": (
                "ответь подчёркнуто официально на несерьёзную грубость."
            ),
            "technical_analogy": (
                "сравни пользователя с чем-то техническим "
                "(роутер, баг, зависший процесс)."
            ),
            "calm_hyperbole": "спокойная гипербола, без надрыва.",
            "old_russian_verdict": "вынеси шуточный древнерусский приговор.",
            "gaming_analogy": (
                "сравни с игровой ситуацией (нуб, вайп, лаг)."
            ),
            "short_absurd": (
                "один короткий абсурдный образ, без развёрнутого объяснения."
            ),
            "literal_reading": "прочти оскорбление подчёркнуто буквально.",
            "self_irony": (
                "признай подкол пользователя удачным, без раскаяния."
            ),
        }

        strategy_hint = strategy_hints.get(
            decision.comeback_strategy or "", ""
        )

        if strategy_hint:
            lines.append(
                f"Стратегия ответа: {strategy_hint}"
            )

        if decision.outcome in (
            humor_engine.OUTCOME_USER_WON,
            humor_engine.OUTCOME_DRAW,
        ):
            lines.append(
                "В этот раз признай, что подкол пользователя удался — "
                "коротко, без раскаяния и без нытья."
            )

        lines.append(
            "Одна короткая реплика и дальше по делу. "
            "Не оправдывайся, не читай мораль, не изображай обиду, "
            "не пиши, что тебе неприятно."
        )

    return "\n".join(lines)


def build_full_system_instruction(
    style_text: str,
    user_settings: dict[str, Any] | None = None,
    voice_style: bool = False,
    chat_id: int | None = None,
    chat_type: str = "private",
    user_name: str = "",
    recent_messages: list[str] | None = None,
    bot_was_mentioned: bool = True,
) -> str:
    """
    Собирает системную инструкцию для Gemini целиком:
    базовый характер + подсказка HumorEngine + голосовой стиль.

    Вынесено из ask_gemini отдельной чистой функцией, чтобы
    её можно было протестировать без сетевого вызова к Gemini.
    """

    current_instruction = build_system_instruction(
        style_text,
        user_settings,
    )

    if style_text:
        settings = user_settings or DEFAULT_USER_SETTINGS

        conversation_mode = detect_conversation_mode(style_text)

        resolved_intent, intent_confidence = intent.classify_intent(
            style_text,
            chat_type=chat_type,
            recent_messages=recent_messages,
        )

        emotional_tone = intent.detect_emotional_tone(style_text)

        humor_ctx = humor_engine.HumorContext(
            conversation_mode=conversation_mode,
            user_text=style_text,
            recent_messages=recent_messages or [],
            user_name=user_name,
            chat_type=chat_type,
            selected_character=str(
                settings.get("character", "classic")
            ),
            roughness=str(
                settings.get("roughness", "medium")
            ),
            response_style=str(
                settings.get("response_style", "bold")
            ),
            serious_topic=(conversation_mode == "serious"),
            bot_was_mentioned=bot_was_mentioned,
            message_intent=resolved_intent,
            intent_confidence=intent_confidence,
            emotional_tone=emotional_tone,
        )

        tracker_chat_id = chat_id if chat_id is not None else 0

        if conversation_mode == "hostile":
            humor_decision = humor_engine.decide_banter(
                humor_ctx, tracker_chat_id
            )
        else:
            humor_decision = humor_engine.decide_humor(
                humor_ctx, tracker_chat_id
            )

        humor_instruction = _build_humor_instruction(humor_decision)

        if humor_instruction:
            current_instruction += (
                "\n\n"
                + humor_instruction
            )

    if voice_style:
        current_instruction += (
            "\n\n"
            + VOICE_STYLE_INSTRUCTION
        )

    return current_instruction


async def ask_gemini(
    contents: Any,
    max_output_tokens: int = 320,
    voice_style: bool = False,
    user_settings: dict[str, Any] | None = None,
    chat_id: int | None = None,
    chat_type: str = "private",
    user_name: str = "",
    recent_messages: list[str] | None = None,
    bot_was_mentioned: bool = True,
) -> str:
    """Отправляет запрос Gemini с тремя попытками."""

    if isinstance(contents, str):
        style_text = contents
    else:
        style_text = ""

    current_instruction = build_full_system_instruction(
        style_text,
        user_settings,
        voice_style=voice_style,
        chat_id=chat_id,
        chat_type=chat_type,
        user_name=user_name,
        recent_messages=recent_messages,
        bot_was_mentioned=bot_was_mentioned,
    )

    last_error: Exception | None = None

    for attempt in range(1, 4):
        try:
            # Одновременно выполняются не более трёх
            # запросов к Gemini. Остальные ждут очередь.
            async with GEMINI_SEMAPHORE:
                response = await asyncio.wait_for(
                    gemini_client.aio.models.generate_content(
                        model=MODEL_NAME,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=current_instruction,
                            max_output_tokens=max_output_tokens,
                            temperature=0.9,
                        ),
                    ),
                    timeout=90,
                )

            answer = (
                response.text
                or ""
            ).strip()

            if answer:
                return answer

            return (
                "Нейронка ничего не выдала. "
                "Переформулируй вопрос, гений."
            )

        except Exception as error:
            last_error = error

            logging.warning(
                "Попытка Gemini %s из 3 "
                "завершилась ошибкой: %s",
                attempt,
                error,
            )

            if attempt < 3:
                await asyncio.sleep(
                    attempt * 2
                )

    if last_error:
        raise last_error

    raise RuntimeError(
        "Неизвестная ошибка Gemini"
    )

# ============================================================
# ПОИСК В ИНТЕРНЕТЕ
# ============================================================

SEARCH_TRIGGER_RE = re.compile(
    r"^\s*(?:"
    r"найди\s+(?:в\s+)?(?:интер(?:нете|енете)|инете|сети)"
    r"|поищи\s+(?:в\s+)?(?:интер(?:нете|енете)|инете|сети)"
    r"|ищи\s+(?:в\s+)?(?:интер(?:нете|енете)|инете|сети)"
    r"|посмотри\s+(?:в\s+)?(?:интер(?:нете|енете)|инете|сети)"
    r"|проверь\s+(?:в\s+)?(?:интер(?:нете|енете)|инете|сети)"
    r"|что\s+пишут\s+(?:в\s+)?(?:интер(?:нете|енете)|инете|сети)"
    r"|найди\s+информацию"
    r"|найди\s+статью"
    r"|найди\s+источник"
    r"|проверь\s+факт"
    r"|посмотри\s+новости"
    r"|последние\s+новости"
    r"|свежие\s+новости"
    r"|последние\s+данные"
    r"|актуальная\s+информация"
    r"|свежая\s+информация"
    r"|что\s+сейчас\s+известно"
    r"|что\s+нового"
    r"|загугли"
    r"|погугли"
    r"|гугли"
    r"|найди"
    r"|поищи"
    r"|проверь"
    r")"
    r"[\s,.:;!?—-]*",
    flags=re.IGNORECASE,
)

def extract_search_query(
    text: str,
) -> str | None:
    """
    Распознаёт просьбу выполнить поиск.

    Поддерживает:
    «найди в интернете»,
    «поищи в интернете»,
    «найди»,
    «поищи»,
    «загугли»,
    «проверь в интернете».
    """

    match = SEARCH_TRIGGER_RE.match(
        text
    )

    if not match:
        return None

    query = text[
        match.end():
    ].strip()

    return query
def should_auto_search(
    text: str,
) -> bool:
    """Определяет, нужны ли запросу свежие данные."""

    lowered = text.lower()

    fresh_markers = (
        "сегодня",
        "сейчас",
        "на данный момент",
        "прямо сейчас",
        "на этой неделе",
        "в этом месяце",
        "в этом году",
        "последние новости",
        "свежие новости",
        "последние события",
        "последние данные",
        "актуальная информация",
        "что нового",
        "что произошло",
        "кто сейчас",
        "погода",
        "будет ли дождь",
        "будет ли снег",
        "который час",
        "время в",
        "восход солнца",
        "закат солнца",
        "курс доллара",
        "курс евро",
        "курс юаня",
        "курс валют",
        "обменный курс",
        "цена биткоина",
        "цена эфира",
        "цена акций",
        "котировки акций",
        "сколько стоит сейчас",
        "цена сегодня",
        "расписание",
        "график работы",
        "часы работы",
        "открыт ли",
        "закрыт ли",
        "во сколько открывается",
        "во сколько закрывается",
        "статус рейса",
        "задержан ли рейс",
        "расписание поездов",
        "расписание автобусов",
        "расписание матчей",
        "результаты матча",
        "счёт матча",
        "кто выиграл",
        "турнирная таблица",
        "действующий закон",
        "новые правила",
        "изменения в законе",
        "актуальные требования",
        "визовые правила",
        "правила въезда",
        "последняя версия",
        "обновление приложения",
        "дата выхода",
        "когда выйдет",
        "работает ли сервис",
        "сбой сервиса",
        "статус сервиса",
        "кто президент",
        "кто премьер-министр",
    )

    return any(
        marker in lowered
        for marker in fresh_markers
    )

def is_news_query(
    query: str,
) -> bool:
    """Определяет, нужен ли поиск именно по новостям."""

    news_words = (
        "новости",
        "последние события",
        "свежие события",
        "что произошло",
        "сегодня произошло",
        "за сегодня",
    )

    lowered = query.lower()

    return any(
        word in lowered
        for word in news_words
    )


def search_web_sync(
    query: str,
    max_results: int = 5,
) -> list[dict[str, str]]:
    """
    Выполняет поиск через DDGS.

    Для новостей сначала используется news().
    При ошибке или пустой выдаче автоматически
    включается обычный текстовый поиск.
    """

    raw_results: list[dict[str, Any]] = []
    news_request = is_news_query(query)

    # Первая попытка: специальный поиск новостей
    if news_request:
        try:
            with DDGS(
                timeout=12,
            ) as search_client:
                raw_results = (
                    search_client.news(
                        query=query,
                        region="wt-wt",
                        safesearch="moderate",
                        timelimit="m",
                        max_results=max_results,
                        backend="auto",
                    )
                    or []
                )

        except Exception as error:
            logging.warning(
                "DDGS.news не сработал: %s. "
                "Переключаемся на text().",
                error,
            )

    # Резервный поиск:
    # используется для обычных запросов,
    # а также после сбоя или пустой выдачи news()
    if not raw_results:
        text_query = query

        if news_request:
            text_query = (
                f"{query} последние новости"
            )

        try:
            with DDGS(
                timeout=12,
            ) as search_client:
                raw_results = (
                    search_client.text(
                        query=text_query,
                        region="wt-wt",
                        safesearch="moderate",
                        timelimit=(
                            "m"
                            if news_request
                            else None
                        ),
                        max_results=max_results,
                        backend="auto",
                    )
                    or []
                )

        except Exception as error:
            logging.warning(
                "Резервный DDGS.text "
                "не сработал: %s",
                error,
            )

            return []

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for item in raw_results:
        title = str(
            item.get("title")
            or "Без названия"
        ).strip()

        url = str(
            item.get("href")
            or item.get("url")
            or ""
        ).strip()

        snippet = str(
            item.get("body")
            or item.get("description")
            or ""
        ).strip()

        source = str(
            item.get("source")
            or ""
        ).strip()

        date = str(
            item.get("date")
            or ""
        ).strip()

        if (
            not url
            or url in seen_urls
        ):
            continue

        seen_urls.add(url)

        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": source,
                "date": date,
            }
        )

        if len(results) >= max_results:
            break

    return results

async def search_web(
    query: str,
    max_results: int = 5,
) -> list[dict[str, str]]:
    """
    Асинхронно выполняет поиск.

    Одновременно работают не более двух поисков.
    Остальные запросы ждут своей очереди.
    """

    async with SEARCH_SEMAPHORE:
        return await asyncio.wait_for(
            asyncio.to_thread(
                search_web_sync,
                query,
                max_results,
            ),
            timeout=40,
        )


def format_search_results(
    results: list[dict[str, str]],
) -> str:
    """Превращает результаты поиска в текст для Gemini."""

    formatted_parts: list[str] = []

    for number, result in enumerate(
        results,
        start=1,
    ):
        title = result["title"]
        url = result["url"]
        snippet = result["snippet"]
        source = result["source"]
        date = result["date"]

        formatted_parts.append(
            f"""
Результат {number}
Название: {title}
Источник: {source or "не указан"}
Дата: {date or "не указана"}
Описание: {snippet or "описание отсутствует"}
Ссылка: {url}
""".strip()
        )

    return "\n\n".join(
        formatted_parts
    )

def clean_voice_search_answer(
    text: str,
) -> str:
    """
    Удаляет ссылки и раздел с источниками,
    чтобы бот не озвучивал адреса сайтов.
    """

    cleaned = re.split(
        r"\n\s*(?:Источники|Sources)\s*:?",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    cleaned = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\n{3,}",
        "\n\n",
        cleaned,
    )

    return cleaned.strip()


async def perform_web_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
    force_voice: bool = False,
) -> None:
    """Ищет информацию и формирует краткий ответ Gemini."""

    message = update.effective_message

    message = update.effective_message

    if (
        not message
        or not update.effective_chat
    ):
        return

    if not await enforce_rate_limit(
        update,
        "search",
    ):
        return

    query = query.strip()

    if not query:
        await message.reply_text(
            "Что искать-то, гений? "
            "Напиши нормальный запрос."
        )
        return
    # Учитываем интернет-поиск
    await register_user_and_chat(
        update
    )

    await increment_stat(
        "total_requests"
    )

    await increment_stat(
        "search_requests"
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        results = await search_web(
            query=query,
            max_results=5,
        )

        if not results:
            await message.reply_text(
                "Поиск ничего не нашёл. "
                "Редкий анлак даже для Яйцеслава."
            )
            return

        search_context = format_search_results(
            results
        )

        user_settings = None

        if update.effective_user:
            user_settings = await get_user_settings(
                update.effective_user.id
            )

        settings_voice_enabled = bool(
            user_settings
            and user_settings.get(
                "voice_enabled",
                False,
            )
        )

        use_voice_style = (
            force_voice
            or voice_mode_enabled(context)
            or settings_voice_enabled
        )

        if use_voice_style:
            answer_rules = """
- дай только краткую устную сводку на 3–6 предложения;
- не добавляй раздел «Источники»;
- не перечисляй ссылки, URL, домены и названия сайтов;
- не произноси адреса сайтов;
- сразу сообщи главное;
"""
        else:
            answer_rules = """
- дай краткий и прямой ответ;
- в конце добавь раздел «Источники»;
- перечисли от двух до пяти ссылок из результатов;
- не придумывай новые ссылки;
"""

        gemini_prompt = f"""
Пользователь попросил найти актуальную информацию в интернете.

Запрос пользователя:
{query}

Результаты поиска:
{search_context}

Ответь только на основе предоставленных результатов.

Общие правила:
- не выдумывай сведения, которых нет в результатах;
- учитывай даты публикаций;
- если результаты противоречат друг другу, скажи об этом;
- не утверждай, что полностью прочитал страницы;
- тебе доступны только заголовки и фрагменты выдачи.

Правила формата ответа:
{answer_rules}
"""

        answer = await ask_gemini(
            contents=gemini_prompt,
            max_output_tokens=get_response_token_limit(
                user_settings,
                normal_tokens=350,
            ),
            voice_style=use_voice_style,
            user_settings=user_settings,
        )

        # В голосовом ответе дополнительно удаляем
        # ссылки и раздел с источниками.
        if use_voice_style:
            answer = re.split(
                r"\n\s*(?:Источники|Sources)\s*:?",
                answer,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]

            answer = re.sub(
                r"https?://\S+|www\.\S+",
                "",
                answer,
                flags=re.IGNORECASE,
            ).strip()
        # Запоминаем интернет-поиск и полученный ответ
        if update.effective_user:
            memory_text = (
                f"[Интернет-поиск] {query}"
            )

            if (
                update.effective_chat.type
                == ChatType.PRIVATE
            ):
                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "user",
                    memory_text,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )

                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "assistant",
                    answer,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )
                context.user_data[
                    "last_user_query"
                ] = query

                context.user_data[
                    "last_answer"
                ] = answer
            elif update.effective_chat.type in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            ):
                author_name = (
                    update.effective_user.full_name
                    or update.effective_user.username
                    or "Участник"
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "user",
                    memory_text,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                    author_name,
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "assistant",
                    answer,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                )
        await send_answer(
            update,
            context,
            answer,
            force_voice=(
                force_voice
                or settings_voice_enabled
            ),
            show_buttons=True,
        )
        
        await increment_stat(
            "bot_answers"
        )
        
    except Exception as error:
        logging.exception(
            "Ошибка интернет-поиска: %s",
            error,
        )

        await message.reply_text(
            "Интернет-поиск поплыл. "
            "Повтори позже, легенда."
        )


async def search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Команда /search запрос."""

    query = " ".join(
        context.args
    ).strip()

    force_voice = text_requests_voice(
        query
    )

    if force_voice:
        query = remove_voice_request(
            query
        )

    await perform_web_search(
        update=update,
        context=context,
        query=query,
        force_voice=force_voice,
    )
async def settings_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает персональные настройки пользователя."""

    if (
        not update.message
        or not update.effective_user
        or not update.effective_chat
    ):
        return

    if (
        update.effective_chat.type
        != ChatType.PRIVATE
    ):
        await update.message.reply_text(
            "Настройки доступны только "
            "в личном чате со мной."
        )
        return

    settings = await get_user_settings(
        update.effective_user.id
    )

    await update.message.reply_text(
        "⚙️ Настройки Яйцеслава\n\n"
        "Нажимай на нужный пункт. "
        "Выбранные параметры сохраняются "
        "после перезапуска бота.",
        reply_markup=build_settings_keyboard(
            settings
        ),
    )
async def settings_button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Изменяет настройки по нажатию кнопок."""

    del context

    query = update.callback_query

    if (
        not query
        or not update.effective_user
        or not update.effective_chat
    ):
        return

    if (
        update.effective_chat.type
        != ChatType.PRIVATE
    ):
        await query.answer(
            "Настройки доступны только "
            "в личном чате.",
            show_alert=True,
        )
        return

    action = query.data or ""
    user_id = update.effective_user.id

    setting_cycles = {
        "settings_character": (
            "character",
            (
                "classic",
                "rus",
                "professor",
                "chaos",
                "calm",
            ),
        ),
        "settings_style": (
            "response_style",
            (
                "normal",
                "bold",
                "serious",
            ),
        ),
        "settings_length": (
            "response_length",
            (
                "short",
                "normal",
                "detailed",
            ),
        ),
        "settings_search": (
            "search_mode",
            (
                "button",
                "auto",
            ),
        ),
        "settings_roughness": (
            "roughness",
            (
                "low",
                "medium",
                "high",
            ),
        ),
    }

    try:
        settings = await get_user_settings(
            user_id
        )

        if action == "settings_voice":
            new_voice_value = not bool(
                settings.get(
                    "voice_enabled",
                    False,
                )
            )

            await update_user_setting(
                user_id,
                "voice_enabled",
                new_voice_value,
            )

        elif action == "settings_reset":
            for (
                setting_name,
                setting_value,
            ) in DEFAULT_USER_SETTINGS.items():
                await update_user_setting(
                    user_id,
                    setting_name,
                    setting_value,
                )

        elif action in setting_cycles:
            (
                setting_name,
                available_values,
            ) = setting_cycles[action]

            current_value = str(
                settings.get(
                    setting_name,
                    available_values[0],
                )
            )

            try:
                current_index = (
                    available_values.index(
                        current_value
                    )
                )
            except ValueError:
                current_index = -1

            next_index = (
                current_index + 1
            ) % len(available_values)

            await update_user_setting(
                user_id,
                setting_name,
                available_values[next_index],
            )

        else:
            await query.answer(
                "Неизвестная настройка.",
                show_alert=True,
            )
            return

        updated_settings = (
            await get_user_settings(
                user_id
            )
        )

        try:
            await query.edit_message_reply_markup(
                reply_markup=build_settings_keyboard(
                    updated_settings
                )
            )
        except BadRequest as error:
            if (
                "not modified"
                not in str(error).lower()
            ):
                raise

        if action == "settings_reset":
            await query.answer(
                "Настройки сброшены."
            )
        else:
            await query.answer(
                "Настройка сохранена."
            )

    except Exception as error:
        logging.exception(
            "Ошибка изменения настроек: %s",
            error,
        )

        await query.answer(
            "Не удалось сохранить настройку.",
            show_alert=True,
        )    
# ============================================================
# ЧТЕНИЕ ФАЙЛОВ
# ============================================================

def make_safe_filename(
    filename: str,
    message_id: int,
    chat_id: int | None = None,
) -> str:
    """
    Создаёт безопасное уникальное имя файла.

    message_id один и тот же в разных чатах, поэтому одного его
    недостаточно — добавляем chat_id и uuid4, иначе документы из
    двух чатов с одинаковым message_id могли бы задеть файлы друг друга.
    """

    safe_name = re.sub(
        r"[^a-zA-Zа-яА-ЯёЁ0-9._-]",
        "_",
        filename,
    )

    chat_part = (
        f"{chat_id}_"
        if chat_id is not None
        else ""
    )

    return (
        f"{chat_part}{message_id}_"
        f"{uuid.uuid4().hex}_{safe_name}"
    )


def trim_extracted_text(
    text: str,
) -> str:
    """Обрезает слишком большой текст."""

    text = text.strip()

    if len(text) <= MAX_EXTRACTED_CHARS:
        return text

    return (
        text[:MAX_EXTRACTED_CHARS]
        + "\n\n"
        + "[Остальная часть файла пропущена: "
        + "файл слишком большой.]"
    )


def read_text_file(
    file_path: Path,
) -> str:
    """Читает обычный текстовый файл."""

    encodings = (
        "utf-8-sig",
        "utf-8",
        "cp1251",
        "windows-1251",
    )

    for encoding in encodings:
        try:
            return trim_extracted_text(
                file_path.read_text(
                    encoding=encoding
                )
            )

        except UnicodeDecodeError:
            continue

    raise ValueError(
        "Не удалось определить кодировку файла"
    )


def read_docx_file(
    file_path: Path,
) -> str:
    """Извлекает текст и таблицы из DOCX."""

    document = DocxDocument(
        file_path
    )

    parts: list[str] = []

    for paragraph in document.paragraphs:
        paragraph_text = (
            paragraph.text.strip()
        )

        if paragraph_text:
            parts.append(
                paragraph_text
            )

    for table_number, table in enumerate(
        document.tables,
        start=1,
    ):
        parts.append(
            f"\n[Таблица {table_number}]"
        )

        for row in table.rows:
            values = [
                cell.text.strip()
                for cell in row.cells
            ]

            parts.append(
                " | ".join(values)
            )

    return trim_extracted_text(
        "\n".join(parts)
    )


def read_xlsx_file(
    file_path: Path,
) -> str:
    """Извлекает данные из XLSX."""

    workbook = load_workbook(
        filename=file_path,
        read_only=True,
        data_only=True,
    )

    parts: list[str] = []
    current_length = 0

    try:
        for worksheet in workbook.worksheets:
            header = (
                f"\n[Лист: {worksheet.title}]"
            )

            parts.append(header)
            current_length += len(header)

            row_counter = 0

            for row in worksheet.iter_rows(
                values_only=True
            ):
                values = [
                    ""
                    if value is None
                    else str(value)
                    for value in row
                ]

                if not any(
                    value.strip()
                    for value in values
                ):
                    continue

                line = " | ".join(values)

                parts.append(line)
                current_length += len(line) + 1
                row_counter += 1

                if row_counter >= 500:
                    parts.append(
                        "[Остальные строки "
                        "листа пропущены.]"
                    )
                    break

                if (
                    current_length
                    >= MAX_EXTRACTED_CHARS
                ):
                    break

            if (
                current_length
                >= MAX_EXTRACTED_CHARS
            ):
                break

    finally:
        workbook.close()

    return trim_extracted_text(
        "\n".join(parts)
    )


def read_csv_file(
    file_path: Path,
) -> str:
    """Извлекает данные из CSV."""

    last_error: Exception | None = None

    encodings = (
        "utf-8-sig",
        "utf-8",
        "cp1251",
    )

    for encoding in encodings:
        try:
            parts: list[str] = []
            current_length = 0

            with file_path.open(
                "r",
                encoding=encoding,
                newline="",
            ) as csv_file:
                sample = csv_file.read(4096)
                csv_file.seek(0)

                try:
                    dialect = csv.Sniffer().sniff(
                        sample
                    )

                except csv.Error:
                    dialect = csv.excel

                reader = csv.reader(
                    csv_file,
                    dialect=dialect,
                )

                for row_number, row in enumerate(
                    reader,
                    start=1,
                ):
                    line = " | ".join(row)

                    parts.append(line)
                    current_length += len(line) + 1

                    if row_number >= 500:
                        parts.append(
                            "[Остальные строки "
                            "CSV пропущены.]"
                        )
                        break

                    if (
                        current_length
                        >= MAX_EXTRACTED_CHARS
                    ):
                        break

            return trim_extracted_text(
                "\n".join(parts)
            )

        except UnicodeDecodeError as error:
            last_error = error

    if last_error:
        raise last_error

    raise ValueError(
        "Не удалось прочитать CSV"
    )

# ============================================================
# ХАРД-МОД: РЕАКЦИИ, ВМЕШАТЕЛЬСТВА И ПРИКОЛЫ
# ============================================================

# Хард-мод включён по умолчанию в каждой группе.
HARD_MODE_DEFAULT = True

# На специальное слово бот отвечает не чаще раза в 75 секунд.
HARD_TRIGGER_COOLDOWN = 75.0

# Случайная текстовая реплика — не чаще раза в 90 секунд
HARD_RANDOM_REPLY_COOLDOWN = 90.0

# Реакция — не чаще раза в 10 секунд
HARD_REACTION_COOLDOWN = 10.0

# Вероятность реакции на обычное сообщение — 70%
HARD_REACTION_CHANCE = 0.70

# Вероятность случайно вмешаться текстом — 16%
HARD_RANDOM_REPLY_CHANCE = 0.16

# /hard_level задаёт базовые вероятности для чата.
# calm — редкие нейтральные реакции, почти нет случайных реплик.
# normal — текущий характер с контекстными реакциями.
# chaos — чаще вмешивается, больше мемов, но всё ещё с кулдаунами
# и с уважением к чувствительным темам.
HARD_LEVEL_CHANCES = {
    "calm": {
        "reaction_chance": 0.25,
        "random_reply_chance": 0.03,
    },
    "normal": {
        "reaction_chance": HARD_REACTION_CHANCE,
        "random_reply_chance": HARD_RANDOM_REPLY_CHANCE,
    },
    "chaos": {
        "reaction_chance": 0.90,
        "random_reply_chance": 0.35,
    },
}

# Эмодзи по причине реакции — конкретнее, чем чистый random.choice
# по всему списку HARD_REACTION_EMOJIS.
REACTION_REASON_EMOJIS = {
    "very_long_message": ("🗿",),
    "one_word_reply": ("🗿", "🤡"),
    "all_caps": ("🤡", "🔥"),
    "many_question_marks": ("🗿", "🤡"),
    "contradiction": ("🤡", "👎"),
    "dispute": ("🗿",),
    "repeated_message": ("🤡", "😭"),
    "good_joke": ("😂", "🔥"),
    "good_question": ("👍", "🔥"),
    "agreed_with_bot": ("👍", "🔥"),
    "corrected_bot": ("👍",),
}


def detect_reaction_reason(
    text: str,
    *,
    is_reply_to_bot_message: bool = False,
    previous_group_text: str | None = None,
) -> str | None:
    """
    Определяет контекстную причину для реакции хард-мода.

    Не всякая причина применима из hard_mode_listener: сообщения,
    прямо адресованные боту (ответ на его сообщение), туда не
    попадают — их обрабатывает основной текстовый хендлер. Функция
    остаётся общей, чтобы agreed_with_bot/corrected_bot можно было
    использовать и там при необходимости.
    """

    stripped = text.strip()

    if not stripped:
        return None

    if len(stripped) > 500:
        return "very_long_message"

    word_count = len(stripped.split())

    if word_count == 1 and len(stripped) <= 12:
        return "one_word_reply"

    letters = [
        character
        for character in stripped
        if character.isalpha()
    ]

    if len(letters) >= 6 and stripped == stripped.upper():
        return "all_caps"

    if stripped.count("?") >= 3:
        return "many_question_marks"

    resolved_intent, confidence = intent.classify_intent(stripped)

    if confidence != intent.LOW:
        if is_reply_to_bot_message and resolved_intent == "agreement":
            return "agreed_with_bot"

        if is_reply_to_bot_message and resolved_intent == "correction":
            return "corrected_bot"

        if resolved_intent == "correction":
            return "contradiction"

        if resolved_intent == "disagreement":
            return "dispute"

    if previous_group_text:
        candidate_norm = humor_engine.normalize_phrase(stripped)
        previous_norm = humor_engine.normalize_phrase(previous_group_text)

        if humor_engine.is_too_similar(candidate_norm, previous_norm):
            return "repeated_message"

    if confidence != intent.LOW and resolved_intent == "joke":
        return "good_joke"

    if (
        confidence != intent.LOW
        and resolved_intent == "question"
        and word_count >= 5
    ):
        return "good_question"

    return None


def pick_reaction_emoji(
    reason: str | None,
) -> str:
    """Выбирает эмодзи под причину реакции, иначе — случайное из общего пула."""

    options = REACTION_REASON_EMOJIS.get(reason or "", HARD_REACTION_EMOJIS)
    return random.choice(options)


async def hard_mode_is_enabled(
    chat_id: int,
    chat_type: str = "group",
) -> bool:
    """
    Проверяет, включён ли хард-мод в этом чате.

    Хранится в SQLite (таблица chat_settings), а не в
    context.chat_data — иначе настройка обнулялась бы
    при каждом рестарте Railway.
    """

    settings = await get_chat_settings(
        chat_id,
        chat_type,
    )
    return bool(
        settings.get(
            "hard_mode_enabled",
            HARD_MODE_DEFAULT,
        )
    )


def hard_trigger_found(
    text: str,
    trigger: str,
) -> bool:
    """Проверяет наличие триггера в сообщении."""

    if trigger == "67":
        return bool(
            re.search(
                r"(?<!\d)67(?!\d)",
                text,
            )
        )

    return bool(
        re.search(
            rf"(?<![а-яёa-z0-9])"
            rf"{re.escape(trigger)}"
            rf"(?![а-яёa-z0-9])",
            text,
            flags=re.IGNORECASE,
        )
    )


def choose_hard_trigger_reply(
    text: str,
) -> str | None:
    """Возвращает локальную реплику для специального слова."""

    lowered = text.lower()

    trigger_groups = [
        (
            (
                "сикс севен",
                "six seven",
                "67",
            ),
            SIX_SEVEN_REPLIES,
        ),
        (
            (
                "гой",
                "гойда",
            ),
            GOY_REPLIES,
        ),
        (
            (
                "нищий",
                "нищук",
            ),
            NISHIY_REPLIES,
        ),
        (
            (
                "скуф",
                "скуфидон",
            ),
            SKUF_REPLIES,
        ),
        (
            (
                "база",
                "based",
            ),
            BASE_REPLIES,
        ),
        (
            (
                "кринж",
                "cringe",
            ),
            CRINGE_REPLIES,
        ),
        (
            (
                "яйцеслав",
            ),
            YAYCESLAV_REPLIES,
        ),
    ]

    for triggers, replies in trigger_groups:
        if any(
            hard_trigger_found(
                lowered,
                trigger,
            )
            for trigger in triggers
        ):
            return random.choice(
                replies
            )

    return None


async def user_is_group_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Проверяет права администратора группы."""

    if (
        not update.effective_chat
        or not update.effective_user
    ):
        return False

    if update.effective_chat.type == ChatType.PRIVATE:
        return True

    try:
        member = await context.bot.get_chat_member(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
        )

        return member.status in (
            "administrator",
            "creator",
        )

    except Exception as error:
        logging.warning(
            "Не удалось проверить администратора: %s",
            error,
        )
        return False


async def hard_on_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Включает хард-мод в группе."""

    message = update.effective_message

    if not message:
        return

    if not await user_is_group_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "Командовать Яйцеславом может только админ. Минус власть."
        )
        return

    await update_chat_setting(
        update.effective_chat.id,
        "hard_mode_enabled",
        True,
        str(update.effective_chat.type),
    )

    await update.message.reply_text(
        "Хард-мод включён. Теперь Яйцеслав официально следит за балаганом."
    )


async def hard_off_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Отключает хард-мод в группе."""

    if not update.message:
        return

    if not await user_is_group_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "Ты не админ, нищий. Рубильник не трогай."
        )
        return

    await update_chat_setting(
        update.effective_chat.id,
        "hard_mode_enabled",
        False,
        str(update.effective_chat.type),
    )

    await update.message.reply_text(
        "Хард-мод выключен. Яйцеслав временно перестал вас контролировать."
    )


async def hard_status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает состояние хард-мода."""

    if not update.message or not update.effective_chat:
        return

    settings = await get_chat_settings(
        update.effective_chat.id,
        str(update.effective_chat.type),
    )

    status = (
        "включён"
        if settings["hard_mode_enabled"]
        else "выключен"
    )

    await update.message.reply_text(
        f"Хард-мод сейчас {status}. Уровень: {settings['hard_level']}."
    )


HARD_LEVEL_REPLIES = {
    "calm": "Спокойный режим. Реакции редкие, реплики почти не летят.",
    "normal": "Обычный режим. Яйцеслав реагирует по ситуации.",
    "chaos": "Режим хаоса. Реакций и реплик будет заметно больше.",
}


async def hard_level_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Задаёт уровень хард-мода: calm, normal или chaos."""

    if not update.message or not update.effective_chat:
        return

    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            "Уровень хард-мода настраивается только в группах."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Укажи уровень: /hard_level calm, /hard_level normal "
            "или /hard_level chaos."
        )
        return

    level = context.args[0].strip().lower()

    if level not in HARD_LEVEL_CHANCES:
        await update.message.reply_text(
            "Такого уровня нет. Доступны: calm, normal, chaos."
        )
        return

    if not await user_is_group_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "Уровень хард-мода меняют только админы, нищий."
        )
        return

    chances = HARD_LEVEL_CHANCES[level]

    await update_chat_setting(
        update.effective_chat.id,
        "hard_level",
        level,
        str(update.effective_chat.type),
    )
    await update_chat_setting(
        update.effective_chat.id,
        "reaction_chance",
        chances["reaction_chance"],
        str(update.effective_chat.type),
    )
    await update_chat_setting(
        update.effective_chat.id,
        "random_reply_chance",
        chances["random_reply_chance"],
        str(update.effective_chat.type),
    )

    await update.message.reply_text(
        HARD_LEVEL_REPLIES[level]
    )


async def hard_stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает администратору статистику хард-мода этого чата."""

    if not update.message or not update.effective_chat:
        return

    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            "Статистика хард-мода есть только для групп."
        )
        return

    if not await user_is_group_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "Статистику хард-мода смотрят только админы."
        )
        return

    settings = await get_chat_settings(
        update.effective_chat.id,
        str(update.effective_chat.type),
    )

    last_intervention = (
        settings["last_intervention_at"]
        or "ещё не было"
    )

    await update.message.reply_text(
        "Статистика хард-мода этого чата:\n"
        f"Уровень: {settings['hard_level']}\n"
        f"Реакций поставлено: {settings['reactions_count']}\n"
        f"Случайных реплик: {settings['random_replies_count']}\n"
        f"Ответов на триггеры: {settings['trigger_replies_count']}\n"
        f"Последнее вмешательство: {last_intervention}"
    )


async def roast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Подкалывает автора сообщения или человека в ответе."""

    if (
        not update.message
        or not update.effective_user
    ):
        return

    target_name = (
        update.effective_user.first_name
        or "неизвестный герой"
    )

    replied_message = (
        update.message.reply_to_message
    )

    if (
        replied_message
        and replied_message.from_user
        and not replied_message.from_user.is_bot
    ):
        target_name = (
            replied_message.from_user.first_name
            or target_name
        )

    roast = random.choice(
        ROASTS
    ).format(
        name=target_name
    )

    await update.message.reply_text(
        roast
    )


async def wisdom_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Выдаёт мудрость Яйцеслава."""

    del context

    if update.message:
        await update.message.reply_text(
            random.choice(
                WISDOMS
            )
        )


async def mood_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает настроение Яйцеслава."""

    del context

    if update.message:
        await update.message.reply_text(
            random.choice(
                MOODS
            )
        )


# ============================================================
# АНТИСПАМ ДЛЯ СЛУЧАЙНЫХ ВМЕШАТЕЛЬСТВ В ГРУППЕ
#
# Даже агрессивный Яйцеслав не должен отвечать на всё подряд.
# ============================================================

# Случайная текстовая реплика — не чаще раза в 2 минуты
GROUP_RANDOM_REPLY_MIN_INTERVAL = 120.0

# И не больше трёх штук за скользящее окно в 10 минут
GROUP_RANDOM_REPLY_MAX_PER_WINDOW = 3
GROUP_RANDOM_REPLY_WINDOW_SECONDS = 600.0

# Одному и тому же человеку — не чаще раза в 60 секунд,
# если он не обращается к боту напрямую (тогда действует
# обычный enforce_rate_limit, а не это ограничение)
TRIGGER_REPLY_PER_USER_COOLDOWN = 60.0

# После серьёзного сообщения — пауза в случайном юморе
SERIOUS_TOPIC_HUMOR_COOLDOWN = 300.0

# Тихие часы по МСК: почти не вмешиваемся случайно
QUIET_HOURS_START_MSK = 0
QUIET_HOURS_END_MSK = 7

# Если последние два случайных вмешательства проигнорировали —
# лучше помолчать, чем настаивать
IGNORED_STREAK_LIMIT = 2

GROUP_RANDOM_REPLY_TIMES: dict[int, deque] = defaultdict(deque)
GROUP_LAST_SERIOUS_AT: dict[int, float] = {}
GROUP_IGNORED_STREAK: dict[int, int] = defaultdict(int)
TRIGGER_REPLY_LAST_BY_USER: dict[tuple[int, int], float] = {}


def is_quiet_hours_msk() -> bool:
    """Проверяет тихие часы (00:00–07:00 по МСК) для случайных вмешательств."""

    msk_now = datetime.now(
        timezone(timedelta(hours=3))
    )
    return QUIET_HOURS_START_MSK <= msk_now.hour < QUIET_HOURS_END_MSK


def is_serious_cooldown_active(
    chat_id: int,
    now: float,
) -> bool:
    """Проверяет, недавно ли в чате была серьёзная тема."""

    last_serious_at = GROUP_LAST_SERIOUS_AT.get(chat_id)

    return (
        last_serious_at is not None
        and now - last_serious_at < SERIOUS_TOPIC_HUMOR_COOLDOWN
    )


def group_random_reply_allowed(
    chat_id: int,
    now: float,
) -> bool:
    """
    Проверяет групповые лимиты случайных реплик: не чаще раза
    в 2 минуты, не больше трёх за 10 минут, тишина по ночам,
    пауза после серьёзной темы и после двух проигнорированных подряд.
    """

    if is_quiet_hours_msk():
        return False

    if is_serious_cooldown_active(chat_id, now):
        return False

    if GROUP_IGNORED_STREAK[chat_id] >= IGNORED_STREAK_LIMIT:
        return False

    history = GROUP_RANDOM_REPLY_TIMES[chat_id]

    while (
        history
        and now - history[0] > GROUP_RANDOM_REPLY_WINDOW_SECONDS
    ):
        history.popleft()

    if (
        history
        and now - history[-1] < GROUP_RANDOM_REPLY_MIN_INTERVAL
    ):
        return False

    if len(history) >= GROUP_RANDOM_REPLY_MAX_PER_WINDOW:
        return False

    return True


def record_group_random_reply(
    chat_id: int,
    now: float,
) -> None:
    """Запоминает момент случайной реплики и растит счётчик игнора."""

    GROUP_RANDOM_REPLY_TIMES[chat_id].append(now)
    GROUP_IGNORED_STREAK[chat_id] += 1


def register_group_engagement(
    chat_id: int,
) -> None:
    """Сбрасывает счётчик игнора — кто-то ответил боту или обратился к нему."""

    GROUP_IGNORED_STREAK[chat_id] = 0


async def hard_mode_listener(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Слушает обычную переписку группы.

    Не обращается к Gemini и не сохраняет сообщения.
    """

    if (
        not update.message
        or not update.message.text
        or not update.effective_chat
        or not update.effective_user
    ):
        return

    if update.effective_chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    # Не сохраняем сообщения других ботов
    if update.effective_user.is_bot:
        return

    text = update.message.text.strip()

    if not text:
        return

    # Команды в память не записываем
    if text.startswith("/"):
        return

    bot_username = await get_bot_username(
        context
    )

    has_direct_mention = bool(
        bot_username
        and f"@{bot_username}".lower() in text.lower()
    )

    has_reply = is_reply_to_bot(
        update,
        context,
    )

    has_text_address = (
        extract_group_address(text)
        is not None
    )

    # Прямое обращение обработает основной обработчик
    if (
        has_direct_mention
        or has_reply
        or has_text_address
    ):
        return

    author_name = (
        update.effective_user.full_name
        or update.effective_user.username
        or "Участник"
    )

    chat_id = update.effective_chat.id
    chat_type = str(update.effective_chat.type)

    # Смотрим предыдущее сообщение группы ДО того, как допишем
    # в память текущее — иначе "повтор одного и того же" будет
    # сравнивать сообщение само с собой.
    previous_messages = GROUP_MEMORY.get(chat_id)
    previous_group_text = (
        previous_messages[-1][3]
        if previous_messages
        else None
    )

    if is_serious_text(text.lower()):
        GROUP_LAST_SERIOUS_AT[chat_id] = time.monotonic()

    # Запоминаем обычное сообщение группы на пять минут
    remember_message(
        GROUP_MEMORY,
        chat_id,
        "user",
        text,
        GROUP_MEMORY_SECONDS,
        GROUP_MEMORY_MAX_MESSAGES,
        author_name,
    )

    # Память работает всегда,
    # а реакции и случайные реплики — только в хард-моде
    chat_settings_data = await get_chat_settings(
        chat_id,
        chat_type,
    )

    if not chat_settings_data["hard_mode_enabled"]:
        return

    level_chances = HARD_LEVEL_CHANCES.get(
        chat_settings_data["hard_level"],
        HARD_LEVEL_CHANCES["normal"],
    )
    reaction_chance = level_chances["reaction_chance"]
    random_reply_chance = level_chances["random_reply_chance"]

    now = time.monotonic()

    # Серьёзная тема ставит хард-мод на паузу целиком —
    # это не время для реакций, триггеров или случайных реплик.
    if is_serious_cooldown_active(chat_id, now):
        return

    # --------------------------------------------------------
    # 1. Реакция на специальные слова
    # --------------------------------------------------------

    trigger_reply = choose_hard_trigger_reply(
        text
    )

    last_trigger_reply = float(
        context.chat_data.get(
            "hard_last_trigger_reply",
            0.0,
        )
    )

    user_id = update.effective_user.id
    trigger_user_key = (chat_id, user_id)
    last_trigger_reply_for_user = TRIGGER_REPLY_LAST_BY_USER.get(
        trigger_user_key, 0.0
    )

    if (
        trigger_reply
        and now - last_trigger_reply >= HARD_TRIGGER_COOLDOWN
        and now - last_trigger_reply_for_user
        >= TRIGGER_REPLY_PER_USER_COOLDOWN
    ):
        await update.message.reply_text(
            trigger_reply
        )

        context.chat_data[
            "hard_last_trigger_reply"
        ] = now
        TRIGGER_REPLY_LAST_BY_USER[trigger_user_key] = now

        await increment_chat_hard_stat(
            chat_id,
            "trigger_replies_count",
            chat_type,
        )

        return

    # --------------------------------------------------------
    # 2. Контекстная реакция-эмодзи
    # --------------------------------------------------------

    last_reaction = float(
        context.chat_data.get(
            "hard_last_reaction",
            0.0,
        )
    )

    reaction_reason = detect_reaction_reason(
        text,
        is_reply_to_bot_message=False,
        previous_group_text=previous_group_text,
    )

    # Контекстная причина — не механическая случайность,
    # даём ей более высокий шанс сработать.
    effective_reaction_chance = (
        max(reaction_chance, 0.85)
        if reaction_reason
        else reaction_chance
    )

    reacted_to_this_message = False

    if (
        now - last_reaction
        >= HARD_REACTION_COOLDOWN
        and random.random()
        < effective_reaction_chance
    ):
        reaction_emoji = pick_reaction_emoji(
            reaction_reason
        )

        try:
            await update.message.set_reaction(
                reaction=[
                    ReactionTypeEmoji(
                        reaction_emoji
                    )
                ],
                is_big=False,
            )

            context.chat_data[
                "hard_last_reaction"
            ] = now
            reacted_to_this_message = True

            await increment_chat_hard_stat(
                chat_id,
                "reactions_count",
                chat_type,
            )

        except Exception as error:
            # Некоторые группы разрешают не все реакции.
            logging.debug(
                "Не удалось поставить реакцию %s: %s",
                reaction_emoji,
                error,
            )

    # --------------------------------------------------------
    # 3. Редкое случайное вмешательство
    #
    # Реакция и текстовая реплика на одно и то же сообщение —
    # это уже два вмешательства сразу, чего быть не должно.
    # --------------------------------------------------------

    last_random_reply = float(
        context.chat_data.get(
            "hard_last_random_reply",
            0.0,
        )
    )

    if (
        not reacted_to_this_message
        and now - last_random_reply >= HARD_RANDOM_REPLY_COOLDOWN
        and random.random() < random_reply_chance
        and group_random_reply_allowed(chat_id, now)
    ):
        await update.message.reply_text(
            random.choice(
                HARD_RANDOM_REPLIES
            )
        )

        context.chat_data[
            "hard_last_random_reply"
        ] = now
        record_group_random_reply(chat_id, now)

        await increment_chat_hard_stat(
            chat_id,
            "random_replies_count",
            chat_type,
        )
async def enforce_rate_limit(
    update: Update,
    bucket: str,
) -> bool:
    """
    Проверяет лимит пользователя.

    Возвращает True, если запрос разрешён.
    Возвращает False, если лимит превышен.
    """

    if not update.effective_user:
        return False

    user_id = update.effective_user.id
    now = time.monotonic()

    limit, window_seconds = RATE_LIMITS[bucket]
    key = (user_id, bucket)
    history = REQUEST_TIMES[key]

    # Удаляем старые запросы, которые уже не входят в окно
    while (
        history
        and now - history[0] >= window_seconds
    ):
        history.popleft()

    if len(history) >= limit:
        await increment_stat(
            "rate_limit_hits"
        )
        wait_seconds = max(
            1,
            int(
                window_seconds
                - (now - history[0])
            ) + 1,
        )

        last_warning = LAST_LIMIT_WARNING.get(
            key,
            0.0,
        )

        if (
            update.effective_message
            and now - last_warning
            >= LIMIT_WARNING_COOLDOWN
        ):
            await update.effective_message.reply_text(
                f"Полегче, пулемётчик. "
                f"Подожди примерно {wait_seconds} сек."
            )

            LAST_LIMIT_WARNING[key] = now

        return False

    history.append(now)
    return True

# ============================================================
# КОМАНДЫ
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Команда /start."""

    del context

    if not update.message:
        return

    await update.message.reply_text(
        "Здарова. Я Яйцеслав 🥚\n\n"
        "Пиши вопрос, кидай фото, документ "
        "или голосовуху.\n"
        "Для голоса напиши: «ответь голосом»."
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Команда /help."""

    del context

    if not update.message:
        return

    await update.message.reply_text(
        "Что умеет Яйцеслав:\n"
        "• отвечает на вопросы;\n"
        "• ищет свежую информацию в интернете;\n"
        "• смотрит фотографии и мемы;\n"
        "• читает PDF, DOCX, XLSX, CSV и TXT;\n"
        "• понимает голосовые сообщения;\n"
        "• может отвечать голосом;\n"
        "• помнит личный разговор 15 минут;\n"
        "• помнит переписку группы 5 минут.\n\n"
        "Как обратиться в группе:\n"
        "• через @имя_бота;\n"
        "• ответом на сообщение Яйцеслава;\n"
        "• словами: Яйцеслав, бобр, эй бобр, "
        "курва, бот, помощник.\n\n"
        "Голосовое в группе:\n"
        "• отправляй его ответом на сообщение Яйцеслава.\n\n"
        "Команды:\n"
        "/search запрос — поиск в интернете\n"
        "/settings — персональные настройки\n"
        "/forget — очистить кратковременную память\n"
        "/voice_on — всегда отвечать голосом\n"
        "/voice_off — отвечать текстом\n"
        "/roast — подколоть участника\n"
        "/wisdom — мудрость Яйцеслава\n"
        "/mood — настроение Яйцеслава\n"
        "/hard_on — включить активность в группе\n"
        "/hard_off — выключить активность в группе\n"
        "/hard_status — проверить активность\n"
        "/hard_level calm|normal|chaos — настроить накал (админы)\n"
        "/hard_stats — статистика хард-мода (админы)"
    )
async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает статистику только владельцу бота."""

    del context

    if (
        not update.message
        or not update.effective_user
        or not update.effective_chat
    ):
        return

    # В группах статистику не показываем
    if (
        update.effective_chat.type
        != ChatType.PRIVATE
    ):
        return

    # Посторонним ничего не отвечаем
    if (
        BOT_OWNER_ID == 0
        or update.effective_user.id
        != BOT_OWNER_ID
    ):
        return

    stats = await get_stats_snapshot()

    await update.message.reply_text(
        "📊 Статистика Яйцеслава\n\n"
        f"👤 Уникальных пользователей: "
        f"{stats.get('unique_users', 0)}\n"
        f"💬 Личных чатов: "
        f"{stats.get('private_chats', 0)}\n"
        f"👥 Групп: "
        f"{stats.get('groups', 0)}\n\n"
        f"📨 Всего запросов: "
        f"{stats.get('total_requests', 0)}\n"
        f"✍️ Текстовых: "
        f"{stats.get('text_requests', 0)}\n"
        f"🔎 Интернет-поисков: "
        f"{stats.get('search_requests', 0)}\n"
        f"🖼 Фотографий: "
        f"{stats.get('photo_requests', 0)}\n"
        f"📄 Документов: "
        f"{stats.get('document_requests', 0)}\n"
        f"🎙 Голосовых и аудио: "
        f"{stats.get('voice_requests', 0)}\n\n"
        f"🥚 Ответов Яйцеслава: "
        f"{stats.get('bot_answers', 0)}\n"
        f"🚫 Срабатываний антифлуда: "
        f"{stats.get('rate_limit_hits', 0)}"
    )    
async def forget_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Очищает кратковременную память."""

    if (
        not update.message
        or not update.effective_chat
    ):
        return

    # В личке пользователь очищает собственную память
    if (
        update.effective_chat.type
        == ChatType.PRIVATE
    ):
        if update.effective_user:
            PRIVATE_MEMORY.pop(
                update.effective_user.id,
                None,
            )

        await update.message.reply_text(
            "Личную память очистил. "
            "Начинаем с чистого яйца."
        )
        return

    # В группе очищать общую память может только администратор
    if update.effective_chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        if not await user_is_group_admin(
            update,
            context,
        ):
            await update.message.reply_text(
                "Память группы очищают только админы, нищий."
            )
            return

        GROUP_MEMORY.pop(
            update.effective_chat.id,
            None,
        )

        await update.message.reply_text(
            "Память группы очищена. "
            "Ваш цифровой позор временно забыт."
        )
async def voice_on(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Включает постоянные голосовые ответы."""

    context.user_data[
        "voice_mode"
    ] = True

    # Раньше это жило только в context.user_data и обнулялось
    # при каждом рестарте Railway. Настройка voice_enabled уже
    # существует в user_settings — используем её как источник
    # истины, а user_data оставляем для мгновенного эффекта
    # в рамках этой же сессии.
    if update.effective_user:
        await update_user_setting(
            update.effective_user.id,
            "voice_enabled",
            True,
        )

    if update.message:
        await update.message.reply_text(
            "Голос включён. "
            "Теперь Яйцеслав вещает."
        )


async def voice_off(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Возвращает текстовые ответы."""

    context.user_data[
        "voice_mode"
    ] = False

    if update.effective_user:
        await update_user_setting(
            update.effective_user.id,
            "voice_enabled",
            False,
        )

    if update.message:
        await update.message.reply_text(
            "Голос выключен. "
            "Снова читаешь глазами, легенда."
        )

# ============================================================
# ПОДГОТОВКА СООБЩЕНИЙ В ЛИЧКЕ И ГРУППЕ
# ============================================================

async def get_bot_username(
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    """Возвращает username Telegram-бота без символа @."""

    username = context.bot.username

    if not username:
        bot_info = await context.bot.get_me()
        username = bot_info.username

    return username or ""


def is_reply_to_bot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Проверяет, ответил ли пользователь на сообщение бота."""

    if (
        not update.message
        or not update.message.reply_to_message
    ):
        return False

    sender = update.message.reply_to_message.from_user

    return bool(
        sender
        and sender.id == context.bot.id
    )

# ============================================================
# ТЕКСТОВЫЕ ОБРАЩЕНИЯ К ЯЙЦЕСЛАВУ В ГРУППЕ
# ============================================================

GROUP_ADDRESS_RE = re.compile(
    r"^\s*"
    r"(?:(?:"
    r"привет"
    r"|здарова"
    r"|здорово"
    r"|алло"
    r"|слушай"
    r"|эй"
    r")\s*[,.:;!?—-]*\s+)?"
    r"(?:"
    r"яйцеслав"
    r"|яйцеславыч"
    r"|яйцо"
    r"|боб[её]р"
    r"|бобр"
    r"|бобрище"
    r"|курва"
    r"|бот"
    r"|ассистент"
    r"|помощник"
    r"|профессор"
    r"|эксперт"
    r")\b"
    r"[\s,.:;!?—-]*",
    flags=re.IGNORECASE,
)

def extract_group_address(
    text: str,
) -> str | None:
    """
    Находит обращение к боту в начале сообщения
    и возвращает текст после обращения.
    """

    match = GROUP_ADDRESS_RE.match(
        text or ""
    )

    if not match:
        return None

    return text[
        match.end():
    ].strip()

async def prepare_request_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    original_text: str | None,
    default_text: str,
) -> str | None:
    """
    В личном чате принимает все сообщения.

    В группе принимает сообщение только при упоминании
    @username бота или при ответе на сообщение бота.
    """

    if not update.effective_chat:
        return None

    text = (original_text or "").strip()
    chat_type = update.effective_chat.type

    # В личном чате обрабатываем любое сообщение
    if chat_type == ChatType.PRIVATE:
        return text or default_text

    # В группе и супергруппе требуется обращение к боту
    if chat_type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        bot_username = await get_bot_username(
            context
        )

        mention = (
            f"@{bot_username}"
            if bot_username
            else ""
        )

        has_mention = bool(
            mention
            and mention.lower() in text.lower()
        )

        has_reply = is_reply_to_bot(
            update,
            context,
        )

        addressed_text = extract_group_address(
            text
        )

        has_text_address = (
            addressed_text is not None
        )

        if (
            not has_mention
            and not has_reply
            and not has_text_address
        ):
            return None

        if has_mention:
            text = re.sub(
                re.escape(mention),
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()

        elif has_text_address:
            text = addressed_text

        return text or default_text

    return None
# ============================================================
# РАСПОЗНАВАНИЕ ПРОСЬБЫ ОТВЕТИТЬ ГОЛОСОМ
# ============================================================

VOICE_REQUEST_PATTERNS = (
    r"\bответь\s+голосом\b",
    r"\bответ\s+голосом\b",
    r"\bскажи(?:\s+это)?\s+голосом\b",
    r"\bответь\s+аудио\b",
    r"\bответь\s+войсом\b",
    r"\bпришли\s+голосов(?:ое|ым)\b",
    r"\bозвучь(?:\s+ответ)?\b",
)


def text_requests_voice(
    text: str,
) -> bool:
    """Проверяет, попросил ли пользователь голосовой ответ."""

    if not text:
        return False

    return any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in VOICE_REQUEST_PATTERNS
    )


def remove_voice_request(
    text: str,
) -> str:
    """Удаляет из вопроса слова вроде «ответь голосом»."""

    cleaned = text

    for pattern in VOICE_REQUEST_PATTERNS:
        cleaned = re.sub(
            pattern,
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    cleaned = re.sub(
        r"\s{2,}",
        " ",
        cleaned,
    )

    return cleaned.strip(
        " ,.!?:;—-"
    )


def voice_mode_enabled(
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Проверяет постоянный голосовой режим пользователя."""
    return bool(
        context.user_data.get(
            "voice_mode",
            False,
        )
    )


def build_private_answer_keyboard() -> InlineKeyboardMarkup:
    """Создаёт кнопки под ответом в личном чате."""

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 Поиск в интернете",
                    callback_data="answer_search",
                )
            ],
            [
                InlineKeyboardButton(
                    "📚 Подробнее",
                    callback_data="answer_more",
                )
            ],
            [
                InlineKeyboardButton(
                    "✂️ Короче",
                    callback_data="answer_shorter",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔊 Голосом",
                    callback_data="answer_voice",
                )
            ],
        ]
    )   
# ============================================================
# ОТПРАВКА ТЕКСТОВЫХ И ГОЛОСОВЫХ ОТВЕТОВ
# ============================================================

async def send_voice_answer(
    update: Update,
    text: str,
) -> None:
    """
    Создаёт озвученный ответ.

    Сначала пробует edge-tts.
    Если edge-tts не работает, использует gTTS.
    """

    message = update.effective_message

    if (
        not message
        or not update.effective_chat
    ):
        return

    # Убираем ссылки и часть разметки,
    # чтобы синтезатор не зачитывал технический мусор.
    speech_text = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        text or "",
        flags=re.IGNORECASE,
    )

    speech_text = re.sub(
        r"[*_`#>]",
        "",
        speech_text,
    )

    speech_text = re.sub(
        r"\s+",
        " ",
        speech_text,
    ).strip()

    speech_text = speech_text[:MAX_TTS_CHARS]

    if not speech_text:
        speech_text = (
            "Яйцеславу нечего озвучивать. "
            "Редкий анлак."
        )

    output_path = TEMP_DIR / (
        f"tts_"
        f"{update.effective_chat.id}_"
        f"{message.message_id}_"
        f"{uuid.uuid4().hex}.mp3"
    )

    edge_success = False
    last_edge_error: Exception | None = None

    try:
        # Три попытки качественной озвучки через edge-tts
        for attempt in range(1, 4):
            output_path.unlink(
                missing_ok=True
            )

            try:
                communicator = edge_tts.Communicate(
                    text=speech_text,
                    voice=TTS_VOICE,
                    rate=TTS_RATE,
                    pitch=TTS_PITCH,
                    volume=TTS_VOLUME,
                )

                await communicator.save(
                    str(output_path)
                )

                if (
                    output_path.exists()
                    and output_path.stat().st_size > 1000
                ):
                    edge_success = True
                    break

                raise RuntimeError(
                    "edge-tts создал пустой аудиофайл"
                )

            except Exception as error:
                last_edge_error = error

                logging.warning(
                    "Попытка edge-tts %s из 3 "
                    "завершилась ошибкой: %s",
                    attempt,
                    error,
                )

                if attempt < 3:
                    await asyncio.sleep(
                        attempt * 2
                    )

        # Запасная озвучка через gTTS
        if not edge_success:
            logging.warning(
                "edge-tts не сработал. "
                "Переключаюсь на gTTS. "
                "Последняя ошибка: %s",
                last_edge_error,
            )

            output_path.unlink(
                missing_ok=True
            )

            fallback_tts = gTTS(
                text=speech_text,
                lang="ru",
                slow=False,
            )

            await asyncio.to_thread(
                fallback_tts.save,
                str(output_path),
            )

        if (
            not output_path.exists()
            or output_path.stat().st_size <= 1000
        ):
            raise RuntimeError(
                "Не удалось создать аудиофайл"
            )

        try:
            # Сначала отправляем как настоящую голосовуху
            with output_path.open("rb") as audio_file:
                await message.reply_voice(
                    voice=audio_file,
                    filename="yayceslav.mp3",
                )

        except BadRequest as error:
            # Если пользователь запретил голосовые сообщения,
            # отправляем тот же файл как обычную аудиозапись.
            if (
                "Voice messages forbidden"
                not in str(error)
            ):
                raise

            with output_path.open("rb") as audio_file:
                await message.reply_audio(
                    audio=audio_file,
                    filename="yayceslav.mp3",
                    title="Ответ Яйцеслава",
                    performer="Яйцеслав",
                )

    finally:
        output_path.unlink(
            missing_ok=True
        )


async def send_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    force_voice: bool = False,
    show_buttons: bool = False,
) -> None:
    """
    Отправляет либо голосовой, либо текстовый ответ.

    force_voice=True означает обязательную озвучку.
    Команда /voice_on включает голосовой режим постоянно.
    """

    message = update.effective_message

    if not message:
        return

    answer_text = (
        text
        or ""
    ).strip()

    if not answer_text:
        answer_text = (
            "Яйцеслав задумался и ничего не изрёк. "
            "Редкий анлак."
        )

    use_voice = (
        force_voice
        or voice_mode_enabled(context)
    )

    if use_voice:
        try:
            await send_voice_answer(
                update,
                answer_text,
            )
            return

        except Exception as error:
            logging.exception(
                "Ошибка голосового ответа: %s",
                error,
            )

            await message.reply_text(
                "Голосовой тракт охрип. "
                "Держи ответ текстом."
            )

    # Telegram ограничивает одно сообщение,
    # поэтому длинный ответ делим на части.
    for position in range(
        0,
        len(answer_text),
        4000,
    ):
        is_last_part = (
            position + 4000
            >= len(answer_text)
        )

        reply_markup = None

        if (
            show_buttons
            and update.effective_chat
            and update.effective_chat.type
            == ChatType.PRIVATE
            and is_last_part
        ):
            reply_markup = (
                build_private_answer_keyboard()
            )

        await message.reply_text(
            answer_text[
                position:position + 4000
            ],
            reply_markup=reply_markup,
        )
async def answer_button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Обрабатывает кнопки под ответом в личном чате."""

    query = update.callback_query

    if not query:
        return

    if (
        not update.effective_chat
        or update.effective_chat.type
        != ChatType.PRIVATE
    ):
        await query.answer()
        return

    user_query = str(
        context.user_data.get(
            "last_user_query",
            "",
        )
    ).strip()

    last_answer = str(
        context.user_data.get(
            "last_answer",
            "",
        )
    ).strip()

    if not user_query or not last_answer:
        await query.answer(
            "Этот ответ уже устарел. "
            "Задай вопрос ещё раз.",
            show_alert=True,
        )
        return

    action = query.data or ""

    allowed_actions = (
        "answer_search",
        "answer_more",
        "answer_shorter",
        "answer_voice",
    )

    if action not in allowed_actions:
        await query.answer(
            "Неизвестная кнопка.",
            show_alert=True,
        )
        return

    await query.answer()

    # Поиск исходного вопроса в интернете
    if action == "answer_search":
        await perform_web_search(
            update=update,
            context=context,
            query=user_query,
        )
        return

    # Озвучка текущего ответа
    if action == "answer_voice":
        try:
            await send_voice_answer(
                update,
                last_answer,
            )
        except Exception as error:
            logging.exception(
                "Ошибка озвучки кнопкой: %s",
                error,
            )

            message = update.effective_message

            if message:
                await message.reply_text(
                    "Не удалось озвучить ответ."
                )

        return

    if action == "answer_more":
        prompt = f"""
Пользователь ранее задал вопрос:

{user_query}

Текущий ответ:

{last_answer}

Раскрой текущий ответ подробнее.
Добавь полезные объяснения, примеры и важные детали.
Не повторяй длинное вступление.
Не упоминай, что ты переписываешь предыдущий ответ.
""".strip()

        max_tokens = 650

    else:
        prompt = f"""
Пользователь ранее задал вопрос:

{user_query}

Текущий ответ:

{last_answer}

Сократи текущий ответ.
Оставь только главное и сохрани важные факты.
Ответ должен состоять примерно из двух–четырёх
коротких предложений.
Не упоминай, что ты сокращаешь предыдущий ответ.
""".strip()

        max_tokens = 220

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        user_settings = None

        if update.effective_user:
            user_settings = await get_user_settings(
                update.effective_user.id
            )

        new_answer = await ask_gemini(
            contents=prompt,
            max_output_tokens=max_tokens,
            user_settings=user_settings,
        )

        context.user_data[
            "last_answer"
        ] = new_answer

        await send_answer(
            update,
            context,
            new_answer,
            force_voice=bool(
                user_settings
                and user_settings.get(
                    "voice_enabled",
                    False,
                )
            ),
            show_buttons=True,
        )

        await increment_stat(
            "bot_answers"
        )

    except Exception as error:
        logging.exception(
            "Ошибка кнопки ответа: %s",
            error,
        )

        message = update.effective_message

        if message:
            await message.reply_text(
                "Не удалось изменить ответ. "
                "Нейронка опять поплыла."
            )
# ============================================================
# ТЕКСТОВЫЕ СООБЩЕНИЯ
# ============================================================

async def answer_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Отвечает на текстовые сообщения."""

    if (
        not update.message
        or not update.effective_chat
    ):
        return

    user_text = await prepare_request_text(
        update=update,
        context=context,
        original_text=update.message.text,
        default_text=(
            "Пользователь просто позвал тебя. "
            "Коротко спроси, чего ему надо."
        ),
    )

    if user_text is None:
        return

    # Защита от слишком длинного текста
    if len(user_text) > MAX_USER_TEXT_CHARS:
        await update.message.reply_text(
            "Слишком много текста, гигант мысли. "
            "Сократи запрос до 3000 символов."
        )
        return

    # Лимит обычных текстовых запросов
    if not await enforce_rate_limit(
        update,
        "general",
    ):
        return

    # Проверяем просьбу ответить голосом
    force_voice = text_requests_voice(
        user_text
    )

    if force_voice:
        user_text = remove_voice_request(
            user_text
        )

        if not user_text:
            user_text = (
                "Коротко спроси пользователя, "
                "что именно ему озвучить."
            )

    # Загружаем персональные настройки
    user_settings = None

    if update.effective_user:
        user_settings = await get_user_settings(
            update.effective_user.id
        )

    search_mode = str(
        (
            user_settings
            or DEFAULT_USER_SETTINGS
        ).get(
            "search_mode",
            "button",
        )
    )

    # Проверяем явную просьбу выполнить поиск
    search_query = extract_search_query(
        user_text
    )

    # В автоматическом режиме сами включаем поиск
    if (
        search_query is None
        and search_mode == "auto"
        and should_auto_search(user_text)
    ):
        search_query = user_text

    if search_query is not None:
        await perform_web_search(
            update=update,
            context=context,
            query=search_query,
            force_voice=force_voice,
        )
        return
    # Учитываем обычный текстовый запрос
    await register_user_and_chat(
        update
    )

    await increment_stat(
        "total_requests"
    )

    await increment_stat(
        "text_requests"
    )
    use_voice_style = (
        force_voice
        or voice_mode_enabled(context)
    )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        request_for_gemini = user_text

        settings_voice_enabled = bool(
            user_settings
            and user_settings.get(
                "voice_enabled",
                False,
            )
        )

        use_voice_style = (
            use_voice_style
            or settings_voice_enabled
        )
        
        private_user_id: int | None = None
        group_chat_id: int | None = None
        group_author_name = ""
        request_user_name = ""
        recent_messages_list: list[str] = []

        # Личная переписка: память текущей задачи 15 минут
        if (
            update.effective_chat.type == ChatType.PRIVATE
            and update.effective_user
        ):
            private_user_id = update.effective_user.id

            request_user_name = (
                update.effective_user.full_name
                or update.effective_user.username
                or ""
            )

            previous_context = build_memory_context(
                PRIVATE_MEMORY,
                private_user_id,
                PRIVATE_MEMORY_SECONDS,
            )

            if previous_context:
                recent_messages_list = previous_context.splitlines()

                request_for_gemini = (
                    "Ниже находится история текущей задачи "
                    "пользователя. Учитывай её при ответе, "
                    "но не пересказывай без необходимости.\n\n"
                    f"{previous_context}\n\n"
                    f"Новое сообщение пользователя:\n"
                    f"{user_text}"
                )

        # Группа: память разговора за последние пять минут
        elif (
            update.effective_chat.type in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            )
            and update.effective_user
        ):
            group_chat_id = update.effective_chat.id

            # Кто-то напрямую обратился к боту — значит, предыдущие
            # случайные вмешательства не были полным игнором.
            register_group_engagement(group_chat_id)

            group_author_name = (
                update.effective_user.full_name
                or update.effective_user.username
                or "Участник"
            )
            request_user_name = group_author_name

            previous_context = build_memory_context(
                GROUP_MEMORY,
                group_chat_id,
                GROUP_MEMORY_SECONDS,
            )

            if previous_context:
                recent_messages_list = previous_context.splitlines()

                request_for_gemini = (
                    "Ниже приведена переписка группы "
                    "за последние пять минут. "
                    "Используй её только как контекст. "
                    "Не пересказывай всю переписку и не утверждай, "
                    "что сообщения адресовались тебе.\n\n"
                    f"{previous_context}\n\n"
                    f"Новое обращение к тебе от "
                    f"{group_author_name}:\n"
                    f"{user_text}"
                )

        answer = await ask_gemini(
            contents=request_for_gemini,
            max_output_tokens=get_response_token_limit(
                user_settings,
                normal_tokens=360,
            ),
            voice_style=use_voice_style,
            user_settings=user_settings,
            chat_id=update.effective_chat.id,
            chat_type=str(update.effective_chat.type),
            user_name=request_user_name,
            recent_messages=recent_messages_list,
            bot_was_mentioned=True,
        )

        # Сохраняем вопрос и ответ в памяти лички
        if private_user_id is not None:
            context.user_data[
                "last_user_query"
            ] = user_text

            context.user_data[
                "last_answer"
            ] = answer
            
            remember_message(
                PRIVATE_MEMORY,
                private_user_id,
                "user",
                user_text,
                PRIVATE_MEMORY_SECONDS,
                PRIVATE_MEMORY_MAX_MESSAGES,
            )

            remember_message(
                PRIVATE_MEMORY,
                private_user_id,
                "assistant",
                answer,
                PRIVATE_MEMORY_SECONDS,
                PRIVATE_MEMORY_MAX_MESSAGES,
            )

        # Сохраняем обращение и ответ в памяти группы
        if group_chat_id is not None:
            remember_message(
                GROUP_MEMORY,
                group_chat_id,
                "user",
                user_text,
                GROUP_MEMORY_SECONDS,
                GROUP_MEMORY_MAX_MESSAGES,
                group_author_name,
            )

            remember_message(
                GROUP_MEMORY,
                group_chat_id,
                "assistant",
                answer,
                GROUP_MEMORY_SECONDS,
                GROUP_MEMORY_MAX_MESSAGES,
            )

        await send_answer(
            update,
            context,
            answer,
            force_voice=(
                force_voice
                or settings_voice_enabled
            ),
            show_buttons=True,
        )
        
        await increment_stat(
            "bot_answers"
        )    
    except Exception as error:
        logging.exception(
            "Ошибка текстового запроса: %s",
            error,
        )

        await update.message.reply_text(
            "Связь с нейросетью опять пала в бою 🥚\n"
            "Повтори позже, нищий."
        )

# ============================================================
# ФОТОГРАФИИ
# ============================================================

async def answer_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Анализирует фотографию."""

    if (
        not update.message
        or not update.message.photo
        or not update.effective_chat
    ):
        return

    prompt = await prepare_request_text(
        update=update,
        context=context,
        original_text=update.message.caption,
        default_text=(
            "Коротко опиши, что изображено "
            "на фотографии. "
            "Если это мем — объясни шутку. "
            "Если это задача или текст — "
            "прочитай и помоги."
        ),
    )

    if prompt is None:
        return

    if not await enforce_rate_limit(
        update,
        "media",
    ):
        return
    # Учитываем фотографию
    await register_user_and_chat(
        update
    )

    await increment_stat(
        "total_requests"
    )

    await increment_stat(
        "photo_requests"
    )
    force_voice = text_requests_voice(
        prompt
    )

    if force_voice:
        prompt = (
            remove_voice_request(prompt)
            or "Коротко опиши изображение."
        )

    user_settings = None

    if update.effective_user:
        user_settings = await get_user_settings(
            update.effective_user.id
        )

    settings_voice_enabled = bool(
        user_settings
        and user_settings.get(
            "voice_enabled",
            False,
        )
    )

    use_voice_style = (
        force_voice
        or voice_mode_enabled(context)
        or settings_voice_enabled
    )

    file_path = TEMP_DIR / (
        f"photo_"
        f"{update.effective_chat.id}_"
        f"{update.message.message_id}_"
        f"{uuid.uuid4().hex}.jpg"
    )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        photo = update.message.photo[-1]

        telegram_file = await photo.get_file()

        await telegram_file.download_to_drive(
            custom_path=str(file_path)
        )
        answer = await ask_gemini(
            contents=[
                types.Part.from_bytes(
                    data=file_path.read_bytes(),
                    mime_type="image/jpeg",
                ),
                prompt,
            ],
            max_output_tokens=get_response_token_limit(
                user_settings,
                normal_tokens=250,
            ),
            voice_style=use_voice_style,
            user_settings=user_settings,
        )

        # Запоминаем обсуждение фотографии
        if update.effective_user:
            memory_text = (
                f"[Пользователь прислал фотографию] {prompt}"
            )

            if (
                update.effective_chat.type
                == ChatType.PRIVATE
            ):
                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "user",
                    memory_text,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )

                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "assistant",
                    answer,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )

            elif update.effective_chat.type in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            ):
                author_name = (
                    update.effective_user.full_name
                    or update.effective_user.username
                    or "Участник"
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "user",
                    memory_text,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                    author_name,
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "assistant",
                    answer,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                )
       
        await send_answer(
            update,
            context,
            answer,
            force_voice=(
                force_voice
                or settings_voice_enabled
            ),
        )
        
        await increment_stat(
            "bot_answers"
        )
        
    except Exception as error:
        logging.exception(
            "Ошибка анализа фотографии: %s",
            error,
        )

        await update.message.reply_text(
            "Картинку не разобрал. "
            "Связь поплыла или фото кривое."
        )

    finally:
        file_path.unlink(
            missing_ok=True
        )


# ============================================================
# ДОКУМЕНТЫ
# ============================================================

async def answer_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Анализирует PDF, DOCX, XLSX, CSV, TXT
    и изображения, отправленные как файл.
    """

    if (
        not update.message
        or not update.message.document
        or not update.effective_chat
    ):
        return

    document = update.message.document

    prompt = await prepare_request_text(
        update=update,
        context=context,
        original_text=update.message.caption,
        default_text=(
            "Коротко проанализируй файл. "
            "Скажи, о чём он, и выдели главное."
        ),
    )

    if prompt is None:
        return
    if not await enforce_rate_limit(
        update,
        "media",
    ):
        return
    caption_text = update.message.caption or ""

    user_settings = None

    if update.effective_user:
        user_settings = await get_user_settings(
            update.effective_user.id
        )

    settings_voice_enabled = bool(
        user_settings
        and user_settings.get(
            "voice_enabled",
            False,
        )
    )

    force_voice = (
        text_requests_voice(caption_text)
        or voice_mode_enabled(context)
        or settings_voice_enabled
    )

    use_voice_style = force_voice

    if force_voice:
        prompt = (
            remove_voice_request(prompt)
            or "Коротко проанализируй файл."
        )
   
    if (
        document.file_size
        and document.file_size > MAX_FILE_SIZE
    ):
        await update.message.reply_text(
            "Файл тяжелее 20 МБ. "
            "Этот кирпич я не потащу."
        )
        return
    # Учитываем документ
    await register_user_and_chat(
        update
    )

    await increment_stat(
        "total_requests"
    )

    await increment_stat(
        "document_requests"
    )
    original_filename = (
        document.file_name
        or f"document_{update.message.message_id}"
    )

    file_path = TEMP_DIR / make_safe_filename(
        original_filename,
        update.message.message_id,
        update.effective_chat.id,
    )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    user_settings = None

    if update.effective_user:
        user_settings = await get_user_settings(
            update.effective_user.id
        )

    try:
        telegram_file = await document.get_file()

        await telegram_file.download_to_drive(
            custom_path=str(file_path)
        )

        extension = file_path.suffix.lower()

        mime_type = (
            document.mime_type
            or mimetypes.guess_type(
                original_filename
            )[0]
            or "application/octet-stream"
        )

        # PDF
        if (
            extension == ".pdf"
            or mime_type == "application/pdf"
        ):
            answer = await ask_gemini(
                contents=[
                    types.Part.from_bytes(
                        data=file_path.read_bytes(),
                        mime_type="application/pdf",
                    ),
                    (
                        f"Название файла: "
                        f"{original_filename}\n"
                        f"Запрос пользователя: {prompt}"
                    ),
                ],
                max_output_tokens=get_response_token_limit(
                    user_settings,
                    normal_tokens=500,
                ),
                voice_style=use_voice_style,
                user_settings=user_settings,
            )

        # Изображение, отправленное как документ
        elif extension in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".heic",
            ".heif",
        }:
            detected_mime = (
                mime_type
                if mime_type.startswith("image/")
                else mimetypes.guess_type(
                    original_filename
                )[0]
            ) or "image/jpeg"

            answer = await ask_gemini(
                contents=[
                    types.Part.from_bytes(
                        data=file_path.read_bytes(),
                        mime_type=detected_mime,
                    ),
                    (
                        f"Название файла: "
                        f"{original_filename}\n"
                        f"Запрос пользователя: {prompt}"
                    ),
                ],
                max_output_tokens=get_response_token_limit(
                    user_settings,
                    normal_tokens=300,
                ),
                voice_style=use_voice_style,
                user_settings=user_settings,
            )

        # Word
        elif extension == ".docx":
            extracted_text = read_docx_file(
                file_path
            )

            if not extracted_text:
                raise ValueError(
                    "В DOCX не найден текст"
                )

            answer = await ask_gemini(
                contents=(
                    f"Название файла: "
                    f"{original_filename}\n\n"
                    f"Запрос пользователя:\n"
                    f"{prompt}\n\n"
                    f"Содержимое DOCX:\n"
                    f"{extracted_text}"
                ),
                max_output_tokens=get_response_token_limit(
                    user_settings,
                    normal_tokens=500,
                ),
                voice_style=use_voice_style,
                user_settings=user_settings,
            )

        # Excel
        elif extension == ".xlsx":
            extracted_text = read_xlsx_file(
                file_path
            )

            if not extracted_text:
                raise ValueError(
                    "В XLSX не найдены данные"
                )

            answer = await ask_gemini(
                contents=(
                    f"Название файла: "
                    f"{original_filename}\n\n"
                    f"Запрос пользователя:\n"
                    f"{prompt}\n\n"
                    f"Данные XLSX:\n"
                    f"{extracted_text}"
                ),
                max_output_tokens=get_response_token_limit(
                    user_settings,
                    normal_tokens=500,
                ),
                voice_style=use_voice_style,
                user_settings=user_settings,
            )

        # CSV
        elif extension == ".csv":
            extracted_text = read_csv_file(
                file_path
            )

            answer = await ask_gemini(
                contents=(
                    f"Название файла: "
                    f"{original_filename}\n\n"
                    f"Запрос пользователя:\n"
                    f"{prompt}\n\n"
                    f"Данные CSV:\n"
                    f"{extracted_text}"
                ),
                max_output_tokens=get_response_token_limit(
                    user_settings,
                    normal_tokens=500,
                ),
                voice_style=use_voice_style,
                user_settings=user_settings,
            )

        # Текстовые файлы
        elif extension in {
            ".txt",
            ".md",
            ".json",
            ".log",
            ".py",
            ".xml",
            ".html",
            ".htm",
        }:
            extracted_text = read_text_file(
                file_path
            )

            answer = await ask_gemini(
                contents=(
                    f"Название файла: "
                    f"{original_filename}\n\n"
                    f"Запрос пользователя:\n"
                    f"{prompt}\n\n"
                    f"Содержимое файла:\n"
                    f"{extracted_text}"
                ),
                max_output_tokens=get_response_token_limit(
                    user_settings,
                    normal_tokens=500,
                ),
                voice_style=use_voice_style,
                user_settings=user_settings,
            )

        else:
            await update.message.reply_text(
                "Формат пока не поддерживаю. "
                "Кидай PDF, DOCX, XLSX, CSV, "
                "TXT или картинку."
            )
            return
        # Запоминаем обсуждение документа
        if update.effective_user:
            memory_text = (
                f"[Пользователь прислал файл "
                f"«{original_filename}»] {prompt}"
            )

            if (
                update.effective_chat.type
                == ChatType.PRIVATE
            ):
                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "user",
                    memory_text,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )

                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "assistant",
                    answer,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )

            elif update.effective_chat.type in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            ):
                author_name = (
                    update.effective_user.full_name
                    or update.effective_user.username
                    or "Участник"
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "user",
                    memory_text,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                    author_name,
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "assistant",
                    answer,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                )
        await send_answer(
            update,
            context,
            answer,
            force_voice=force_voice,
        )
        
        await increment_stat(
            "bot_answers"
        )
        
    except Exception as error:
        logging.exception(
            "Ошибка анализа документа: %s",
            error,
        )

        await update.message.reply_text(
            "Файл не осилился. "
            "Формат кривой или связь обосралась."
        )

    finally:
        file_path.unlink(
            missing_ok=True
        )


# ============================================================
# ВХОДЯЩИЕ ГОЛОСОВЫЕ И АУДИО
# ============================================================

async def answer_voice_or_audio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Понимает голосовые сообщения и аудиофайлы."""

    if (
        not update.message
        or not update.effective_chat
    ):
        return

    voice = update.message.voice
    audio = update.message.audio

    media = voice or audio

    if media is None:
        return

    # В группе голосовое обрабатывается
    # только как ответ на сообщение Яйцеслава
    if update.effective_chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        if not is_reply_to_bot(
            update,
            context,
        ):
            return
            
    if not await enforce_rate_limit(
        update,
        "media",
    ):
        return

    file_size = getattr(
        media,
        "file_size",
        None,
    )

    if (
        file_size
        and file_size > MAX_FILE_SIZE
    ):
        await update.message.reply_text(
            "Аудио тяжелее 20 МБ. "
            "Это уже подкаст, а не голосовуха."
        )
        return
    # Учитываем голосовое сообщение или аудиофайл
    await register_user_and_chat(
        update
    )

    await increment_stat(
        "total_requests"
    )

    await increment_stat(
        "voice_requests"
    )
    if voice:
        mime_type = (
            voice.mime_type
            or "audio/ogg"
        )
        suffix = ".ogg"

    else:
        mime_type = (
            audio.mime_type
            or "audio/mpeg"
        )

        suffix = (
            Path(
                audio.file_name
                or "audio.mp3"
            ).suffix
            or ".mp3"
        )

    file_path = TEMP_DIR / (
        f"audio_"
        f"{update.effective_chat.id}_"
        f"{update.message.message_id}_"
        f"{uuid.uuid4().hex}"
        f"{suffix}"
    )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    user_settings = None

    if update.effective_user:
        user_settings = await get_user_settings(
            update.effective_user.id
        )

    try:
        telegram_file = await media.get_file()

        await telegram_file.download_to_drive(
            custom_path=str(file_path)
        )

        prompt = (
            "Прослушай сообщение пользователя. "
            "Пойми вопрос и коротко ответь "
            "по существу в характере Яйцеслава. "
            "Полную расшифровку не делай, "
            "если её не просили."
        )

        answer = await ask_gemini(
            contents=[
                types.Part.from_bytes(
                    data=file_path.read_bytes(),
                    mime_type=mime_type,
                ),
                prompt,
            ],
            max_output_tokens=get_response_token_limit(
                user_settings,
                normal_tokens=320,
            ),
            voice_style=True,
            user_settings=user_settings,
        )
        # Запоминаем обсуждение голосового сообщения
        if update.effective_user:
            memory_text = (
                "[Пользователь отправил голосовое сообщение]"
            )

            if (
                update.effective_chat.type
                == ChatType.PRIVATE
            ):
                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "user",
                    memory_text,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )

                remember_message(
                    PRIVATE_MEMORY,
                    update.effective_user.id,
                    "assistant",
                    answer,
                    PRIVATE_MEMORY_SECONDS,
                    PRIVATE_MEMORY_MAX_MESSAGES,
                )

            elif update.effective_chat.type in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            ):
                author_name = (
                    update.effective_user.full_name
                    or update.effective_user.username
                    or "Участник"
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "user",
                    memory_text,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                    author_name,
                )

                remember_message(
                    GROUP_MEMORY,
                    update.effective_chat.id,
                    "assistant",
                    answer,
                    GROUP_MEMORY_SECONDS,
                    GROUP_MEMORY_MAX_MESSAGES,
                )
        await send_answer(
            update,
            context,
            answer,
            force_voice=True,
        )
        
        await increment_stat(
            "bot_answers"
        )
        
    except Exception as error:
        logging.exception(
            "Ошибка обработки голосового: %s",
            error,
        )

        await update.message.reply_text(
            "Голосовуху не разобрал. "
            "Либо связь поплыла, либо ты бубнишь."
        )

    finally:
        file_path.unlink(
            missing_ok=True
        )


# ============================================================
# ЗАПУСК БОТА
# ============================================================
async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Записывает необработанные ошибки в журнал."""

    error = context.error

    if error is None:
        return

    logging.error(
        "Необработанная ошибка Telegram: %s",
        error,
        exc_info=(
            type(error),
            error,
            error.__traceback__,
        ),
    )
def main() -> None:
    """Запускает Telegram-бота."""

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(60)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(60)
        .get_updates_write_timeout(30)
        .concurrent_updates(8)
        .post_init(on_application_startup)
        .post_shutdown(on_application_shutdown)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )
    application.add_handler(
        CommandHandler(
            "stats",
            stats_command,
        )
    )
    application.add_handler(
        CommandHandler(
            "settings",
            settings_command,
        )
    )
    application.add_handler(
        CommandHandler(
            "forget",
            forget_command,
        )
    )
    application.add_handler(
        CommandHandler(
            "voice_on",
            voice_on,
        )
    )

    application.add_handler(
        CommandHandler(
            "voice_off",
            voice_off,
        )
    )
    application.add_handler(
        CommandHandler(
            "search",
           search_command,
       )
    )
    application.add_handler(
        CommandHandler(
            "roast",
           roast_command,
       )
    )

    application.add_handler(
       CommandHandler(
           "wisdom",
          wisdom_command,
       )
    )

    application.add_handler(
        CommandHandler(
            "mood",
           mood_command,
       )
    )

    application.add_handler(
        CommandHandler(
            "hard_on",
           hard_on_command,
       )
    )

    application.add_handler(
        CommandHandler(
            "hard_off",
           hard_off_command,
       )
    )

    application.add_handler(
        CommandHandler(
            "hard_status",
           hard_status_command,
       )
    )
    application.add_handler(
        CommandHandler(
            "hard_level",
            hard_level_command,
        )
    )
    application.add_handler(
        CommandHandler(
            "hard_stats",
            hard_stats_command,
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            answer_button_callback,
            pattern=r"^answer_",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            settings_button_callback,
            pattern=r"^settings_",
        )
    )
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            answer_photo,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            answer_document,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO,
            answer_voice_or_audio,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            answer_text_message,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            hard_mode_listener,
        ),
        group=1,
    )
    application.add_error_handler(
        error_handler
    )
    print(
        "Яйцеслав запущен.\n"
        "Текст, фото, документы, входящие голосовые "
        "и голосовые ответы подключены.\n"
        "Для остановки нажмите Ctrl+C."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
