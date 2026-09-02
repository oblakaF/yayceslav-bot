"""Attach dual-source lyrics analysis to the existing music handler.

The bridge wraps ``music_runtime._route_music`` before the handler is registered.
Non-lyrics questions fall through unchanged to the stable MusicBrainz catalog
runtime. Lyrics questions try catalog resolution only as optional enrichment;
LRCLIB/Musixmatch matching does not depend on MusicBrainz succeeding.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from telegram.ext import ApplicationHandlerStop

import entity_continuity_runtime
import lyrics_runtime
import music_runtime


_INSTALLED = False


async def _optional_catalog_track(query: str) -> dict[str, Any] | None:
    """Best-effort MusicBrainz enrichment; failure must not block lyrics lookup."""
    try:
        return await music_runtime.lookup_track(query)
    except Exception as error:
        logging.info("Lyrics catalog enrichment skipped query=%r: %s", query, error)
        return None


async def _send_lyrics_answer(
    module: Any,
    update: Any,
    context: Any,
    *,
    prepared: str,
    mode: str,
    query: str,
) -> bool:
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if message is None or chat is None or user is None:
        return False

    enforce = getattr(module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "general"):
        return True

    catalog = await _optional_catalog_track(query)
    result = await lyrics_runtime.lookup_lyrics(query, catalog_track=catalog)
    if not result:
        # Last-resort factual path: use the bot's existing real web-search
        # implementation rather than asking Gemini to invent lyrics from memory.
        perform_web_search = getattr(module, "perform_web_search", None)
        if callable(perform_web_search):
            search_query = f"{query} песня текст смысл"
            logging.info("Lyrics providers empty; using generic search fallback query=%r", search_query)
            await perform_web_search(
                update=update,
                context=context,
                query=search_query,
                force_voice=False,
            )
            return True
        return False

    entity = " — ".join(
        value
        for value in (
            str(result.get("artist_name") or "").strip(),
            str(result.get("track_name") or query).strip(),
        )
        if value
    )
    if entity:
        entity_continuity_runtime.remember_topic(int(chat.id), entity)

    prompt, source_url = lyrics_runtime.build_lyrics_context(
        result,
        user_text=prepared,
        mode=mode,
        catalog_track=catalog,
    )
    try:
        answer = await module.ask_gemini(
            contents=prompt,
            max_output_tokens=520,
            chat_id=int(chat.id),
            chat_type=str(getattr(chat, "type", "private")),
            user_name=(getattr(user, "full_name", "") or getattr(user, "username", "") or ""),
            user_id=int(user.id),
            bot_was_mentioned=True,
            thinking_level="minimal",
        )
    except Exception as error:
        logging.warning("Lyrics analysis generation failed: %s", error)
        return False

    answer_text = str(answer or "").strip()
    if source_url and source_url not in answer_text:
        answer_text += f"\n\nИсточник текста: {source_url}"

    send_answer = getattr(module, "send_answer", None)
    if callable(send_answer):
        await send_answer(update, context, answer_text, force_voice=False)
    else:
        await message.reply_text(answer_text)

    register = getattr(module, "register_user_and_chat", None)
    increment = getattr(module, "increment_stat", None)
    if callable(register):
        await register(update)
    if callable(increment):
        await increment("total_requests")
        await increment("bot_answers")

    logging.info(
        "Lyrics route: provider=%s query=%r entity=%r",
        result.get("provider"),
        query,
        entity,
    )
    return True


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    original = music_runtime._route_music
    if getattr(original, "_yayceslav_dual_source_lyrics", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    async def route_music_with_lyrics(update: Any, context: Any) -> None:
        module = music_runtime._find_bot_module()
        message = getattr(update, "effective_message", None)
        chat = getattr(update, "effective_chat", None)
        if module is None or message is None or chat is None:
            return await original(update, context)

        original_text = str(getattr(message, "text", "") or "")
        if not original_text:
            return await original(update, context)

        prepared = await module.prepare_request_text(
            update=update,
            context=context,
            original_text=original_text,
            default_text="",
        )
        if prepared is None:
            return

        topic = entity_continuity_runtime.current_topic(int(chat.id))
        intent = lyrics_runtime.classify_lyrics_intent(prepared, current_topic=topic)
        if intent is None:
            return await original(update, context)

        mode, query = intent
        handled = await _send_lyrics_answer(
            module,
            update,
            context,
            prepared=prepared,
            mode=mode,
            query=query,
        )
        if handled:
            raise ApplicationHandlerStop
        return await original(update, context)

    route_music_with_lyrics._yayceslav_dual_source_lyrics = True
    music_runtime._route_music = route_music_with_lyrics
    _INSTALLED = True
    logging.warning(
        "Lyrics runtime ready: LRCLIB -> optional Musixmatch -> real-search fallback; no durable full-lyrics storage"
    )
    return True
