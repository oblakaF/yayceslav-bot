"""Pure content pool for unprompted ("initiative") chat messages.

Matches the existing precedent (daily titles, jokes, news are all
templated/canned, never a fresh live Gemini call sent unprompted): this
is a static pool, optionally split by today's chat mood, never a network
call. Keeping it canned means Initiative costs nothing extra in API
calls or latency and stays predictable in tone.
"""

from __future__ import annotations

import random

INITIATIVE_LINE_POOL: dict[str, tuple[str, ...]] = {
    "раздражённый": (
        "Что-то тихо у вас. Кто-то опять затупил и стесняется признаться?",
        "Задолбали молчать, а ну кто-нибудь скажи что-то нормальное.",
    ),
    "благодушный": (
        "Заходил мимо — у вас тут неплохо сегодня. Продолжайте, не буду мешать.",
        "Сижу, никого не трогаю. Хорошего вам дня, шайтаны.",
    ),
    "циничный": (
        "Опять все молчат. Ну ладно, так даже спокойнее.",
        "Никто ничего интересного не пишет — как обычно, короче.",
    ),
    "энергичный": (
        "Ну что, кто первый начнёт движ сегодня?",
        "Скучно висите. Двигайтесь, у меня сегодня настроение есть.",
    ),
    "уставший": (
        "Устал сегодня что-то. Вы там сами разбирайтесь, я подремлю.",
        "Даже докапываться лень. Живите пока сами.",
    ),
    "подозрительный": (
        "Что-то подозрительно тихо. Признавайтесь, кто что натворил.",
        "Ловлю себя на мысли, что вы что-то замышляете без меня.",
    ),
    "мемный": (
        "Раз тишина — расскажу, что я думаю о половине из вас. Шутка. Или нет.",
        "Соскучился по вашему дурдому, го кто-нибудь напиши уже что-то смешное.",
    ),
    "нейтральный": (
        "Заглянул проверить, живы ли вы тут вообще.",
        "Тишина в чате. Ну и ладно, я подожду.",
    ),
    "generic": (
        "Здарова, я тут. Как жизнь у обитателей этого чата?",
        "Соскучился, если что. Не то чтобы сильно.",
        "Никто не звал, я сам пришёл. Что тут у вас происходит?",
    ),
}


def pick_initiative_line(mood_key: str | None, rng: random.Random | random) -> str:
    pool = INITIATIVE_LINE_POOL.get(str(mood_key or ""), INITIATIVE_LINE_POOL["generic"])
    return rng.choice(pool)
