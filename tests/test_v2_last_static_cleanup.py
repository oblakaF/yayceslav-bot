from pathlib import Path

import bot


def test_legacy_random_and_flat_title_imports_removed():
    source = Path("bot.py").read_text(encoding="utf-8")
    import_start = source.index("from vocabulary import (")
    import_end = source.index("\n)", import_start)
    block = source[import_start:import_end]
    assert "HARD_RANDOM_REPLIES" not in block
    assert "JOKE_TITLES" not in block


def test_story_state_is_pruned_by_runtime_cleanup(monkeypatch):
    bot.STORY_STATE.clear()
    bot.STORY_LAST_UPDATED.clear()
    bot.STORY_STATE[777].append("старый абзац")
    bot.STORY_LAST_UPDATED[777] = 10.0
    monkeypatch.setattr(bot.time, "monotonic", lambda: 1000.0)
    result = bot.cleanup_in_memory_state(max_age_seconds=100.0)
    assert 777 not in bot.STORY_STATE
    assert 777 not in bot.STORY_LAST_UPDATED
    assert result["story_chats"] >= 1


def test_recent_story_survives_cleanup(monkeypatch):
    bot.STORY_STATE.clear()
    bot.STORY_LAST_UPDATED.clear()
    bot.STORY_STATE[778].append("свежий абзац")
    bot.STORY_LAST_UPDATED[778] = 950.0
    monkeypatch.setattr(bot.time, "monotonic", lambda: 1000.0)
    bot.cleanup_in_memory_state(max_age_seconds=100.0)
    assert bot.STORY_STATE[778] == ["свежий абзац"]
    assert bot.STORY_LAST_UPDATED[778] == 950.0
