import hostile_streak_engine as streaks

from conflict_rage_runtime import build_conflict_instruction


def setup_function():
    streaks.reset()


def test_second_text_attack_gets_counterattack_rage_floor():
    text = build_conflict_instruction(
        2,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )
    lowered = text.lower()
    assert "ACTIVE CONFLICT RAGE" in text
    assert "контратак" in lowered
    assert "дружище" in lowered
    assert "не угрожай" in lowered
    assert "защищён" in lowered
    assert "последнее слово" in lowered


def test_first_attack_is_hard_but_not_full_rage():
    text = build_conflict_instruction(
        1,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )
    assert "первый прямой наезд" in text
    assert "Полный контратакующий RAGE" in text
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


def test_hot_conflict_statement_does_not_restart_fight_but_stays_cold():
    text = build_conflict_instruction(
        3,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=False,
    )
    lowered = text.lower()
    assert "AFTERGLOW" in text
    assert "не начинай новый срач" in lowered
    assert "холодный" in lowered
    assert "колкий" in lowered
    assert "дружище" in lowered


def test_serious_topic_suppresses_rage_even_when_heat_is_high():
    assert build_conflict_instruction(
        4,
        current_mode="serious",
        media_kind="text",
        serious_topic=True,
        is_question=True,
    ) == ""


def test_second_voice_attack_is_conditionally_counterattack_rage_without_calling_it_hostile_first():
    text = build_conflict_instruction(
        1,
        current_mode="media_unknown",
        media_kind="voice_or_audio",
        serious_topic=False,
    )
    lowered = text.lower()
    assert "второй наезд" in text
    assert "если" in lowered
    assert "RAGE" in text
    assert "контратак" in lowered
    assert "нейтральное" in lowered


def test_hot_media_question_must_answer_and_end_with_sting():
    text = build_conflict_instruction(
        3,
        current_mode="media_unknown",
        media_kind="voice_or_audio",
        serious_topic=False,
    )
    assert "ОБЯЗАТЕЛЬНО ответь по существу" in text
    assert "последнее слово" in text
