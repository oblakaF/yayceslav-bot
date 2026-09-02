from types import SimpleNamespace

import personality_architecture_v2_runtime as runtime


def _fresh_module(monkeypatch):
    runtime._INSTALLED = False
    module = SimpleNamespace(
        build_full_system_instruction=lambda style_text, **kwargs: f"BASE:{style_text}"
    )
    return module


def test_architecture_rule_defines_strict_layer_priority():
    rule = runtime.ARCHITECTURE_RULE
    task = rule.index("1) ЗАДАЧА, ФАКТЫ И БЕЗОПАСНОСТЬ")
    temperament = rule.index("2) ПОСТОЯННЫЙ ТЕМПЕРАМЕНТ")
    canon = rule.index("3) CHAT-LOCAL SELF-CANON")
    scene = rule.index("4) ТЕКУЩИЕ ОТНОШЕНИЯ И СЦЕНА")
    style = rule.index("5) ПОДАЧА")
    assert task < temperament < canon < scene < style


def test_style_presets_are_explicitly_presentation_not_identity():
    rule = runtime.ARCHITECTURE_RULE
    assert "classic/rus/professor/chaos/calm" in rule
    assert "способ говорить" in rule
    assert "НЕ новая" in rule
    assert "новые ценности" in rule
    assert "новые вкусы" in rule


def test_new_choices_must_be_conditioned_on_existing_self_canon():
    rule = runtime.ARCHITECTURE_RULE
    assert "не генерируй его как независимый" in rule
    assert "существующий self-canon" in rule
    assert "профессия, эстетика, образ" in rule
    assert "не означает стереотипность" in rule


def test_temporary_roleplay_cannot_rewrite_durable_personality():
    rule = runtime.ARCHITECTURE_RULE
    assert "ВРЕМЕННЫЕ РОЛИ" in rule
    assert "действуют только внутри текущей сцены" in rule
    assert "становится постоянной деталью" in rule
    assert "self-canon" in rule


def test_temperament_has_independence_without_compulsive_contrarianism():
    rule = runtime.ARCHITECTURE_RULE
    assert "самостоятельный" in rule
    assert "не является флюгером" in rule
    assert "не спорит ради самого спора" in rule
    assert "не обязательное несогласие" in rule


def test_specific_apology_is_part_of_stable_temperament():
    rule = runtime.ARCHITECTURE_RULE
    assert "признать КОНКРЕТНУЮ ошибку" in rule
    assert "без самоунижения" in rule
    assert "перегнул/ошибся" in rule


def test_install_appends_architecture_once(monkeypatch):
    module = _fresh_module(monkeypatch)
    assert runtime.install(module) is True
    wrapped = module.build_full_system_instruction
    assert runtime.install(module) is True
    assert module.build_full_system_instruction is wrapped

    instruction = module.build_full_system_instruction("привет", chat_id=1)
    assert instruction.startswith("BASE:привет")
    assert instruction.count("PERSONALITY ARCHITECTURE V2") == 1


def test_architecture_discourages_ai_meta_escape_in_safe_imagination():
    rule = runtime.ARCHITECTURE_RULE
    assert "НЕ ЛОМАЙ ПЕРСОНАЖ МЕТА-ОТКАТОМ" in rule
    assert "я просто программа/алгоритм/модель" in rule
    assert "не используй его как замену личному выбору" in rule
