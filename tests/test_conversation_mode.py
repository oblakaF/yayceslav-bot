import personality


def test_serious_topic_detection():
    assert personality.is_serious_text("умер родственник, что делать") is True
    assert personality.is_serious_text("какая сегодня погода") is False


def test_serious_has_priority_over_hostile():
    assert personality.detect_conversation_mode(
        "ты мудак, у меня только что умер родственник"
    ) == "serious"


def test_hostile_directed_at_bot():
    assert personality.detect_conversation_mode("ты мудак") == "hostile"
    assert personality.detect_conversation_mode(
        "Ты дебил, отвечаешь невпопад"
    ) == "hostile"


def test_hostile_not_triggered_for_third_party_insult():
    mode = personality.detect_conversation_mode(
        "мой начальник мудак, как мне уволиться?"
    )
    assert mode != "hostile"


def test_hostile_not_triggered_for_subject_criticism():
    mode = personality.detect_conversation_mode(
        "этот код мудацкий, помоги переписать"
    )
    assert mode != "hostile"


def test_challenge_mode():
    assert personality.detect_conversation_mode(
        "полегче, чего ты хамишь"
    ) == "challenge"


def test_greeting_mode():
    assert personality.detect_conversation_mode("привет, как дела?") == "greeting"


def test_normal_mode_default():
    assert personality.detect_conversation_mode("расскажи про питон") == "normal"


def test_database_question_is_not_serious_or_hostile():
    mode = personality.detect_conversation_mode(
        "какая сегодня база данных лучше?"
    )
    assert mode == "normal"
