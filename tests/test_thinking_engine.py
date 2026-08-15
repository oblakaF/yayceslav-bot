import pytest

import thinking_engine


def test_short_casual_message_uses_minimal():
    assert thinking_engine.choose_thinking_level("привет, ты где") == "minimal"
    assert thinking_engine.choose_thinking_level("100%") == "minimal"
    assert thinking_engine.choose_thinking_level("ну ты и дебил") == "minimal"


def test_short_explanatory_question_uses_low():
    assert thinking_engine.choose_thinking_level("почему небо голубое?") == "low"
    assert thinking_engine.choose_thinking_level("что такое API?") == "low"


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
    ) == "low"
