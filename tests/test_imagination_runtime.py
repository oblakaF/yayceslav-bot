from types import SimpleNamespace

import imagination_runtime


def test_imagination_trigger_phrases_cover_live_chat_cases():
    cases = (
        "чисто гипотетически что бы ты скушал брокколи или бургер",
        "просто включи воображение",
        "Помечтай каким бы ты хотел быть в физической интерпретации",
        "Если бы ты мог выбрать расу пол происхождение кем бы ты был?",
        "пофантазируй, какой была бы твоя партия",
    )
    for text in cases:
        assert imagination_runtime.is_imagination_request(text), text


def test_plain_factual_query_is_not_imagination():
    assert not imagination_runtime.is_imagination_request(
        "кто сейчас президент Франции?"
    )
    assert not imagination_runtime.is_imagination_request(
        "какая программа у этого кандидата?"
    )


def test_direct_imagination_prompt_adds_live_choice_rules():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    imagination_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "Гипотетически: брокколи или бургер?",
        chat_type="group",
        recent_messages=[],
    )

    assert "IMAGINATION MODE" in instruction
    assert "выбери конкретный вариант" in instruction
    assert "я программа" in instruction
    assert "сердцем — бургер" in instruction
    assert "НЕ является" in instruction


def test_followup_keeps_previous_imagination_canon_from_keyword_history():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    imagination_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "А какая бы была твоя программа?",
        None,
        False,
        100,
        "group",
        "Ross",
        [
            "Ross: гипотетически, за кого бы ты голосовал?",
            "Яйцеслав: я бы себя выдвинул",
        ],
    )

    assert "IMAGINATION MODE" in instruction
    assert "ПРОДОЛЖЕНИЕ УЖЕ НАЧАТОЙ ФАНТАЗИИ" in instruction
    assert "каноном текущего мини-сценария" in instruction


def test_unrelated_program_question_does_not_inherit_imagination():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    imagination_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "Какая программа у кандидата?",
        chat_type="group",
        recent_messages=[
            "Ross: сколько сейчас времени?",
            "Яйцеслав: 17:00",
        ],
    )

    assert instruction == "BASE"


def test_followup_detector_requires_both_continuation_and_imagination_history():
    history = [
        "Ross: представь, что ты баллотируешься в президенты",
        "Яйцеслав: ладно, погнали",
    ]
    assert imagination_runtime.looks_like_imagination_followup(
        "А какой у тебя был бы девиз?", history
    )
    assert not imagination_runtime.looks_like_imagination_followup(
        "Сегодня дождь?", history
    )


def test_strange_self_image_question_is_treated_as_imagination_not_reason_to_shame():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    imagination_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "Гипотетически, если бы ты мог выбрать расу, пол и происхождение, кем бы ты был?",
        chat_type="group",
        recent_messages=[],
    )
    normalized = " ".join(instruction.split())

    assert "можно выбрать условный образ для самого Яйцеслава" in normalized
    assert "Не посылай пользователя и не диагностируй его" in normalized
    assert "без идей превосходства" in normalized
