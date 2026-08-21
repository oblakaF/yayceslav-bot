"""Fetches and extracts readable text from a URL pasted or forwarded by a user.

The bot previously had no way to actually read a link a user pasted or
forwarded -- Gemini would only ever see the bare URL string, which it
cannot browse. Mirrors the existing daily_content_runtime.py fetch
pattern (requests + lxml), scoped tighter: plain-text extraction only,
no link discovery, a hard time/size budget so one pasted link can't
stall a reply or blow up the prompt.
"""

from __future__ import annotations

import re

import requests
from lxml import html as lxml_html

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ").,!?»\"'”’"

_HTTP_HEADERS = {
    "User-Agent": "YayceslavBot/2.0 (+https://github.com/oblakaF/yayceslav-bot)",
}

FETCH_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ARTICLE_CHARS = 6000
MIN_ARTICLE_CHARS = 200


def find_first_url(text: str) -> str | None:
    match = _URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(_TRAILING_PUNCTUATION)


def _extract_readable_text(html_text: str) -> str:
    try:
        tree = lxml_html.fromstring(html_text)
    except Exception:
        return ""
    for tag in tree.xpath("//script | //style | //noscript | //nav | //footer | //header"):
        tag.drop_tree()
    text = " ".join(tree.xpath("//text()"))
    return re.sub(r"\s+", " ", text).strip()


def fetch_article_text_sync(url: str) -> str | None:
    """Best-effort plain-text extraction from a URL. None on any failure."""
    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme not in ("http", "https"):
        return None

    try:
        response = requests.get(
            url,
            headers=_HTTP_HEADERS,
            timeout=FETCH_TIMEOUT_SECONDS,
            stream=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return None
        raw = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
        html_text = raw[:MAX_RESPONSE_BYTES].decode(
            response.encoding or "utf-8", errors="ignore"
        )
    except Exception:
        return None

    text = _extract_readable_text(html_text)
    if len(text) < MIN_ARTICLE_CHARS:
        return None
    return text[:MAX_ARTICLE_CHARS]
