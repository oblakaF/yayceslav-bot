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
    assert "не защищайся пассивно" in lowered
    assert "реально видим" in lowered
    assert "финальная фраза" in lowered
    assert "не объявляй диалог оконченным" in lowered


def test_first_attack_is_warning_not_full_war():
    text = conflict_rage_runtime.build_conflict_instruction(
        1,
        current_mode="hostile",
        media_kind="text",
        serious_topic=False,
    )

    lowered = text.lower()
    assert "первый прямой наезд" in lowered
    assert "не устраивай полноценную войну" in lowered
    assert "второй прямой наезд" in lowered


def test_hot_neutral_question_still_gets_useful_answer_plus_last_word():
    text = conflict_rage_runtime.build_conflict_instruction(
        hostile_streak_engine.HOSTILE_ESCALATION_FROM,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
        is_question=True,
    )

    lowered = text.lower()
    assert "обязательно" in lowered
    assert "по существу" in lowered
    assert "закончи одной короткой жёсткой осадкой" in lowered
    assert "latch остаётся активным" in lowered


def test_hot_neutral_statement_does_not_restore_normal_relationship_tone():
    text = conflict_rage_runtime.build_conflict_instruction(
        hostile_streak_engine.HOSTILE_ESCALATION_FROM,
        current_mode="normal",
        media_kind="text",
        serious_topic=False,
    )
    lowered = text.lower()
    assert "latch still active" in lowered
    assert "normal relationship baseline" in lowered
    assert "10 минут" in lowered


def test_serious_topic_suppresses_rage():
    assert conflict_rage_runtime.build_conflict_instruction(
        4,
        current_mode="serious",
        media_kind="text",
        serious_topic=True,
    ) == ""
