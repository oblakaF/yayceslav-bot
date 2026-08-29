from __future__ import annotations

import asyncio

import daily_content_runtime as runtime

# News building deliberately stays on daily_content_runtime._build_news_item
# (NEWS_RSS_SOURCES) rather than being overridden here. This module used to
# chain Dzen News -> TASS -> government.ru/kremlin.ru scraping, all three
# fragile HTML-anchor scrapers -- Dzen is a JS-rendered SPA that a plain
# requests.get() can't see any content in at all -- which is why news kept
# silently failing to arrive some days. RSS is the reliable path now.

_ORIGINAL_BUILD_JOKE_ITEM = runtime._build_joke_item


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


def install() -> None:
    runtime._build_joke_item = _build_joke_item_translated_only


install()
