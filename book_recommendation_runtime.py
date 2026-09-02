"""Open Library-backed book recommendations with a Yayceslav identity lens.

High-confidence book recommendation requests resolve one seed work through Open
Library Search API, then use its observed subjects to retrieve related works.
Provider facts and Yayceslav's self-canon stay separate; no recommendation
silently rewrites canon and no extra Gemini classifier call is used.
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
import identity_recommendation_runtime


OPEN_LIBRARY_BASE = "https://openlibrary.org"
OPEN_LIBRARY_USER_AGENT = "YayceslavBot/2.0 (https://github.com/oblakaF/yayceslav-bot)"
REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL_SECONDS = 10 * 60
CACHE_MAX_ENTRIES = 192
MIN_REQUEST_INTERVAL_SECONDS = 0.35
MAX_CANDIDATES = 10
_PREPARED_APPLICATION_IDS: set[int] = set()


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    created_at: float


_CACHE: dict[str, CacheEntry] = {}
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


_BOOK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:что|какую|какие)\s+(?:ты\s+)?(?:книгу|книги)\s+посовету(?:ешь|й)\s*,?\s*"
        r"(?:если\s+)?(?:мне\s+)?(?:нравится|нравятся|люблю|зашла|зашли)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(
        r"\b(?:что|какую|какие)\s+почитать\s*,?\s*(?:если\s+)?(?:мне\s+)?"
        r"(?:нравится|нравятся|люблю|зашла|зашли)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(
        r"\b(?:посоветуй|подбери|дай)\s+(?:мне\s+)?(?:3|5|пять|несколько)?\s*"
        r"(?:книг|книги)\s+(?:как|похожих\s+на|в\s+духе)\s+(?P<query>.+)$",
        re.I,
    ),
    re.compile(r"\b(?:книги|книга)\s+похож(?:ие|ая)\s+на\s+(?P<query>.+)$", re.I),
    re.compile(r"\b(?:books?\s+like|recommend\s+books?\s+like)\s+(?P<query>.+)$", re.I),
)

_FOLLOWUP_RE = re.compile(
    r"^\s*(?:а\s+)?(?:ещ[её]|что\s+ещ[её]|дай\s+ещ[её]|ещ[её]\s+книги|а\s+похожее)\s*[?!.]*\s*$",
    re.I,
)

_GENERIC_SUBJECTS = {
    "fiction",
    "literature",
    "accessible book",
    "protected daisy",
    "in library",
    "open library staff picks",
    "translations into english",
}


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "prepare_request_text", None)):
            return module
    return None


def _clean_query(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" \t\r\n,.:;!?—-\"'«»")
    text = re.sub(r"^(?:книга|роман|book)\s+", "", text, flags=re.I)
    return text[:200]


def classify_book_recommendation_intent(text: str, *, chat_id: int | None = None) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return ""
    for pattern in _BOOK_PATTERNS:
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


async def _openlibrary_get(path: str, params: dict[str, Any]) -> Any:
    global _LAST_REQUEST_AT
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
        headers = {"User-Agent": OPEN_LIBRARY_USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
            response = await client.get(f"{OPEN_LIBRARY_BASE}/{path.lstrip('/')}", params=params)
            _LAST_REQUEST_AT = time.monotonic()
            if response.status_code in {204, 404}:
                return None
            response.raise_for_status()
            payload = response.json()
        _cache_put(cache_key, payload)
        return payload


def _docs(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    docs = payload.get("docs")
    return [item for item in docs or [] if isinstance(item, dict)]


def _authors(item: dict[str, Any]) -> list[str]:
    values = item.get("author_name") or []
    return [str(value).strip() for value in values if str(value).strip()][:4]


def _subjects(item: dict[str, Any]) -> list[str]:
    values = item.get("subject") or []
    result: list[str] = []
    for raw in values:
        value = " ".join(str(raw or "").split()).strip()
        normalized = value.casefold()
        if not value or normalized in _GENERIC_SUBJECTS or len(value) > 70:
            continue
        if normalized not in {item.casefold() for item in result}:
            result.append(value)
        if len(result) >= 18:
            break
    return result


def _work_summary(item: dict[str, Any]) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    key = str(item.get("key") or "").strip()
    authors = _authors(item)
    if not title or not key:
        return None
    if not key.startswith("/"):
        key = "/works/" + key.lstrip("/")
    return {
        "key": key,
        "title": title,
        "authors": authors,
        "first_publish_year": int(item.get("first_publish_year") or 0),
        "edition_count": int(item.get("edition_count") or 0),
        "subjects": _subjects(item),
        "source_url": OPEN_LIBRARY_BASE + key,
    }


def _normalize_title(value: Any) -> str:
    return re.sub(r"[^\wёЁ]+", " ", str(value or "").casefold(), flags=re.UNICODE).strip()


def _subject_overlap(seed_subjects: list[str], candidate_subjects: list[str]) -> int:
    seed = {item.casefold() for item in seed_subjects}
    return sum(1 for item in candidate_subjects if item.casefold() in seed)


def _useful_seed_subjects(subjects: list[str]) -> list[str]:
    preferred: list[str] = []
    for subject in subjects:
        lowered = subject.casefold()
        if any(token in lowered for token in ("fiction", "novel", "fantasy", "science fiction", "dystop", "mystery", "thriller", "horror", "histor", "psycholog", "philosoph", "adventure", "satire", "war", "detective", "romance")):
            preferred.append(subject)
        if len(preferred) >= 4:
            break
    if preferred:
        return preferred
    return subjects[:3]


async def resolve_seed_work(query: str) -> dict[str, Any] | None:
    payload = await _openlibrary_get(
        "search.json",
        {
            "q": query,
            "fields": "key,title,author_name,first_publish_year,edition_count,subject",
            "limit": 6,
        },
    )
    rows = _docs(payload)
    if not rows:
        return None
    normalized_query = _normalize_title(query)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        summary = _work_summary(row)
        if not summary:
            continue
        title = _normalize_title(summary["title"])
        score = max(0, 25 - index)
        if title == normalized_query:
            score += 100
        elif normalized_query and normalized_query in title:
            score += 50
        score += min(summary["edition_count"], 50) // 5
        ranked.append((score, summary))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


async def recommend_from_book(query: str) -> dict[str, Any] | None:
    seed = await resolve_seed_work(query)
    if not seed:
        return None
    seed_subjects = _useful_seed_subjects(seed.get("subjects") or [])
    if not seed_subjects:
        return None

    # Search API is documented/stable; avoid depending on the experimental
    # Subjects API. One OR query keeps provider traffic bounded.
    subject_query = " OR ".join(f'subject:"{subject.replace(chr(34), "")}"' for subject in seed_subjects[:3])
    payload = await _openlibrary_get(
        "search.json",
        {
            "q": subject_query,
            "fields": "key,title,author_name,first_publish_year,edition_count,subject",
            "limit": 35,
        },
    )
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _docs(payload):
        item = _work_summary(row)
        if not item or item["key"] == seed["key"] or item["key"] in seen:
            continue
        seen.add(item["key"])
        overlap = _subject_overlap(seed_subjects, item["subjects"])
        if overlap <= 0:
            continue
        item["subject_overlap"] = overlap
        item["matching_subjects"] = [
            subject for subject in item["subjects"] if subject.casefold() in {value.casefold() for value in seed_subjects}
        ][:4]
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            int(item.get("subject_overlap") or 0),
            min(int(item.get("edition_count") or 0), 500),
        ),
        reverse=True,
    )
    return {"seed": seed, "seed_subjects": seed_subjects, "candidates": candidates[:MAX_CANDIDATES]} if candidates else None


def build_book_recommendation_context(
    data: dict[str, Any],
    *,
    user_text: str,
    identity_lens: dict[str, str] | None,
) -> str:
    seed = data.get("seed") or {}
    rows: list[str] = []
    for index, item in enumerate(data.get("candidates") or [], start=1):
        author = ", ".join(item.get("authors") or []) or "автор не указан"
        subjects = ", ".join(item.get("matching_subjects") or []) or "нет точного пересечения тегов"
        rows.append(
            f"{index}. {item['title']} — {author} | year={item.get('first_publish_year') or 'unknown'} | "
            f"edition_count={item.get('edition_count') or 0} | shared_subjects={subjects} | source={item['source_url']}"
        )

    return (
        "Пользователь просит рекомендации книг. Ниже реальные работы Open Library, найденные по темам реально "
        "разрешённой seed-книги. Выбери 3–5 кандидатов только из списка, не придумывай другие названия/авторов. "
        "edition_count — сигнал распространённости из каталога, не оценка качества. Subject-теги Open Library "
        "краудсорсинговые и могут быть неровными, поэтому формулируй сходство как основанное на каталоговых темах, "
        "а не как математическую гарантию.\n"
        + identity_recommendation_runtime.identity_separation_rules("книги")
        + "\n\n"
        f"ВОПРОС: {user_text}\n"
        f"SEED: {seed.get('title') or ''} — {', '.join(seed.get('authors') or [])}\n"
        f"SEED SUBJECTS: {', '.join(data.get('seed_subjects') or [])}\n"
        "SELF-CANON LENS:\n"
        + identity_recommendation_runtime.format_identity_lens(identity_lens)
        + "\n\nOPEN LIBRARY CANDIDATES:\n"
        + "\n".join(rows)
    )


async def _route_book_recommendations(update: Any, context: Any) -> None:
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
    query = classify_book_recommendation_intent(prepared, chat_id=int(chat.id))
    if not query:
        return

    enforce = getattr(module, "enforce_rate_limit", None)
    if callable(enforce) and not await enforce(update, "general"):
        raise ApplicationHandlerStop

    try:
        data = await recommend_from_book(query)
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
        logging.warning("Open Library recommendation failed query=%r: %s", query, error)
        return
    except Exception as error:
        logging.exception("Unexpected Open Library recommendation failure query=%r: %s", query, error)
        return
    if not data:
        return

    seed = data.get("seed") or {}
    seed_title = str(seed.get("title") or query)
    entity_continuity_runtime.remember_topic(int(chat.id), seed_title)
    lens = identity_recommendation_runtime.load_identity_lens(module, int(chat.id))
    prompt = build_book_recommendation_context(data, user_text=prepared, identity_lens=lens)
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
    if "openlibrary.org" not in answer_text.lower():
        answer_text += "\n\nИсточник каталога: Open Library"

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
    logging.info("Open Library recommendation route: query=%r seed=%r", query, seed_title)
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _route_book_recommendations),
        group=-3,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Book recommendations ready: Open Library seed/subject candidates + provider-neutral self-canon lens"
    )
