from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin

import daily_content_runtime as runtime


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
    # Rewrite even today's cached item so a restart before 19:30 cannot restore
    # the old 'English original + translation' format.
    await asyncio.to_thread(
        runtime._save_item_sync,
        bot_module,
        current_date.isoformat(),
        fixed,
    )
    return fixed


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
        # Feed navigation and one-word section links are not news headlines.
        if not (24 <= len(title) <= 320):
            continue
        lowered = title.lower()
        if lowered in {"подробнее", "читать", "лента материалов", "новости"}:
            continue

        seen.add(url)
        results.append(("ТАСС", title, url))
        if len(results) >= limit:
            break

    return results


def _fetch_news_candidates_with_tass_sync() -> list[tuple[str, str, str]]:
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


async def _build_news_item_with_rotation(bot_module, current_date):
    day = current_date.isoformat()
    cached = await asyncio.to_thread(runtime._load_item_sync, bot_module, day, "news")
    if cached:
        return cached

    candidates = await asyncio.to_thread(_fetch_news_candidates_with_tass_sync)
    if not candidates:
        return None

    # One news item per day. Rotate source priority so TASS is not permanently
    # hidden behind government.ru/kremlin.ru when all three are healthy.
    source_cycle = ("ТАСС", "Правительство России", "Президент России")
    preferred = source_cycle[current_date.toordinal() % len(source_cycle)]
    ordered = sorted(
        candidates,
        key=lambda item: (0 if item[0] == preferred else 1, source_cycle.index(item[0]) if item[0] in source_cycle else 99),
    )

    recent = await asyncio.to_thread(runtime._recent_item_keys_sync, bot_module, "news", 14)
    chosen = next(
        ((source, title, url, "news:" + url) for source, title, url in ordered if "news:" + url not in recent),
        None,
    )
    if chosen is None:
        source, title, url = ordered[0]
        chosen = (source, title, url, "news:" + url)

    source_name, title, url, item_key = chosen
    comment_result = await runtime._comment_news(bot_module, title, source_name)
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
    runtime._fetch_official_news_candidates_sync = _fetch_news_candidates_with_tass_sync
    runtime._build_news_item = _build_news_item_with_rotation


install()
