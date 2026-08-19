import random

import positive_engine as positive


def test_praise_and_affection_only_count_when_directed_at_bot():
    assert positive.detect_event("красава", directed_at_bot=False) is None
    assert positive.detect_event("красава", directed_at_bot=True) == "praise"
    assert positive.detect_event("мы тебя любим", directed_at_bot=False) is None
    assert positive.detect_event("мы тебя любим", directed_at_bot=True) == "affection"


def test_user_success_support_and_result_are_real_positive_events():
    assert positive.detect_event("я сдал экзамен") == "achievement"
    assert positive.detect_event("меня взяли на работу") == "achievement"
    assert positive.detect_event("пожелай мне удачи, завтра экзамен") == "support"
    assert positive.detect_event("зацени, вот мой проект") == "show_result"


def test_reconciliation_requires_direction_and_context_flag():
    assert positive.detect_event("сорян", directed_at_bot=True) is None
    assert (
        positive.detect_event(
            "сорян",
            directed_at_bot=True,
            reconciliation=True,
        )
        == "reconciliation"
    )
    assert (
        positive.detect_event(
            "сорян",
            directed_at_bot=False,
            reconciliation=True,
        )
        is None
    )


def test_affinity_levels_are_separate_from_familiarity():
    assert positive.affinity_level(0) == 0
    assert positive.affinity_level(2) == 0
    assert positive.affinity_level(3) == 1
    assert positive.affinity_level(8) == 2
    assert positive.affinity_level(18) == 3
    assert positive.affinity_level(35) == 4


def test_spontaneous_warmth_is_rare_and_bounded():
    assert positive.spontaneous_warmth_probability(
        positive.PositiveState(affinity_points_30d=35, positive_streak=1)
    ) == 0.0
    chance = positive.spontaneous_warmth_probability(
        positive.PositiveState(affinity_points_30d=100, positive_streak=20)
    )
    assert 0.0 < chance <= 0.08


def test_hostility_suppresses_positive_event_and_spontaneous_warmth():
    state = positive.PositiveState(affinity_points_30d=35, positive_streak=8)
    decision = positive.decide(
        "мы тебя любим",
        state,
        directed_at_bot=True,
        hostile=True,
        rng=random.Random(1),
    )
    assert decision.event is None
    assert decision.allow_spontaneous_warmth is False
    assert decision.affinity_level == 4


def test_achievement_instruction_is_positive_but_not_sycophantic():
    state = positive.PositiveState(affinity_points_30d=9, positive_streak=3)
    decision = positive.decide(
        "я сдал экзамен",
        state,
        rng=random.Random(1),
    )
    text = positive.build_instruction(decision, state)
    assert "реальным успехом" in text
    assert "1–2 коротких" in text
    assert "Не хвали без реального повода" in text
    assert "не лизоблюдство" not in text  # level 2, not yet inner-circle warmth


def test_inner_circle_warmth_stays_bounded():
    state = positive.PositiveState(affinity_points_30d=40, positive_streak=5)
    decision = positive.decide("обычный вопрос", state, cooldown_ready=False)
    text = positive.build_instruction(decision, state)
    assert "очень свой" in text
    assert "не лизоблюдство" in text
