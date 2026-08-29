import pytest

import thinking_engine


def test_short_casual_message_uses_minimal():
    assert thinking_engine.choose_thinking_level("привет, ты где") == "minimal"
    assert thinking_engine.choose_thinking_level("100%") == "minimal"
    assert thinking_engine.choose_thinking_level("ну ты и дебил") == "minimal"


def test_short_substantive_question_uses_low():
    assert thinking_engine.choose_thinking_level("почему небо голубое?") == "low"
    assert thinking_engine.choose_thinking_level("что такое API?") == "low"


def test_explicit_explanation_uses_medium():
    assert thinking_engine.choose_thinking_level(
        "объясни что такое API"
    ) == "medium"


def test_ordinary_substantive_chat_uses_low():
    text = "Расскажи, что ты думаешь об этой идее и какие моменты тут важны."
    assert thinking_engine.choose_thinking_level(text) == "low"


def test_analysis_and_comparison_use_medium():
    assert thinking_engine.choose_thinking_level(
        "Сравни два подхода и проанализируй их сильные и слабые стороны"
    ) == "medium"
    assert thinking_engine.choose_thinking_level(
        "Разбери подробно аргументы за и против"
    ) == "medium"


def test_search_context_uses_medium():
    assert thinking_engine.choose_thinking_level(
        "Результаты поиска и источники: проверь достоверность"
    ) == "medium"


def test_explicit_level_wins():
    assert thinking_engine.choose_thinking_level(
        "привет",
        explicit="medium",
    ) == "medium"


def test_invalid_explicit_level_fails():
    with pytest.raises(ValueError):
        thinking_engine.choose_thinking_level(
            "test",
            explicit="turbo",
        )


def test_multimodal_list_uses_text_part():
    assert thinking_engine.choose_thinking_level(
        [object(), "объясни что изображено"],
    ) == "medium"


def test_initial_token_budget_has_safe_floors():
    assert thinking_engine.initial_token_budget(120, "minimal") == 384
    assert thinking_engine.initial_token_budget(360, "low") == 512
    assert thinking_engine.initial_token_budget(350, "medium") == 768


def test_requested_larger_budget_is_preserved():
    assert thinking_engine.initial_token_budget(900, "low") == 900
    assert thinking_engine.initial_token_budget(1200, "medium") == 1200
