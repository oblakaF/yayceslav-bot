from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import urljoin

import daily_content_runtime as runtime


DZEN_NEWS_URL = "https://dzen.ru/news"
TASS_FEED_URL = "https://tass.ru/feed"
_ORIGINAL_BUILD_JOKE_ITEM = runtime._build_joke_item
_ORIGINAL_FETCH_NEWS = runtime._fetch_official_news_candidates_sync


def _translated_only_rendered(rendered: str) -> str:
    marker = "Для тех, кто прогуливал английский:\n"
    text = str(rendered or "")
    if marker not in text:
        return text
    translated = text.split(marker, 1)[1].strip()
    if not translated:
        return text
    return "🥚 ВНИМАНИЕ, АНЕКДОТ:\n\n" + translated


async def _build_joke_item_translated_only(bot_module, current_date):
    item = await _ORIGINAL_BUILD_JOKE_ITEM(bot_module, current_date)
    if item is None:
        return None

    rendered = _translated_only_rendered(item.rendered_text)
    if rendered == item.rendered_text:
        return item

    fixed = runtime.DailyItem(
        kind=item.kind,
        source_name=item.source_name,
        source_url=item.source_url,
        raw_text=item.raw_text,
        rendered_text=rendered,
        item_key=item.item_key,
    )
    await asyncio.to_thread(
        runtime._save_item_sync,
        bot_module,
        current_date.isoformat(),
        fixed,
    )
    return fixed


def _anchor_title(anchor) -> str:
    for attr in ("aria-label", "title"):
        value = runtime._clean_space(anchor.get(attr) or "")
        if 20 <= len(value) <= 320:
            return value
    return runtime._clean_space(" ".join(anchor.itertext()))


def _fetch_dzen_candidates_sync(limit: int = 8) -> list[tuple[str, str, str]]:
    """Return Dzen News stories in page order.

    Dzen does not expose a public view-count API for the news ranking, so the
    first visible story is treated as the aggregator's top-ranked/main story,
    not as a mathematically proven 'most viewed' item.
    """
    try:
        html_text = runtime._fetch_html_sync(DZEN_NEWS_URL)
        tree = runtime.lxml_html.fromstring(html_text)
    except Exception as error:
        logging.warning("Dzen News source failed: %s", error)
        return []

    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for anchor in tree.xpath("//a[@href]"):
        href = str(anchor.get("href") or "").strip()
        if "/news/story/" not in href:
            continue
        url = urljoin(DZEN_NEWS_URL, href)
        if url in seen:
            continue
        title = _anchor_title(anchor)
        if not (24 <= len(title) <= 320):
            continue
        lowered = title.lower()
        if lowered in {"подробнее", "читать", "новости", "главное"}:
            continue
        seen.add(url)
        results.append(("Дзен Новости", title, url))
        if len(results) >= limit:
            break

    return results


def _fetch_tass_candidates_sync(limit: int = 10) -> list[tuple[str, str, str]]:
    try:
        html_text = runtime._fetch_html_sync(TASS_FEED_URL)
        tree = runtime.lxml_html.fromstring(html_text)
    except Exception as error:
        logging.warning("TASS daily news source failed: %s", error)
        return []

    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    article_re = re.compile(r"^https://tass\.ru/[a-z0-9_-]+/\d+/?$", re.IGNORECASE)

    for anchor in tree.xpath("//a[@href]"):
        href = str(anchor.get("href") or "").strip()
        url = urljoin(TASS_FEED_URL, href)
        if url in seen or not article_re.match(url):
            continue

        title = runtime._clean_space(" ".join(anchor.itertext()))
        if not (24 <= len(title) <= 320):
            continue
        if title.lower() in {"подробнее", "читать", "лента материалов", "новости"}:
            continue

        seen.add(url)
        results.append(("ТАСС", title, url))
        if len(results) >= limit:
            break

    return results


def _fetch_fallback_news_sync() -> list[tuple[str, str, str]]:
    original = _ORIGINAL_FETCH_NEWS()
    tass = _fetch_tass_candidates_sync(limit=10)
    combined: list[tuple[str, str, str]] = []
    seen_urls: set[str] = set()
    for source_name, title, url in tass + original:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        combined.append((source_name, title, url))
    return combined


async def _comment_news_general(bot_module, title: str, source_name: str) -> tuple[str, str] | None:
    api_key = str(getattr(bot_module, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None

    prompt = (
        "Ниже заголовок ОДНОЙ реальной новости, уже полученной из внешнего новостного источника. "
        "Не добавляй фактов, которых нет в заголовке. "
        "Определи эмоциональный тон как positive, negative или neutral и придумай ОДИН короткий комментарий Яйцеслава. "
        "Позитивное — победно или иронично; негативное — ворчливо; нейтральное — сухо и смешно. "
        "Мат допустим, если уместен. Не агитируй, не искажай новость и не пересказывай её. "
        "Верни строго JSON: {\"tone\":\"positive|negative|neutral\",\"comment\":\"...\"}. "
        "Комментарий максимум 110 символов.\n\n"
        f"Источник: {source_name}\nЗаголовок: {title}"
    )

    try:
        client = runtime.genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=str(getattr(bot_module, "MODEL_NAME", "gemini-3.6-flash")),
            contents=prompt,
            config=runtime.types.GenerateContentConfig(
                temperature=0.85,
                max_output_tokens=320,
                system_instruction=(
                    "Ты Яйцеслав. Комментарий к новости — короткий мемный хвост, не пересказ и не политическая агитация."
                ),
            ),
        )
        raw = str(getattr(response, "text", "") or "").strip()
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        payload = json.loads(match.group(0) if match else raw)
        tone = str(payload.get("tone", "neutral")).strip().lower()
        comment = runtime._clean_space(payload.get("comment", ""))
    except Exception as error:
        logging.warning("Daily news comment generation failed: %s", error)
        return None

    if tone not in {"positive", "negative", "neutral"}:
        tone = "neutral"
    if not (8 <= len(comment) <= 140):
        return None
    return tone, comment


async def _build_news_item_dzen_first(bot_module, current_date):
    day = current_date.isoformat()
    cached = await asyncio.to_thread(runtime._load_item_sync, bot_module, day, "news")
    if cached:
        return cached

    recent = await asyncio.to_thread(runtime._recent_item_keys_sync, bot_module, "news", 14)

    # Primary: the first/top-ranked Dzen News story available on the page.
    dzen = await asyncio.to_thread(_fetch_dzen_candidates_sync, 8)
    chosen = None
    for source_name, title, url in dzen:
        key = "news:" + url
        if key not in recent:
            chosen = (source_name, title, url, key)
            break
    if chosen is None and dzen:
        source_name, title, url = dzen[0]
        chosen = (source_name, title, url, "news:" + url)

    # Fallback: TASS, then official government/Kremlin feeds.
    if chosen is None:
        fallback = await asyncio.to_thread(_fetch_fallback_news_sync)
        for source_name, title, url in fallback:
            key = "news:" + url
            if key not in recent:
                chosen = (source_name, title, url, key)
                break
        if chosen is None and fallback:
            source_name, title, url = fallback[0]
            chosen = (source_name, title, url, "news:" + url)

    if chosen is None:
        return None

    source_name, title, url, item_key = chosen
    comment_result = await _comment_news_general(bot_module, title, source_name)
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
        rendered = "📰 НОВОСТЬ ДНЯ СЕГОДНЯ ТАКАЯ:\n\n" + title + "\n\nИсточник: " + url

    item = runtime.DailyItem(
        kind="news",
        source_name=source_name,
        source_url=url,
        raw_text=title,
        rendered_text=rendered,
        item_key=item_key,
    )
    await asyncio.to_thread(runtime._save_item_sync, bot_module, day, item)
    return item


def install() -> None:
    runtime._build_joke_item = _build_joke_item_translated_only
    runtime._build_news_item = _build_news_item_dzen_first


install()
