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


def test_self_portrait_trigger_phrases_cover_natural_requests():
    cases = (
        "опиши себя полностью",
        "расскажи мне о себе",
        "каким ты себя видишь?",
        "кто ты такой?",
        "дай полный портрет самого себя",
        "составь свой автопортрет",
        "что ты за персонаж?",
    )
    for text in cases:
        assert imagination_runtime.is_self_portrait_request(text), text


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
    normalized = " ".join(instruction.split())

    assert "IMAGINATION MODE" in instruction
    assert "выбери конкретный вариант" in normalized
    assert "я программа" in normalized
    assert "сердцем — бургер" in normalized
    assert "НЕ является" in normalized
    assert "я не электоральная единица" in normalized
    assert "объект визуализирован" in normalized


def test_plain_self_portrait_request_reads_existing_canon_without_imagination_mode():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    imagination_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "Опиши себя полностью",
        chat_type="group",
        recent_messages=[],
    )
    normalized = " ".join(instruction.split())

    assert "SELF-PORTRAIT MODE" in instruction
    assert "используй ВСЕ уже сохранённые черты" in normalized
    assert "ЧТЕНИЕ текущего self-canon" in normalized
    assert "IMAGINATION MODE" not in instruction


def test_hypothetical_self_portrait_can_both_recall_and_extend_persona():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    imagination_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "Гипотетически опиши себя полностью и дорисуй, чего не хватает",
        chat_type="group",
        recent_messages=[],
    )

    assert "SELF-PORTRAIT MODE" in instruction
    assert "IMAGINATION MODE" in instruction


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
    assert imagination_runtime.looks_like_imagination_followup(
        "а из существующих видов на планете земля?", history
    )
    assert imagination_runtime.looks_like_imagination_followup(
        "ты представил? ты в кейптауне и ты японец? как ты затеряешься?", history
    )
    assert not imagination_runtime.looks_like_imagination_followup(
        "Сегодня дождь?", history
    )


def test_strange_self_image_question_keeps_playful_personal_associations():
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
    assert "субъективные, слегка абсурдные культурные/эстетические ассоциации" in normalized
    assert "дисциплина, технологии и минимализм" in normalized
    assert "Не превращай это в серьёзное заявление" in normalized
    assert "не строй иерархий" in normalized


def test_real_party_question_gets_real_choice_rule_not_invented_party_rule():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    imagination_runtime._install_prompt_rule(module)

    instruction = module.build_full_system_instruction(
        "ну а конкретно гипотетически какую бы партию выбрал?",
        chat_type="group",
        recent_messages=[
            "Ross: а на выборах в сентябре за кого бы ты гипотетически проголосовал?",
            "Яйцеслав: выбрал бы того, кто меньше болтает и больше делает",
        ],
    )

    assert "ГИПОТЕТИЧЕСКИЙ ВЫБОР НА РЕАЛЬНЫХ ВЫБОРАХ" in instruction
    assert "не подменяй это выдуманной «Партией Технического Рационализма»" in instruction
    assert "дай конкретную гипотетическую симпатию персонажа" in instruction


def test_user_correction_about_fake_party_stays_in_same_scene():
    history = [
        "Ross: ну а конкретно гипотетически какую бы партию выбрал?",
        "Яйцеслав: Партию Технического Рационализма",
    ]
    assert imagination_runtime.looks_like_imagination_followup(
        "нет такой", history
    )
    assert imagination_runtime.is_real_political_choice_request(
        "нет такой", history
    )
