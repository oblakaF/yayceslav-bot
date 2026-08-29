"""Declarative live-language patterns used by Fight Routing v3.

This module is the single source of truth for fight/bait regexes. It contains
no runtime installation side effects and does not mutate another module at
import time.
"""

from __future__ import annotations

import re


EXTRA_FIGHT_RE = re.compile(
    r"(?:"
    r"\b(?:ну\s+)?ты\s+(?:и\s+)?(?:залупа|пиздабол|хуесос|у[её]бан|долбо[её]б|мудак|чмо|гумыза)\w*\b|"
    r"\b(?:ху[йя])\s+(?:будешь\s+)?нюхать\b|"
    r"\bнюхал\s+ху[йя]\b|"
    r"\bметнул(?:ся|ась)\s+к\s+ху(?:ю|я|й)\b(?:.{0,24}\bнюх\w*)?|"
    r"\b(?:нюхай|нюхать)\s+ху[йя]\b|"
    r"\bты\s+нарываешься\b|"
    r"\bне\s+указывай\s+мне\s+что\s+делать\b.{0,80}\bместо\s+яйцеслава\b|"
    r"\bпапа\s+в\s+прайме\b|"
    r"\bотчество\s+нюх\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)


BAIT_REVEAL_RE = re.compile(
    r"(?:"
    r"\b(?:байт|байтил|байтила|разв[её]л|развела|наебал|наебала|на[её]бка)\b|"
    r"\b(?:шутил|шутила|пошутил|пошутила|прикалывался|прикалывалась)\b|"
    r"\bфотк\w*\s+.{0,24}\b(?:недел|месяц|год)\w*\s+назад\b|"
    r"\bфотк\w*.{0,64}\b(?:давност\w*|назад)\b|"
    r"\bна\s+самом\s+деле\b.{0,50}\b(?:жив|норм|не\s+умер|не\s+было)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
