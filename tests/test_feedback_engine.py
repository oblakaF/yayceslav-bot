import feedback_engine


class Reaction:
    def __init__(self, emoji):
        self.emoji = emoji


def test_reaction_delta_scores_human_feedback():
    delta, count_delta = feedback_engine.reaction_delta(
        [Reaction("👍")],
        [Reaction("😂")],
    )
    assert delta > 0
    assert count_delta == 0


def test_adaptation_is_soft_and_bounded():
    rows = [
        {
            "voice_pack": "blat",
            "humor_type": "layered_taunt",
            "verdict_used": False,
            "reaction_score": 4.0,
            "reaction_count": 2,
        }
        for _ in range(20)
    ]
    adaptation = feedback_engine.build_adaptation(rows)
    assert 1.0 < adaptation["pack_multipliers"]["blat"] <= 1.15
    assert 1.0 < adaptation["layered_multiplier"] <= 1.15
    assert adaptation["taunt_multiplier"] == 1.0


def test_response_trace_is_task_local_api():
    feedback_engine.reset_current_trace()
    assert feedback_engine.get_current_trace() is None
    trace = feedback_engine.ResponseTrace(chat_id=-100, voice_pack="chat_native")
    feedback_engine.set_current_trace(trace)
    assert feedback_engine.get_current_trace() == trace
    feedback_engine.reset_current_trace()
