import title_pools


def test_positive_title_pool_has_exactly_seven_mild_titles():
    assert title_pools.TITLE_POOLS["positive"] == (
        "Умничка",
        "Хороший мальчик",
        "Красавчик",
        "Молодец дня",
        "Золотой человек",
        "Надёжный человек",
        "Свой человек",
    )
    assert len(title_pools.TITLE_POOLS["positive"]) == 7


def test_positive_titles_are_part_of_active_title_set():
    for title in title_pools.TITLE_POOLS["positive"]:
        assert title in title_pools.ALL_TITLES
