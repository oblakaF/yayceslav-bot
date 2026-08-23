"""Pure logic for the birthday calendar: parsing dates and picking a warm
congratulation. No I/O, no Telegram, no DB -- kept testable in isolation.

Congratulation text is a fixed template pool, not a live Gemini call:
unlike ordinary banter, a birthday message is sent once a year to a real
person and is far more visible/sensitive if it comes out off-tone, so
predictability wins over novelty here. Per the earlier decision that
neutral/positive registers use plain human language (see
yayceslav-aggression-rebalance memory), these are ordinary warm sentences,
not slang-styled.
"""

from __future__ import annotations

import random
import re
from datetime import date as date_type

_DATE_RE = re.compile(
    r"^\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/]\d{2,4})?\s*$"
)


def parse_date_arg(text: str) -> tuple[int, int] | None:
    """Parses "ДД.ММ" (year, if present, is accepted and ignored).

    Returns (day, month) or None if the text isn't a valid calendar date.
    """

    match = _DATE_RE.match(text)
    if not match:
        return None

    day, month = int(match.group(1)), int(match.group(2))
    try:
        # 2000 is a leap year, so Feb 29 validates correctly; the year
        # itself is never stored -- birthdays repeat every year.
        date_type(2000, month, day)
    except ValueError:
        return None

    return day, month


def is_birthday_today(day: int, month: int, today: date_type) -> bool:
    return today.day == day and today.month == month


CONGRATULATION_TEMPLATES: tuple[str, ...] = (
    "Сегодня день рождения у {name}! Пусть год будет добрым, а всё задуманное — получится. С праздником! 🎉",
    "{name}, с днём рождения! Здоровья, сил и побольше поводов для радости в этом году.",
    "Не могу не поздравить {name} с днём рождения — пусть этот год принесёт только хорошее. Обнимаю!",
    "Сегодня особенный день у {name}. С днём рождения! Пусть всё, что задумано, обязательно сбудется.",
    "{name}, поздравляю с днём рождения! Оставайся собой, а год пусть будет лёгким и удачным.",
)


def pick_congratulation(display_name: str, *, rng: random.Random | None = None) -> str:
    chooser = rng or random
    template = chooser.choice(CONGRATULATION_TEMPLATES)
    return template.format(name=display_name)
