import random

import title_pools


def test_exactly_thirteen_title_personalities():
    assert set(title_pools.TITLE_POOLS) == {
        "classic",
        "youth",
        "skoof",
        "old_russian",
        "blat",
        "operative",
        "battle_2017",
        "post_irony",
        "runet_2007",
        "runet_2012_2016",
        "lan_2000s",
        "runet_classic",
        "street_memes",
    }


def test_each_personality_has_exactly_ten_titles():
    for personality, titles in title_pools.TITLE_POOLS.items():
        assert len(titles) == 10, personality
        assert len(titles) == len(set(titles)), personality


def test_all_titles_are_globally_unique_and_total_130():
    assert len(title_pools.ALL_TITLES) == 130
    assert len(title_pools.ALL_TITLES) == len(set(title_pools.ALL_TITLES))


def test_requested_blat_titles_exist():
    blat = title_pools.TITLE_POOLS["blat"]
    assert "Поц районный" in blat
    assert "Фраер ушастый" in blat
    assert "Смотрящий за чатом" in blat


def test_requested_operative_titles_exist():
    operative = title_pools.TITLE_POOLS["operative"]
    assert "Товарищ майор" in operative
    assert "Старший опер по мемам" in operative
    assert "Полковник переписки" in operative


def test_requested_street_meme_titles_exist():
    street = title_pools.TITLE_POOLS["street_memes"]
    for title in (
        "Скуф",
        "Шлюшка",
        "Танкист",
        "Задрот",
        "Алкашик",
        "Душнила",
    ):
        assert title in street


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
