from types import SimpleNamespace

import shared_banter_runtime


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
