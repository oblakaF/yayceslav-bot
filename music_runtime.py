"""Specialist MusicBrainz routing for common music catalog questions.

This runtime deliberately handles only high-confidence artist/track metadata
questions. It runs before the ordinary text handler, uses the bot's normal
address rules, queries MusicBrainz with a polite global rate limiter and bounded
RAM cache, then passes normalized facts into the existing Gemini/Yayceslav
answer path. No extra Gemini call is used for intent classification.

Lyrics and recommendations are intentionally out of scope for this foundation;
they are separate roadmap stages (LRCLIB and ListenBrainz).
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from telegram.constants import ChatType
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters

import entity_continuity_runtime


MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_SITE = "https://musicbrainz.org"
MUSICBRAINZ_USER_AGENT = "YayceslavBot/2.0 (https://github.com/oblakaF/yayceslav-bot)"
REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL_SECONDS = 10 * 60
CACHE_MAX_ENTRIES = 256
MIN_REQUEST_INTERVAL_SECONDS = 1.05
_PREPARED_APPLICATION_IDS: set[int] = set()


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    created_at: float


_CACHE: dict[str, CacheEntry] = {}
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


_TRACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:кто\s+(?:по[её]т|исполняет)|чья\s+песня)\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:что\s+за\s+(?:песня|трек)|расскажи\s+про\s+(?:песню|трек))\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:из\s+какого\s+альбома|какого\s+года)\s+(?:песня|трек)?\s*(?P<query>.+)$", re.I),
)

_ARTIST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:кто\s+(?:такие|такой|такая)|расскажи\s+про)\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:что\s+ещ[её]\s+(?:есть\s+)?у|альбомы|дискография)\s+(?P<query>.+)$", re.I),
)

_MUSIC_WORD_RE = re.compile(
    r"\b(?:песн\w*|трек\w*|альбом\w*|дискограф\w*|исполнител\w*|музык\w*|групп\w*)\b",
    re.I,
)

_FOLLOWUP_MUSIC_RE = re.compile(
    r"^\s*(?:а\s+)?(?:из\s+какого\s+(?:она|он)\s+альбома|"
    r"какого\s+(?:она|он)\s+года|кто\s+(?:е[её]|его)\s+по[её]т|"
    r"что\s+ещ[её]\s+у\s+(?:них|него|не[её]))\s*[?!.]*\s*$",
    re.I,
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "prepare_request_text", None)):
            return module
    return None


def _clean_query(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" \t\r\n,.:;!?—-\"'«»")
    text = re.sub(r"^(?:песня|трек|группа|исполнитель)\s+", "", text, flags=re.I)
    return text[:180]


def classify_music_intent(text: str, *, chat_id: int | None = None) -> tuple[str, str] | None:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return None

    for pattern in _TRACK_PATTERNS:
        match = pattern.search(value)
        if match:
            query = _clean_query(match.group("query"))
            if query:
                return "track", query

    for pattern in _ARTIST_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        query = _clean_query(match.group("query"))
        # Generic "кто такой X" belongs to the ordinary/entity path unless the
        # current turn also clearly says music/group/artist.
        if query and (_MUSIC_WORD_RE.search(value) or re.search(r"\b(?:группа|исполнитель)\b", value, re.I)):
            return "artist", query
        if pattern is _ARTIST_PATTERNS[1] and query:
            return "artist", query

    if chat_id is not None and _FOLLOWUP_MUSIC_RE.search(value):
        topic = entity_continuity_runtime.current_topic(int(chat_id))
        topic = _clean_query(topic)
        if topic:
            if re.search(r"альбом|года|по[её]т", value, re.I):
                return "track", topic
            return "artist", topic

    return None


def _cache_get(key: str) -> Any | None:
    now = time.monotonic()
    stale = [item for item, entry in _CACHE.items() if now - entry.created_at > CACHE_TTL_SECONDS]
    for item in stale:
        _CACHE.pop(item, None)
    entry = _CACHE.get(key)
    return None if entry is None else entry.value


def _cache_put(key: str, value: Any) -> None:
    if len(_CACHE) >= CACHE_MAX_ENTRIES and key not in _CACHE:
        oldest = min(_CACHE.items(), key=lambda item: item[1].created_at)[0]
        _CACHE.pop(oldest, None)
    _CACHE[key] = CacheEntry(value=value, created_at=time.monotonic())


async def _musicbrainz_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    global _LAST_REQUEST_AT
    cache_key = path + "?" + "&".join(f"{key}={params[key]}" for key in sorted(params))
    cached = _cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    async with _REQUEST_LOCK:
        cached = _cache_get(cache_key)
        if isinstance(cached, dict):
            return cached

        delay = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)

        headers = {"User-Agent": MUSICBRAINZ_USER_AGENT, "Accept": "application/json"}
        query = dict(params)
        query["fmt"] = "json"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
            response = await client.get(f"{MUSICBRAINZ_BASE}/{path}", params=query)
            _LAST_REQUEST_AT = time.monotonic()
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("MusicBrainz returned non-object JSON")
        _cache_put(cache_key, payload)
        return payload


def _artist_credit(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for credit in item.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        name = str(credit.get("name") or (credit.get("artist") or {}).get("name") or "").strip()
        if name:
            parts.append(name + str(credit.get("joinphrase") or ""))
    return "".join(parts).strip()


def _recording_summary(item: dict[str, Any]) -> dict[str, Any]:
    releases: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for release in item.get("releases") or []:
        if not isinstance(release, dict):
            continue
        title = str(release.get("title") or "").strip()
        rg = release.get("release-group") if isinstance(release.get("release-group"), dict) else {}
        group_title = str(rg.get("title") or title).strip()
        group_type = str(rg.get("primary-type") or "").strip()
        key = (group_title.lower(), group_type.lower())
        if group_title and key not in seen:
            seen.add(key)
            releases.append({"title": group_title, "type": group_type})
        if len(releases) >= 5:
            break
    return {
        "mbid": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "artist": _artist_credit(item),
        "first_release_date": str(item.get("first-release-date") or ""),
        "score": int(item.get("score") or 0),
        "releases": releases,
    }


async def lookup_track(query: str) -> dict[str, Any] | None:
    escaped = query.replace('"', '\\"')
    payload = await _musicbrainz_get(
        "recording/",
        {"query": f'recording:"{escaped}"', "limit": 5},
    )
    recordings = payload.get("recordings") or []
    candidates = [_recording_summary(item) for item in recordings if isinstance(item, dict)]
    candidates = [item for item in candidates if item["title"] and item["artist"]]
    return candidates[0] if candidates else None


def _artist_summary(item: dict[str, Any]) -> dict[str, Any]:
    area = item.get("area") if isinstance(item.get("area"), dict) else {}
    life = item.get("life-span") if isinstance(item.get("life-span"), dict) else {}
    return {
        "mbid": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "sort_name": str(item.get("sort-name") or ""),
        "type": str(item.get("type") or ""),
        "country": str(item.get("country") or ""),
        "area": str(area.get("name") or ""),
        "begin": str(life.get("begin") or ""),
        "end": str(life.get("end") or ""),
        "disambiguation": str(item.get("disambiguation") or ""),
        "score": int(item.get("score") or 0),
    }


async def lookup_artist(query: str) -> dict[str, Any] | None:
    escaped = query.replace('"', '\\"')
    payload = await _musicbrainz_get("artist/", {"query": f'artist:"{escaped}"', "limit": 5})
    artists = [_artist_summary(item) for item in payload.get("artists") or [] if isinstance(item, dict)]
    artists = [item for item in artists if item["name"] and item["mbid"]]
    if not artists:
        return None

    artist = artists[0]
    releases_payload = await _musicbrainz_get(
        "release-group/",
        {
            "artist": artist["mbid"],
            "limit": 12,
            "inc": "artist-credits",
            "type": "album|ep|single",
        },
    )
    release_groups: list[dict[str, str]] = []
    for item in releases_payload.get("release-groups") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        release_groups.append(
            {
                "title": title,
                "type": str(item.get("primary-type") or ""),
                "date": str(item.get("first-release-date") or ""),
            }
        )
        if len(release_groups) >= 8:
            break
    artist["release_groups"] = release_groups
    return artist


def _music_context(kind: str, data: dict[str, Any], user_text: str) -> tuple[str, str]:
    if kind == "track":
        source_url = f"{MUSICBRAINZ_SITE}/recording/{data['mbid']}"
        releases = "; ".join(
            f"{item['title']}" + (f" ({item['type']})" if item.get("type") else "")
            for item in data.get("releases") or []
        ) or "не указаны в результате поиска"
        facts = (
            f"Тип сущности: recording\nНазвание: {data['title']}\nИсполнитель: {data['artist']}\n"
            f"Первый релиз: {data.get('first_release_date') or 'не указан'}\n"
            f"Релизы/release groups: {releases}\nMBID: {data['mbid']}\nИсточник: {source_url}"
        )
    else:
        source_url = f"{MUSICBRAINZ_SITE}/artist/{data['mbid']}"
        releases = "; ".join(
            f"{item['title']}" + (f" ({item['type']})" if item.get("type") else "")
            + (f", {item['date']}" if item.get("date") else "")
            for item in data.get("release_groups") or []
        ) or "не удалось получить"
        facts = (
            f"Тип сущности: artist\nИмя: {data['name']}\nТип: {data.get('type') or 'не указан'}\n"
            f"Страна/область: {data.get('country') or data.get('area') or 'не указана'}\n"
            f"Начало: {data.get('begin') or 'не указано'}\n"
            f"Уточнение MusicBrainz: {data.get('disambiguation') or 'нет'}\n"
            f"Несколько release groups: {releases}\nMBID: {data['mbid']}\nИсточник: {source_url}"
        )

    prompt = (
        "Пользователь задал музыкальный вопрос. Ниже факты из MusicBrainz. "
        "Ответь по-русски как обычный Яйцеслав: сначала прямой ответ, потом при необходимости 1–3 детали. "
        "Не придумывай сведения, которых нет в данных. Если вопрос шире данных, прямо отдели известное от неизвестного. "
        "Не называй MusicBrainz своей памятью; это внешний каталог. Не переписывай self-canon.music на основании каталога.\n\n"
        f"ВОПРОС: {user_text}\n\nMUSICBRAINZ DATA:\n{facts}"
    )
    return prompt, source_url


async def _route_music(update: Any, context: Any) -> None:
    module = _find_bot_module()
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if module is None or message is None or chat is None or user is None:
        return
    original_text = str(getattr(message, "text", "") or "")
    if not original_text:
        return

    prepared = await module.prepare_request_text(
        update=update,
        context=context,
        original_text=original_text,
        default_text="",
    )
    if prepared is None:
        return

    resolved = entity_continuity_runtime.resolve_followup(int(chat.id), prepared)
    intent = classify_music_intent(prepared, chat_id=int(chat.id))
    if intent is None and resolved != prepared:
        intent = classify_music_intent(resolved, chat_id=int(chat.id))
    if intent is None:
        return

    kind, query = intent
    if not query:
        return

    enforce = getattr(module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "general"):
        raise ApplicationHandlerStop

    try:
        data = await (lookup_track(query) if kind == "track" else lookup_artist(query))
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
        logging.warning("MusicBrainz lookup failed kind=%s query=%r: %s", kind, query, error)
        return
    except Exception as error:
        logging.exception("Unexpected MusicBrainz failure kind=%s query=%r: %s", kind, query, error)
        return

    if not data:
        return

    entity_name = str(data.get("title") if kind == "track" else data.get("name") or query)
    if entity_name:
        entity_continuity_runtime.remember_topic(int(chat.id), entity_name)

    prompt, source_url = _music_context(kind, data, prepared)
    try:
        answer = await module.ask_gemini(
            contents=prompt,
            max_output_tokens=420,
            chat_id=int(chat.id),
            chat_type=str(getattr(chat, "type", "private")),
            user_name=(getattr(user, "full_name", "") or getattr(user, "username", "") or ""),
            user_id=int(user.id),
            bot_was_mentioned=True,
            thinking_level="minimal",
        )
    except Exception as error:
        logging.warning("Music answer generation failed: %s", error)
        return

    answer_text = str(answer or "").strip()
    if source_url not in answer_text:
        answer_text += f"\n\nИсточник: {source_url}"

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

    logging.info("MusicBrainz route: kind=%s query=%r entity=%r", kind, query, entity_name)
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _route_music),
        group=-1,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "MusicBrainz runtime ready: track/artist catalog, 10m cache, >=1.05s provider spacing; no classifier model call"
    )
