import vocabulary


def test_combined_lists_have_no_exact_duplicates():
    combined_lists = [
        vocabulary.SLANG_WORDS,
        vocabulary.ADDRESSES,
        vocabulary.TAUNTS,
        vocabulary.FLEX_PHRASES,
        vocabulary.ROUGH_WORDS,
    ]
    for values in combined_lists:
        assert len(values) == len(set(values))


def test_reply_pools_are_nonempty():
    pools = [
        vocabulary.SIX_SEVEN_REPLIES,
        vocabulary.GOY_REPLIES,
        vocabulary.NISHIY_REPLIES,
        vocabulary.SKUF_REPLIES,
        vocabulary.BASE_REPLIES,
        vocabulary.CRINGE_REPLIES,
        vocabulary.YAYCESLAV_REPLIES,
        vocabulary.HARD_RANDOM_REPLIES,
        vocabulary.ROASTS,
        vocabulary.WISDOMS,
        vocabulary.MOODS,
    ]
    for pool in pools:
        assert len(pool) > 0


def test_roasts_format_with_a_name():
    sample = vocabulary.ROASTS[0].format(name="Тест")
    assert "Тест" in sample
