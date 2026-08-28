import hostile_streak_engine as streaks

from conflict_rage_runtime import build_conflict_instruction


def setup_function():
    streaks.reset()


def test_second_text_attack_gets_rage_floor():
    text = build_conflict_instruction(
        2,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )
    assert "ACTIVE CONFLICT RAGE" in text
    assert "дружище" in text
    assert "Не угрожай" in text
    assert "защищённые" in text


def test_first_attack_is_hard_but_not_full_rage():
    text = build_conflict_instruction(
        1,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )
    assert "первый прямой наезд" in text
    assert "Полный RAGE" in text
    assert "ACTIVE CONFLICT RAGE —" not in text


def test_hot_conflict_question_gets_answer_and_sting():
    text = build_conflict_instruction(
        3,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=True,
    )
    assert "ANSWER-AND-STING" in text
    assert "ОБЯЗАТЕЛЬНО сначала нормально" in text
    assert "РОВНО ОДНУ" in text
    assert "последнее слово" in text
    assert "дружище" in text


def test_hot_conflict_statement_stays_cold_without_attacking_first():
    text = build_conflict_instruction(
        3,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=False,
    )
    assert "AFTERGLOW" in text
    assert "не нападай первым" in text
    assert "дружище" in text


def test_serious_topic_suppresses_rage_even_when_heat_is_high():
    assert build_conflict_instruction(
        4,
        current_mode="serious",
        media_kind="text",
        serious_topic=True,
        is_question=True,
    ) == ""


def test_second_voice_attack_is_conditionally_rage_without_calling_it_hostile_first():
    text = build_conflict_instruction(
        1,
        current_mode="media_unknown",
        media_kind="voice_or_audio",
        serious_topic=False,
    )
    assert "второй наезд" in text
    assert "если" in text.lower()
    assert "RAGE" in text
    assert "нейтральное" in text


def test_hot_media_question_must_answer_and_end_with_sting():
    text = build_conflict_instruction(
        3,
        current_mode="media_unknown",
        media_kind="voice_or_audio",
        serious_topic=False,
    )
    assert "ОБЯЗАТЕЛЬНО ответь по существу" in text
    assert "последнее слово" in text
