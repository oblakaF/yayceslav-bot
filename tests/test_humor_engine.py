import humor_engine


def test_normalize_phrase_collapses_case_punct_and_yo():
    normalized = humor_engine.normalize_phrase("Ещё раз?! Точно...  Да!!")
    assert normalized == "еще раз точно да"


def test_is_too_similar_detects_near_duplicate():
    a = humor_engine.normalize_phrase("Сам сходи, раз маршрут так хорошо знаешь.")
    b = humor_engine.normalize_phrase("сам сходи раз маршрут так хорошо знаешь")
    assert humor_engine.is_too_similar(a, b) is True


def test_is_too_similar_false_for_different_phrases():
    a = humor_engine.normalize_phrase("Сам сходи, раз маршрут так хорошо знаешь.")
    b = humor_engine.normalize_phrase("Твой словарный запас кончился раньше уверенности.")
    assert humor_engine.is_too_similar(a, b) is False


def test_repetition_tracker_avoids_immediate_repeats():
    tracker = humor_engine.RepetitionTracker(maxlen=20)
    pool = ["Раз", "Два", "Три"]
    picks = [tracker.pick(1, "test", pool) for _ in range(3)]
    assert set(picks) == set(pool)


def test_repetition_tracker_prune_inactive_removes_stale_chat():
    tracker = humor_engine.RepetitionTracker(maxlen=5)
    tracker.record(42, "taunt", "тестовая фраза")

    removed = tracker.prune_inactive(max_age_seconds=-1)

    assert removed == [42]
    assert 42 not in tracker._history


def test_decide_humor_disabled_for_serious_topic():
    ctx = humor_engine.HumorContext(
        conversation_mode="normal",
        serious_topic=True,
    )
    decision = humor_engine.decide_humor(ctx, chat_id=1)
    assert decision.humor_allowed is False


def test_decide_humor_disabled_for_grieving_tone():
    ctx = humor_engine.HumorContext(
        conversation_mode="normal",
        emotional_tone="grieving",
    )
    decision = humor_engine.decide_humor(ctx, chat_id=2)
    assert decision.humor_allowed is False


def test_decide_humor_disabled_for_serious_response_style():
    ctx = humor_engine.HumorContext(
        conversation_mode="normal",
        response_style="serious",
    )
    decision = humor_engine.decide_humor(ctx, chat_id=3)
    assert decision.humor_allowed is False


def test_decide_humor_does_not_repeat_last_type_immediately(monkeypatch):
    monkeypatch.setattr(humor_engine.random, "random", lambda: 0.0)
    tracker = humor_engine.RepetitionTracker(maxlen=20)
    ctx = humor_engine.HumorContext(
        conversation_mode="normal",
        selected_character="professor",
    )

    first = humor_engine.decide_humor(ctx, chat_id=999, tracker=tracker)
    second = humor_engine.decide_humor(ctx, chat_id=999, tracker=tracker)

    assert first.humor_allowed and second.humor_allowed
    assert first.humor_type != second.humor_type


def test_professor_character_stays_within_dry_reflective_types(monkeypatch):
    monkeypatch.setattr(humor_engine.random, "random", lambda: 0.0)
    tracker = humor_engine.RepetitionTracker(maxlen=20)
    ctx = humor_engine.HumorContext(
        conversation_mode="normal",
        selected_character="professor",
    )

    seen_types = set()
    for i in range(10):
        decision = humor_engine.decide_humor(ctx, chat_id=3000 + i, tracker=tracker)
        assert decision.humor_allowed
        seen_types.add(decision.humor_type)

    assert seen_types <= set(
        humor_engine._CHARACTER_TYPE_FILTERS["professor"]
    )


def test_banter_not_triggered_for_third_party_insult():
    ctx = humor_engine.HumorContext(
        conversation_mode="normal",
        user_text="мой начальник мудак, как мне уволиться?",
    )
    decision = humor_engine.decide_banter(ctx, chat_id=1001)
    assert decision.humor_allowed is False


def test_banter_triggered_for_direct_insult():
    ctx = humor_engine.HumorContext(
        conversation_mode="hostile",
        user_text="ты мудак",
    )
    decision = humor_engine.decide_banter(ctx, chat_id=1002)
    assert decision.humor_allowed is True
    assert decision.humor_type == "banter_hostile"
    assert decision.selected_phrase is not None
    assert decision.comeback_strategy is not None


def test_banter_intensity_group_is_hard():
    ctx = humor_engine.HumorContext(
        conversation_mode="hostile",
        user_text="ты мудак",
        chat_type="group",
    )
    assert (
        humor_engine.estimate_banter_intensity(ctx)
        == humor_engine.BANTER_LEVEL_HARD
    )


def test_banter_intensity_low_roughness_is_light():
    ctx = humor_engine.HumorContext(
        conversation_mode="hostile",
        user_text="ты мудак",
        roughness="low",
    )
    assert (
        humor_engine.estimate_banter_intensity(ctx)
        == humor_engine.BANTER_LEVEL_LIGHT
    )


def test_banter_disabled_on_serious_topic():
    ctx = humor_engine.HumorContext(
        conversation_mode="hostile",
        user_text="ты мудак",
        serious_topic=True,
    )
    assert (
        humor_engine.estimate_banter_intensity(ctx)
        == humor_engine.BANTER_LEVEL_NONE
    )
    decision = humor_engine.decide_banter(ctx, chat_id=1003)
    assert decision.humor_allowed is False


def test_select_comeback_strategy_within_level_pool():
    strategy = humor_engine.select_comeback_strategy(
        humor_engine.BANTER_LEVEL_HARD
    )
    assert strategy in humor_engine.BANTER_STRATEGIES_BY_LEVEL[
        humor_engine.BANTER_LEVEL_HARD
    ]


def test_repeated_insult_gets_different_comebacks(monkeypatch):
    monkeypatch.setattr(humor_engine.random, "random", lambda: 0.99)
    tracker = humor_engine.RepetitionTracker(maxlen=20)
    ctx = humor_engine.HumorContext(
        conversation_mode="hostile",
        user_text="ты мудак",
        chat_type="group",
    )

    phrases = set()
    for _ in range(5):
        decision = humor_engine.decide_banter(ctx, chat_id=2000, tracker=tracker)
        phrases.add(decision.selected_phrase)

    assert len(phrases) == 5
