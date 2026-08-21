# ============================================================
# YAICESLAV V2 TITLE POOLS
#
# Только утверждённые титулы. Размер категорий свободный:
# лучше меньше, но смешнее. Street Memes и Legendary хранятся
# отдельными пулами и не смешиваются с тематическими категориями.
# ============================================================

from __future__ import annotations

import random


TITLE_POOLS: dict[str, tuple[str, ...]] = {
    "classic": (
        "Почётный эксперт чата",
    ),
    "positive": (
        "Умничка",
        "Хороший мальчик",
        "Красавчик",
        "Молодец дня",
        "Золотой человек",
        "Надёжный человек",
        "Свой человек",
    ),
    "youth": (
        "Сигма на минималках",
        "NPC районного масштаба",
        "Тюбик в прайме",
        "Лорд минус-ауры",
        "Кринж-менеджер",
        "Повелитель рофла",
    ),
    "blat": (
        "Поц районный",
        "Фраер ушастый",
        "Кент без расклада",
        "Авторитет диванный",
        "Бродяга цифровой",
        "Смотрящий за чатом",
        "Решала без вопросов",
        "Пахан комментариев",
        "Барыга аргументов",
        "Мастер малявы",
    ),
    "operative": (
        "Товарищ майор",
    ),
    "absurd": (
        "Генеральный директор пиздеца",
        "Почётный безработный",
        "Человек с демоверсией мозга",
        "Лауреат премии «Ну и нахуй»",
        "Главный по хуете",
        "Временно исполняющий обязанности долбоёба",
        "Почётный член дивана",
        "Магистр проёбанного времени",
        "Начальник отдела «А мне похуй»",
        "Исполняющий обязанности легенды",
        "Командир последней извилины",
        "Почётный потребитель кислорода",
        "Первый заместитель хуй знает кого",
        "Председатель гаражного консилиума",
        "Советник при самом себе",
        "Лицо, принимающее решения наугад",
        "Специалист по созданию проблем из воздуха",
    ),
    "profane": (
        "Магистр ебанистики",
        "Почётный долбоёб района",
        "Старший специалист по пиздежу",
        "Временно исполняющий обязанности мудака",
        "Лауреат премии «Иди нахуй»",
        "Сертифицированный долбоёб",
        "Мудак Премиум",
        "Пиздец На Ножках",
        "Еблан Особого Назначения",
    ),
    "street_memes": (
        "Скуф",
        "Шлюшенция",
        "Танкист",
        "Задрот",
        "Алкашик",
        "Душнила",
        "Подкаблучник",
        "Куколдини",
        "Курва",
        "Бобр",
    ),
    "legendary": (
        "Звёздный Лорд",
        "Боба Фетт",
        "Абсолютный Скуф",
        "Владелец Последней Извилины",
        "Избранный Ящерами",
        "Сын Маминой Подруги: Final Form",
        "Верховный Куколдини",
        "Скуф Омега-Уровня",
        "Владелец Золотого Тюбика",
        "Космический Мусор",
        "Прометей без Факела",
        "Начальник Станции Крепёжной",
    ),
}


ALL_TITLES: tuple[str, ...] = tuple(
    title
    for pool in TITLE_POOLS.values()
    for title in pool
)


PERSONALITY_NAMES: tuple[str, ...] = tuple(TITLE_POOLS)


# Which tone a pool leans toward, so the daily title can follow how someone
# actually treats Yayceslav instead of being a pure coin flip. "classic" and
# "positive" are unambiguously wholesome; "absurd" and "profane" are
# insults/mockery; everything else is playful-neutral either way.
POOL_SENTIMENT: dict[str, str] = {
    "classic": "positive",
    "positive": "positive",
    "youth": "neutral",
    "blat": "neutral",
    "operative": "neutral",
    "absurd": "negative",
    "profane": "negative",
    "street_memes": "neutral",
    "legendary": "neutral",
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
    rng=random,
) -> str:
    """Сначала выбирает пул (в рамках тональности, если задана), затем титул."""

    pool_names = pools_for_tier(tier) if tier else tuple(TITLE_POOLS)

    eligible: list[tuple[str, tuple[str, ...]]] = []
    for personality in pool_names:
        pool = TITLE_POOLS[personality]
        candidates = tuple(
            title
            for title in pool
            if title != previous_title
        )
        if candidates:
            eligible.append((personality, candidates))

    if not eligible:
        # A tier can run dry (e.g. only one title left and it was
        # yesterday's) -- fall back to the full pool rather than repeat.
        if tier:
            return pick_title(previous_title, rng=rng)
        return rng.choice(ALL_TITLES)

    _personality, candidates = rng.choice(eligible)
    return rng.choice(candidates)
