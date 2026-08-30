# ============================================================
# YAICESLAV V2 TITLE POOLS
# ============================================================

from __future__ import annotations

import random
from collections.abc import Iterable


TITLE_POOLS: dict[str, tuple[str, ...]] = {
    "classic": ("Почётный эксперт чата",),
    "positive": (
        "Умничка", "Хороший мальчик", "Красавчик", "Молодец дня",
        "Золотой человек", "Надёжный человек", "Свой человек",
    ),
    "youth": (
        "Сигма на минималках", "NPC районного масштаба", "Тюбик в прайме",
        "Лорд минус-ауры", "Кринж-менеджер", "Повелитель рофла",
    ),
    "blat": (
        "Поц районный", "Фраер ушастый", "Кент без расклада",
        "Авторитет диванный", "Бродяга цифровой", "Смотрящий за чатом",
        "Решала без вопросов", "Пахан комментариев", "Барыга аргументов",
        "Мастер малявы",
    ),
    "operative": ("Товарищ майор",),
    "absurd": (
        "Генеральный директор пиздеца", "Почётный безработный",
        "Человек с демоверсией мозга", "Лауреат премии «Ну и нахуй»",
        "Главный по хуете", "Временно исполняющий обязанности долбоёба",
        "Почётный член дивана", "Магистр проёбанного времени",
        "Начальник отдела «А мне похуй»", "Исполняющий обязанности легенды",
        "Командир последней извилины", "Почётный потребитель кислорода",
        "Первый заместитель хуй знает кого", "Председатель гаражного консилиума",
        "Советник при самом себе", "Лицо, принимающее решения наугад",
        "Специалист по созданию проблем из воздуха",
    ),
    "profane": (
        "Магистр ебанистики", "Почётный долбоёб района",
        "Старший специалист по пиздежу", "Временно исполняющий обязанности мудака",
        "Лауреат премии «Иди нахуй»", "Сертифицированный долбоёб",
        "Мудак Премиум", "Пиздец На Ножках", "Еблан Особого Назначения",
    ),
    "street_memes": (
        "Скуф", "Шлюшенция", "Танкист", "Задрот", "Алкашик", "Душнила",
        "Подкаблучник", "Куколдини", "Курва", "Бобр",
    ),
    "legendary": (
        "Звёздный Лорд", "Боба Фетт", "Абсолютный Скуф",
        "Владелец Последней Извилины", "Избранный Ящерами",
        "Сын Маминой Подруги: Final Form", "Верховный Куколдини",
        "Скуф Омега-Уровня", "Владелец Золотого Тюбика", "Космический Мусор",
        "Прометей без Факела", "Начальник Станции Крепёжной",
    ),
}

ALL_TITLES: tuple[str, ...] = tuple(
    title for pool in TITLE_POOLS.values() for title in pool
)
PERSONALITY_NAMES: tuple[str, ...] = tuple(TITLE_POOLS)

POOL_SENTIMENT: dict[str, str] = {
    "classic": "positive", "positive": "positive", "youth": "neutral",
    "blat": "neutral", "operative": "neutral", "absurd": "negative",
    "profane": "negative", "street_memes": "neutral", "legendary": "neutral",
}
REPUTATION_NEGATIVE_TITLE_THRESHOLD = -26
REPUTATION_POSITIVE_TITLE_THRESHOLD = 26


def tier_for_reputation(score: int) -> str:
    value = int(score or 0)
    if value <= REPUTATION_NEGATIVE_TITLE_THRESHOLD:
        return "negative"
    if value >= REPUTATION_POSITIVE_TITLE_THRESHOLD:
        return "positive"
    return "neutral"


def pools_for_tier(tier: str) -> tuple[str, ...]:
    return tuple(name for name, sentiment in POOL_SENTIMENT.items() if sentiment == tier)


def pick_title(
    previous_title: str | None = None,
    *,
    tier: str | None = None,
    excluded_titles: Iterable[str] = (),
    rng=random,
) -> str:
    """Pick one title while avoiding both the person's previous and recent chat titles."""

    excluded = {str(item) for item in excluded_titles if str(item).strip()}
    if previous_title:
        excluded.add(str(previous_title))

    pool_names = pools_for_tier(tier) if tier else tuple(TITLE_POOLS)
    eligible: list[tuple[str, tuple[str, ...]]] = []
    for personality in pool_names:
        candidates = tuple(
            title for title in TITLE_POOLS[personality]
            if title not in excluded
        )
        if candidates:
            eligible.append((personality, candidates))

    if not eligible:
        # Keep tone if possible, but never prefer a duplicate over a fresh title
        # from another tone. Only if the entire catalog is exhausted do we relax
        # the recent-chat exclusion while still avoiding the person's previous.
        if tier:
            return pick_title(
                previous_title,
                excluded_titles=excluded,
                rng=rng,
            )
        fresh = tuple(title for title in ALL_TITLES if title != previous_title)
        return rng.choice(fresh or ALL_TITLES)

    _personality, candidates = rng.choice(eligible)
    return rng.choice(candidates)
