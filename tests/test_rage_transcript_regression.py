import roast_engine


def setup_function():
    roast_engine._SESSIONS.clear()


def test_sniff_loop_uses_observed_words_without_inventing_biography():
    roast_engine.observe_and_plan(100, 7, "Хуй будешь нюхать?")
    plan = roast_engine.observe_and_plan(100, 7, "По факту метнулся к хую и нюхаешь")
    prompt = roast_engine.prompt_for_plan(plan).lower()

    assert plan.angle == "fixation"
    assert any("нюх" in line.lower() or "хую" in line.lower() for line in plan.evidence)
    assert "не придумывай биографию" in prompt
    assert "наблюдаем" in prompt
    assert "что человек сам написал" in prompt or "сам написал" in prompt


def test_bait_reveal_is_an_attack_angle_not_a_new_fact():
    plan = roast_engine.observe_and_plan(101, 8, "ахах я тебя байтил, фотка двухнедельной давности")
    prompt = roast_engine.prompt_for_plan(plan)

    assert plan.angle == "failed_bait"
    assert "байт" in plan.weak_point
    assert "Не придумывай биографию" in prompt


def test_evidence_window_is_bounded_and_recent():
    for index in range(8):
        plan = roast_engine.observe_and_plan(102, 9, f"реплика номер {index} про спор")

    assert len(plan.evidence) == 4
    assert plan.evidence[0].startswith("реплика номер 4")
    assert plan.evidence[-1].startswith("реплика номер 7")


def test_prompt_rejects_stale_meta_roast_shortcuts():
    plan = roast_engine.observe_and_plan(103, 10, "ты опять пиздабол")
    prompt = roast_engine.prompt_for_plan(plan).lower()

    for stale in ("словарный запас", "детский сад", "цирк", "комплексы", "альфа-самца"):
        assert stale in prompt
    assert "придумай заново" in prompt
    assert "1–2 коротких предложения" in prompt


def test_angle_rotation_survives_quality_v2_evidence():
    first = roast_engine.observe_and_plan(104, 11, "хуй будешь нюхать?")
    second = roast_engine.observe_and_plan(104, 11, "ну че нюхал хуй?")
    third = roast_engine.observe_and_plan(104, 11, "нюхай хуй дальше")

    assert first.angle != "fixation"
    assert second.angle == "fixation"
    assert third.angle != second.angle
    assert "fixation" in third.avoid
