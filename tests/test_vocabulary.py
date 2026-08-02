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


def test_banter_comeback_levels_are_nonempty_and_distinct():
    all_lines = []
    for level in (1, 2, 3):
        pool = vocabulary.BANTER_COMEBACKS_BY_LEVEL[level]
        assert len(pool) > 0
        all_lines.extend(pool)
    assert len(all_lines) == len(set(all_lines))


def test_self_irony_has_no_duplicates():
    assert len(vocabulary.SELF_IRONY) == len(set(vocabulary.SELF_IRONY))
    assert len(vocabulary.SELF_IRONY) > 0


def test_reaction_lines_cover_expected_categories():
    expected_categories = {
        "agreement",
        "doubt",
        "surprise",
        "disappointment",
        "approval",
        "observation",
        "soft_taunt",
        "admits_mistake",
    }
    assert expected_categories <= vocabulary.REACTION_LINES.keys()
    for lines in vocabulary.REACTION_LINES.values():
        assert len(lines) > 0


def test_absurd_comparisons_cover_expected_themes():
    expected_themes = {
        "техника",
        "работа",
        "учёба",
        "отношения",
        "интернет",
        "игры",
        "деньги",
        "бытовые ситуации",
        "программирование",
        "древнерусский быт",
    }
    assert expected_themes <= vocabulary.ABSURD_COMPARISONS.keys()
    for comparisons in vocabulary.ABSURD_COMPARISONS.values():
        assert len(comparisons) > 0
