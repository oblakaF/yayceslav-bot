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
    assert "финаль" in lowered


def test_first_attack_is_warning_not_full_rage():
    text = build_conflict_instruction(
        1,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )
    lowered = text.lower()
    assert "ACTIVE CONFLICT WARNING" in text
    assert "первый прямой наезд" in lowered
    assert "второй" in lowered
    assert "ACTIVE CONFLICT RAGE —" not in text


def test_hot_conflict_question_gets_answer_and_sting_without_cooling():
    text = build_conflict_instruction(
        3,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=True,
    )
    lowered = text.lower()
    assert "ANSWER-AND-STING" in text
    assert "обязательно" in lowered
    assert "по существу" in lowered
    assert "latch" in lowered
    assert "10 минут" in lowered


def test_hot_neutral_statement_stays_rage_latched_not_afterglow():
    text = build_conflict_instruction(
        3,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=False,
    )
    lowered = text.lower()
    assert "LATCH STILL ACTIVE" in text
    assert "afterglow" not in lowered
    assert "не возвращается" in lowered
    assert "10 минут" in lowered
    assert "не объявляй срач законченным" in lowered


def test_one_old_hit_plus_neutral_turn_does_not_create_rage():
    text = build_conflict_instruction(
        1,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=False,
    )
    assert text == ""


def test_serious_topic_suppresses_rage_even_when_heat_is_high():
    assert build_conflict_instruction(
        4,
        current_mode="serious",
        media_kind="text",
        serious_topic=True,
        is_question=True,
    ) == ""


def test_second_voice_attack_is_conditional_before_transcript_is_known():
    text = build_conflict_instruction(
        1,
        current_mode="media_unknown",
        media_kind="voice_or_audio",
        serious_topic=False,
    )
    lowered = text.lower()
    assert "WARNING" in text
    assert "второй наезд" in lowered
    assert "если" in lowered
    assert "нейтральное" in lowered


def test_hot_media_stays_latched_and_question_must_get_answer():
    text = build_conflict_instruction(
        3,
        current_mode="media_unknown",
        media_kind="voice_or_audio",
        serious_topic=False,
    )
    lowered = text.lower()
    assert "RAGE LATCH" in text
    assert "не сбрасывается" in lowered
    assert "10 минут" in lowered
    assert "выполни её по существу" in lowered
