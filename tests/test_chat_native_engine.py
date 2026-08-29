import chat_native_engine


def test_extracts_local_words_and_phrases_without_raw_identifiers():
    terms = set(
        chat_native_engine.extract_candidate_terms(
            "@vasya минус аура, опять палтуса принесли https://example.com /week"
        )
    )
    assert "минус аура" in terms
    assert "палтуса" in terms
    assert all("vasya" not in term for term in terms)
    assert all("http" not in term for term in terms)
    assert all("week" not in term for term in terms)


def test_bigram_is_dropped_when_either_word_is_a_stopword():
    # Regression: "тоже" is a stopword but "пройдено" isn't, so the old
    # "skip only if BOTH are stopwords" rule let this noise phrase through
    # and it ended up shown as a whoami "monthly theme".
    terms = set(
        chat_native_engine.extract_candidate_terms("уровень тоже пройдено вчера")
    )
    assert "тоже пройдено" not in terms
    assert "уровень" in terms
    assert "пройдено" in terms


def test_compile_requires_repeat_and_multiple_people():
    selected = chat_native_engine.compile_profile_terms(
        [
            ("минус аура", 8, 4),
            ("палтуса", 7, 3),
            ("одиночный мем", 20, 1),
            ("редкость", 2, 5),
        ]
    )
    assert "минус аура" in selected
    assert "палтуса" in selected
    assert "одиночный мем" not in selected
    assert "редкость" not in selected


def test_chat_native_instruction_is_exclusive_pack():
    instruction = chat_native_engine.build_pack_instruction(
        ("минус аура", "палтуса"),
        conversation_mode="normal",
        roughness="high",
    )
    assert "Речевой пакет этого ответа: chat_native" in instruction
    assert "Не смешивай" in instruction
    assert "минус аура" in instruction
