import fight_memory_afterburner_v2 as memory
import fight_sticker_budget as sticker_budget
import rage_pacing_runtime as pacing
import roast_engine


def setup_function():
    roast_engine._SESSIONS.clear()
    pacing._STATES.clear()
    sticker_budget.reset()


def test_long_fight_rotates_attack_angles_and_keeps_recent_evidence():
    turns = (
        "хуй будешь нюхать?",
        "ну че, опять нюхал хуй?",
        "пиздабол, нюхай хуй дальше",
        "ахах я тебя байтил, фотка двухнедельной давности",
        "ты опять пиздабол и всё",
        "ну ты клоун конечно",
        "пиздабол, уже третий круг пошел",
        "ты сам себя поймал и опять выкручиваешься",
    )

    plans = [roast_engine.observe_and_plan(-100, 7, turn) for turn in turns]
    angles = [plan.angle for plan in plans]

    assert all(left != right for left, right in zip(angles, angles[1:]))
    assert any(plan.callback for plan in plans[2:])
    assert all(len(plan.evidence) <= 4 for plan in plans)
    assert plans[-1].evidence[-1] == turns[-1]
    assert len(roast_engine._SESSIONS[(-100, 7)].messages) <= roast_engine.MAX_HISTORY


def test_sensitive_bait_never_becomes_callback_material():
    texts = [
        "собака умерла вчера",
        "ты опять пиздабол",
        "пиздабол, повторяю",
        "ахах это был байт, фотка старая",
    ]

    safe = memory.safe_fight_texts(texts)
    callback = memory.callback_token(texts)

    assert all("умер" not in line.lower() for line in safe)
    assert callback.lower() == "пиздабол"
    assert memory.fight_event(texts) == "bait_reveal"


def test_one_double_punch_per_hot_session_then_reconciliation_stops_it(monkeypatch):
    monkeypatch.setattr(pacing, "_is_rage", lambda *_: True)
    monkeypatch.setattr(pacing.hostile_streak_engine, "current", lambda *args, **kwargs: 99)

    assert pacing.should_double_punch(-100, 7, "пиздабол опять", now=100.0)
    state = pacing._state(-100, 7, 100.0)
    state.fired = True

    for index, turn in enumerate(
        (
            "ну ты пиздабол",
            "пиздабол и всё",
            "опять пиздабол",
            "ты клоун",
        ),
        start=1,
    ):
        assert not pacing.should_double_punch(-100, 7, turn, now=100.0 + index)

    assert not pacing.should_double_punch(-100, 7, "сорян, давай без срача", now=110.0)


def test_pending_double_punch_can_be_cancelled_before_it_fires():
    class FakeTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    task = FakeTask()
    state = pacing._state(-100, 7, 100.0)
    state.task = task

    pacing._cancel(-100, 7)

    assert task.cancelled is True
    assert (-100, 7) not in pacing._STATES


def test_long_chat_has_at_most_two_fight_stickers_even_with_two_targets():
    first = 100.0
    second = first + sticker_budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0
    third = second + sticker_budget.FIGHT_STICKER_MIN_GAP_SECONDS + 1.0

    assert sticker_budget.allowed(-100, 7, first)
    sticker_budget.record(-100, 7, first)
    assert sticker_budget.allowed(-100, 8, second)
    sticker_budget.record(-100, 8, second)

    assert sticker_budget.chat_count(-100, third) == 2
    assert not sticker_budget.allowed(-100, 7, third)
    assert not sticker_budget.allowed(-100, 8, third)
    assert not sticker_budget.allowed(-100, 9, third)
