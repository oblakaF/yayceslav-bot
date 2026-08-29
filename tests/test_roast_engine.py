from collections import deque

import roast_engine


def setup_function():
    roast_engine._SESSIONS.clear()


def test_repeated_sniff_theme_prefers_fixation_when_first_detected():
    first = roast_engine.observe_and_plan(1, 2, "хуй будешь нюхать?")
    second = roast_engine.observe_and_plan(1, 2, "ну че нюхал хуй?")

    assert first.angle != "fixation"
    assert second.angle == "fixation"
    assert second.callback


def test_fixation_rotates_away_on_immediate_followup():
    first = roast_engine.observe_and_plan(10, 20, "хуй будешь нюхать?")
    second = roast_engine.observe_and_plan(10, 20, "ну че нюхал хуй?")
    third = roast_engine.observe_and_plan(10, 20, "нюхай хуй дальше")
    fourth = roast_engine.observe_and_plan(10, 20, "опять нюхай хуй")

    assert second.angle == "fixation"
    assert third.angle != second.angle
    assert "fixation" in third.avoid
    assert first.angle != second.angle
    assert fourth.angle in roast_engine.roast_lexicon.ANGLE_LABELS


def test_failed_bait_is_detected():
    plan = roast_engine.observe_and_plan(3, 4, "ахах я тебя байтил и ты повелся")
    assert plan.angle == "failed_bait"


def test_empty_aggression_is_available_for_short_abuse():
    session = roast_engine._session(5, 6)
    session.used_angles = deque(["literal_flip"], maxlen=roast_engine.MAX_USED_ANGLES)
    plan = roast_engine.observe_and_plan(5, 6, "долбоеб хуесос нахуй")
    assert plan.angle == "empty_aggression"


def test_prompt_keeps_profanity_as_support_not_goal():
    plan = roast_engine.observe_and_plan(7, 8, "ты опять пиздабол")
    prompt = roast_engine.prompt_for_plan(plan)
    assert "Мат допустим" in prompt
    assert "0–2" in prompt
    assert "Не придумывай биографию" in prompt


def test_regression_repeated_sniff_fight_keeps_exact_recent_evidence():
    roast_engine.observe_and_plan(100, 77, "Хуй будешь нюхать?")
    plan = roast_engine.observe_and_plan(100, 77, "По факту метнулся к хую и нюхаешь")
    prompt = roast_engine.prompt_for_plan(plan)

    assert plan.angle == "fixation"
    assert "Хуй будешь нюхать?" in plan.evidence
    assert "метнулся к хую" in prompt
    assert "конкретное наблюдение" in prompt


def test_regression_bait_reveal_attacks_reveal_not_invented_biography():
    plan = roast_engine.observe_and_plan(101, 88, "Ахах, да я тебя просто байтил")
    prompt = roast_engine.prompt_for_plan(plan)

    assert plan.angle == "failed_bait"
    assert plan.evidence == ("Ахах, да я тебя просто байтил",)
    assert "самоподстав" in prompt
    assert "Не придумывай биографию" in prompt


def test_quality_prompt_rejects_stale_generic_roast_shortcuts():
    plan = roast_engine.observe_and_plan(102, 99, "Ну ты и залупа")
    prompt = roast_engine.prompt_for_plan(plan).lower()

    for stale in ("словарный запас", "детский сад", "цирк", "конструктив", "комплексы", "альфа-самца"):
        assert stale in prompt
    assert "придумай заново" in prompt
    assert "1–2 коротких предложения" in prompt


def test_evidence_window_is_bounded_to_four_unique_recent_lines():
    for idx in range(7):
        plan = roast_engine.observe_and_plan(103, 55, f"реплика номер {idx} про спор")

    assert len(plan.evidence) == 4
    assert plan.evidence[0].startswith("реплика номер 3")
    assert plan.evidence[-1].startswith("реплика номер 6")
