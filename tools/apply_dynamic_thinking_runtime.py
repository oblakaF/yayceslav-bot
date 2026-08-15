from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


def replace_in_section(
    text: str,
    start_marker: str,
    end_marker: str,
    old: str,
    new: str,
    label: str,
) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    section = text[start:end]
    count = section.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match in section, got {count}")
    section = section.replace(old, new, 1)
    return text[:start] + section + text[end:]


bot_path = Path("bot.py")
text = bot_path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "import state_engine\nimport style_engine\nimport title_pools\n",
    "import state_engine\nimport style_engine\nimport thinking_engine\nimport title_pools\n",
    "thinking import",
)

text = replace_once(
    text,
    '''    bot_was_mentioned: bool = True,\n    user_id: int | None = None,\n) -> str:\n''',
    '''    bot_was_mentioned: bool = True,\n    user_id: int | None = None,\n    thinking_level: str | None = None,\n) -> str:\n''',
    "ask_gemini signature",
)

text = replace_once(
    text,
    '''    last_error: Exception | None = None\n    request_token_budget = max_output_tokens\n\n    for attempt in range(1, 4):\n        try:\n''',
    '''    resolved_thinking_level = thinking_engine.choose_thinking_level(\n        contents,\n        explicit=thinking_level,\n    )\n    last_error: Exception | None = None\n    request_token_budget = thinking_engine.initial_token_budget(\n        max_output_tokens,\n        resolved_thinking_level,\n    )\n    request_started_at = time.monotonic()\n\n    for attempt in range(1, 4):\n        attempt_started_at = time.monotonic()\n        try:\n''',
    "thinking selection and timing",
)

text = replace_once(
    text,
    '''                            thinking_config=types.ThinkingConfig(\n                                thinking_level="medium",\n                            ),\n''',
    '''                            thinking_config=types.ThinkingConfig(\n                                thinking_level=resolved_thinking_level,\n                            ),\n''',
    "dynamic thinking config",
)

text = replace_once(
    text,
    '''                    timeout=90,\n                )\n\n            answer = (\n''',
    '''                    timeout=90,\n                )\n\n            attempt_elapsed = time.monotonic() - attempt_started_at\n            finish_reason_name = (\n                _gemini_finish_reason_name(response)\n                or "UNKNOWN"\n            )\n            logging.info(\n                "Gemini attempt %s/3: %.2fs thinking=%s budget=%s finish=%s",\n                attempt,\n                attempt_elapsed,\n                resolved_thinking_level,\n                request_token_budget,\n                finish_reason_name,\n            )\n\n            answer = (\n''',
    "attempt timing log",
)

text = replace_once(
    text,
    '''            if answer:\n                return answer\n\n            return (\n''',
    '''            if answer:\n                logging.info(\n                    "Gemini total: %.2fs thinking=%s attempts=%s",\n                    time.monotonic() - request_started_at,\n                    resolved_thinking_level,\n                    attempt,\n                )\n                return answer\n\n            logging.info(\n                "Gemini total: %.2fs thinking=%s attempts=%s empty_response=true",\n                time.monotonic() - request_started_at,\n                resolved_thinking_level,\n                attempt,\n            )\n            return (\n''',
    "total timing log",
)

text = replace_once(
    text,
    '''            logging.warning(\n                "Попытка Gemini %s из 3 "\n                "завершилась ошибкой: %s",\n                attempt,\n                error,\n            )\n''',
    '''            logging.warning(\n                "Gemini attempt %s/3 failed after %.2fs thinking=%s budget=%s: %s",\n                attempt,\n                time.monotonic() - attempt_started_at,\n                resolved_thinking_level,\n                request_token_budget,\n                error,\n            )\n''',
    "failure timing log",
)

text = replace_in_section(
    text,
    "async def answer_text_message(\n",
    "# ============================================================\n# ФОТОГРАФИИ",
    '''            bot_was_mentioned=True,\n            user_id=(\n''',
    '''            bot_was_mentioned=True,\n            thinking_level=thinking_engine.choose_thinking_level(\n                user_text\n            ),\n            user_id=(\n''',
    "normal chat current-message thinking",
)

text = replace_in_section(
    text,
    "async def perform_web_search(\n",
    "async def search_command(\n",
    '''            user_settings=user_settings,\n            chat_id=(\n''',
    '''            user_settings=user_settings,\n            thinking_level="medium",\n            chat_id=(\n''',
    "web search medium thinking",
)

text = replace_in_section(
    text,
    "async def fact_or_bayan_command(\n",
    "_ANTI_ADVICE_FORBIDDEN_RE = re.compile(\n",
    '''            max_output_tokens=320,\n            chat_id=chat_id,\n''',
    '''            max_output_tokens=320,\n            thinking_level="medium",\n            chat_id=chat_id,\n''',
    "fact check first medium thinking",
)

text = replace_in_section(
    text,
    "async def fact_or_bayan_command(\n",
    "_ANTI_ADVICE_FORBIDDEN_RE = re.compile(\n",
    '''                    max_output_tokens=380,\n                    chat_id=chat_id,\n''',
    '''                    max_output_tokens=380,\n                    thinking_level="medium",\n                    chat_id=chat_id,\n''',
    "fact check follow-up medium thinking",
)

bot_path.write_text(text, encoding="utf-8")

ci_path = Path(".github/workflows/v2-ci.yml")
ci = ci_path.read_text(encoding="utf-8")
ci = replace_once(
    ci,
    "daily_title_engine.py state_engine.py title_pools.py",
    "daily_title_engine.py state_engine.py thinking_engine.py title_pools.py",
    "permanent CI compile list",
)
ci_path.write_text(ci, encoding="utf-8")

Path("tests/test_v2_dynamic_thinking_runtime.py").write_text(
    '''import inspect\n\nimport bot\n\n\ndef test_ask_gemini_uses_dynamic_thinking_and_safe_budget():\n    source = inspect.getsource(bot.ask_gemini)\n    assert "thinking_engine.choose_thinking_level" in source\n    assert "thinking_engine.initial_token_budget" in source\n    assert "thinking_level=resolved_thinking_level" in source\n    assert 'thinking_level="medium"' not in source\n\n\ndef test_ask_gemini_logs_attempt_and_total_latency():\n    source = inspect.getsource(bot.ask_gemini)\n    assert "Gemini attempt %s/3: %.2fs" in source\n    assert "Gemini total: %.2fs" in source\n\n\ndef test_normal_text_uses_current_message_for_thinking():\n    source = inspect.getsource(bot.answer_text_message)\n    assert "thinking_level=thinking_engine.choose_thinking_level(" in source\n    assert "user_text" in source\n\n\ndef test_web_search_forces_medium_thinking():\n    source = inspect.getsource(bot.perform_web_search)\n    assert 'thinking_level="medium"' in source\n\n\ndef test_fact_check_forces_medium_for_both_gemini_calls():\n    source = inspect.getsource(bot.fact_or_bayan_command)\n    assert source.count('thinking_level="medium"') == 2\n''',
    encoding="utf-8",
)
