import asyncio
import sqlite3
from pathlib import Path

import aggression_engine
import bot
import passive_engine
import state_engine
import style_engine


def test_db_context_manager_really_closes_connection(tmp_path):
    connection = None
    with bot.get_db_connection(tmp_path / "close.db") as connection:
        connection.execute("CREATE TABLE t (x INTEGER)")
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError("SQLite connection remained open after with-block")


def test_runtime_module_state_can_be_pruned():
    state_engine.reset_state()
    state_engine.resolve_state(101, conversation_mode="normal", now=10.0)
    assert state_engine.prune_stale_state(50.0, now=100.0) == 1

    aggression_engine.COOLDOWN.clear()
    aggression_engine.COOLDOWN.record(1, 2, now=10.0)
    assert aggression_engine.prune_stale_state(50.0, now=100.0) == 1

    passive_engine.reset_state()
    passive_engine.note_group_activity(202)
    passive_engine._LAST_ACTIVITY_AT[202] = 10.0
    assert passive_engine.prune_stale_state(50.0, now=100.0) == 1

    style_engine.reset_length_history()
    style_engine._LENGTH_HISTORY[303].append("short")
    style_engine._LENGTH_LAST_SEEN[303] = 10.0
    assert style_engine.prune_stale_state(50.0, now=100.0) == 1


def test_cleanup_removes_stale_last_message_and_duel(monkeypatch):
    bot.LAST_USER_TEXT_MESSAGE.clear()
    bot.PENDING_DUELS.clear()
    bot.LAST_USER_TEXT_MESSAGE[(1, 2)] = (1.0, "old")
    bot.PENDING_DUELS["dead"] = {"created_at": 1.0}
    monkeypatch.setattr(bot.time, "monotonic", lambda: 10_000.0)
    result = bot.cleanup_in_memory_state(max_age_seconds=100.0)
    assert (1, 2) not in bot.LAST_USER_TEXT_MESSAGE
    assert "dead" not in bot.PENDING_DUELS
    assert result["last_user_messages"] >= 1
    assert result["pending_duels"] >= 1


def test_group_engagement_does_not_leave_zero_key():
    bot.GROUP_IGNORED_STREAK.clear()
    bot.GROUP_IGNORED_STREAK[5] = 2
    bot.register_group_engagement(5)
    assert 5 not in bot.GROUP_IGNORED_STREAK


def test_hard_mode_cooldowns_are_reserved_before_network_await():
    source = Path("bot.py").read_text(encoding="utf-8")
    start = source.index("async def hard_mode_listener(")
    end = source.index("async def enforce_rate_limit(", start)
    block = source[start:end]
    trigger_set = block.index('context.chat_data[\n            "hard_last_trigger_reply"')
    trigger_await = block.index("await update.message.reply_text", trigger_set)
    assert trigger_set < trigger_await
    reaction_set = block.index('context.chat_data[\n            "hard_last_reaction"')
    reaction_await = block.index("await update.message.set_reaction", reaction_set)
    assert reaction_set < reaction_await
    random_set = block.index('context.chat_data[\n                "hard_last_random_reply"')
    random_await = block.index("await update.message.reply_text(drop_decision.text)", random_set)
    assert random_set < random_await


def test_text_user_memory_is_recorded_before_gemini_await():
    source = Path("bot.py").read_text(encoding="utf-8")
    start = source.index("async def answer_text_message(")
    end = source.index("async def answer_photo(", start)
    block = source[start:end]
    ask_pos = block.index("answer = await ask_gemini(")
    private_user = block.index('PRIVATE_MEMORY,\n                private_user_id,\n                "user"')
    group_user = block.index('GROUP_MEMORY,\n                group_chat_id,\n                "user"')
    assert private_user < ask_pos
    assert group_user < ask_pos
    after_ask = block[ask_pos:]
    assert 'PRIVATE_MEMORY,\n                private_user_id,\n                "user"' not in after_ask
    assert 'GROUP_MEMORY,\n                group_chat_id,\n                "user"' not in after_ask
