"""RAWG-backed game recommendations with Yayceslav's provider-neutral identity lens.

RAWG owns objective catalog data. Similarity is computed locally from the
resolved seed's genres, tags and platforms; RAWG rating/Metacritic are weak
catalog signals only. Successful specialist answers always attribute RAWG.
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

RAWG_BASE = "https://api.rawg.io/api"
RAWG_SITE = "https://rawg.io"
REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL_SECONDS = 10 * 60
CACHE_MAX_ENTRIES = 192
MIN_REQUEST_INTERVAL_SECONDS = 0.30
GAME_TOPIC_TTL_SECONDS = 2 * 60 * 60
GAME_TOPIC_MAX_CHATS = 256
MAX_CANDIDATES = 10
MAX_TAG_POOLS = 2
_PREPARED_APPLICATION_IDS: set[int] = set()

# Broad catalog tags are useful evidence, but they should never overpower a
# setting/mechanics tag that actually defines why two games feel alike.
_GENERIC_TAGS = frozenset({
    "singleplayer", "multiplayer", "open-world", "open-world-game", "action",
    "adventure", "role-playing", "rpg", "atmospheric", "story-rich", "great-soundtrack",
    "third-person", "first-person", "exploration", "mature", "violent", "steam-achievements",
    "controller", "full-controller-support", "partial-controller-support", "windows",
})
_DISTINCTIVE_TAGS = frozenset({
    "cyberpunk", "dystopian", "dystopia", "futuristic", "sci-fi", "science-fiction",
    "hacking", "transhumanism", "robots", "android", "artificial-intelligence",
    "detective", "noir", "stealth", "immersive-sim", "choices-matter", "multiple-endings",
    "post-apocalyptic", "space", "souls-like", "turn-based", "tactical", "survival-horror",
})


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    created_at: float


@dataclass(frozen=True)
class GameTopic:
    name: str
    game_id: int
    created_at: float


_CACHE: dict[str, CacheEntry] = {}
_GAME_TOPIC_BY_CHAT: dict[int, GameTopic] = {}
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0

_GAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:во\s+что\s+поиграть|что\s+поиграть)\s*,?\s*(?:если\s+)?(?:мне\s+)?(?:нравится|нравятся|люблю|заш[её]л|зашли)\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:посоветуй|подбери|дай)\s+(?:мне\s+)?(?:3|5|пять|несколько)?\s*(?:игр|игры)\s+(?:как|похожих\s+на|в\s+духе|по\s+типу|типа|вроде|наподобие)\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:игры|игра)\s+(?:похож(?:ие|ая)\s+на|по\s+типу|типа|вроде|наподобие)\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:games?\s+like|recommend\s+games?\s+like)\s+(?P<query>.+)$", re.I),
)
_FOLLOWUP_RE = re.compile(r"^\s*(?:а\s+)?(?:ещ[её]|что\s+ещ[её]|дай\s+ещ[её]|ещ[её]\s+игры|а\s+похожее)\s*[?!.]*\s*$", re.I)
_GAME_QUERY_ALIASES: dict[str, str] = {
    "киберпанк": "Cyberpunk 2077",
    "cyberpunk": "Cyberpunk 2077",
    "киберпанк 2077": "Cyberpunk 2077",
    "cyberpunk2077": "Cyberpunk 2077",
}


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "prepare_request_text", None)):
            return module
    return None


def rawg_api_key() -> str:
    return str(os.getenv("RAWG_API_KEY", "") or "").strip()


def _clean_query(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" \t\r\n,.:;!?—-\"'«»")
    return re.sub(r"^(?:игра|game)\s+", "", text, flags=re.I)[:200]


def _normalize_game_query(value: Any) -> str:
    clean = _clean_query(value)
    folded = re.sub(r"\s+", " ", clean.casefold()).strip()
    return _GAME_QUERY_ALIASES.get(folded, clean)


def _prune_topics(now: float) -> None:
    stale = [chat_id for chat_id, topic in _GAME_TOPIC_BY_CHAT.items() if now - topic.created_at > GAME_TOPIC_TTL_SECONDS]
    for chat_id in stale:
        _GAME_TOPIC_BY_CHAT.pop(chat_id, None)
    while len(_GAME_TOPIC_BY_CHAT) > GAME_TOPIC_MAX_CHATS:
        oldest = min(_GAME_TOPIC_BY_CHAT, key=lambda key: _GAME_TOPIC_BY_CHAT[key].created_at)
        _GAME_TOPIC_BY_CHAT.pop(oldest, None)


def remember_game_topic(chat_id: int, name: str, game_id: int, *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else float(now)
    _prune_topics(current)
    clean = _clean_query(name)
    if clean and int(game_id) > 0:
        _GAME_TOPIC_BY_CHAT[int(chat_id)] = GameTopic(clean, int(game_id), current)


def current_game_topic(chat_id: int, *, now: float | None = None) -> GameTopic | None:
    current = time.monotonic() if now is None else float(now)
    _prune_topics(current)
    return _GAME_TOPIC_BY_CHAT.get(int(chat_id))


def classify_game_recommendation_intent(text: str, *, chat_id: int | None = None) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return ""
    for pattern in _GAME_PATTERNS:
        match = pattern.search(value)
        if match:
            return _normalize_game_query(match.group("query"))
    if chat_id is not None and _FOLLOWUP_RE.search(value):
        topic = current_game_topic(int(chat_id))
        return topic.name if topic else ""
    return ""


def _cache_get(key: str) -> Any | None:
    now = time.monotonic()
    for item, entry in list(_CACHE.items()):
        if now - entry.created_at > CACHE_TTL_SECONDS:
            _CACHE.pop(item, None)
    entry = _CACHE.get(key)
    return None if entry is None else entry.value


def _cache_put(key: str, value: Any) -> None:
    if len(_CACHE) >= CACHE_MAX_ENTRIES and key not in _CACHE:
        oldest = min(_CACHE.items(), key=lambda item: item[1].created_at)[0]
        _CACHE.pop(oldest, None)
    _CACHE[key] = CacheEntry(value=value, created_at=time.monotonic())


async def _reserve_request_slot() -> float:
    """Reserve a staggered start time without serializing the HTTP request itself."""
    global _LAST_REQUEST_AT
    async with _REQUEST_LOCK:
        now = time.monotonic()
        start_at = max(now, _LAST_REQUEST_AT + MIN_REQUEST_INTERVAL_SECONDS)
        _LAST_REQUEST_AT = start_at
        return max(0.0, start_at - now)


async def _rawg_get(path: str, params: dict[str, Any] | None = None) -> Any:
    key = rawg_api_key()
    if not key:
        return None
    request_params = dict(params or {})
    safe_key = path + "?" + "&".join(f"{k}={request_params[k]}" for k in sorted(request_params))
    cached = _cache_get(safe_key)
    if cached is not None:
        return cached

    delay = await _reserve_request_slot()
    if delay > 0:
        await asyncio.sleep(delay)
    # A previous concurrent request may have populated the cache while we waited.
    cached = _cache_get(safe_key)
    if cached is not None:
        return cached

    request_params["key"] = key
    headers = {"Accept": "application/json", "User-Agent": "YayceslavBot/2.0 (https://github.com/oblakaF/yayceslav-bot)"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
        response = await client.get(f"{RAWG_BASE}/{path.lstrip('/')}", params=request_params)
        if response.status_code in {204, 404}:
            return None
        response.raise_for_status()
        payload = response.json()
    _cache_put(safe_key, payload)
    return payload


def _results(payload: Any) -> list[dict[str, Any]]:
    return [item for item in (payload.get("results") if isinstance(payload, dict) else []) or [] if isinstance(item, dict)]


def _names(rows: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split()).strip()
        folded = name.casefold()
        if name and folded not in seen:
            seen.add(folded)
            result.append(name)
    return result


def _slugs(rows: Any) -> list[str]:
    result: list[str] = []
    for item in rows or []:
        if isinstance(item, dict):
            slug = str(item.get("slug") or "").strip()
            if slug and slug not in result:
                result.append(slug)
    return result


def _platform_slugs(rows: Any) -> list[str]:
    result: list[str] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        platform = item.get("platform") if isinstance(item.get("platform"), dict) else item
        slug = str(platform.get("slug") or "").strip() if isinstance(platform, dict) else ""
        if slug and slug not in result:
            result.append(slug)
    return result


def _game_summary(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        game_id = int(item.get("id") or 0)
    except (TypeError, ValueError):
        return None
    name = " ".join(str(item.get("name") or "").split()).strip()
    if game_id <= 0 or not name:
        return None
    slug = str(item.get("slug") or "").strip()
    return {
        "id": game_id,
        "name": name,
        "slug": slug,
        "released": str(item.get("released") or "")[:10],
        "genres": _slugs(item.get("genres")),
        "genre_names": _names(item.get("genres")),
        "tags": _slugs(item.get("tags"))[:30],
        "tag_names": _names(item.get("tags"))[:30],
        "platforms": _platform_slugs(item.get("platforms")),
        "rating": float(item.get("rating") or 0.0),
        "ratings_count": int(item.get("ratings_count") or 0),
        "metacritic": int(item.get("metacritic") or 0),
        "description": " ".join(str(item.get("description_raw") or "").split())[:900],
        "source_url": f"{RAWG_SITE}/games/{slug}" if slug else RAWG_SITE,
    }


def _has_seed_metadata(game: dict[str, Any]) -> bool:
    return bool(game.get("genres") and game.get("tags") and game.get("platforms"))


async def resolve_seed_game(query: str) -> dict[str, Any] | None:
    normalized_query = _normalize_game_query(query)
    payload = await _rawg_get("games", {"search": normalized_query, "search_precise": "true", "page_size": 10})
    normalized = normalized_query.casefold()
    ranked: list[tuple[float, dict[str, Any]]] = []
    for index, row in enumerate(_results(payload)[:10]):
        game = _game_summary(row)
        if not game:
            continue
        name = game["name"].casefold()
        score = max(0.0, 30.0 - index)
        if normalized == name:
            score += 150.0
        elif normalized and normalized in name:
            score += 75.0
        score += min(math.log10(max(1, game["ratings_count"]) + 1), 5.0) * 2.0
        ranked.append((score, game))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    seed = ranked[0][1]
    # Search results normally already contain genres/tags/platforms. Avoid a
    # redundant details round-trip unless those fields are actually missing.
    if _has_seed_metadata(seed):
        return seed
    details = await _rawg_get(f"games/{seed['id']}")
    detailed = _game_summary(details) if isinstance(details, dict) else None
    return detailed or seed


def _overlap(left: list[str], right: list[str]) -> list[str]:
    right_set = set(right)
    return [value for value in left if value in right_set]


def _tag_weight(tag: str) -> float:
    value = str(tag or "").casefold()
    if value in _DISTINCTIVE_TAGS:
        return 6.0
    if value in _GENERIC_TAGS:
        return 0.65
    return 2.0


def _ordered_seed_tags(seed: dict[str, Any]) -> list[str]:
    tags = list(dict.fromkeys(seed.get("tags") or []))
    return sorted(tags, key=lambda tag: (_tag_weight(tag), tag in _DISTINCTIVE_TAGS), reverse=True)


def _candidate_score(item: dict[str, Any], seed: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(item)
    genres = _overlap(candidate.get("genres") or [], seed.get("genres") or [])
    tags = _overlap(candidate.get("tags") or [], seed.get("tags") or [])
    platforms = _overlap(candidate.get("platforms") or [], seed.get("platforms") or [])
    weighted_tags = sum(_tag_weight(tag) for tag in tags)
    distinctive = [tag for tag in tags if _tag_weight(tag) >= 6.0]
    candidate["shared_genres"] = genres
    candidate["shared_tags"] = sorted(tags, key=_tag_weight, reverse=True)[:8]
    candidate["shared_distinctive_tags"] = distinctive[:8]
    candidate["shared_platforms"] = platforms[:8]
    candidate["tag_similarity_weight"] = round(weighted_tags, 2)

    genre_ratio = len(genres) / max(1, min(len(set(candidate.get("genres") or [])), len(set(seed.get("genres") or [])))) if seed.get("genres") else 0.0
    score = len(genres) * 34.0 + genre_ratio * 26.0
    score += weighted_tags * 18.0
    score += len(distinctive) * 42.0
    score += min(len(platforms), 3) * 2.5
    # Catalog popularity/quality fields are deliberately tiny tie-breakers.
    score += min(math.log10(max(1, int(candidate.get("ratings_count") or 0)) + 1), 5.0) * 1.0
    score += min(max(float(candidate.get("rating") or 0.0), 0.0), 5.0) * 0.55
    score += min(max(int(candidate.get("metacritic") or 0), 0), 100) * 0.015
    candidate["relevance_score"] = round(score, 3)
    candidate["passes_genre_gate"] = (not seed.get("genres")) or bool(genres)
    return candidate


def _genre_pool_params(seed: dict[str, Any]) -> dict[str, Any]:
    return {"genres": ",".join((seed.get("genres") or [])[:3]), "page_size": 40, "ordering": "-rating"}


def _tag_pool_params(tag: str) -> dict[str, Any]:
    return {"tags": str(tag), "page_size": 40, "ordering": "-rating"}


async def recommend_from_game(query: str) -> dict[str, Any] | None:
    seed = await resolve_seed_game(query)
    if not seed:
        return None

    calls: list[Any] = []
    source_names: list[str] = []
    if seed.get("genres"):
        calls.append(_rawg_get("games", _genre_pool_params(seed)))
        source_names.append("genres")
    for tag in _ordered_seed_tags(seed)[:MAX_TAG_POOLS]:
        calls.append(_rawg_get("games", _tag_pool_params(tag)))
        source_names.append(f"tag:{tag}")
    if not calls:
        return None

    payloads = await asyncio.gather(*calls)
    by_id: dict[int, dict[str, Any]] = {}
    for source_name, payload in zip(source_names, payloads):
        for row in _results(payload):
            item = _game_summary(row)
            if not item or item["id"] == seed["id"]:
                continue
            existing = by_id.get(item["id"])
            if existing is None:
                item["provider_sources"] = [source_name]
                by_id[item["id"]] = item
            else:
                if source_name not in existing["provider_sources"]:
                    existing["provider_sources"].append(source_name)
                for key in ("genres", "genre_names", "tags", "tag_names", "platforms"):
                    if len(item.get(key) or []) > len(existing.get(key) or []):
                        existing[key] = item[key]

    scored = [_candidate_score(item, seed) for item in by_id.values()]
    if seed.get("genres"):
        scored = [item for item in scored if item.get("passes_genre_gate")]
    # A candidate that appears in more than one independent RAWG pool gets a
    # modest corroboration bonus, after semantic similarity has been computed.
    for item in scored:
        item["relevance_score"] = round(
            float(item.get("relevance_score") or 0.0) + max(0, len(item.get("provider_sources") or []) - 1) * 12.0,
            3,
        )
    scored.sort(key=lambda item: float(item.get("relevance_score") or 0.0), reverse=True)
    return {"seed": seed, "candidates": scored[:MAX_CANDIDATES]} if scored else None


def build_game_recommendation_context(data: dict[str, Any], *, user_text: str, identity_lens: dict[str, str] | None) -> str:
    seed = data.get("seed") or {}
    rows: list[str] = []
    for index, item in enumerate(data.get("candidates") or [], start=1):
        rows.append(
            f"{index}. {item['name']} | released={item.get('released') or 'unknown'} | shared_genres={', '.join(item.get('shared_genres') or []) or 'нет'} | "
            f"shared_tags={', '.join(item.get('shared_tags') or []) or 'нет'} | distinctive={', '.join(item.get('shared_distinctive_tags') or []) or 'нет'} | "
            f"sources={','.join(item.get('provider_sources') or []) or 'unknown'} | rating={item.get('rating'):.2f} ratings_count={item.get('ratings_count')} "
            f"metacritic={item.get('metacritic')} | relevance={item.get('relevance_score'):.1f} | source={item.get('source_url')}"
        )
    return (
        "Пользователь просит рекомендации игр. Ниже реальные кандидаты RAWG. Похожесть уже посчитана по жанрам и тегам seed-игры, причём "
        "специфические теги сеттинга/механик (например cyberpunk, dystopian, hacking) весят намного больше массовых тегов вроде singleplayer/open-world. "
        "RAWG rating/Metacritic/ratings_count — только слабые каталожные сигналы, не объективная оценка качества. Выбирай только реально сильные варианты из списка; "
        "не добивай ответ до пяти, если сильных кандидатов меньше. Объясняй сходство через shared_genres/shared_tags/distinctive. Не придумывай отсутствующие факты.\n"
        + identity_recommendation_runtime.identity_separation_rules("игры")
        + f"\n\nВОПРОС: {user_text}\nSEED: {seed.get('name') or ''}\n"
        + f"SEED GENRES: {', '.join(seed.get('genre_names') or seed.get('genres') or []) or 'нет'}\n"
        + f"SEED TAGS: {', '.join((seed.get('tag_names') or seed.get('tags') or [])[:15]) or 'нет'}\n"
        + "SELF-CANON LENS:\n" + identity_recommendation_runtime.format_identity_lens(identity_lens)
        + "\n\nRAWG CANDIDATES:\n" + "\n".join(rows)
        + "\n\nВ конце обязательно добавь отдельной строкой: Источник каталога: RAWG — https://rawg.io"
    )


async def _route_game_recommendations(update: Any, context: Any) -> None:
    if not rawg_api_key():
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
    prepared = await module.prepare_request_text(update=update, context=context, original_text=original_text, default_text="")
    if prepared is None:
        return
    query = classify_game_recommendation_intent(prepared, chat_id=int(chat.id))
    if not query:
        return
    enforce = getattr(module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "general"):
        raise ApplicationHandlerStop
    try:
        data = await recommend_from_game(query)
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
        logging.warning("RAWG recommendation failed query=%r: %s", query, error)
        return
    except Exception as error:
        logging.exception("Unexpected RAWG recommendation failure query=%r: %s", query, error)
        return
    if not data:
        return
    seed = data.get("seed") or {}
    seed_name = str(seed.get("name") or query)
    remember_game_topic(int(chat.id), seed_name, int(seed.get("id") or 0))
    entity_continuity_runtime.remember_topic(int(chat.id), seed_name)
    lens = identity_recommendation_runtime.load_identity_lens(module, int(chat.id))
    prompt = build_game_recommendation_context(data, user_text=prepared, identity_lens=lens)
    answer = await module.ask_gemini(contents=prompt, max_output_tokens=700, chat_id=int(chat.id), chat_type=str(getattr(chat, "type", "private")), user_name=(getattr(user, "full_name", "") or getattr(user, "username", "") or ""), user_id=int(user.id), bot_was_mentioned=True, thinking_level="minimal")
    answer_text = str(answer or "").strip()
    if "rawg.io" not in answer_text.lower():
        answer_text += "\n\nИсточник каталога: RAWG — https://rawg.io"
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
    logging.info("RAWG recommendation route: query=%r seed=%r", query, seed_name)
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _route_game_recommendations), group=-7)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Game recommendations ready: RAWG distinctive-tag ranking + staggered concurrent requests + colloquial RU routing + identity lens")