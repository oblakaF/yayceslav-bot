from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date as date_type

import requests
from google import genai
from google.genai import types
from telegram.ext import Application


JOKE_HOUR_MSK = 19
JOKE_MINUTE_MSK = 30
NEWS_HOUR_MSK = 20
NEWS_MINUTE_MSK = 0

JOKE_API_URL = "https://v2.jokeapi.dev/joke/Any"

# Government/Kremlin scraping was fragile (HTML markup drift silently
# broke it) and produced only dry official-speak. RSS is a standardized,
# machine-readable format -- far more robust to parse than arbitrary HTML
# -- and several popular sources are tried per run so one feed being down
# doesn't stop news from arriving at all. Content doesn't need to be
# serious; it just needs to reliably show up.
NEWS_RSS_SOURCES: tuple[tuple[str, str], ...] = (
    ("Lenta.ru", "https://lenta.ru/rss/news"),
    ("РИА Новости", "https://ria.ru/export/rss2/archive/index.xml"),
    ("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
)

_HTTP_HEADERS = {
    "User-Agent": "YayceslavBot/2.0 (+https://github.com/oblakaF/yayceslav-bot)",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
}

_PREPARED_APPLICATION_IDS: set[int] = set()


@dataclass(frozen=True)
class DailyItem:
    kind: str
    source_name: str
    source_url: str
    raw_text: str
    rendered_text: str
    item_key: str


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def _due(now, hour: int, minute: int) -> bool:
    return (now.hour, now.minute) >= (int(hour), int(minute))


def joke_due(now) -> bool:
    return _due(now, JOKE_HOUR_MSK, JOKE_MINUTE_MSK)


def news_due(now) -> bool:
    return _due(now, NEWS_HOUR_MSK, NEWS_MINUTE_MSK)


def _initialize_tables(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_content_items (
                date TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                rendered_text TEXT NOT NULL,
                item_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (date, kind)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_content_deliveries (
                chat_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                kind TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, date, kind)
            )
            """
        )
        connection.commit()


def _known_chat_ids_sync(bot_module) -> list[int]:
    _initialize_tables(bot_module)
    with bot_module.get_db_connection() as connection:
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT chat_id
                FROM chat_membership_registry
                WHERE is_active = 1 AND is_bot = 0
                ORDER BY chat_id
                """
            ).fetchall()
        except Exception:
            rows = connection.execute(
                """
                SELECT DISTINCT chat_id
                FROM chats
                WHERE chat_type IN ('group', 'supergroup')
                ORDER BY chat_id
                """
            ).fetchall()
    return [int(row[0]) for row in rows]


def _delivery_sent_sync(bot_module, chat_id: int, day: str, kind: str) -> bool:
    _initialize_tables(bot_module)
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM daily_content_deliveries WHERE chat_id = ? AND date = ? AND kind = ?",
            (chat_id, day, kind),
        ).fetchone()
    return bool(row)


def _mark_delivery_sync(bot_module, chat_id: int, day: str, kind: str) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO daily_content_deliveries(chat_id, date, kind) VALUES (?, ?, ?)",
            (chat_id, day, kind),
        )
        connection.commit()


def _load_item_sync(bot_module, day: str, kind: str) -> DailyItem | None:
    _initialize_tables(bot_module)
    with bot_module.get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT source_name, source_url, raw_text, rendered_text, item_key
            FROM daily_content_items
            WHERE date = ? AND kind = ?
            """,
            (day, kind),
        ).fetchone()
    if not row:
        return None
    return DailyItem(
        kind=kind,
        source_name=str(row[0]),
        source_url=str(row[1]),
        raw_text=str(row[2]),
        rendered_text=str(row[3]),
        item_key=str(row[4]),
    )


def _save_item_sync(bot_module, day: str, item: DailyItem) -> None:
    _initialize_tables(bot_module)
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO daily_content_items(
                date, kind, source_name, source_url, raw_text, rendered_text, item_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day,
                item.kind,
                item.source_name,
                item.source_url,
                item.raw_text,
                item.rendered_text,
                item.item_key,
            ),
        )
        connection.commit()


def _recent_item_keys_sync(bot_module, kind: str, limit: int = 30) -> set[str]:
    _initialize_tables(bot_module)
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT item_key
            FROM daily_content_items
            WHERE kind = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (kind, int(limit)),
        ).fetchall()
    return {str(row[0]) for row in rows if row and row[0]}


def _clean_space(text: str) -> str:
    return re.sub(r"[ \t]+", " ", str(text or "")).replace("\r\n", "\n").strip()


def _joke_text_from_payload(payload: dict) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict) or payload.get("error"):
        return None, None
    joke_id = payload.get("id")
    item_key = f"jokeapi:{joke_id}" if joke_id is not None else None
    if payload.get("type") == "single":
        text = _clean_space(payload.get("joke", ""))
    elif payload.get("type") == "twopart":
        setup = _clean_space(payload.get("setup", ""))
        delivery = _clean_space(payload.get("delivery", ""))
        text = (setup + "\n" + delivery).strip() if setup and delivery else ""
    else:
        text = ""
    if not (20 <= len(text) <= 900):
        return None, None
    return text, item_key


def _fetch_external_joke_sync(language: str, recent_keys: set[str]) -> tuple[str, str, str]:
    params = {
        "lang": language,
        "blacklistFlags": "racist,sexist,religious",
        "format": "json",
    }
    last_error: Exception | None = None
    for _attempt in range(6):
        try:
            response = requests.get(
                JOKE_API_URL,
                params=params,
                headers=_HTTP_HEADERS,
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            text, item_key = _joke_text_from_payload(payload)
            if not text or not item_key or item_key in recent_keys:
                continue
            source_url = f"{JOKE_API_URL}?lang={language}"
            return text, item_key, source_url
        except Exception as error:
            last_error = error
    if last_error:
        raise last_error
    raise RuntimeError("JokeAPI returned no usable non-repeating joke")


_SENTENCE_END_CHARS = (".", "!", "?", "…", "»", '"')


def _looks_like_complete_joke(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped[-1] in _SENTENCE_END_CHARS


async def _translate_joke(bot_module, english_text: str) -> str | None:
    api_key = str(getattr(bot_module, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None
    prompt = (
        "Переведи этот АНГЛИЙСКИЙ анекдот ПОЛНОСТЬЮ на естественный разговорный русский, "
        "не обрывая на середине. Не придумывай новую шутку, не меняй смысл, не добавляй "
        "пояснений, цензуру или комментарии. Верни только перевод.\n\n" + english_text
    )
    try:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=str(getattr(bot_module, "MODEL_NAME", "gemini-3.6-flash")),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.15,
                # Generous margin over the 900-char cap on the source joke --
                # a truncated mid-sentence punchline (finish_reason=MAX_TOKENS
                # with no retry, unlike ask_gemini's Gemini calls) previously
                # got sent to users as-is.
                max_output_tokens=768,
                system_instruction="Ты точный переводчик юмора. Не сочиняй ничего от себя.",
            ),
        )
        translated = _clean_space(getattr(response, "text", "") or "")
    except Exception as error:
        logging.warning("Daily joke translation failed: %s", error)
        return None
    if len(translated) < 12:
        return None
    if not _looks_like_complete_joke(translated):
        # Doesn't end on a sentence boundary -- treat as a truncated/failed
        # translation rather than showing a joke that stops mid-word. The
        # caller falls back to a native-language joke instead.
        logging.warning("Daily joke translation looked truncated, discarding it")
        return None
    return translated


async def _build_joke_item(bot_module, current_date: date_type) -> DailyItem | None:
    day = current_date.isoformat()
    cached = await asyncio.to_thread(_load_item_sync, bot_module, day, "joke")
    if cached:
        return cached

    recent = await asyncio.to_thread(_recent_item_keys_sync, bot_module, "joke", 30)
    # Stable daily alternation: both Russian and English material appear over time.
    preferred = "ru" if current_date.toordinal() % 2 else "en"
    languages = (preferred, "en" if preferred == "ru" else "ru")

    for language in languages:
        try:
            joke_text, item_key, source_url = await asyncio.to_thread(
                _fetch_external_joke_sync,
                language,
                recent,
            )
        except Exception as error:
            logging.warning("Daily joke source failed lang=%s: %s", language, error)
            continue

        if language == "en":
            translated = await _translate_joke(bot_module, joke_text)
            if not translated:
                continue
            rendered = (
                "🥚 ВНИМАНИЕ, АНЕКДОТ:\n\n"
                + joke_text
                + "\n\nДля тех, кто прогуливал английский:\n"
                + translated
            )
        else:
            rendered = "🥚 ВНИМАНИЕ, АНЕКДОТ:\n\n" + joke_text

        item = DailyItem(
            kind="joke",
            source_name="JokeAPI",
            source_url=source_url,
            raw_text=joke_text,
            rendered_text=rendered,
            item_key=item_key,
        )
        await asyncio.to_thread(_save_item_sync, bot_module, day, item)
        return item
    return None


def _fetch_html_sync(url: str) -> str:
    response = requests.get(url, headers=_HTTP_HEADERS, timeout=15)
    response.raise_for_status()
    return response.text


_RSS_NAMESPACES = {"content": "http://purl.org/rss/1.0/modules/content/"}


def _parse_rss_items(xml_text: str, *, limit: int = 8) -> list[tuple[str, str]]:
    """Extracts (title, link) pairs from a standard RSS 2.0 feed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = _clean_space(str((title_el.text if title_el is not None else "") or ""))
        link = str((link_el.text if link_el is not None else "") or "").strip()
        if not title or not link or link in seen:
            continue
        if len(title) < 12 or len(title) > 320:
            continue
        seen.add(link)
        results.append((title, link))
        if len(results) >= limit:
            break
    return results


def _fetch_news_candidates_sync() -> list[tuple[str, str, str]]:
    all_candidates: list[tuple[str, str, str]] = []
    for source_name, feed_url in NEWS_RSS_SOURCES:
        try:
            xml_text = _fetch_html_sync(feed_url)
            items = _parse_rss_items(xml_text, limit=5)
        except Exception as error:
            logging.warning("News RSS source failed %s: %s", source_name, error)
            continue
        if not items:
            # The fetch succeeded (no exception) but zero usable items came
            # out -- most likely the feed's shape changed or it returned an
            # empty/error body. Unlike a fetch exception, this failure mode
            # would otherwise leave no trace and repeat silently all day.
            logging.warning(
                "News RSS source returned zero usable items %s (feed length=%s)",
                source_name,
                len(xml_text),
            )
            continue
        all_candidates.extend((source_name, title, link) for title, link in items)
    return all_candidates


async def _comment_news(bot_module, title: str, source_name: str) -> tuple[str, str] | None:
    api_key = str(getattr(bot_module, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None
    prompt = (
        "Ниже заголовок ОДНОЙ новости из популярного российского СМИ. "
        "Не добавляй никаких фактов, которых нет в заголовке. "
        "Определи эмоциональный тон новости как positive, negative или neutral и придумай ОДИН короткий комментарий Яйцеслава. "
        "Позитивное можно отметить победно/иронично, негативное — ворчливо в духе «ну опять всё как всегда», нейтральное — сухо и смешно. "
        "Мат допустим, если он уместен, но не обязателен. Не агитируй и не искажай новость. "
        "Верни СТРОГО JSON: {\"tone\":\"positive|negative|neutral\",\"comment\":\"...\"}. "
        "Комментарий максимум 110 символов.\n\n"
        f"Источник: {source_name}\nЗаголовок: {title}"
    )
    try:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=str(getattr(bot_module, "MODEL_NAME", "gemini-3.6-flash")),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.85,
                max_output_tokens=320,
                system_instruction=(
                    "Ты Яйцеслав. Комментарий к новости — короткий мемный хвост, а не пересказ и не политическая агитация."
                ),
            ),
        )
        raw = str(getattr(response, "text", "") or "").strip()
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        payload = json.loads(match.group(0) if match else raw)
        tone = str(payload.get("tone", "neutral")).strip().lower()
        comment = _clean_space(payload.get("comment", ""))
    except Exception as error:
        logging.warning("Daily news comment generation failed: %s", error)
        return None
    if tone not in {"positive", "negative", "neutral"}:
        tone = "neutral"
    if not (8 <= len(comment) <= 140):
        return None
    return tone, comment


async def _build_news_item(bot_module, current_date: date_type) -> DailyItem | None:
    day = current_date.isoformat()
    cached = await asyncio.to_thread(_load_item_sync, bot_module, day, "news")
    if cached:
        return cached

    candidates = await asyncio.to_thread(_fetch_news_candidates_sync)
    if not candidates:
        return None

    # Alternate the primary official source by date for variety, while keeping
    # the other source as fallback. We still publish only one news item.
    preferred = "Правительство России" if current_date.toordinal() % 2 else "Президент России"
    ordered = sorted(candidates, key=lambda item: 0 if item[0] == preferred else 1)
    recent = await asyncio.to_thread(_recent_item_keys_sync, bot_module, "news", 14)

    chosen = None
    for source_name, title, url in ordered:
        key = "news:" + url
        if key not in recent:
            chosen = (source_name, title, url, key)
            break
    if chosen is None:
        source_name, title, url = ordered[0]
        chosen = (source_name, title, url, "news:" + url)

    source_name, title, url, item_key = chosen
    comment_result = await _comment_news(bot_module, title, source_name)
    if comment_result:
        _tone, comment = comment_result
        rendered = (
            "📰 НОВОСТЬ ДНЯ СЕГОДНЯ ТАКАЯ:\n\n"
            + title
            + "\n\nЯйцеслав: "
            + comment
            + "\n\nИсточник: "
            + url
        )
    else:
        # The factual headline is still useful and sourced; if AI commentary
        # fails we do not invent a canned reaction.
        rendered = "📰 НОВОСТЬ ДНЯ СЕГОДНЯ ТАКАЯ:\n\n" + title + "\n\nИсточник: " + url

    item = DailyItem(
        kind="news",
        source_name=source_name,
        source_url=url,
        raw_text=title,
        rendered_text=rendered,
        item_key=item_key,
    )
    await asyncio.to_thread(_save_item_sync, bot_module, day, item)
    return item


async def _deliver_item(application: Application, bot_module, item: DailyItem, day: str) -> None:
    chat_ids = await asyncio.to_thread(_known_chat_ids_sync, bot_module)
    for chat_id in chat_ids:
        if await asyncio.to_thread(_delivery_sent_sync, bot_module, chat_id, day, item.kind):
            continue
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=item.rendered_text,
                disable_web_page_preview=True,
            )
        except Exception as error:
            logging.warning("Daily %s delivery failed chat=%s: %s", item.kind, chat_id, error)
            continue
        await asyncio.to_thread(_mark_delivery_sync, bot_module, chat_id, day, item.kind)


async def run_daily_content_if_due(application: Application) -> None:
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    now = bot_module.current_msk_datetime()
    day = now.date().isoformat()

    if joke_due(now):
        item = await _build_joke_item(bot_module, now.date())
        if item:
            await _deliver_item(application, bot_module, item, day)

    if news_due(now):
        item = await _build_news_item(bot_module, now.date())
        if item:
            await _deliver_item(application, bot_module, item, day)


def _patch_scheduler(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_daily_content_patch", False):
        return
    original = bot_module.run_due_daily_titles

    async def wrapped(application: Application) -> None:
        await original(application)
        await run_daily_content_if_due(application)

    bot_module.run_due_daily_titles = wrapped
    bot_module._yayceslav_daily_content_patch = True


def _prepare_application(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    bot_module = _find_bot_module()
    if bot_module is None:
        return
    _initialize_tables(bot_module)
    _patch_scheduler(bot_module)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning(
        "Daily external content ready: joke=19:30 MSK (JokeAPI ru/en); "
        "news=20:00 MSK (%s)",
        ", ".join(name for name, _url in NEWS_RSS_SOURCES),
    )
