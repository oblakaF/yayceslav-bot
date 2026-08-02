import intent


def test_insult_directed_at_bot_is_high_confidence():
    result_intent, confidence = intent.classify_intent("ты мудак")
    assert result_intent == "insult_directed_at_bot"
    assert confidence == intent.HIGH


def test_third_party_complaint_with_question_gets_help_not_hostility():
    result_intent, confidence = intent.classify_intent(
        "мой начальник мудак, как мне уволиться?"
    )
    assert result_intent != "insult_directed_at_bot"
    assert result_intent in ("technical_help", "recommendation", "question")
    assert confidence == intent.HIGH


def test_criticism_of_a_thing_is_not_third_party_insult():
    result_intent, _ = intent.classify_intent("этот код мудацкий, помоги переписать")
    assert result_intent != "insult_about_third_party"
    assert result_intent != "insult_directed_at_bot"


def test_plain_third_party_insult_without_question():
    result_intent, confidence = intent.classify_intent(
        "мой сосед редкостный мудак если честно"
    )
    assert result_intent == "insult_about_third_party"
    assert confidence == intent.MEDIUM


def test_serious_topic_overrides_everything_else():
    result_intent, confidence = intent.classify_intent(
        "врач сказал у меня серьёзная болезнь, что делать"
    )
    assert result_intent == "serious_issue"
    assert confidence == intent.HIGH


def test_greeting_detected():
    result_intent, _ = intent.classify_intent("привет, как дела?")
    assert result_intent == "greeting"


def test_low_confidence_falls_back_gracefully():
    result_intent, confidence = intent.classify_intent("...")
    assert confidence == intent.LOW


def test_empty_text_is_unknown_low_confidence():
    result_intent, confidence = intent.classify_intent("")
    assert result_intent == "unknown"
    assert confidence == intent.LOW


def test_database_question_is_a_question_not_a_hard_trigger():
    result_intent, _ = intent.classify_intent("какая сегодня база данных лучше?")
    assert result_intent == "question"


def test_grieving_tone_detected_and_suppresses_humor():
    tone = intent.detect_emotional_tone("умер родственник, что делать")
    assert tone == "grieving"
    assert intent.humor_allowed_for_tone(tone) is False


def test_anxious_tone_detected_and_suppresses_humor():
    tone = intent.detect_emotional_tone("не хочу жить, всё плохо")
    assert tone == "anxious"
    assert intent.humor_allowed_for_tone(tone) is False


def test_neutral_tone_allows_humor():
    tone = intent.detect_emotional_tone("расскажи анекдот про питон")
    assert tone == "neutral"
    assert intent.humor_allowed_for_tone(tone) is True


def test_joking_tone_from_laugh_markers():
    tone = intent.detect_emotional_tone("ахахах ну ты и придумал")
    assert tone == "joking"
