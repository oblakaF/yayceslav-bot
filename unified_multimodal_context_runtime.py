"""Unify short-lived context across text, voice, video notes and videos.

Yayceslav already has 15-minute RAM conversation memory for ordinary text and a
separate 15-minute semantic voice window. This runtime connects those existing
paths instead of introducing another persistent store:

- voice/video-note requests receive the same recent text RAM context;
- successful voice transcripts replace generic "voice message" placeholders in
  the ordinary conversation memory;
- video-note memory keeps both a safe visual summary and spoken meaning when
  available;
- ordinary Telegram videos get one multimodal handler that watches frames and
  listens to audio, then writes the exchange to the same short-term RAM memory.

Nothing here writes transcripts, media or conversation content to SQLite. Raw
video bytes live only in the existing temporary directory for the current turn.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, MessageHandler, filters

import voice2_runtime
import voice_live_bridge_runtime


_INSTALLED = False
_PREPARED_APPLICATION_IDS: set[int] = set()
_HANDLER_GROUP = -3
SEMANTIC_CAPTURE_MAX_AGE_SECONDS = 120.0
MEMORY_TRANSCRIPT_MAX_CHARS = 700
VIDEO_CONTEXT_MAX_CHARS = 700

_VOICE_PLACEHOLDER = "[Пользователь отправил голосовое сообщение]"
_VIDEO_NOTE_PLACEHOLDER = "[Пользователь отправил видео-кружок]"


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def _normalize_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _is_private(chat_type: Any) -> bool:
    value = str(chat_type or "").lower()
    return value == str(ChatType.PRIVATE).lower() or value.endswith("private")


def _memory_context(
    bot_module: Any,
    *,
    chat_id: Any,
    chat_type: Any,
    user_id: Any,
) -> list[str] | None:
    """Read the bot's existing 15-minute text RAM memory as prompt lines."""
    builder = getattr(bot_module, "build_memory_context", None)
    if not callable(builder):
        return None

    if _is_private(chat_type):
        memory = getattr(bot_module, "PRIVATE_MEMORY", None)
        ttl = getattr(bot_module, "PRIVATE_MEMORY_SECONDS", None)
        key = user_id if user_id is not None else chat_id
    else:
        memory = getattr(bot_module, "GROUP_MEMORY", None)
        ttl = getattr(bot_module, "GROUP_MEMORY_SECONDS", None)
        key = chat_id

    if memory is None or ttl is None or key is None:
        return None
    try:
        text = str(builder(memory, int(key), ttl) or "")
    except Exception as error:
        logging.debug("Unified context read failed: %s", error)
        return None
    return text.splitlines() if text else None


def _latest_voice_semantics(
    chat_id: Any,
    *,
    now: float | None = None,
) -> tuple[str, str]:
    """Return only a very recent semantic voice turn, never an older topic."""
    if chat_id is None:
        return "", ""
    timestamp = float(time.monotonic() if now is None else now)
    try:
        turns = voice_live_bridge_runtime._VOICE_CONTEXT.get(int(chat_id), ())
        turn = turns[-1] if turns else None
    except Exception:
        turn = None
    if turn is None or timestamp - float(turn.timestamp) > SEMANTIC_CAPTURE_MAX_AGE_SECONDS:
        return "", ""
    return (
        _normalize_text(turn.transcript, MEMORY_TRANSCRIPT_MAX_CHARS),
        _normalize_text(turn.answer, 420),
    )


def _semantic_media_memory(text: str, *, video_note: bool, visual: str = "") -> str:
    spoken = _normalize_text(text, MEMORY_TRANSCRIPT_MAX_CHARS)
    visual = _normalize_text(visual, 240)
    if video_note:
        parts: list[str] = []
        if visual:
            parts.append(f"видно: {visual}")
        if spoken:
            parts.append(f"сказано: {spoken}")
        return f"[Видео-кружок: {'; '.join(parts)}]" if parts else _VIDEO_NOTE_PLACEHOLDER
    return f"[Голосовое: {spoken}]" if spoken else _VOICE_PLACEHOLDER


def _patch_voice_memory_placeholders(bot_module: Any) -> None:
    original = getattr(bot_module, "remember_message", None)
    if not callable(original) or getattr(original, "_yayceslav_unified_media_memory", False):
        return

    @functools.wraps(original)
    def remember_semantic_media(*args: Any, **kwargs: Any):
        positional = list(args)
        role = kwargs.get("role") if "role" in kwargs else (positional[2] if len(positional) > 2 else None)

        text_key = next((key for key in ("text", "content", "message") if key in kwargs), None)
        text = kwargs.get(text_key) if text_key else (positional[3] if len(positional) > 3 else None)
        memory_id = kwargs.get("memory_id") if "memory_id" in kwargs else (positional[1] if len(positional) > 1 else None)

        raw_text = str(text or "")
        if role == "user" and raw_text in (_VOICE_PLACEHOLDER, _VIDEO_NOTE_PLACEHOLDER):
            transcript, _ = _latest_voice_semantics(memory_id)
            is_video_note = raw_text == _VIDEO_NOTE_PLACEHOLDER
            visual = ""
            if is_video_note:
                try:
                    visual = voice2_runtime._normalize_memory_summary(
                        voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.get()
                    )
                    voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.set("")
                except Exception:
                    visual = ""
            replacement = _semantic_media_memory(
                transcript,
                video_note=is_video_note,
                visual=visual,
            )
            if text_key:
                kwargs[text_key] = replacement
            elif len(positional) > 3:
                positional[3] = replacement

        return original(*positional, **kwargs)

    remember_semantic_media._yayceslav_unified_media_memory = True
    bot_module.remember_message = remember_semantic_media


def _patch_voice_input_context(bot_module: Any) -> None:
    """Feed existing text/video RAM context into structured voice/video-note turns."""
    original = getattr(bot_module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_unified_voice_context", False):
        return

    @functools.wraps(original)
    async def ask_with_cross_modal_context(contents: Any, *args: Any, **kwargs: Any):
        call_kwargs = dict(kwargs)
        try:
            is_voice_turn = voice2_runtime._is_voice_decision_request(contents)
        except Exception:
            is_voice_turn = False
        if is_voice_turn and not call_kwargs.get("recent_messages"):
            context = _memory_context(
                bot_module,
                chat_id=call_kwargs.get("chat_id"),
                chat_type=call_kwargs.get("chat_type", "private"),
                user_id=call_kwargs.get("user_id"),
            )
            if context:
                call_kwargs["recent_messages"] = context
        return await original(contents, *args, **call_kwargs)

    ask_with_cross_modal_context._yayceslav_unified_voice_context = True
    bot_module.ask_gemini = ask_with_cross_modal_context


def _remember_exchange(
    bot_module: Any,
    *,
    chat_id: int,
    chat_type: Any,
    user_id: int,
    user_name: str,
    user_text: str,
    answer: str,
) -> None:
    remember = getattr(bot_module, "remember_message", None)
    if not callable(remember):
        return

    if _is_private(chat_type):
        memory = getattr(bot_module, "PRIVATE_MEMORY", None)
        ttl = getattr(bot_module, "PRIVATE_MEMORY_SECONDS", None)
        cap = getattr(bot_module, "PRIVATE_MEMORY_MAX_MESSAGES", None)
        key = user_id
        author = None
    else:
        memory = getattr(bot_module, "GROUP_MEMORY", None)
        ttl = getattr(bot_module, "GROUP_MEMORY_SECONDS", None)
        cap = getattr(bot_module, "GROUP_MEMORY_MAX_MESSAGES", None)
        key = chat_id
        author = user_name or "Участник"

    if memory is None or ttl is None or cap is None:
        return
    remember(memory, int(key), "user", user_text, ttl, cap, author)
    remember(memory, int(key), "assistant", str(answer), ttl, cap)


def _video_prompt(user_request: str) -> str:
    request = _normalize_text(user_request, VIDEO_CONTEXT_MAX_CHARS)
    return (
        "Это обычное Telegram-видео. ПОСМОТРИ видимые кадры и одновременно "
        "ПРОСЛУШАЙ аудиодорожку. Отвечай по обоим каналам: речь, действия, "
        "предметы и события, которые реально можно понять. Не заявляй, что видео "
        "недоступно, если кадры читаются. Не придумывай невидимые детали, личности "
        "или скрытые причины. Если пользователь задаёт конкретный вопрос — сначала "
        "ответь на него, а не пересказывай ролик целиком.\n\n"
        f"Запрос пользователя: {request or 'Коротко прокомментируй, что происходит в видео.'}"
    )


async def _handle_video(update: Any, context: Any) -> None:
    bot_module = _find_bot_module()
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    video = getattr(message, "video", None) if message is not None else None
    if bot_module is None or message is None or chat is None or user is None or video is None:
        return
    if getattr(user, "is_bot", False):
        return

    prepare_text = getattr(bot_module, "prepare_request_text", None)
    if callable(prepare_text):
        prompt_text = await prepare_text(
            update=update,
            context=context,
            original_text=getattr(message, "caption", None),
            default_text="Коротко прокомментируй это видео: что происходит и что в нём важного?",
        )
        if prompt_text is None:
            return
    else:
        # Without the bot's normal mention/reply routing helper, stay conservative
        # in groups and only accept videos in private chats.
        if not _is_private(getattr(chat, "type", "")):
            return
        prompt_text = str(getattr(message, "caption", "") or "") or "Прокомментируй это видео."

    enforce = getattr(bot_module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "media"):
        return

    file_size = int(getattr(video, "file_size", 0) or 0)
    max_file_size = int(getattr(bot_module, "MAX_FILE_SIZE", 20 * 1024 * 1024))
    if file_size and file_size > max_file_size:
        await message.reply_text("Видео тяжелее 20 МБ. Скинь покороче или ужми — тогда разберу.")
        return

    register = getattr(bot_module, "register_user_and_chat", None)
    if callable(register):
        await register(update)
    increment = getattr(bot_module, "increment_stat", None)
    if callable(increment):
        await increment("total_requests")

    get_settings = getattr(bot_module, "get_user_settings", None)
    user_settings = await get_settings(int(user.id)) if callable(get_settings) else None

    force_voice = False
    text_requests_voice = getattr(bot_module, "text_requests_voice", None)
    voice_mode_enabled = getattr(bot_module, "voice_mode_enabled", None)
    if callable(text_requests_voice):
        force_voice = bool(text_requests_voice(prompt_text))
    if callable(voice_mode_enabled):
        force_voice = force_voice or bool(voice_mode_enabled(context))
    force_voice = force_voice or bool(user_settings and user_settings.get("voice_enabled", False))

    temp_dir = Path(getattr(bot_module, "TEMP_DIR", Path("temp")))
    temp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(str(getattr(video, "file_name", "") or "video.mp4")).suffix or ".mp4"
    file_path = temp_dir / f"video_{int(chat.id)}_{int(message.message_id)}_{uuid.uuid4().hex}{suffix}"
    keep_alive_task = None
    keep_alive = getattr(bot_module, "_keep_chat_action_alive", None)

    try:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        if callable(keep_alive):
            keep_alive_task = asyncio.create_task(keep_alive(chat.id, context))

        telegram_file = await video.get_file()
        await telegram_file.download_to_drive(custom_path=str(file_path))

        recent = _memory_context(
            bot_module,
            chat_id=int(chat.id),
            chat_type=getattr(chat, "type", "private"),
            user_id=int(user.id),
        )
        mime_type = str(getattr(video, "mime_type", "") or "video/mp4")
        token_helper = getattr(bot_module, "get_response_token_limit", None)
        max_tokens = int(token_helper(user_settings, normal_tokens=360)) if callable(token_helper) else 360

        answer = await bot_module.ask_gemini(
            contents=[
                bot_module.types.Part.from_bytes(data=file_path.read_bytes(), mime_type=mime_type),
                _video_prompt(prompt_text),
            ],
            max_output_tokens=max_tokens,
            voice_style=force_voice,
            user_settings=user_settings,
            chat_id=int(chat.id),
            chat_type=str(getattr(chat, "type", "private")),
            user_name=(getattr(user, "full_name", "") or getattr(user, "username", "") or ""),
            recent_messages=recent,
            bot_was_mentioned=True,
            user_id=int(user.id),
            thinking_level="low",
        )

        memory_label = f"[Пользователь прислал видео] {_normalize_text(prompt_text, VIDEO_CONTEXT_MAX_CHARS)}"
        _remember_exchange(
            bot_module,
            chat_id=int(chat.id),
            chat_type=getattr(chat, "type", "private"),
            user_id=int(user.id),
            user_name=(getattr(user, "full_name", "") or getattr(user, "username", "") or ""),
            user_text=memory_label,
            answer=str(answer),
        )

        send_answer = getattr(bot_module, "send_answer", None)
        if callable(send_answer):
            await send_answer(update, context, str(answer), force_voice=force_voice)
        else:
            await message.reply_text(str(answer))
        if callable(increment):
            await increment("bot_answers")
    except Exception as error:
        logging.exception("Telegram video analysis failed: %s", error)
        await message.reply_text("Видео сейчас не разобралось. Перешли ещё раз или скинь кусок покороче.")
    finally:
        if keep_alive_task is not None:
            keep_alive_task.cancel()
            try:
                await keep_alive_task
            except asyncio.CancelledError:
                pass
        file_path.unlink(missing_ok=True)


def install(bot_module: Any | None = None) -> bool:
    """Install cross-modal prompt/memory bridges after Voice Live is available."""
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _patch_voice_input_context(module)
    _patch_voice_memory_placeholders(module)
    _INSTALLED = True
    logging.warning(
        "Unified multimodal context ready: text<->voice<->video-note 15m RAM bridge; no SQLite"
    )
    return True


def prepare_application_runtime(application: Application) -> None:
    """Register ordinary Telegram VIDEO analysis once per Application."""
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    application.add_handler(MessageHandler(filters.VIDEO, _handle_video), group=_HANDLER_GROUP)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Telegram video runtime ready: frames + audio + shared short context")
