import random

import bot
import style_engine
import voice_runtime


def test_first_two_hostile_turns_never_become_normal_or_long():
    style_engine.reset_length_history()
    for streak in (1, 2):
        for seed in range(80):
            plan = style_engine.choose_response_length(
                9001,
                style_engine.ResponseLengthContext(
                    user_text="ты ебобо",
                    conversation_mode="hostile",
                    hostile_streak=streak,
                ),
                rng=random.Random(seed),
                record=False,
            )
            assert plan.category in {"micro", "short"}
            assert plan.max_chars <= 180


def test_third_fourth_hostile_turns_can_escalate_but_never_to_long_wall():
    categories = set()
    for streak in (3, 4):
        for seed in range(120):
            plan = style_engine.choose_response_length(
                9002,
                style_engine.ResponseLengthContext(
                    user_text="да пошел ты еще раз",
                    conversation_mode="hostile",
                    hostile_streak=streak,
                ),
                rng=random.Random(seed),
                record=False,
            )
            categories.add(plan.category)
            assert plan.category != "long"
            assert plan.max_chars <= 450
    assert "normal" in categories


def test_hostile_length_instruction_distinguishes_short_fuse_and_escalation():
    short_plan = style_engine.ResponseLengthPlan(
        category="micro", min_chars=12, max_chars=90, target_chars=30,
        conversation_mode="hostile", hostile_streak=1,
    )
    escalated_plan = style_engine.ResponseLengthPlan(
        category="normal", min_chars=200, max_chars=450, target_chars=320,
        conversation_mode="hostile", hostile_streak=3,
    )
    assert "Одна матерная фраза" in style_engine.build_length_instruction(short_plan)
    assert "2–5 предложений" in style_engine.build_length_instruction(escalated_plan)


def test_plain_hostile_voice_instruction_allows_one_line_sendoff_and_stop():
    class Rng:
        @staticmethod
        def random():
            return 0.99
        @staticmethod
        def choice(seq):
            return seq[0]

    material = voice_runtime.choose_voice_material(
        "blat", conversation_mode="hostile", roughness="high", rng=Rng()
    )
    instruction = voice_runtime.build_voice_instruction(material)
    assert "иди нахуй" in instruction
    assert "ПОЛНЫМ ответом" in instruction
    assert "не продолжай" in instruction


def test_feedback_status_distinguishes_tracked_from_reacted(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATS_DB_PATH", tmp_path / "feedback-status.db")
    bot.initialize_stats_database()

    trace = bot.feedback_engine.ResponseTrace(
        chat_id=-100, chat_type="group", voice_pack="blat", humor_type="rough"
    )
    bot.store_bot_response_feedback_sync(-100, 77, trace)

    status = bot.get_chat_native_learning_status_sync(-100)
    assert status["tracked_messages"] == 1
    assert status["reacted_messages"] == 0

    assert bot.apply_bot_reaction_delta_sync(-100, 77, -1.2, 1)
    status = bot.get_chat_native_learning_status_sync(-100)
    assert status["tracked_messages"] == 1
    assert status["reacted_messages"] == 1
