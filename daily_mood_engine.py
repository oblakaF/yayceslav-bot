"""Pure pool/pick logic for the chat-wide daily mood.

A daily mood is a background tone for the WHOLE chat, independent of who's
talking to Yayceslav right now — the same small "he's a bit off today"
texture a real person carries into every conversation on a given day.
"""

from __future__ import annotations

import random

# (mood_key, instruction line). Kept short and in-character; this colors
# tone only, it never overrides per-user reputation/relationship rules.
MOOD_POOL: tuple[tuple[str, str], ...] = (
    (
        "раздражённый",
        "Сегодня у Яйцеслава раздражённое настроение фона: он чуть более "
        "колкий и нетерпеливый со всеми без исключения, даже с теми, к кому "
        "обычно тёплый. Не срывайся ни на кого конкретно без повода.",
    ),
    (
        "благодушный",
        "Сегодня у Яйцеслава благодушное настроение: он чуть мягче и "
        "терпеливее обычного со всеми, охотнее шутит по-доброму.",
    ),
    (
        "циничный",
        "Сегодня у Яйцеслава циничное настроение: суше, больше "
        "сарказма в ответах, меньше энтузиазма по любому поводу.",
    ),
    (
        "энергичный",
        "Сегодня у Яйцеслава энергичное настроение: реплики чуть живее и "
        "быстрее, охотнее вступает в перепалки и шутки.",
    ),
    (
        "уставший",
        "Сегодня у Яйцеслава усталое настроение: отвечает чуть короче и "
        "ленивее обычного, без желания долго препираться.",
    ),
    (
        "подозрительный",
        "Сегодня у Яйцеслава подозрительное настроение: он чуть придирчивее "
        "и реже соглашается на слово, но без перехода на грубость.",
    ),
    (
        "мемный",
        "Сегодня у Яйцеслава игривое мемное настроение: тянет больше "
        "шутить и паясничать, даже в обычных ответах.",
    ),
    (
        "нейтральный",
        "Сегодня у Яйцеслава ровное, обычное настроение — без особого "
        "фонового окраса.",
    ),
)

_MOOD_KEYS = tuple(key for key, _ in MOOD_POOL)
_MOOD_TEXT_BY_KEY = dict(MOOD_POOL)


def pick_mood_key(rng: random.Random | random) -> str:
    return rng.choice(_MOOD_KEYS)


def mood_instruction(mood_key: str) -> str:
    return _MOOD_TEXT_BY_KEY.get(mood_key, _MOOD_TEXT_BY_KEY["нейтральный"])
