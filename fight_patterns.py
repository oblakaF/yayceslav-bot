"""Declarative live-language patterns used by Fight Routing v3.

This module is the single source of truth for fight/bait regexes. It contains
no runtime installation side effects and does not mutate another module at
import time.
"""

from __future__ import annotations

import re


# Keep this deliberately narrower than a generic profanity detector. These are
# direct attacks/bait patterns that should extend the production conflict FSM
# through fight_routing_v3._patch_conflict_detector().
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
    r"\bотчество\s+нюх\b|"

    # Orphan-branch recovery (fix/conflict-detection-lazy-gate): direct strong
    # insults that were useful in the old classifier but were not all present
    # in the later conflict FSM lexicon. They are recovered here instead of
    # reviving the old personality/humanizer monkey-patch.
    r"^\s*(?:"
    r"ублюд\w*|падл\w*|сволоч\w*|говнюк\w*|говноед\w*|"
    r"идиот\w*|кретин\w*|придур\w*|недоум\w*|имбецил\w*|"
    r"тупорыл\w*|шавк\w*|отъеб\w*|съеб\w*"
    r")\s*[!?.]*\s*$|"
    r"\b(?:завали|закрой)\s+ебало\b|"
    r"\bебало\s+(?:завали|закрой)\b|"
    r"\bхуй\s+соси\b|"
    r"\b(?:иди|пош[её]л)\s+в\s+пизду\b|"

    # Ambiguous nouns only count when clearly directed, or when the whole
    # message is the insult. This preserves ordinary sentences such as
    # "у меня собака заболела" and "в цирке выступает клоун".
    r"\b(?:ты|тебя|тебе|твой|твоя|тво[её]|твои)\b.{0,28}\b(?:"
    r"клоун\w*|баран\w*|ос[её]л\w*|коз[её]л\w*|собак\w*|"
    r"крыс\w*|свин\w*|обезьян\w*|скуф\w*|бомж\w*|"
    r"нищ\w*|позорищ\w*|ничтож\w*|жалк\w*|никч[её]мн\w*|тормоз\w*"
    r")\b|"
    r"\b(?:"
    r"клоун\w*|баран\w*|ос[её]л\w*|коз[её]л\w*|собак\w*|"
    r"крыс\w*|свин\w*|обезьян\w*|скуф\w*|бомж\w*|"
    r"нищ\w*|позорищ\w*|ничтож\w*|жалк\w*|никч[её]мн\w*|тормоз\w*"
    r")\b.{0,20}\b(?:ты|тебя|тебе)\b|"
    r"^\s*(?:"
    r"клоун\w*|баран\w*|ос[её]л\w*|коз[её]л\w*|собак\w*|"
    r"крыс\w*|свин\w*|обезьян\w*|скуф\w*|бомж\w*|"
    r"нищ\w*|позорищ\w*|ничтож\w*|жалк\w*|никч[её]мн\w*|тормоз\w*"
    r")\s*[!?.]*\s*$"
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
