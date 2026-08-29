"""Route slang/word-definition verification to the real search path.

Live chat exposed a specific failure mode: after discussing an unfamiliar word,
``проверь значение слова, вместе со ссылками`` was parsed as a search for the
incidental word ``вместе``.  This wrapper runs after Search 2.0 and returns an
empty query for anaphoric definition follow-ups, which tells the existing
search_context_runtime to reuse the immediately previous chat topic.  When the
word is explicitly present, it builds a concrete ``значение слова X`` query.

No extra web/model call is added; this only improves query extraction.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any


_INSTALLED = False

_DEFINITION_REQUEST_RE = re.compile(
    r"(?:"
    r"\b(?:проверь|чекни|глянь|поищи|найди)\b.{0,30}\b(?:значение|что\s+значит)\b|"
    r"\b(?:значение|что\s+значит)\b.{0,30}\b(?:проверь|чекни|глянь|поищи|найди)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_EXPLICIT_WORD_RE = re.compile(
    r"(?:"
    r"\bзначение\s+(?:слова\s+)?[«\"']?([A-Za-zА-Яа-яЁё0-9_-]{3,32})[»\"']?|"
    r"\bчто\s+значит\s+[«\"']?([A-Za-zА-Яа-яЁё0-9_-]{3,32})[»\"']?"
    r")",
    re.IGNORECASE,
)

# Words that are structural parts of the request, not likely lexical targets.
_REQUEST_NOISE = {
    "слова", "слово", "вместе", "ссылками", "ссылкой", "ссылка", "ссылки",
    "источниками", "источник", "источники", "интернете", "инете", "сети",
    "пожалуйста", "нормально", "точно", "реально",
}


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "extract_search_query", None)):
            return module
    return None


def definition_search_query(text: str) -> str | None:
    """Concrete query, empty string for prior-topic reuse, or None."""

    value = " ".join(str(text or "").split()).strip()
    if not value or not _DEFINITION_REQUEST_RE.search(value):
        return None

    match = _EXPLICIT_WORD_RE.search(value)
    if match:
        candidate = next((group for group in match.groups() if group), "").strip(".,!?;:")
        if candidate and candidate.lower() not in _REQUEST_NOISE:
            return f"значение слова {candidate}"

    # The word was omitted: e.g. "проверь значение слова, вместе со ссылками".
    # Existing search_context_runtime resolves empty queries from previous chat
    # memory, preserving the actual subject rather than guessing from filler.
    return ""


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False

    original = getattr(module, "extract_search_query", None)
    if not callable(original):
        return False
    if getattr(original, "_yayceslav_lexical_search_v3", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def extract_with_lexical_followup(text: str) -> str | None:
        lexical = definition_search_query(text)
        if lexical is not None:
            return lexical
        return original(text)

    extract_with_lexical_followup._yayceslav_lexical_search_v3 = True
    module.extract_search_query = extract_with_lexical_followup
    _INSTALLED = True
    logging.warning("Lexical search v3 ready: definition follow-ups reuse the real previous topic")
    return True
