"""Short-lived Telegram video-note recall for explicit follow-up requests.

An unaddressed video circle keeps the existing 20% proactive-reaction gate.
Independently of that gate, this runtime remembers only the Telegram ``file_id``
of the most recent video note in each chat for a few minutes. If somebody then
writes a high-confidence phrase such as ``че по кружку?`` or ``посмотри видео
выше``, Yayceslav can fetch and inspect that same circle on demand.

The cache is RAM-only, TTL-limited and hard-capped. Raw MP4 bytes are downloaded
only for the explicit follow-up request and deleted immediately afterwards.
There is no SQLite state, background worker or extra Gemini call unless a user
actually asks to inspect the recent circle.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters


RECENT_VIDEO_NOTE_TTL_SECONDS = 180.0
MAX_RECENT_VIDEO_NOTE_CHATS = 256
_HANDLER_GROUP = -3
_PREPARED_APPLICATION_IDS: set[int] = set()


@dataclass(frozen=True)
class RecentVideoNote:
    file_id: str
    message_id: int
    sender_id: int | None
    file_size: int
    cached_at: float


_RECENT_VIDEO_NOTES: dict[int, RecentVideoNote] = {}

_MEDIA_WORD = r"(?:круж\w*|видео|видос\w*)"
_FOLLOWUP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\b(?:что|че|чё)\s+(?:ты\s+)?(?:скажешь|думаешь)\s+"
        rf"(?:по|про|о)\s+(?:(?:этом|этому|том|прошлом|прошлому|предыдущем|предыдущему|последнем|последнему)\s+)?{_MEDIA_WORD}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:что|че|чё)\s+(?:по|про)\s+"
        rf"(?:(?:этому|тому|прошлому|предыдущему|последнему)\s+)?{_MEDIA_WORD}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:посмотри|глянь|оцени|прокомментируй|разбери)\s+"
        rf"(?:(?:этот|тот|прошлый|предыдущий|последний)\s+)?{_MEDIA_WORD}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:как\s+тебе|что\s+думаешь\s+(?:про|о))\s+"
        rf"(?:(?:этот|тот|прошлый|предыдущий|последний)\s+)?{_MEDIA_WORD}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:я\s+)?(?:там\s+)?{_MEDIA_WORD}\s+"
        rf"(?:скинул|кинул|отправил|переслал)\b.*?"
        rf"\b(?:что|че|чё|как)\b.*?\b(?:нему|это|круж\w*|видео|видос\w*)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"\b{_MEDIA_WORD}\s+(?:выше|прошлым|предыдущим|последним)\s+сообщением\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:что|че|чё)\s+там\s+(?:в|на)\s+{_MEDIA_WORD}\b",
        re.IGNORECASE,
    ),
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def is_recent_video_note_followup(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _FOLLOWUP_PATTERNS)


def _prune_recent_video_notes(now: float) -> None:
    stale = [
        chat_id
        for chat_id, item in _RECENT_VIDEO_NOTES.items()
        if now - item.cached_at > RECENT_VIDEO_NOTE_TTL_SECONDS
    ]
    for chat_id in stale:
        _RECENT_VIDEO_NOTES.pop(chat_id, None)

    while len(_RECENT_VIDEO_NOTES) > MAX_RECENT_VIDEO_NOTE_CHATS:
        oldest_chat_id = next(iter(_RECENT_VIDEO_NOTES))
        _RECENT_VIDEO_NOTES.pop(oldest_chat_id, None)


def remember_recent_video_note(
    chat_id: int,
    *,
    file_id: str,
    message_id: int,
    sender_id: int | None,
    file_size: int | None = None,
    now: float | None = None,
) -> None:
    timestamp = time.monotonic() if now is None else float(now)
    _prune_recent_video_notes(timestamp)
    key = int(chat_id)
    # Reinsert so dict insertion order also reflects recency for the hard cap.
    _RECENT_VIDEO_NOTES.pop(key, None)
    _RECENT_VIDEO_NOTES[key] = RecentVideoNote(
        file_id=str(file_id),
        message_id=int(message_id),
        sender_id=(int(sender_id) if sender_id is not None else None),
        file_size=max(0, int(file_size or 0)),
        cached_at=timestamp,
    )
    _prune_recent_video_notes(timestamp)


def get_recent_video_note(
    chat_id: int,
    *,
    now: float | None = None,
) -> RecentVideoNote | None:
    timestamp = time.monotonic() if now is None else float(now)
    _prune_recent_video_notes(timestamp)
    return _RECENT_VIDEO_NOTES.get(int(chat_id))


async def _cache_video_note(update, context) -> None:
    del context
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    video_note = getattr(message, "video_note", None) if message is not None else None
    if message is None or chat is None or video_note is None:
        return

    user = getattr(update, "effective_user", None)
    remember_recent_video_note(
        int(chat.id),
        file_id=str(video_note.file_id),
        message_id=int(message.message_id),
        sender_id=(int(user.id) if user is not None else None),
        file_size=getattr(video_note, "file_size", None),
    )


def _recent_messages(bot_module, chat_id: int) -> list[str] | None:
    builder = getattr(bot_module, "build_memory_context", None)
    memory = getattr(bot_module, "GROUP_MEMORY", None)
    ttl = getattr(bot_module, "GROUP_MEMORY_SECONDS", None)
    if not callable(builder) or memory is None or ttl is None:
        return None
    try:
        context_text = str(builder(memory, int(chat_id), ttl) or "")
    except Exception:
        return None
    return context_text.splitlines() if context_text else None


def _remember_exchange(bot_module, update, user_text: str, answer: str) -> None:
    remember = getattr(bot_module, "remember_message", None)
    if not callable(remember):
        return
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if chat is None or user is None:
        return

    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        memory = getattr(bot_module, "GROUP_MEMORY", None)
        ttl = getattr(bot_module, "GROUP_MEMORY_SECONDS", None)
        cap = getattr(bot_module, "GROUP_MEMORY_MAX_MESSAGES", None)
        if memory is None or ttl is None or cap is None:
            return
        author = user.full_name or user.username or "Участник"
        remember(memory, int(chat.id), "user", user_text, ttl, cap, author)
        remember(memory, int(chat.id), "assistant", answer, ttl, cap)


def _response_token_limit(bot_module, user_settings: dict[str, Any] | None) -> int:
    helper = getattr(bot_module, "get_response_token_limit", None)
    if callable(helper):
        try:
            return int(helper(user_settings, normal_tokens=360))
        except Exception:
            pass
    return 360


async def _handle_recent_video_note_followup(update, context) -> None:
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    text = str(getattr(message, "text", "") or "") if message is not None else ""

    if (
        message is None
        or chat is None
        or user is None
        or user.is_bot
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or not is_recent_video_note_followup(text)
    ):
        return

    recent = get_recent_video_note(int(chat.id))
    if recent is None:
        # No live pointer means this runtime cannot safely identify a concrete
        # old circle. Fall through to the normal text/memory path instead of
        # guessing which historical media the user meant.
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    enforce = getattr(bot_module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "media"):
        raise ApplicationHandlerStop

    max_file_size = int(getattr(bot_module, "MAX_FILE_SIZE", 20 * 1024 * 1024))
    if recent.file_size and recent.file_size > max_file_size:
        await message.reply_text("Прошлый кружок слишком тяжёлый. Перешли его ещё раз покороче.")
        raise ApplicationHandlerStop

    register = getattr(bot_module, "register_user_and_chat", None)
    if callable(register):
        await register(update)

    increment = getattr(bot_module, "increment_stat", None)
    if callable(increment):
        await increment("total_requests")
        await increment("voice_requests")

    get_settings = getattr(bot_module, "get_user_settings", None)
    user_settings = await get_settings(user.id) if callable(get_settings) else None

    voice_enabled = bool(user_settings and user_settings.get("voice_enabled", False))
    text_requests_voice = getattr(bot_module, "text_requests_voice", None)
    voice_mode_enabled = getattr(bot_module, "voice_mode_enabled", None)
    force_voice = bool(
        (callable(text_requests_voice) and text_requests_voice(text))
        or (callable(voice_mode_enabled) and voice_mode_enabled(context))
        or voice_enabled
    )

    temp_dir = Path(getattr(bot_module, "TEMP_DIR", Path("temp")))
    temp_dir.mkdir(parents=True, exist_ok=True)
    file_path = temp_dir / (
        f"recent_video_note_{int(chat.id)}_{recent.message_id}_{uuid.uuid4().hex}.mp4"
    )

    keep_alive_task = None
    keep_alive = getattr(bot_module, "_keep_chat_action_alive", None)
    try:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        if callable(keep_alive):
            keep_alive_task = asyncio.create_task(keep_alive(chat.id, context))

        telegram_file = await context.bot.get_file(recent.file_id)
        await telegram_file.download_to_drive(custom_path=str(file_path))

        prompt = (
            "Прослушай сообщение пользователя и одновременно ПОСМОТРИ приложенный "
            "Telegram видео-кружок. Полную расшифровку не делай, если её не просили. "
            "Это именно предыдущий video_note из этого чата, на который пользователь "
            "сейчас ссылается текстом. Анализируй и видимые кадры, и звук. Если речи "
            "нет, всё равно ответь по тому, что реально видно. Не говори, что видео "
            "не прикрепилось или тебе недоступно, если кадры читаются. Не придумывай "
            "детали, которых не видно.\n\n"
            f"Текстовый запрос пользователя: {text}\n"
            "Ответь непосредственно по содержанию кружка, коротко и естественно."
        )

        answer = await bot_module.ask_gemini(
            contents=[
                bot_module.types.Part.from_bytes(
                    data=file_path.read_bytes(),
                    mime_type="video/mp4",
                ),
                prompt,
            ],
            max_output_tokens=_response_token_limit(bot_module, user_settings),
            voice_style=force_voice,
            user_settings=user_settings,
            chat_id=int(chat.id),
            chat_type=str(chat.type),
            user_name=(user.full_name or user.username or ""),
            recent_messages=_recent_messages(bot_module, int(chat.id)),
            bot_was_mentioned=True,
            user_id=int(user.id),
            thinking_level="low",
        )

        _remember_exchange(bot_module, update, text, str(answer))
        await bot_module.send_answer(
            update,
            context,
            str(answer),
            force_voice=force_voice,
        )
        if callable(increment):
            await increment("bot_answers")

    except ApplicationHandlerStop:
        raise
    except Exception as error:
        logging.exception("Recent video-note follow-up failed: %s", error)
        await message.reply_text(
            "Прошлый кружок сейчас не смог забрать или разобрать. Перешли его ещё раз."
        )
    finally:
        if keep_alive_task is not None:
            keep_alive_task.cancel()
            try:
                await keep_alive_task
            except asyncio.CancelledError:
                pass
        file_path.unlink(missing_ok=True)

    # The explicit media follow-up has been fully answered here. Do not let the
    # normal text handler generate a second response to the same message.
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return

    # One handler group is enough: VIDEO_NOTE and TEXT filters are disjoint.
    # It runs before natural_router (-2) and the ordinary bot handlers (0), but
    # the cache listener never stops propagation, so the existing 20% proactive
    # video-note behavior remains untouched.
    application.add_handler(
        MessageHandler(filters.VIDEO_NOTE, _cache_video_note),
        group=_HANDLER_GROUP,
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_recent_video_note_followup),
        group=_HANDLER_GROUP,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Recent video-note runtime ready: TTL=%ss chats<=%s; explicit follow-ups can inspect the last circle",
        int(RECENT_VIDEO_NOTE_TTL_SECONDS),
        MAX_RECENT_VIDEO_NOTE_CHATS,
    )
