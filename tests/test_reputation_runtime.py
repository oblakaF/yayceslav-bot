import sqlite3
from datetime import datetime
from types import SimpleNamespace

from telegram.ext import Application, MessageHandler

import aggression_engine
import reputation_runtime as runtime


def _db_bot(tmp_path):
    path = tmp_path / "reputation.db"

    def get_db_connection():
        return sqlite3.connect(path)

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        current_msk_datetime=lambda: datetime(2026, 8, 20, 1, 0, 0),
        build_full_system_instruction=lambda *args, **kwargs: "BASE",
        get_member_profile_sync=lambda chat_id, user_id: {"user_id": user_id},
        get_member_profile=lambda chat_id, user_id: None,
        detect_conversation_mode=lambda text: "hostile" if "нахуй" in str(text) else "normal",
    )


def test_missing_member_reputation_is_exactly_zero(tmp_path):
    bot = _db_bot(tmp_path)
    runtime._initialize_table(bot)
    state = runtime._state_sync(bot, 1, 2)
    assert state["score"] == 0
    assert state["positive_events"] == 0
    assert state["negative_events"] == 0


def test_score_persists_and_clamps_at_both_limits(tmp_path):
    bot = _db_bot(tmp_path)
    runtime._initialize_table(bot)
    for _ in range(15):
        runtime._apply_delta_sync(bot, 1, 2, 10, "positive")
    assert runtime._state_sync(bot, 1, 2)["score"] == 100
    for _ in range(25):
        runtime._apply_delta_sync(bot, 1, 2, -10, "negative")
    state = runtime._state_sync(bot, 1, 2)
    assert state["score"] == -100
    assert state["positive_points"] == 150
    assert state["negative_points"] == 250


def test_profile_enrichment_keeps_reputation_separate(tmp_path):
    bot = _db_bot(tmp_path)
    runtime._initialize_table(bot)
    runtime._apply_delta_sync(bot, 1, 2, 5, "positive")
    profile = runtime._enrich_profile(bot, {"chat_level": 4}, 1, 2)
    assert profile["chat_level"] == 4
    assert profile["reputation_score"] == 5
    assert profile["reputation_label"] == "нейтрально"


def test_neutral_instruction_explicitly_overrides_old_aggressive_default():
    text = runtime._reputation_instruction(0)
    assert "нейтральный человек" in text
    assert "aggressive by default" in text
    assert "Не начинай агрессию" in text


def test_negative_history_changes_long_term_attitude():
    text = runtime._reputation_instruction(-75)
    assert "устойчивую токсичность" in text
    assert "жёсткую дистанцию" in text


def test_positive_history_is_warm_but_not_sycophantic():
    text = runtime._reputation_instruction(80)
    assert "очень свой" in text
    assert "не льсти" in text


def test_reputation_gate_blocks_proactive_dokop_for_neutral_user(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    runtime._initialize_table(bot)

    original = aggression_engine.decide_aggression
    monkeypatch.setattr(aggression_engine, "decide_aggression", original)
    runtime._patch_proactive_aggression(bot)

    ctx = aggression_engine.AggressionContext(
        user_text="очевидно это факт",
        intent="group_banter",
        chat_type="group",
        roughness="high",
        chat_id=1,
        user_id=2,
    )
    decision = aggression_engine.decide_aggression(ctx)
    assert decision.active is False
    assert decision.reason == "reputation_neutral"


def test_prepare_registers_group10_observer_once(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    calls = []
    monkeypatch.setattr(runtime, "_find_bot_module", lambda: bot)
    monkeypatch.setattr(runtime, "_initialize_table", lambda value: calls.append("table"))
    monkeypatch.setattr(runtime, "_augment_profile_functions", lambda value: calls.append("profile"))
    monkeypatch.setattr(runtime, "_patch_instruction", lambda value: calls.append("instruction"))
    monkeypatch.setattr(runtime, "_patch_proactive_aggression", lambda value: calls.append("aggression"))

    application = Application.builder().token("123456:TESTTOKEN").build()
    runtime._PREPARED_APPLICATION_IDS.discard(id(application))
    runtime._prepare_application(application)
    runtime._prepare_application(application)

    assert calls == ["table", "profile", "instruction", "aggression"]
    handlers = application.handlers.get(10, ())
    assert len(handlers) == 1
    assert isinstance(handlers[0], MessageHandler)
    assert handlers[0].callback is runtime._observe_reputation
