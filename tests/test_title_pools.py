import random

import title_pools


def test_active_title_categories_are_the_approved_compact_pools():
    assert set(title_pools.TITLE_POOLS) == {
        "classic",
        "youth",
        "blat",
        "operative",
        "absurd",
        "profane",
        "street_memes",
        "legendary",
        "positive",
    }


def test_each_active_title_pool_is_nonempty_and_unique():
    for personality, titles in title_pools.TITLE_POOLS.items():
        assert titles, personality
        assert len(titles) == len(set(titles)), personality


def test_all_approved_titles_are_globally_unique_and_total_73():
    assert len(title_pools.ALL_TITLES) == 73
    assert len(title_pools.ALL_TITLES) == len(set(title_pools.ALL_TITLES))


def test_requested_blat_titles_exist():
    blat = title_pools.TITLE_POOLS["blat"]
    assert "Поц районный" in blat
    assert "Фраер ушастый" in blat
    assert "Смотрящий за чатом" in blat


def test_compact_operative_pool_keeps_tovarish_major():
    assert title_pools.TITLE_POOLS["operative"] == ("Товарищ майор",)


def test_requested_street_meme_titles_exist():
    street = title_pools.TITLE_POOLS["street_memes"]
    for title in (
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
    ):
        assert title in street


def test_requested_legendary_examples_exist():
    legendary = title_pools.TITLE_POOLS["legendary"]
    for title in (
        "Звёздный Лорд",
        "Боба Фетт",
        "Абсолютный Скуф",
        "Избранный Ящерами",
        "Космический Мусор",
    ):
        assert title in legendary


def test_picker_never_repeats_previous_active_title():
    rng = random.Random(20260815)
    for previous in title_pools.ALL_TITLES[:40]:
        for _ in range(10):
            assert title_pools.pick_title(previous, rng=rng) != previous


def test_picker_accepts_legacy_title_from_database():
    legacy_title = "Позор дружины"
    result = title_pools.pick_title(legacy_title, rng=random.Random(7))
    assert result in title_pools.ALL_TITLES
    assert result != legacy_title


def test_every_pool_has_a_sentiment_tier():
    assert set(title_pools.POOL_SENTIMENT) == set(title_pools.TITLE_POOLS)
    assert set(title_pools.POOL_SENTIMENT.values()) == {"positive", "neutral", "negative"}


def test_tier_for_reputation_matches_score_bands():
    assert title_pools.tier_for_reputation(-100) == "negative"
    assert title_pools.tier_for_reputation(-26) == "negative"
    assert title_pools.tier_for_reputation(-25) == "neutral"
    assert title_pools.tier_for_reputation(0) == "neutral"
    assert title_pools.tier_for_reputation(25) == "neutral"
    assert title_pools.tier_for_reputation(26) == "positive"
    assert title_pools.tier_for_reputation(100) == "positive"


def test_picker_with_positive_tier_only_draws_from_positive_pools():
    rng = random.Random(1)
    positive_titles = {t for pool in ("classic", "positive") for t in title_pools.TITLE_POOLS[pool]}
    for _ in range(50):
        assert title_pools.pick_title(tier="positive", rng=rng) in positive_titles


def test_picker_with_negative_tier_only_draws_from_negative_pools():
    rng = random.Random(2)
    negative_titles = {t for pool in ("absurd", "profane") for t in title_pools.TITLE_POOLS[pool]}
    for _ in range(50):
        assert title_pools.pick_title(tier="negative", rng=rng) in negative_titles


def test_picker_with_neutral_tier_avoids_positive_and_negative_pools():
    rng = random.Random(3)
    off_limits = {
        t
        for pool in ("classic", "positive", "absurd", "profane")
        for t in title_pools.TITLE_POOLS[pool]
    }
    for _ in range(50):
        assert title_pools.pick_title(tier="neutral", rng=rng) not in off_limits
