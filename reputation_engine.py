"""Deterministic lifetime reputation scoring for Yayceslav.

Reputation is not the same thing as familiarity or the 30-day positive-affinity
state. Every member starts at zero. Only messages actually directed at
Yayceslav can move the score, so unrelated group praise/abuse never changes the
relationship. One message produces at most one signed delta in [-10, 10].
"""

from __future__ import annotations

import re
from dataclasses import dataclass


MIN_REPUTATION = -100
MAX_REPUTATION = 100


# Strongest match wins. The values intentionally stay human-readable and
# deterministic instead of spending a Gemini call to judge every message.
_NEGATIVE_RULES: tuple[tuple[int, re.Pattern[str]], ...] = (
    (-10, re.compile(r"\b(?:я\s+тебя\s+обоссу|убью\s+тебя)\b", re.IGNORECASE)),
    (-9, re.compile(r"\b(?:пош[её]л\s+(?:ты\s+)?(?:нахуй|на\s+хуй)|иди\s+(?:ты\s+)?(?:нахуй|на\s+хуй)|соси)\b", re.IGNORECASE)),
    (-8, re.compile(r"\b(?:долбо[её]б\w*|еблан\w*|пиздабол\w*)\b", re.IGNORECASE)),
    (-7, re.compile(r"\b(?:мудак\w*|чмо|дебил\w*|идиот\w*)\b", re.IGNORECASE)),
    (-6, re.compile(r"\b(?:сука|сучка|урод\w*|кретин\w*)\b", re.IGNORECASE)),
    (-5, re.compile(r"\b(?:заебал\w*|заткнись|иди\s+(?:ты\s+)?(?:нахер|на\s+хер)|пош[её]л\s+(?:ты\s+)?(?:нахер|на\s+хер))\b", re.IGNORECASE)),
    (-3, re.compile(r"\b(?:отвали|достал\w*|иди\s+отсюда|нахер\s+тебя|на\s+хер\s+тебя)\b", re.IGNORECASE)),
    (-1, re.compile(r"\b(?:не\s+беси|отстань)\b", re.IGNORECASE)),
)

_POSITIVE_RULES: tuple[tuple[int, re.Pattern[str]], ...] = (
    (10, re.compile(r"\b(?:обожаю\s+тебя|мы\s+тебя\s+обожаем)\b", re.IGNORECASE)),
    (9, re.compile(r"\b(?:люблю\s+тебя|мы\s+тебя\s+любим|ты\s+лучший)\b", re.IGNORECASE)),
    (8, re.compile(r"\b(?:огромн\w*\s+спасибо|безумно\s+благодар\w*|очень\s+сильно\s+помог)\b", re.IGNORECASE)),
    (7, re.compile(r"\b(?:спасибо\s+огромн\w*|очень\s+помог|реально\s+выручил)\b", re.IGNORECASE)),
    (6, re.compile(r"\b(?:большое\s+спасибо|спасибо\s+большое|очень\s+благодар\w*)\b", re.IGNORECASE)),
    (5, re.compile(r"\b(?:красава|красавчик|молодец|респект|уважух\w*)\b", re.IGNORECASE)),
    (4, re.compile(r"\b(?:отличн\w+\s+сделал|хорошая\s+работа|классно\s+сделал)\b", re.IGNORECASE)),
    (3, re.compile(r"\b(?:спасибо|благодарю)\b", re.IGNORECASE)),
    (2, re.compile(r"\b(?:класс|круто|хорош)\b", re.IGNORECASE)),
    (1, re.compile(r"\bспс\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class ReputationDecision:
    delta: int = 0
    reason: str = "neutral"


def clamp_score(score: int) -> int:
    return max(MIN_REPUTATION, min(MAX_REPUTATION, int(score or 0)))


def reputation_label(score: int) -> str:
    value = clamp_score(score)
    if value <= -70:
        return "токсичный"
    if value <= -35:
        return "негативный"
    if value <= -10:
        return "настороженно"
    if value < 10:
        return "нейтрально"
    if value < 35:
        return "симпатия"
    if value < 70:
        return "хорошее отношение"
    return "очень свой"


def negative_delta(text: str) -> int:
    value = str(text or "")
    for delta, pattern in _NEGATIVE_RULES:
        if pattern.search(value):
            return delta
    return 0


def positive_delta(text: str) -> int:
    value = str(text or "")
    for delta, pattern in _POSITIVE_RULES:
        if pattern.search(value):
            return delta
    return 0


def score_message(
    text: str,
    *,
    directed_at_bot: bool,
    hostile_mode: bool = False,
) -> ReputationDecision:
    """Score one user message toward Yayceslav.

    Negative intent wins over praise in mixed messages such as
    "спасибо, мудак". `hostile_mode` is only a guard confirming that the
    existing conversation classifier also sees hostility; it never invents a
    delta when none of the explicit severity phrases matched.
    """
    if not directed_at_bot:
        return ReputationDecision()

    neg = negative_delta(text)
    if neg < 0:
        return ReputationDecision(delta=neg, reason="negative")

    pos = positive_delta(text)
    if pos > 0:
        return ReputationDecision(delta=pos, reason="positive")

    # A hostile classification without one of the explicit severity phrases is
    # intentionally not scored: reputation should be conservative, not guessy.
    if hostile_mode:
        return ReputationDecision()
    return ReputationDecision()
