from pathlib import Path
from types import SimpleNamespace

import bot
import humor_engine
import style_engine


def test_no_chat_id_does_not_create_length_key_zero():
    style_engine.reset_length_history()
    bot.build_full_system_instruction("обычный вопрос", chat_id=None, user_id=None)
    assert 0 not in style_engine._LENGTH_HISTORY
    assert 0 not in style_engine._LENGTH_LAST_SEEN


def test_no_chat_id_does_not_create_humor_key_zero():
    humor_engine.REPETITION_TRACKER._history.clear()
    humor_engine.REPETITION_TRACKER._last_touched.clear()
    humor_engine.LAST_HUMOR_TYPE.clear()
    for _ in range(30):
        bot.build_full_system_instruction(
            "ну давай поговорим смешно", chat_id=None, user_id=None
        )
    assert 0 not in humor_engine.REPETITION_TRACKER._history
    assert 0 not in humor_engine.REPETITION_TRACKER._last_touched
    assert 0 not in humor_engine.LAST_HUMOR_TYPE


def test_gemini_finish_reason_detection_is_generic():
    response = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="MAX_TOKENS"))]
    )
    assert bot._gemini_hit_max_tokens(response)
    assert bot._next_gemini_token_budget(100) == 512
    assert bot._next_gemini_token_budget(512) == 1024
    assert bot._next_gemini_token_budget(1500) == 2048


def test_readme_names_current_model_only():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "gemini-3.6-flash" in readme
    assert "gemini-3.1-flash-lite" not in readme


def test_bot_does_not_import_unused_v1_system_instruction():
    source = Path("bot.py").read_text(encoding="utf-8")
    import_block = source[source.index("from personality import ("):source.index(")", source.index("from personality import ("))]
    assert "build_system_instruction" not in import_block

def test_removed_familiarity_bonus_is_not_dead_api():
    import social_engine
    assert not hasattr(social_engine, "familiarity_humor_bonus")
