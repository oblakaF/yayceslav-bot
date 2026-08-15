from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "bot.py",
        '''    GOY_REPLIES,\n    HARD_RANDOM_REPLIES,\n    HARD_REACTION_EMOJIS,\n    JOKE_TITLES,\n    MOODS,\n''',
        '''    GOY_REPLIES,\n    HARD_REACTION_EMOJIS,\n    MOODS,\n''',
        "remove dead legacy imports",
    )

    replace_once(
        "bot.py",
        '''STORY_STATE: dict[int, list[str]] = defaultdict(list)\nSTORY_MAX_PARAGRAPHS = 12\n''',
        '''STORY_STATE: dict[int, list[str]] = defaultdict(list)\nSTORY_LAST_UPDATED: dict[int, float] = {}\nSTORY_MAX_PARAGRAPHS = 12\n''',
        "story activity timestamps",
    )

    replace_once(
        "bot.py",
        '''    chat_id = update.effective_chat.id\n    paragraphs = STORY_STATE[chat_id]\n''',
        '''    chat_id = update.effective_chat.id\n    paragraphs = STORY_STATE[chat_id]\n    STORY_LAST_UPDATED[chat_id] = time.monotonic()\n''',
        "touch story activity",
    )

    replace_once(
        "bot.py",
        '''    stale_duel_tokens = [\n        token\n        for token, duel in PENDING_DUELS.items()\n        if now - float(duel.get("created_at", 0.0)) > PENDING_DUEL_TTL_SECONDS\n    ]\n    for token in stale_duel_tokens:\n        PENDING_DUELS.pop(token, None)\n\n    stale_state_chats = state_engine.prune_stale_state(\n''',
        '''    stale_duel_tokens = [\n        token\n        for token, duel in PENDING_DUELS.items()\n        if now - float(duel.get("created_at", 0.0)) > PENDING_DUEL_TTL_SECONDS\n    ]\n    for token in stale_duel_tokens:\n        PENDING_DUELS.pop(token, None)\n\n    stale_story_chats = [\n        chat_id\n        for chat_id, last_updated in STORY_LAST_UPDATED.items()\n        if now - last_updated > max_age_seconds\n    ]\n    for chat_id in stale_story_chats:\n        STORY_STATE.pop(chat_id, None)\n        STORY_LAST_UPDATED.pop(chat_id, None)\n\n    stale_state_chats = state_engine.prune_stale_state(\n''',
        "cleanup stale stories",
    )

    replace_once(
        "bot.py",
        '''        "pending_duels": len(stale_duel_tokens),\n        "state_chats": stale_state_chats,\n''',
        '''        "pending_duels": len(stale_duel_tokens),\n        "story_chats": len(stale_story_chats),\n        "state_chats": stale_state_chats,\n''',
        "story cleanup metric",
    )

    Path("tests/test_v2_last_static_cleanup.py").write_text(
        '''from pathlib import Path\n\nimport bot\n\n\ndef test_legacy_random_and_flat_title_imports_removed():\n    source = Path("bot.py").read_text(encoding="utf-8")\n    import_start = source.index("from vocabulary import (")\n    import_end = source.index("\\n)", import_start)\n    block = source[import_start:import_end]\n    assert "HARD_RANDOM_REPLIES" not in block\n    assert "JOKE_TITLES" not in block\n\n\ndef test_story_state_is_pruned_by_runtime_cleanup(monkeypatch):\n    bot.STORY_STATE.clear()\n    bot.STORY_LAST_UPDATED.clear()\n    bot.STORY_STATE[777].append("старый абзац")\n    bot.STORY_LAST_UPDATED[777] = 10.0\n    monkeypatch.setattr(bot.time, "monotonic", lambda: 1000.0)\n    result = bot.cleanup_in_memory_state(max_age_seconds=100.0)\n    assert 777 not in bot.STORY_STATE\n    assert 777 not in bot.STORY_LAST_UPDATED\n    assert result["story_chats"] >= 1\n\n\ndef test_recent_story_survives_cleanup(monkeypatch):\n    bot.STORY_STATE.clear()\n    bot.STORY_LAST_UPDATED.clear()\n    bot.STORY_STATE[778].append("свежий абзац")\n    bot.STORY_LAST_UPDATED[778] = 950.0\n    monkeypatch.setattr(bot.time, "monotonic", lambda: 1000.0)\n    bot.cleanup_in_memory_state(max_age_seconds=100.0)\n    assert bot.STORY_STATE[778] == ["свежий абзац"]\n    assert bot.STORY_LAST_UPDATED[778] == 950.0\n''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
