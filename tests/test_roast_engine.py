from collections import deque

import roast_engine


def setup_function():
    roast_engine._SESSIONS.clear()


def test_repeated_sniff_theme_prefers_fixation():
    roast_engine.observe_and_plan(1, 2, "хуй будешь нюхать?")
    roast_engine.observe_and_plan(1, 2, "ну че нюхал хуй?")
    plan = roast_engine.observe_and_plan(1, 2, "нюхай хуй дальше")
    assert plan.angle == "fixation"
    assert plan.callback


def test_angle_does_not_repeat_immediately():
    first = roast_engine.observe_and_plan(10, 20, "хуй будешь нюхать?")
    second = roast_engine.observe_and_plan(10, 20, "ну че нюхал хуй?")
    third = roast_engine.observe_and_plan(10, 20, "нюхай хуй дальше")
    fourth = roast_engine.observe_and_plan(10, 20, "опять нюхай хуй")
    assert third.angle == "fixation"
    assert fourth.angle != third.angle
    assert first.angle != second.angle or second.angle != third.angle


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
