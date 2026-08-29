"""Slang and skeptical follow-ups that should trigger the existing real search path.

This layer is intentionally deterministic and cheap: it only broadens
``extract_search_query``. It adds no Gemini call, web call, storage, timer or
background work by itself. Empty string means: verify the previous topic using
the existing search-context recovery layer.
"""

from __future__ import annotations

import functools
import re
import sys
from typing import Any


_INSTALLED = False

# High-confidence proof/challenge phrases. Keep these colloquial: this is the
# vocabulary people actually use when they doubt a factual answer in chat.
_PROOF_SLANG_RE = re.compile(
    r"(?:"
    r"\b(?:пруфани|пруфни|пруфанешь|пруфнешь|пруфуйте|запруфай|запруфь)\b|"
    r"\b(?:где|дай|давай|покажи|скинь|предъяви)\s+(?:же\s+)?пруф(?:ы|а|ов)?\b|"
    r"\bпруф(?:ы|а|ов)?\s+(?:где|есть|будут)\b|"
    r"\b(?:а\s+)?(?:ты\s+)?не\s+(?:пизд(?:ишь|ите)|вр[её]шь|гон(?:ишь|ите))\b|"
    r"\bпахнет\s+(?:каким[- ]то\s+|прям\s+|явным\s+)?пизд[еёи]ж\w*\b|"
    r"\b(?:это|тут|там)\s+(?:же\s+)?пизд[еёи]ж\w*\??\b|"
    r"\b(?:не\s+)?выдумал\??\b|"
    r"\b(?:не\s+)?придумал\??\b"
    r")",
    re.IGNORECASE,
)

# Very short skeptical replies are safe to treat as "verify the previous fact".
# Requiring the whole message avoids turning ordinary sentences containing
# "уверен" or "точно" into web searches.
_SHORT_SKEPTIC_RE = re.compile(
    r"^\s*(?:"
    r"(?:ты\s+)?уверен(?:\s+в\s+этом)?|"
    r"точно|точняк|прям\s+точно|точно\s+уверен|"
    r"серь[её]зно|без\s+пизд[еёи]жа|"
    r"пруф|пруфы|пруфчик|источник|источники|ссылки"
    r")\s*[?!.]*\s*$",
    re.IGNORECASE,
)


def is_slang_proof_request(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return False
    return bool(_PROOF_SLANG_RE.search(value) or _SHORT_SKEPTIC_RE.fullmatch(value))


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "extract_search_query", None)):
            return module
    return None


def install(bot_module: Any | None = None) -> bool:
    """Wrap the final extractor after search_context_runtime has installed."""
    global _INSTALLED

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    original = getattr(module, "extract_search_query", None)
    if not callable(original):
        return False
    if getattr(original, "_yayceslav_search_slang", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def extract_search_query_with_slang(text: str) -> str | None:
        existing = original(text)
        if existing is not None:
            return existing
        if is_slang_proof_request(text):
            # Existing perform_web_search wrapper resolves "" to the previous
            # concrete chat topic, so we verify instead of asking Gemini to
            # improvise an answer about whether it was right.
            return ""
        return None

    extract_search_query_with_slang._yayceslav_search_slang = True
    module.extract_search_query = extract_search_query_with_slang
    module._yayceslav_search_slang_installed = True
    _INSTALLED = True
    return True
