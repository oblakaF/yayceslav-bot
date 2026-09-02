"""Lyrics provider layer for music analysis.

Provider order is intentionally independent from MusicBrainz success:
1. LRCLIB exact lookup when catalog metadata is available.
2. LRCLIB free-text search from the user's raw track query.
3. Musixmatch when MUSIXMATCH_API_KEY is configured.
4. The caller may then fall back to Yayceslav's existing web-search path.

Full lyrics are kept only in a short-lived in-memory cache and are supplied to
Gemini for analysis, never written to SQLite by this runtime.  Prompts explicitly
forbid reproducing a full copyrighted lyric in the answer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


LRCLIB_BASE = "https://lrclib.net/api"
MUSIXMATCH_BASE = "https://api.musixmatch.com/ws/1.1"
LYRICS_USER_AGENT = "YayceslavBot/2.0 (https://github.com/oblakaF/yayceslav-bot)"
REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL_SECONDS = 10 * 60
CACHE_MAX_ENTRIES = 192
LRCLIB_MIN_REQUEST_INTERVAL_SECONDS = 0.30
MUSIXMATCH_MIN_REQUEST_INTERVAL_SECONDS = 0.25
MAX_PROVIDER_RETRY_AFTER_SECONDS = 30.0


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    created_at: float


_CACHE: dict[str, CacheEntry] = {}
_LRCLIB_LOCK = asyncio.Lock()
_MUSIXMATCH_LOCK = asyncio.Lock()
_LRCLIB_LAST_REQUEST_AT = 0.0
_MUSIXMATCH_LAST_REQUEST_AT = 0.0
_LRCLIB_BLOCKED_UNTIL = 0.0
_MUSIXMATCH_BLOCKED_UNTIL = 0.0


_LYRIC_INTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "lyrics",
        re.compile(
            r"\b(?:текст|слова)\s+(?:песни|трека)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "meaning",
        re.compile(
            r"\b(?:о\s+ч[её]м|про\s+что|смысл|объясни\s+смысл|разбери\s+текст)\s+"
            r"(?:песни|песня|трека|трек)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "meaning",
        re.compile(
            r"\b(?:что\s+значит|что\s+означает)\s+(?:песня|трек)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "line",
        re.compile(
            r"\b(?:что\s+значит|что\s+означает|объясни)\s+(?:эта\s+)?(?:строка|фраза)\b"
            r".+?\b(?:в|из)\s+(?:песне|песни|треке|трека)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "lyrics",
        re.compile(
            r"\b(?:lyrics|words\s+to)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "meaning",
        re.compile(
            r"\b(?:what\s+is|what's)\s+(?:the\s+)?meaning\s+of\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
    ),
)

_LYRIC_FOLLOWUP_RE = re.compile(
    r"^\s*(?:а\s+)?(?:о\s+ч[её]м\s+(?:она|он)|про\s+что\s+(?:она|он)|"
    r"а?\s*смысл\s+(?:какой|в\s+ч[её]м)|текст\s+есть|слова\s+есть)\s*[?!.]*\s*$",
    re.IGNORECASE,
)

_NOTICE_RE = re.compile(
    r"\n?\*{3,}.*?(?:commercial\s+use|not\s+for\s+commercial\s+use).*?$",
    re.IGNORECASE | re.DOTALL,
)
_TIMESTAMP_RE = re.compile(r"^\s*\[[0-9:.]+\]\s*", re.MULTILINE)
_TOKEN_RE = re.compile(r"[\wёЁ]+", re.UNICODE)


def _clean_query(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" \t\r\n,.:;!?—-\"'«»")
    text = re.sub(r"^(?:песня|трек)\s+", "", text, flags=re.IGNORECASE)
    return text[:220]


def classify_lyrics_intent(text: str, *, current_topic: str = "") -> tuple[str, str] | None:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return None
    for mode, pattern in _LYRIC_INTENT_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        query = _clean_query(match.group("query"))
        if query:
            return mode, query
    if current_topic and _LYRIC_FOLLOWUP_RE.search(value):
        return "meaning", _clean_query(current_topic)
    return None


def musixmatch_api_key() -> str:
    return str(os.getenv("MUSIXMATCH_API_KEY", "") or "").strip()


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


def _retry_after_seconds(response: httpx.Response) -> float:
    raw = str(response.headers.get("Retry-After", "") or "").strip()
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = 5.0
    return max(1.0, min(seconds, MAX_PROVIDER_RETRY_AFTER_SECONDS))


async def _lrclib_get(path: str, params: dict[str, Any]) -> Any | None:
    global _LRCLIB_LAST_REQUEST_AT, _LRCLIB_BLOCKED_UNTIL
    now = time.monotonic()
    if now < _LRCLIB_BLOCKED_UNTIL:
        return None

    cache_key = "lrclib:" + path + "?" + "&".join(f"{key}={params[key]}" for key in sorted(params))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    async with _LRCLIB_LOCK:
        now = time.monotonic()
        if now < _LRCLIB_BLOCKED_UNTIL:
            return None
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        delay = LRCLIB_MIN_REQUEST_INTERVAL_SECONDS - (now - _LRCLIB_LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)

        headers = {"User-Agent": LYRICS_USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
            response = await client.get(f"{LRCLIB_BASE}/{path.lstrip('/')}", params=params)
            _LRCLIB_LAST_REQUEST_AT = time.monotonic()
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                _LRCLIB_BLOCKED_UNTIL = time.monotonic() + _retry_after_seconds(response)
                logging.warning("LRCLIB rate limited; provider cooldown until %.2f", _LRCLIB_BLOCKED_UNTIL)
                return None
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, (dict, list)):
            _cache_put(cache_key, payload)
            return payload
        raise ValueError("LRCLIB returned unsupported JSON")


async def _musixmatch_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
    global _MUSIXMATCH_LAST_REQUEST_AT, _MUSIXMATCH_BLOCKED_UNTIL
    api_key = musixmatch_api_key()
    if not api_key:
        return None
    now = time.monotonic()
    if now < _MUSIXMATCH_BLOCKED_UNTIL:
        return None

    public_params = dict(params)
    cache_key = "musixmatch:" + endpoint + "?" + "&".join(
        f"{key}={public_params[key]}" for key in sorted(public_params)
    )
    cached = _cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    async with _MUSIXMATCH_LOCK:
        now = time.monotonic()
        if now < _MUSIXMATCH_BLOCKED_UNTIL:
            return None
        cached = _cache_get(cache_key)
        if isinstance(cached, dict):
            return cached
        delay = MUSIXMATCH_MIN_REQUEST_INTERVAL_SECONDS - (now - _MUSIXMATCH_LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)

        query = dict(public_params)
        query["apikey"] = api_key
        headers = {"User-Agent": LYRICS_USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
            response = await client.get(f"{MUSIXMATCH_BASE}/{endpoint}", params=query)
            _MUSIXMATCH_LAST_REQUEST_AT = time.monotonic()
            if response.status_code == 429:
                _MUSIXMATCH_BLOCKED_UNTIL = time.monotonic() + _retry_after_seconds(response)
                logging.warning("Musixmatch rate limited; provider cooldown until %.2f", _MUSIXMATCH_BLOCKED_UNTIL)
                return None
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Musixmatch returned non-object JSON")
        status = int((((payload.get("message") or {}).get("header") or {}).get("status_code") or 0))
        if status and status != 200:
            return None
        _cache_put(cache_key, payload)
        return payload


def _normalized(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е")
    return " ".join(_TOKEN_RE.findall(text))


def _tokens(value: Any) -> set[str]:
    return set(_normalized(value).split())


def _candidate_score(
    track_name: str,
    artist_name: str,
    *,
    raw_query: str = "",
    target_track: str = "",
    target_artist: str = "",
) -> float:
    title = _normalized(track_name)
    artist = _normalized(artist_name)
    combined_tokens = _tokens(f"{track_name} {artist_name}")
    score = 0.0

    if target_track:
        target = _normalized(target_track)
        if title == target:
            score += 65.0
        else:
            overlap = _tokens(target_track) & _tokens(track_name)
            total = max(1, len(_tokens(target_track)))
            score += 40.0 * len(overlap) / total
    if target_artist:
        target = _normalized(target_artist)
        if artist == target:
            score += 55.0
        else:
            overlap = _tokens(target_artist) & _tokens(artist_name)
            total = max(1, len(_tokens(target_artist)))
            score += 35.0 * len(overlap) / total

    query_tokens = _tokens(raw_query)
    if query_tokens:
        overlap = query_tokens & combined_tokens
        score += 55.0 * len(overlap) / max(1, len(query_tokens))
        if query_tokens <= combined_tokens:
            score += 20.0

    return score


def _clean_lyrics_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    text = _NOTICE_RE.sub("", text).strip()
    return text[:40000]


def _plain_from_synced(value: Any) -> str:
    text = _clean_lyrics_text(value)
    return _TIMESTAMP_RE.sub("", text).strip()


def _normalize_lrclib(item: dict[str, Any]) -> dict[str, Any] | None:
    track = str(item.get("trackName") or item.get("name") or "").strip()
    artist = str(item.get("artistName") or "").strip()
    plain = _clean_lyrics_text(item.get("plainLyrics"))
    synced = _clean_lyrics_text(item.get("syncedLyrics"))
    if not plain and synced:
        plain = _plain_from_synced(synced)
    instrumental = bool(item.get("instrumental"))
    if not track or not artist or (not plain and not synced and not instrumental):
        return None
    return {
        "provider": "LRCLIB",
        "provider_id": str(item.get("id") or ""),
        "track_name": track,
        "artist_name": artist,
        "album_name": str(item.get("albumName") or "").strip(),
        "duration": float(item.get("duration") or 0.0),
        "plain_lyrics": plain,
        "synced_lyrics": synced,
        "instrumental": instrumental,
        "language": "",
        "source_url": f"https://lrclib.net/api/get/{item.get('id')}" if item.get("id") else "https://lrclib.net",
    }


def _best_lrclib(
    items: list[Any],
    *,
    raw_query: str = "",
    target_track: str = "",
    target_artist: str = "",
) -> dict[str, Any] | None:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = _normalize_lrclib(raw)
        if not item:
            continue
        score = _candidate_score(
            item["track_name"],
            item["artist_name"],
            raw_query=raw_query,
            target_track=target_track,
            target_artist=target_artist,
        )
        ranked.append((score, item))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = ranked[0]
    minimum = 85.0 if (target_track and target_artist) else 65.0
    if best_score < minimum:
        return None
    # A one-token raw query with no independently resolved artist is too
    # ambiguous for a lyrics match (e.g. dozens of songs named "Отпускай").
    if not target_artist and len(_tokens(raw_query)) <= 1:
        return None
    return best


async def lookup_lrclib(
    raw_query: str,
    *,
    track_name: str = "",
    artist_name: str = "",
    album_name: str = "",
    duration: float | int | None = None,
) -> dict[str, Any] | None:
    if track_name and artist_name:
        params: dict[str, Any] = {"track_name": track_name, "artist_name": artist_name}
        if album_name:
            params["album_name"] = album_name
        if duration and 1 <= float(duration) <= 3600:
            params["duration"] = round(float(duration), 2)
        exact = await _lrclib_get("get", params)
        if isinstance(exact, dict):
            normalized = _normalize_lrclib(exact)
            if normalized:
                return normalized

        search_params: dict[str, Any] = {"track_name": track_name, "artist_name": artist_name}
        if album_name:
            search_params["album_name"] = album_name
        search = await _lrclib_get("search", search_params)
        if isinstance(search, list):
            matched = _best_lrclib(
                search,
                raw_query=raw_query,
                target_track=track_name,
                target_artist=artist_name,
            )
            if matched:
                return matched

    query = _clean_query(raw_query)
    if not query:
        return None
    search = await _lrclib_get("search", {"q": query})
    if isinstance(search, list):
        return _best_lrclib(search, raw_query=query)
    return None


def _musixmatch_lyrics_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    body = (((payload.get("message") or {}).get("body") or {}).get("lyrics") or {})
    if not isinstance(body, dict):
        return None
    text = _clean_lyrics_text(body.get("lyrics_body"))
    if not text:
        return None
    return {
        "provider_id": str(body.get("lyrics_id") or ""),
        "plain_lyrics": text,
        "language": str(body.get("lyrics_language") or "").strip(),
        "explicit": bool(body.get("explicit")),
    }


def _musixmatch_track_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (((payload.get("message") or {}).get("body") or {}).get("track_list") or [])
    rows: list[dict[str, Any]] = []
    for item in raw:
        track = item.get("track") if isinstance(item, dict) else None
        if isinstance(track, dict):
            rows.append(track)
    return rows


def _best_musixmatch_track(
    rows: list[dict[str, Any]],
    *,
    raw_query: str,
    target_track: str = "",
    target_artist: str = "",
) -> dict[str, Any] | None:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for track in rows:
        title = str(track.get("track_name") or "").strip()
        artist = str(track.get("artist_name") or "").strip()
        if not title or not artist:
            continue
        score = _candidate_score(
            title,
            artist,
            raw_query=raw_query,
            target_track=target_track,
            target_artist=target_artist,
        )
        ranked.append((score, track))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    score, track = ranked[0]
    minimum = 85.0 if (target_track and target_artist) else 65.0
    if score < minimum:
        return None
    if not target_artist and len(_tokens(raw_query)) <= 1:
        return None
    return track


async def lookup_musixmatch(
    raw_query: str,
    *,
    track_name: str = "",
    artist_name: str = "",
) -> dict[str, Any] | None:
    if not musixmatch_api_key():
        return None

    if track_name and artist_name:
        payload = await _musixmatch_get(
            "matcher.lyrics.get",
            {"q_track": track_name, "q_artist": artist_name},
        )
        if isinstance(payload, dict):
            lyrics = _musixmatch_lyrics_payload(payload)
            if lyrics:
                return {
                    "provider": "Musixmatch",
                    "track_name": track_name,
                    "artist_name": artist_name,
                    "album_name": "",
                    "duration": 0.0,
                    "synced_lyrics": "",
                    "instrumental": False,
                    "source_url": "https://www.musixmatch.com",
                    **lyrics,
                }

    query = _clean_query(raw_query)
    if not query:
        return None
    search = await _musixmatch_get(
        "track.search",
        {
            "q_track_artist": query,
            "f_has_lyrics": 1,
            "s_track_rating": "desc",
            "page": 1,
            "page_size": 5,
        },
    )
    if not isinstance(search, dict):
        return None
    track = _best_musixmatch_track(
        _musixmatch_track_rows(search),
        raw_query=query,
        target_track=track_name,
        target_artist=artist_name,
    )
    if not track:
        return None
    commontrack_id = track.get("commontrack_id")
    track_id = track.get("track_id")
    lyrics_params: dict[str, Any]
    if commontrack_id:
        lyrics_params = {"commontrack_id": commontrack_id}
    elif track_id:
        lyrics_params = {"track_id": track_id}
    else:
        return None
    payload = await _musixmatch_get("track.lyrics.get", lyrics_params)
    if not isinstance(payload, dict):
        return None
    lyrics = _musixmatch_lyrics_payload(payload)
    if not lyrics:
        return None
    return {
        "provider": "Musixmatch",
        "track_name": str(track.get("track_name") or track_name or query),
        "artist_name": str(track.get("artist_name") or artist_name),
        "album_name": str(track.get("album_name") or ""),
        "duration": 0.0,
        "synced_lyrics": "",
        "instrumental": False,
        "source_url": str(track.get("track_share_url") or "https://www.musixmatch.com"),
        **lyrics,
    }


async def lookup_lyrics(
    raw_query: str,
    *,
    catalog_track: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    catalog = catalog_track or {}
    track_name = str(catalog.get("title") or "").strip()
    artist_name = str(catalog.get("artist") or "").strip()
    album_name = str(catalog.get("album_name") or "").strip()
    duration = catalog.get("duration_seconds")

    try:
        result = await lookup_lrclib(
            raw_query,
            track_name=track_name,
            artist_name=artist_name,
            album_name=album_name,
            duration=duration,
        )
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
        logging.warning("LRCLIB lookup failed query=%r: %s", raw_query, error)
        result = None
    if result:
        return result

    try:
        return await lookup_musixmatch(
            raw_query,
            track_name=track_name,
            artist_name=artist_name,
        )
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
        logging.warning("Musixmatch lookup failed query=%r: %s", raw_query, error)
        return None


def build_lyrics_context(
    result: dict[str, Any],
    *,
    user_text: str,
    mode: str,
    catalog_track: dict[str, Any] | None = None,
) -> tuple[str, str]:
    provider = str(result.get("provider") or "lyrics provider")
    track = str(result.get("track_name") or "").strip()
    artist = str(result.get("artist_name") or "").strip()
    album = str(result.get("album_name") or "").strip()
    lyrics = _clean_lyrics_text(result.get("plain_lyrics"))
    instrumental = bool(result.get("instrumental"))
    source_url = str(result.get("source_url") or "").strip()

    catalog_note = ""
    if catalog_track:
        catalog_note = (
            f"\nMusicBrainz resolution (optional, not required for this match): "
            f"{catalog_track.get('artist') or ''} — {catalog_track.get('title') or ''}; "
            f"MBID={catalog_track.get('mbid') or ''}."
        )

    task_rule = {
        "lyrics": "Пользователь просит текст. Не выдавай полный текст песни; вместо этого кратко объясни содержание и предложи разобрать конкретный фрагмент.",
        "line": "Объясни именно смысл указанной пользователем строки/фразы в контексте песни.",
        "meaning": "Объясни смысл, тему, настроение и важные образы песни по retrieved lyrics.",
    }.get(mode, "Проанализируй песню по retrieved lyrics.")

    prompt = (
        "Пользователь задал вопрос о тексте песни. Ниже внутренний specialist context из lyrics-provider. "
        "Это материал ДЛЯ АНАЛИЗА, а не для воспроизведения. Не копируй полный текст песни и не выдавай длинные отрывки. "
        "Если цитата действительно нужна для объяснения, процитируй максимум одну короткую строку/фразу до 80 символов. "
        "Не выдумывай строки, которых нет в retrieved lyrics. Не сохраняй lyrics в self-canon и не называй их своей памятью. "
        f"{task_rule}\n\n"
        f"ВОПРОС: {user_text}\n"
        f"ПРОВАЙДЕР: {provider}\nТРЕК: {artist} — {track}\nАЛЬБОМ: {album or 'не указан'}\n"
        f"INSTRUMENTAL: {instrumental}{catalog_note}\n\n"
        f"LYRICS FOR ANALYSIS ONLY:\n{lyrics if lyrics else '[текст отсутствует; возможно instrumental]'}"
    )
    return prompt, source_url
