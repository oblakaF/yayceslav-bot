"""Bounded Search 2.0 enrichment for Railway free-tier deployments.

The existing DDGS search remains the source discovery layer. This runtime only:
- ranks obvious low-value/social/coupon results lower;
- fetches readable text for at most two useful pages concurrently;
- injects at most a few thousand characters per page into Gemini context.

No persistent cache, browser, vector DB or unbounded memory is introduced.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import urlparse

import url_content_fetcher


MAX_ENRICHED_PAGES = 2
MAX_PAGE_CONTEXT_CHARS = 4500
MAX_TOTAL_PAGE_CONTEXT_CHARS = 8000

_LOW_VALUE_HOST_PARTS = (
    "tiktok.com",
    "vk.com",
    "vkvideo.ru",
    "pinterest.",
    "promokod",
    "promocode",
    "coupon",
    "rutube.ru",
)

_HIGH_VALUE_HOST_PARTS = (
    ".gov",
    ".edu",
    "who.int",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "nature.com",
    "science.org",
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def result_quality_score(result: dict[str, str]) -> int:
    """Small deterministic ranking signal, not a truth/reliability oracle."""

    url = str(result.get("url") or "")
    host = _host(url)
    title = str(result.get("title") or "").strip()
    snippet = str(result.get("snippet") or "").strip()

    score = 0
    if title:
        score += 1
    if len(snippet) >= 80:
        score += 1
    if host:
        score += 1
    if any(part in host for part in _HIGH_VALUE_HOST_PARTS):
        score += 4
    if any(part in host for part in _LOW_VALUE_HOST_PARTS):
        score -= 5
    return score


def rank_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    # Stable sort preserves DDGS ordering among equal-quality results.
    return sorted(results, key=result_quality_score, reverse=True)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "search_web", None)):
            return module
    return None


async def _fetch_page_text(result: dict[str, str]) -> tuple[dict[str, str], str | None]:
    url = str(result.get("url") or "").strip()
    if not url:
        return result, None
    text = await asyncio.to_thread(url_content_fetcher.fetch_article_text_sync, url)
    if text:
        text = text[:MAX_PAGE_CONTEXT_CHARS]
    return result, text


def install() -> bool:
    bot_module = _find_bot_module()
    if bot_module is None:
        return False
    if getattr(bot_module, "_yayceslav_search_enrichment_installed", False):
        return True

    original_search_web = bot_module.search_web
    original_format_search_results = bot_module.format_search_results

    async def search_web_enriched(query: str, max_results: int = 5):
        results = await original_search_web(query=query, max_results=max_results)
        if not results:
            return results

        ranked = rank_results([dict(item) for item in results])
        candidates = [
            item
            for item in ranked
            if result_quality_score(item) >= 0
        ][:MAX_ENRICHED_PAGES]

        if candidates:
            fetched = await asyncio.gather(
                *(_fetch_page_text(item) for item in candidates),
                return_exceptions=True,
            )
            remaining = MAX_TOTAL_PAGE_CONTEXT_CHARS
            page_text_by_url: dict[str, str] = {}
            for item in fetched:
                if isinstance(item, Exception):
                    logging.debug("Search page enrichment failed: %s", item)
                    continue
                result, page_text = item
                if not page_text or remaining <= 0:
                    continue
                clipped = page_text[:remaining]
                remaining -= len(clipped)
                page_text_by_url[str(result.get("url") or "")] = clipped

            for item in ranked:
                page_text = page_text_by_url.get(str(item.get("url") or ""))
                if page_text:
                    item["page_text"] = page_text

        return ranked

    def format_search_results_enriched(results):
        base = original_format_search_results(results)
        enriched_parts: list[str] = []
        for number, result in enumerate(results, start=1):
            page_text = str(result.get("page_text") or "").strip()
            if page_text:
                enriched_parts.append(
                    f"Текст страницы результата {number} (частично):\n{page_text}"
                )
        if not enriched_parts:
            return base
        return base + "\n\n" + "\n\n".join(enriched_parts)

    search_web_enriched._yayceslav_search_enrichment = True
    format_search_results_enriched._yayceslav_search_enrichment = True
    bot_module.search_web = search_web_enriched
    bot_module.format_search_results = format_search_results_enriched
    bot_module._yayceslav_search_enrichment_installed = True
    logging.warning(
        "Search enrichment ready: max %s pages, max %s chars total",
        MAX_ENRICHED_PAGES,
        MAX_TOTAL_PAGE_CONTEXT_CHARS,
    )
    return True
