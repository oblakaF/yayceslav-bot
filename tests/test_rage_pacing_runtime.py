import types

import rage_pacing_runtime as pacing


def setup_function():
    pacing._STATES.clear()


def test_followup_requires_grounded_callback():
    assert pacing.followup_line("") == ""
    line = pacing.followup_line("пиздабол")
    assert "пиздабол" in line.lower()


def test_sensitive_topic_never_double_punches(monkeypatch):
    monkeypatch.setattr(pacing, "_is_rage", lambda *_: True)
    monkeypatch.setattr(pacing.hostile_streak_engine, "current", lambda *args, **kwargs: 99)
    assert not pacing.should_double_punch(-100, 7, "собака умерла вчера", now=100.0)


def test_outside_rage_never_double_punches(monkeypatch):
    monkeypatch.setattr(pacing, "_is_rage", lambda *_: False)
    monkeypatch.setattr(pacing.hostile_streak_engine, "current", lambda *args, **kwargs: 99)
    assert not pacing.should_double_punch(-100, 7, "пиздабол опять", now=100.0)


def test_requires_strong_heat(monkeypatch):
    monkeypatch.setattr(pacing, "_is_rage", lambda *_: True)
    monkeypatch.setattr(
        pacing.hostile_streak_engine,
        "current",
        lambda *args, **kwargs: pacing.DOUBLE_PUNCH_MIN_HEAT - 1,
    )
    assert not pacing.should_double_punch(-100, 7, "пиздабол опять", now=100.0)


def test_one_shot_per_session(monkeypatch):
    monkeypatch.setattr(pacing, "_is_rage", lambda *_: True)
    monkeypatch.setattr(pacing.hostile_streak_engine, "current", lambda *args, **kwargs: 99)
    assert pacing.should_double_punch(-100, 7, "пиздабол опять", now=100.0)
    pacing._state(-100, 7, 100.0).fired = True
    assert not pacing.should_double_punch(-100, 7, "пиздабол опять", now=101.0)


def test_session_expiry_allows_new_double_punch(monkeypatch):
    monkeypatch.setattr(pacing, "_is_rage", lambda *_: True)
    monkeypatch.setattr(pacing.hostile_streak_engine, "current", lambda *args, **kwargs: 99)
    old = pacing._state(-100, 7, 100.0)
    old.fired = True
    later = 100.0 + pacing.DOUBLE_PUNCH_SESSION_SECONDS + 1.0
    assert pacing.should_double_punch(-100, 7, "пиздабол опять", now=later)
    assert pacing._STATES[(-100, 7)] is not old


def test_callback_comes_from_repeated_target_authored_fight_text(monkeypatch):
    import fight_routing_v3 as v3

    state = v3.AfterburnerState(
        chat_id=-100,
        user_id=7,
        fight_texts=["пиздабол опять", "ну ты пиздабол"],
    )
    monkeypatch.setitem(v3._AFTERBURNER_STATES, (-100, 7), state)
    assert pacing._callback_from_live_fight(-100, 7, "пиздабол и всё").lower() == "пиздабол"
