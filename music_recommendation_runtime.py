"""ListenBrainz-backed music recommendations for Yayceslav.

High-confidence recommendation requests are resolved to a MusicBrainz artist,
then ListenBrainz LB Radio supplies recordings from similar artists. A single
ListenBrainz metadata batch turns recording MBIDs into user-facing candidates.
The existing chat-local self_canon.music is injected only as a preference lens;
it never changes provider facts and no recommendation silently rewrites canon.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters

import entity_continuity_runtime
import music_runtime
import self_canon_runtime


LISTENBRAINZ_BASE = "https://api.listenbrainz.org/1"
REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL_SECONDS = 10 * 60
CACHE_MAX_ENTRIES = 192
MIN_REQUEST_INTERVAL_SECONDS = 0.30
MAX_CANDIDATES = 12
_PREPARED_APPLICATION_IDS: set[int] = set()


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    created_at: float


_CACHE: dict[str, CacheEntry] = {}
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


_RECOMMEND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:что|кого)\s+(?:ты\s+)?посовету(?:ешь|й)\s*,?\s*(?:если\s+)?(?:мне\s+)?"
        r"(?:нравится|нравятся|заходит|люблю)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(
        r"\b(?:что|кого)\s+послушать\s*,?\s*(?:если\s+)?(?:мне\s+)?(?:нравится|нравятся|заходит|люблю)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(r"\b(?:на\s+кого|на\s+что)\s+похож(?:а|и)?\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:похожие\s+(?:исполнители|артисты|группы)|похожая\s+музыка)\s+(?:на\s+)?(?P<query>.+)$", re.I),
    re.compile(r"\b(?:дай|подбери|посоветуй)\s+(?:мне\s+)?(?:3|5|пять|несколько)?\s*"
               r"(?:треков|песен|исполнителей|артистов)\s+(?:как|похожих\s+на|в\s+духе)\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:recommend|similar\s+to|artists\s+like)\s+(?P<query>.+)$", re.I),
)

_FOLLOWUP_RE = re.compile(
    r"^\s*(?:а\s+)?(?:ещ[её]|что\s+ещ[её]|дай\s+ещ[её]|а\s+похожее|похожее\s+ещ[её])\s*[?!.]*\s*$",
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
    text = re.sub(r"^(?:группа|исполнитель|артист)\s+", "", text, flags=re.I)
    return text[:180]


def classify_recommendation_intent(text: str, *, chat_id: int | None = None) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return ""
    for pattern in _RECOMMEND_PATTERNS:
        match = pattern.search(value)
        if match:
            return _clean_query(match.group("query"))
    if chat_id is not None and _FOLLOWUP_RE.search(value):
        return _clean_query(entity_continuity_runtime.current_topic(int(chat_id)))
    return ""


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


async def _listenbrainz_get(path: str, params: dict[str, Any] | None = None) -> Any:
    global _LAST_REQUEST_AT
    params = params or {}
    cache_key = path + "?" + "&".join(f"{key}={params[key]}" for key in sorted(params))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    async with _REQUEST_LOCK:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        delay = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)
        headers = {"User-Agent": music_runtime.MUSICBRAINZ_USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
            response = await client.get(f"{LISTENBRAINZ_BASE}/{path.lstrip('/')}", params=params)
            _LAST_REQUEST_AT = time.monotonic()
            if response.status_code in {204, 404}:
                return None
            response.raise_for_status()
            payload = response.json()
        _cache_put(cache_key, payload)
        return payload


def _radio_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("payload", "recordings", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for nested in ("recordings", "results"):
                rows = value.get(nested)
                if isinstance(rows, list):
                    return [item for item in rows if isinstance(item, dict)]
    # Current LB Radio may also return a mapping/grouped structure.
    rows: list[dict[str, Any]] = []
    for value in payload.values():
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _metadata_map(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("recordings"), dict):
            return {str(k): v for k, v in payload["recordings"].items() if isinstance(v, dict)}
        return {str(k): v for k, v in payload.items() if isinstance(v, dict)}
    return {}


def _recording_name(meta: dict[str, Any]) -> str:
    for key in ("recording_name", "name", "title"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    recording = meta.get("recording")
    if isinstance(recording, dict):
        return str(recording.get("name") or recording.get("title") or "").strip()
    return ""


def _artist_name(meta: dict[str, Any]) -> str:
    artist = meta.get("artist")
    if isinstance(artist, dict):
        value = str(artist.get("name") or artist.get("artist_credit_name") or "").strip()
        if value:
            return value
        artists = artist.get("artists")
        if isinstance(artists, list):
            names = [str(item.get("name") or "").strip() for item in artists if isinstance(item, dict)]
            names = [name for name in names if name]
            if names:
                return ", ".join(names)
    for key in ("artist_name", "artist_credit_name"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    return ""


def _tags(meta: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    tag = meta.get("tag")
    if isinstance(tag, dict):
        for group in ("recording", "artist", "release_group"):
            for item in tag.get(group) or []:
                if isinstance(item, dict):
                    value = str(item.get("tag") or "").strip()
                    if value and value.lower() not in {x.lower() for x in tags}:
                        tags.append(value)
                if len(tags) >= 8:
                    return tags
    return tags


async def recommend_from_artist(artist_query: str) -> dict[str, Any] | None:
    artist = await music_runtime.lookup_artist(artist_query)
    if not artist or not artist.get("mbid"):
        return None
    seed_mbid = str(artist["mbid"])
    radio = await _listenbrainz_get(
        f"lb-radio/artist/{seed_mbid}",
        {
            "mode": "medium",
            "max_similar_artists": 8,
            "max_recordings_per_artist": 2,
            "pop_begin": 25,
            "pop_end": 100,
        },
    )
    rows = _radio_rows(radio)
    if not rows:
        return None

    raw: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        mbid = str(row.get("recording_mbid") or "").strip()
        if not mbid or mbid in seen:
            continue
        seen.add(mbid)
        raw.append(
            {
                "recording_mbid": mbid,
                "similar_artist_mbid": str(row.get("similar_artist_mbid") or ""),
                "similar_artist_name": str(row.get("similar_artist_name") or "").strip(),
                "listen_count": int(row.get("total_listen_count") or 0),
            }
        )
        if len(raw) >= MAX_CANDIDATES:
            break
    if not raw:
        return None

    metadata = await _listenbrainz_get(
        "metadata/recording/",
        {"recording_mbids": ",".join(item["recording_mbid"] for item in raw), "inc": "artist tag release"},
    )
    meta_map = _metadata_map(metadata)
    candidates: list[dict[str, Any]] = []
    for item in raw:
        meta = meta_map.get(item["recording_mbid"], {})
        title = _recording_name(meta)
        artist_name = _artist_name(meta) or item["similar_artist_name"]
        if not title or not artist_name:
            continue
        if artist_name.casefold() == str(artist.get("name") or artist_query).casefold():
            continue
        candidates.append(
            {
                **item,
                "title": title,
                "artist": artist_name,
                "tags": _tags(meta),
            }
        )
    candidates.sort(key=lambda item: item["listen_count"], reverse=True)
    return {"seed": artist, "candidates": candidates[:8]} if candidates else None


def _load_music_canon(bot_module: Any, chat_id: int) -> str:
    try:
        canon = self_canon_runtime.load_canon_sync(bot_module, int(chat_id))
    except Exception:
        logging.exception("Recommendation runtime could not load self-canon")
        return ""
    return str(canon.get("music") or "").strip()


def build_recommendation_context(data: dict[str, Any], *, user_text: str, canon_music: str) -> str:
    seed = data.get("seed") or {}
    lines: list[str] = []
    for index, item in enumerate(data.get("candidates") or [], start=1):
        tags = ", ".join(item.get("tags") or []) or "нет тегов"
        lines.append(
            f"{index}. {item['artist']} — {item['title']} | listens={item['listen_count']} | tags={tags} | "
            f"recording_mbid={item['recording_mbid']}"
        )
    canon = canon_music or "не установлен"
    return (
        "Пользователь просит музыкальную рекомендацию. Ниже кандидаты из ListenBrainz LB Radio, "
        "полученные от реально разрешённого seed-исполнителя MusicBrainz. Не придумывай другие треки. "
        "Выбери 3–5 лучших кандидатов и кратко объясни каждый выбор. total_listen_count — сигнал популярности, "
        "а не оценка качества. Если теги есть, используй их как дополнительный сигнал сходства.\n"
        "Отдельно учитывай музыкальный self-canon Яйцеслава как личный вкус: он может сказать, что сам выбрал бы "
        "из списка, но не должен притворяться, что его вкус является объективным рейтингом. Рекомендация не меняет "
        "self_canon.music автоматически.\n\n"
        f"ВОПРОС: {user_text}\nSEED: {seed.get('name') or ''} | MBID={seed.get('mbid') or ''}\n"
        f"SELF_CANON.MUSIC: {canon}\n\nLISTENBRAINZ CANDIDATES:\n" + "\n".join(lines)
    )


async def _route_recommendations(update: Any, context: Any) -> None:
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
    query = classify_recommendation_intent(prepared, chat_id=int(chat.id))
    if not query:
        return

    enforce = getattr(module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "general"):
        raise ApplicationHandlerStop

    try:
        data = await recommend_from_artist(query)
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
        logging.warning("ListenBrainz recommendation failed query=%r: %s", query, error)
        return
    except Exception as error:
        logging.exception("Unexpected ListenBrainz recommendation failure query=%r: %s", query, error)
        return
    if not data:
        return

    seed_name = str((data.get("seed") or {}).get("name") or query)
    entity_continuity_runtime.remember_topic(int(chat.id), seed_name)
    prompt = build_recommendation_context(
        data,
        user_text=prepared,
        canon_music=_load_music_canon(module, int(chat.id)),
    )
    answer = await module.ask_gemini(
        contents=prompt,
        max_output_tokens=650,
        chat_id=int(chat.id),
        chat_type=str(getattr(chat, "type", "private")),
        user_name=(getattr(user, "full_name", "") or getattr(user, "username", "") or ""),
        user_id=int(user.id),
        bot_was_mentioned=True,
        thinking_level="minimal",
    )
    answer_text = str(answer or "").strip()
    if "listenbrainz.org" not in answer_text.lower():
        answer_text += "\n\nИсточник рекомендаций: ListenBrainz"

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
    logging.info("ListenBrainz recommendation route: query=%r seed=%r", query, seed_name)
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _route_recommendations), group=-3)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "ListenBrainz recommendations ready: artist-seed LB Radio + batch metadata + self-canon music lens"
    )
