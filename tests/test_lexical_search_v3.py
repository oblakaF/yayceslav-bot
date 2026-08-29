import lexical_search_v3 as lexical


def test_explicit_unknown_word_becomes_concrete_search_query():
    assert (
        lexical.definition_search_query("проверь значение слова гумыза со ссылками")
        == "значение слова гумыза"
    )


def test_anaphoric_definition_followup_reuses_previous_topic():
    assert lexical.definition_search_query(
        "проверь значение слова, вместе со ссылками на источники"
    ) == ""


def test_unrelated_check_is_left_to_existing_search_router():
    assert lexical.definition_search_query("проверь концерт Б.А.У. в Саратове") is None


def test_plain_definition_without_search_verb_is_not_forced_to_web():
    assert lexical.definition_search_query("что значит гумыза?") is None
