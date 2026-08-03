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


def test_absurd_comparisons_reach_at_least_a_hundred_total():
    total = sum(len(v) for v in vocabulary.ABSURD_COMPARISONS.values())
    assert total >= 100


def test_absurd_comparisons_have_no_exact_duplicates_within_theme():
    for theme, comparisons in vocabulary.ABSURD_COMPARISONS.items():
        assert len(comparisons) == len(set(comparisons)), theme


def test_slang_2010s_and_2020s_do_not_overlap():
    overlap = set(vocabulary.SLANG_2010S) & set(vocabulary.SLANG_2020S)
    assert overlap == set()


def test_slang_2010s_and_2020s_have_no_internal_duplicates():
    assert len(vocabulary.SLANG_2010S) == len(set(vocabulary.SLANG_2010S))
    assert len(vocabulary.SLANG_2020S) == len(set(vocabulary.SLANG_2020S))


def test_russian_internet_classics_nonempty_and_distinct():
    assert len(vocabulary.RUSSIAN_INTERNET_CLASSICS) > 0
    assert len(vocabulary.RUSSIAN_INTERNET_CLASSICS) == len(
        set(vocabulary.RUSSIAN_INTERNET_CLASSICS)
    )


def test_old_russian_metaphors_nonempty_and_distinct():
    assert len(vocabulary.OLD_RUSSIAN_METAPHORS) > 0
    assert len(vocabulary.OLD_RUSSIAN_METAPHORS) == len(
        set(vocabulary.OLD_RUSSIAN_METAPHORS)
    )


def test_fun_command_pools_are_nonempty_and_distinct():
    pools = [
        vocabulary.JOKE_TITLES,
        vocabulary.TOASTS,
        vocabulary.PROPHECIES,
        vocabulary.EXCUSES,
    ]
    for pool in pools:
        assert len(pool) > 0
        assert len(pool) == len(set(pool))


def test_award_templates_cover_all_labels():
    assert vocabulary.AWARD_TEMPLATES.keys() == vocabulary.AWARD_LABELS.keys()


def test_award_templates_have_name_placeholder_and_no_duplicates():
    for key, templates in vocabulary.AWARD_TEMPLATES.items():
        assert len(templates) > 0, key
        assert len(templates) == len(set(templates)), key
        for template in templates:
            assert "{name}" in template, (key, template)


def test_popular_awards_have_at_least_fifteen_variants():
    popular_awards = (
        "chat_leader",
        "voice_leader",
        "wall_of_text",
        "bot_caller",
    )
    for key in popular_awards:
        assert len(vocabulary.AWARD_TEMPLATES[key]) >= 15, key
