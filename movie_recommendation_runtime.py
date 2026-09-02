"""TMDB-backed movie recommendations with a provider-neutral Yayceslav identity lens.

The specialist route is enabled only when ``TMDB_API_TOKEN`` is configured.
Without a token it falls through to Yayceslav's ordinary answer/search path.
Movie follow-ups use category-local state so generic ``а ещё?`` cannot leak a
book/music seed into this vertical. Provider data never rewrites self-canon.

Candidate ranking is relevance-first: TMDB relation evidence, shared genres and
plot-keyword overlap dominate. Vote/popularity fields are only weak tie-breakers.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters

import entity_continuity_runtime
import identity_recommendation_runtime


TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_SITE = "https://www.themoviedb.org"
REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL_SECONDS = 10 * 60
CACHE_MAX_ENTRIES = 192
MIN_REQUEST_INTERVAL_SECONDS = 0.25
MOVIE_TOPIC_TTL_SECONDS = 2 * 60 * 60
MOVIE_TOPIC_MAX_CHATS = 256
MAX_CANDIDATES = 10
KEYWORD_ENRICH_MAX_CANDIDATES = 12
MIN_RELEVANT_CANDIDATES = 5
_PREPARED_APPLICATION_IDS: set[int] = set()

TMDB_GENRE_NAMES: dict[int, str] = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
}


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    created_at: float


@dataclass(frozen=True)
class MovieTopic:
    title: str
    movie_id: int
    created_at: float


_CACHE: dict[str, CacheEntry] = {}
_MOVIE_TOPIC_BY_CHAT: dict[int, MovieTopic] = {}
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


_MOVIE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:что|какой|какие)\s+(?:фильм|фильмы)\s+посовету(?:ешь|й)\s*,?\s*"
        r"(?:если\s+)?(?:мне\s+)?(?:нравится|нравятся|люблю|заш[её]л|зашли)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(
        r"\b(?:что|какой|какие)\s+посмотреть\s*,?\s*(?:если\s+)?(?:мне\s+)?"
        r"(?:нравится|нравятся|люблю|заш[её]л|зашли)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(
        r"\b(?:посоветуй|подбери|дай)\s+(?:мне\s+)?(?:3|5|пять|несколько)?\s*"
        r"(?:фильмов|фильмы)\s+(?:как|похожих\s+на|в\s+духе)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(r"\b(?:фильмы|фильм)\s+похож(?:ие|ий)\s+на\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:movies?\s+like|recommend\s+movies?\s+like)\s+(?P<query>.+)$", re.I),
)

_FOLLOWUP_RE = re.compile(
    r"^\s*(?:а\s+)?(?:ещ[её]|что\s+ещ[её]|дай\s+ещ[её]|ещ[её]\s+фильмы|а\s+похожее)\s*[?!.]*\s*$",
    re.I,
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "prepare_request_text", None)):
            return module
    return None


def tmdb_api_token() -> str:
    return str(os.getenv("TMDB_API_TOKEN", "") or "").strip()


def _clean_query(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" \t\r\n,.:;!?—-\"'«»")
    text = re.sub(r"^(?:фильм|movie)\s+", "", text, flags=re.I)
    return text[:200]


def _prune_topics(now: float) -> None:
    stale = [
        chat_id
        for chat_id, topic in _MOVIE_TOPIC_BY_CHAT.items()
        if now - topic.created_at > MOVIE_TOPIC_TTL_SECONDS
    ]
    for chat_id in stale:
        _MOVIE_TOPIC_BY_CHAT.pop(chat_id, None)
    while len(_MOVIE_TOPIC_BY_CHAT) > MOVIE_TOPIC_MAX_CHATS:
        oldest = min(_MOVIE_TOPIC_BY_CHAT, key=lambda key: _MOVIE_TOPIC_BY_CHAT[key].created_at)
        _MOVIE_TOPIC_BY_CHAT.pop(oldest, None)


def remember_movie_topic(chat_id: int, title: str, movie_id: int, *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else float(now)
    _prune_topics(current)
    clean = _clean_query(title)
    if clean and int(movie_id) > 0:
        _MOVIE_TOPIC_BY_CHAT[int(chat_id)] = MovieTopic(clean, int(movie_id), current)


def current_movie_topic(chat_id: int, *, now: float | None = None) -> MovieTopic | None:
    current = time.monotonic() if now is None else float(now)
    _prune_topics(current)
    return _MOVIE_TOPIC_BY_CHAT.get(int(chat_id))


def classify_movie_recommendation_intent(text: str, *, chat_id: int | None = None) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return ""
    for pattern in _MOVIE_PATTERNS:
        match = pattern.search(value)
        if match:
            return _clean_query(match.group("query"))
    if chat_id is not None and _FOLLOWUP_RE.search(value):
        topic = current_movie_topic(int(chat_id))
        return topic.title if topic else ""
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


async def _tmdb_get(path: str, params: dict[str, Any] | None = None) -> Any:
    global _LAST_REQUEST_AT
    token = tmdb_api_token()
    if not token:
        return None
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
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "YayceslavBot/2.0 (https://github.com/oblakaF/yayceslav-bot)",
        }
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
            response = await client.get(f"{TMDB_BASE}/{path.lstrip('/')}", params=params)
            _LAST_REQUEST_AT = time.monotonic()
            if response.status_code in {204, 404}:
                return None
            response.raise_for_status()
            payload = response.json()
        _cache_put(cache_key, payload)
        return payload


def _results(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [item for item in payload.get("results") or [] if isinstance(item, dict)]


def _keyword_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    values = payload.get("keywords")
    if values is None:
        values = payload.get("results")
    return [item for item in values or [] if isinstance(item, dict)]


def _keyword_ids(payload: Any) -> list[int]:
    result: list[int] = []
    for item in _keyword_rows(payload):
        value = item.get("id")
        try:
            keyword_id = int(value)
        except (TypeError, ValueError):
            continue
        if keyword_id > 0 and keyword_id not in result:
            result.append(keyword_id)
    return result


def _keyword_names(payload: Any) -> list[str]:
    result: list[str] = []
    for item in _keyword_rows(payload):
        value = " ".join(str(item.get("name") or "").split()).strip()
        if value and value.casefold() not in {name.casefold() for name in result}:
            result.append(value)
    return result[:20]


def _detail_genre_ids(payload: Any) -> list[int]:
    if not isinstance(payload, dict):
        return []
    result: list[int] = []
    for item in payload.get("genres") or []:
        if not isinstance(item, dict):
            continue
        try:
            genre_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if genre_id > 0 and genre_id not in result:
            result.append(genre_id)
    return result


def _year(value: Any) -> int:
    text = str(value or "")
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else 0


def _movie_summary(item: dict[str, Any]) -> dict[str, Any] | None:
    movie_id = int(item.get("id") or 0)
    title = str(item.get("title") or item.get("original_title") or "").strip()
    if movie_id <= 0 or not title:
        return None
    return {
        "id": movie_id,
        "title": title,
        "original_title": str(item.get("original_title") or "").strip(),
        "year": _year(item.get("release_date")),
        "overview": " ".join(str(item.get("overview") or "").split())[:700],
        "genre_ids": [int(value) for value in item.get("genre_ids") or [] if str(value).isdigit()],
        "vote_average": float(item.get("vote_average") or 0.0),
        "vote_count": int(item.get("vote_count") or 0),
        "popularity": float(item.get("popularity") or 0.0),
        "source_url": f"{TMDB_SITE}/movie/{movie_id}",
    }


async def resolve_seed_movie(query: str) -> dict[str, Any] | None:
    payload = await _tmdb_get("search/movie", {"query": query, "include_adult": "false", "language": "ru-RU"})
    rows = _results(payload)
    if not rows:
        return None
    normalized = _clean_query(query).casefold()
    ranked: list[tuple[float, dict[str, Any]]] = []
    for index, row in enumerate(rows[:10]):
        movie = _movie_summary(row)
        if not movie:
            continue
        title = movie["title"].casefold()
        original = movie["original_title"].casefold()
        score = max(0.0, 30.0 - index)
        if normalized in {title, original}:
            score += 120.0
        elif normalized and (normalized in title or normalized in original):
            score += 60.0
        score += min(movie["vote_count"], 10000) / 1000.0
        ranked.append((score, movie))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _overlap_values(left: list[int], right: list[int]) -> list[int]:
    right_set = set(right)
    return [value for value in left if value in right_set]


def _relation_bonus(item: dict[str, Any]) -> float:
    sources = set(item.get("tmdb_relations") or [])
    bonus = 0.0
    if "similar" in sources:
        bonus += 24.0
    if "recommendations" in sources:
        bonus += 15.0
    if len(sources) >= 2:
        bonus += 22.0
    ranks = item.get("relation_ranks") or {}
    for source in sources:
        rank = int(ranks.get(source) or 99)
        bonus += max(0.0, 13.0 - min(rank, 13)) * 1.2
    return bonus


def _apply_similarity_features(
    item: dict[str, Any],
    *,
    seed_genres: list[int],
    seed_keywords: list[int],
) -> dict[str, Any]:
    candidate = dict(item)
    genre_overlap = _overlap_values(candidate.get("genre_ids") or [], seed_genres)
    keyword_overlap = _overlap_values(candidate.get("keyword_ids") or [], seed_keywords)
    candidate["genre_overlap_ids"] = genre_overlap
    candidate["keyword_overlap_ids"] = keyword_overlap
    candidate_keyword_names = {
        keyword_id: name
        for keyword_id, name in zip(candidate.get("keyword_ids") or [], candidate.get("keyword_names") or [])
    }
    candidate["keyword_overlap_names"] = [
        candidate_keyword_names[keyword_id]
        for keyword_id in keyword_overlap
        if keyword_id in candidate_keyword_names
    ][:6]

    genre_denominator = max(1, min(len(set(seed_genres)), len(set(candidate.get("genre_ids") or []))))
    keyword_denominator = max(1, min(len(set(seed_keywords)), len(set(candidate.get("keyword_ids") or []))))
    genre_ratio = len(genre_overlap) / genre_denominator if seed_genres else 0.0
    keyword_ratio = len(keyword_overlap) / keyword_denominator if seed_keywords else 0.0

    provider_score = _relation_bonus(candidate)
    relevance_score = (
        provider_score
        + len(genre_overlap) * 34.0
        + genre_ratio * 30.0
        + len(keyword_overlap) * 48.0
        + keyword_ratio * 42.0
    )
    # Catalog popularity/ratings are deliberately weak tie-breakers only.
    relevance_score += min(math.log10(max(1, int(candidate.get("vote_count") or 0)) + 1), 5.0) * 1.6
    relevance_score += min(max(float(candidate.get("vote_average") or 0.0), 0.0), 10.0) * 0.45
    relevance_score += min(max(float(candidate.get("popularity") or 0.0), 0.0), 100.0) * 0.025
    candidate["relevance_score"] = round(relevance_score, 3)
    return candidate


def _merge_relation_candidates(
    seed_id: int,
    recommendation_payload: Any,
    similar_payload: Any,
) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for source_name, payload in (("recommendations", recommendation_payload), ("similar", similar_payload)):
        for rank, row in enumerate(_results(payload), start=1):
            item = _movie_summary(row)
            if not item or item["id"] == seed_id:
                continue
            existing = by_id.get(item["id"])
            if existing is None:
                item["tmdb_relations"] = [source_name]
                item["relation_ranks"] = {source_name: rank}
                by_id[item["id"]] = item
                continue
            if source_name not in existing["tmdb_relations"]:
                existing["tmdb_relations"].append(source_name)
            existing["relation_ranks"][source_name] = min(
                int(existing["relation_ranks"].get(source_name) or rank),
                rank,
            )
            if not existing.get("overview") and item.get("overview"):
                existing["overview"] = item["overview"]
    for item in by_id.values():
        item["tmdb_relation"] = "+".join(item.get("tmdb_relations") or [])
        item["source_count"] = len(item.get("tmdb_relations") or [])
    return list(by_id.values())


async def _enrich_shortlist_keywords(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shortlist = candidates[:KEYWORD_ENRICH_MAX_CANDIDATES]
    if not shortlist:
        return []
    payloads = await asyncio.gather(
        *[_tmdb_get(f"movie/{int(item['id'])}/keywords") for item in shortlist],
        return_exceptions=True,
    )
    enriched: list[dict[str, Any]] = []
    for item, payload in zip(shortlist, payloads):
        current = dict(item)
        if isinstance(payload, BaseException):
            logging.info("TMDB candidate keywords skipped movie_id=%s: %s", item.get("id"), payload)
            current["keyword_ids"] = []
            current["keyword_names"] = []
        else:
            current["keyword_ids"] = _keyword_ids(payload)
            current["keyword_names"] = _keyword_names(payload)
        enriched.append(current)
    return enriched


async def recommend_from_movie(query: str) -> dict[str, Any] | None:
    seed = await resolve_seed_movie(query)
    if not seed:
        return None
    movie_id = int(seed["id"])

    bundle = await _tmdb_get(
        f"movie/{movie_id}",
        {"language": "ru-RU", "append_to_response": "keywords,recommendations,similar"},
    )
    recommendation_payload = bundle.get("recommendations") if isinstance(bundle, dict) else None
    similar_payload = bundle.get("similar") if isinstance(bundle, dict) else None

    missing_requests: list[tuple[str, str]] = []
    if not isinstance(recommendation_payload, dict):
        missing_requests.append(("recommendations", f"movie/{movie_id}/recommendations"))
    if not isinstance(similar_payload, dict):
        missing_requests.append(("similar", f"movie/{movie_id}/similar"))
    if missing_requests:
        fallback_payloads = await asyncio.gather(
            *[_tmdb_get(path, {"language": "ru-RU", "page": 1}) for _, path in missing_requests]
        )
        for (name, _), payload in zip(missing_requests, fallback_payloads):
            if name == "recommendations":
                recommendation_payload = payload
            else:
                similar_payload = payload

    seed_genres = _detail_genre_ids(bundle) or list(seed.get("genre_ids") or [])
    seed_keywords = _keyword_ids(bundle.get("keywords") if isinstance(bundle, dict) else None)
    seed_keyword_names = _keyword_names(bundle.get("keywords") if isinstance(bundle, dict) else None)
    seed = dict(seed)
    seed["genre_ids"] = seed_genres
    seed["keyword_ids"] = seed_keywords
    seed["keyword_names"] = seed_keyword_names

    candidates = _merge_relation_candidates(movie_id, recommendation_payload, similar_payload)
    if not candidates:
        return None

    # First pass is already relevance-first, so expensive keyword enrichment is
    # bounded to the strongest provider/genre shortlist instead of every result.
    preliminary = [
        _apply_similarity_features(item, seed_genres=seed_genres, seed_keywords=[])
        for item in candidates
    ]
    preliminary.sort(key=lambda item: float(item.get("relevance_score") or 0.0), reverse=True)
    enriched = await _enrich_shortlist_keywords(preliminary)
    final_candidates = [
        _apply_similarity_features(item, seed_genres=seed_genres, seed_keywords=seed_keywords)
        for item in enriched
    ]
    final_candidates.sort(key=lambda item: float(item.get("relevance_score") or 0.0), reverse=True)

    strong = [
        item
        for item in final_candidates
        if item.get("genre_overlap_ids") or item.get("keyword_overlap_ids")
    ]
    if len(strong) >= MIN_RELEVANT_CANDIDATES:
        final_candidates = strong
    else:
        supported = [
            item
            for item in final_candidates
            if item.get("genre_overlap_ids")
            or item.get("keyword_overlap_ids")
            or int(item.get("source_count") or 0) >= 2
        ]
        if len(supported) >= MIN_RELEVANT_CANDIDATES:
            final_candidates = supported

    return {
        "seed": seed,
        "candidates": final_candidates[:MAX_CANDIDATES],
    } if final_candidates else None


def _genre_labels(values: list[int]) -> list[str]:
    return [TMDB_GENRE_NAMES.get(int(value), str(value)) for value in values]


def build_movie_recommendation_context(
    data: dict[str, Any],
    *,
    user_text: str,
    identity_lens: dict[str, str] | None,
) -> str:
    seed = data.get("seed") or {}
    rows: list[str] = []
    for index, item in enumerate(data.get("candidates") or [], start=1):
        shared_genres = ", ".join(_genre_labels(item.get("genre_overlap_ids") or [])) or "нет"
        shared_keywords = ", ".join(item.get("keyword_overlap_names") or []) or "нет"
        rows.append(
            f"{index}. {item['title']} ({item.get('year') or 'year unknown'}) | relations={item.get('tmdb_relation')} | "
            f"shared_genres={shared_genres} | shared_keywords={shared_keywords} | relevance={item.get('relevance_score', 0):.1f} | "
            f"rating={item.get('vote_average'):.1f} votes={item.get('vote_count')} popularity={item.get('popularity'):.1f} | "
            f"overview={item.get('overview') or 'нет описания'} | source={item['source_url']}"
        )
    seed_genres = ", ".join(_genre_labels(seed.get("genre_ids") or [])) or "нет"
    seed_keywords = ", ".join(seed.get("keyword_names") or []) or "нет"
    return (
        "Пользователь просит рекомендации фильмов. Ниже реальные кандидаты TMDB, связанные с реально разрешённым "
        "seed-фильмом. Ранжирование уже учитывает TMDB recommendations/similar, совпадение жанров и plot-keywords; "
        "rating/popularity используются только как слабые tie-breakers. Выбирай 3–5 только из списка и прежде всего "
        "объясняй реальное тематическое сходство через shared_genres/shared_keywords и overview. Не натягивай слабое "
        "сходство ради заполнения пятёрки: если сильных вариантов меньше, лучше назвать меньше. Не придумывай другие "
        "фильмы и не додумывай сюжет при пустом/кратком overview. Внутренний relevance — эвристика отбора, а не "
        "объективная оценка качества фильма.\n"
        + identity_recommendation_runtime.identity_separation_rules("фильмы")
        + "\n\n"
        f"ВОПРОС: {user_text}\nSEED: {seed.get('title') or ''} ({seed.get('year') or 'year unknown'})\n"
        f"SEED GENRES: {seed_genres}\nSEED KEYWORDS: {seed_keywords}\n"
        "SELF-CANON LENS:\n"
        + identity_recommendation_runtime.format_identity_lens(identity_lens)
        + "\n\nTMDB CANDIDATES:\n"
        + "\n".join(rows)
    )


async def _route_movie_recommendations(update: Any, context: Any) -> None:
    if not tmdb_api_token():
        return
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
    query = classify_movie_recommendation_intent(prepared, chat_id=int(chat.id))
    if not query:
        return

    enforce = getattr(module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "general"):
        raise ApplicationHandlerStop

    try:
        data = await recommend_from_movie(query)
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
        logging.warning("TMDB recommendation failed query=%r: %s", query, error)
        return
    except Exception as error:
        logging.exception("Unexpected TMDB recommendation failure query=%r: %s", query, error)
        return
    if not data:
        return

    seed = data.get("seed") or {}
    seed_title = str(seed.get("title") or query)
    seed_id = int(seed.get("id") or 0)
    remember_movie_topic(int(chat.id), seed_title, seed_id)
    entity_continuity_runtime.remember_topic(int(chat.id), seed_title)
    lens = identity_recommendation_runtime.load_identity_lens(module, int(chat.id))
    prompt = build_movie_recommendation_context(data, user_text=prepared, identity_lens=lens)
    answer = await module.ask_gemini(
        contents=prompt,
        max_output_tokens=700,
        chat_id=int(chat.id),
        chat_type=str(getattr(chat, "type", "private")),
        user_name=(getattr(user, "full_name", "") or getattr(user, "username", "") or ""),
        user_id=int(user.id),
        bot_was_mentioned=True,
        thinking_level="minimal",
    )
    answer_text = str(answer or "").strip()
    if "themoviedb.org" not in answer_text.lower():
        answer_text += "\n\nИсточник каталога: TMDB"

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
    logging.info("TMDB recommendation route: query=%r seed=%r", query, seed_title)
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _route_movie_recommendations),
        group=-6,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Movie recommendations ready: TMDB relevance-first genres/keywords + category-local continuity + identity lens"
    )