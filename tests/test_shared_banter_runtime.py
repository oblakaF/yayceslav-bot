from types import SimpleNamespace

import hostile_streak_engine
import shared_banter_runtime


def setup_function():
    hostile_streak_engine.reset()


def test_temporal_word_alone_does_not_force_search():
    assert shared_banter_runtime.temporal_marker_alone_is_not_search(
        "он постоянно шепчет что сейчас заставит кого-то нюхать хуй"
    )
    assert shared_banter_runtime.temporal_marker_alone_is_not_search(
        "он сейчас дверь тараном ломает"
    )


def test_real_fresh_factual_queries_are_preserved():
    assert not shared_banter_runtime.temporal_marker_alone_is_not_search(
        "кто сейчас президент Франции?"
    )
    assert not shared_banter_runtime.temporal_marker_alone_is_not_search(
        "что сейчас происходит в Иране?"
    )
    assert not shared_banter_runtime.temporal_marker_alone_is_not_search(
        "проверь сейчас последние новости по рейсу"
    )


def test_search_wrapper_suppresses_only_loose_temporal_trigger():
    calls = []

    def original(text):
        calls.append(text)
        return "сейчас" in text.lower()

    module = SimpleNamespace(should_auto_search=original)
    shared_banter_runtime._install_search_narrowing(module)

    assert module.should_auto_search(
        "а один из них шепчет что сейчас заставит кого-то нюхать хуй"
    ) is False
    assert module.should_auto_search("кто сейчас президент Франции?") is True
    assert len(calls) == 2


def test_reported_hostility_is_not_direct_sender_attack():
    assert shared_banter_runtime.is_reported_banter_hostility(
        "Братан он прям уже навис над тобой и продолжает бормотать что ты будешь нюхать хуй в бусике"
    )
    assert shared_banter_runtime.is_reported_banter_hostility(
        "он уже трогает ручку твоего серверного шкафа и орет что тебе конец"
    )
    assert not shared_banter_runtime.is_reported_banter_hostility(
        "ты долбоеб, нюхай хуй"
    )
    assert not shared_banter_runtime.is_reported_banter_hostility(
        "отъебись интернет-боец"
    )


def test_group_prompt_prioritizes_shared_improv_over_defense():
    def original(*args, **kwargs):
        return "BASE"

    module = SimpleNamespace(build_full_system_instruction=original)
    shared_banter_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "Братан а там реально кто то стоит перед серверным шкафом",
        chat_type="group",
        recent_messages=[
            "Ross: автобусик уже у серверной двери",
            "Яйцеслав: пакуем стойки в бардачок",
            "Кирилл: я уже и сам чую запах, держись друг",
            "Серега: там реально кто-то стоит перед шкафом",
        ],
    )

    assert "SHARED BANTER FRAME" in instruction
    assert "локальной реальностью ШУТКИ" in instruction
    assert "не становись фактчекером" in instruction
    assert "второй/третий участник" in instruction
    assert "патологическая фиксация" in instruction


def test_narrated_banter_clears_false_heat_before_inner_conflict_router():
    chat_id = 10
    user_id = 20
    hostile_streak_engine.observe(chat_id, user_id, hostile=True)
    hostile_streak_engine.observe(chat_id, user_id, hostile=True)
    assert hostile_streak_engine.current(chat_id, user_id) >= 2

    module = SimpleNamespace(
        detect_conversation_mode=lambda text: "hostile" if "хуй" in text else "normal",
    )

    def inner_builder(*args, **kwargs):
        # This simulates the inner conflict owner: by the time it runs, the
        # sender's false heat is gone and conversation mode is neutralized.
        assert hostile_streak_engine.current(chat_id, user_id) == 0
        return "MODE=" + module.detect_conversation_mode(args[0])

    module.build_full_system_instruction = inner_builder
    shared_banter_runtime._install_mode_override(module)
    shared_banter_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "Братан он навис над тобой и бормочет что ты будешь нюхать хуй в бусике",
        chat_id=chat_id,
        chat_type="group",
        user_id=user_id,
        recent_messages=[],
    )

    assert instruction.startswith("MODE=normal")
    assert "ТЕКУЩАЯ РЕПЛИКА — ПЕРЕСКАЗ/ПРОДОЛЖЕНИЕ СЦЕНЫ" in instruction
    assert hostile_streak_engine.current(chat_id, user_id) == 0


def test_direct_insult_keeps_conflict_mode_and_heat():
    chat_id = 11
    user_id = 21
    hostile_streak_engine.observe(chat_id, user_id, hostile=True)

    module = SimpleNamespace(
        detect_conversation_mode=lambda text: "hostile",
        build_full_system_instruction=lambda *args, **kwargs: "MODE=" + module.detect_conversation_mode(args[0]),
    )
    shared_banter_runtime._install_mode_override(module)
    shared_banter_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "ты долбоеб, нюхай хуй",
        chat_id=chat_id,
        chat_type="group",
        user_id=user_id,
        recent_messages=[],
    )

    assert instruction.startswith("MODE=hostile")
    assert hostile_streak_engine.current(chat_id, user_id) == 1


def test_private_prompt_does_not_add_group_banter_rule():
    def original(*args, **kwargs):
        return "BASE"

    module = SimpleNamespace(build_full_system_instruction=original)
    shared_banter_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "привет",
        chat_type="private",
        recent_messages=[],
    )
    assert instruction == "BASE"
