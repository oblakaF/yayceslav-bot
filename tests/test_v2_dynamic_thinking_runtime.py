import inspect

import bot


def test_ask_gemini_uses_dynamic_thinking_and_safe_budget():
    source = inspect.getsource(bot.ask_gemini)
    assert "thinking_engine.choose_thinking_level" in source
    assert "thinking_engine.initial_token_budget" in source
    assert "thinking_level=resolved_thinking_level" in source
    assert 'thinking_level="medium"' not in source


def test_ask_gemini_logs_attempt_and_total_latency():
    source = inspect.getsource(bot.ask_gemini)
    assert "Gemini attempt %s/3: %.2fs" in source
    assert "Gemini total: %.2fs" in source


def test_normal_text_uses_current_message_for_thinking():
    source = inspect.getsource(bot.answer_text_message)
    assert "thinking_level=thinking_engine.choose_thinking_level(" in source
    assert "user_text" in source


def test_web_search_forces_medium_thinking():
    source = inspect.getsource(bot.perform_web_search)
    assert 'thinking_level="medium"' in source


def test_fact_check_forces_medium_for_both_gemini_calls():
    source = inspect.getsource(bot.fact_or_bayan_command)
    assert source.count('thinking_level="medium"') == 2
