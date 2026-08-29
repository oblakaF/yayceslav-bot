"""Small live-language extension for Fight Routing v3.

Keeping these observed Telegram phrasings separate makes it easy to extend the
lexicon without touching the conflict/session logic. Importing this module
extends (never replaces) the base v3 regexes.
"""

from __future__ import annotations

import re

import fight_routing_v3 as v3


_INSTALLED = False

_DIRECT_INSULT_EXTENSION = (
    r"(?:"
    r"\b(?:ну\s+)?ты\s+(?:и\s+)?(?:"
    r"залупа|пиздабол|хуесос|у[её]бан|долбо[её]б|мудак|чмо|гумыза"
    r")\w*\b|"
    # Live wording: «метнулся к хую и нюхаешь». The base expression covered
    # nominative/genitive forms but missed the dative «хую».
    r"\bметнул(?:ся|ась)\s+к\s+ху(?:ю|я|й)\b(?:.{0,24}\bнюх\w*)?"
    r")"
)

_OLD_PHOTO_REVEAL_EXTENSION = (
    r"\bфотк\w*.{0,64}\b(?:давност\w*|назад)\b"
)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    v3._EXTRA_FIGHT_RE = re.compile(
        f"(?:{v3._EXTRA_FIGHT_RE.pattern})|(?:{_DIRECT_INSULT_EXTENSION})",
        re.IGNORECASE | re.DOTALL,
    )
    v3._BAIT_REVEAL_RE = re.compile(
        f"(?:{v3._BAIT_REVEAL_RE.pattern})|(?:{_OLD_PHOTO_REVEAL_EXTENSION})",
        re.IGNORECASE | re.DOTALL,
    )
    _INSTALLED = True


install()
