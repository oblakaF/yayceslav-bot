import hostile_streak_engine
import conflict_rage_runtime


def test_second_hostile_turn_requires_active_counterattack():
    text = conflict_rage_runtime.build_conflict_instruction(
        hostile_streak_engine.HOSTILE_ESCALATION_FROM,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )

    lowered = text.lower()
    assert "контратак" in lowered
    assert "не просто отражает" in lowered
    assert "найди в них" in lowered
    assert "финал должен быть сильнее начала" in lowered
    assert "не придумывай биографические факты" in lowered


def test_first_attack_is_hard_but_not_full_war():
    text = conflict_rage_runtime.build_conflict_instruction(
        1,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )

    lowered = text.lower()
    assert "первый прямой наезд" in lowered
    assert "не разворачивай полноценную войну" in lowered


def test_hot_neutral_question_still_gets_useful_answer_plus_last_word():
    text = conflict_rage_runtime.build_conflict_instruction(
        hostile_streak_engine.HOSTILE_ESCALATION_FROM,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=True,
    )

    lowered = text.lower()
    assert "обязательно сначала нормально и по существу ответь" in lowered
    assert "ровно одну" in lowered
    assert "последнее слово остаётся за яйцеславом" in lowered


def test_serious_topic_suppresses_rage():
    assert conflict_rage_runtime.build_conflict_instruction(
        4,
        current_mode="serious",
        media_kind="text",
        serious_topic=True,
    ) == ""
