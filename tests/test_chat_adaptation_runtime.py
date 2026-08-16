import inspect

import bot
import feedback_engine


def test_adaptation_migration_creates_persistent_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATS_DB_PATH", tmp_path / "adaptation.db")
    bot.initialize_stats_database()

    with bot.get_db_connection() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "chat_native_terms",
        "chat_native_term_users",
        "chat_native_profiles",
        "bot_response_feedback",
    } <= tables


def test_main_requests_reaction_updates_and_registers_handler():
    source = inspect.getsource(bot.main)
    assert "MessageReactionHandler" in source
    assert "message_reaction_feedback_handler" in source
    assert "UpdateType.MESSAGE_REACTION" in source


def test_primary_text_path_can_use_humanizer_but_media_paths_do_not():
    source = inspect.getsource(bot.answer_text_message)
    assert "source_user_text=user_text" in source

    assert "source_user_text=" not in inspect.getsource(bot.answer_document)
    assert "source_user_text=" not in inspect.getsource(bot.answer_voice_or_audio)


def test_chat_native_is_exclusive_voice_pack(monkeypatch):
    feedback_engine.reset_current_trace()
    monkeypatch.setattr(
        bot,
        "get_chat_native_profile_sync",
        lambda chat_id: {
            "terms": ["минус аура", "палтуса", "местный мем", "чатовая база"],
            "distinct_users": 4,
            "compiled_at": "2026-08-16T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        bot,
        "get_chat_feedback_adaptation_sync",
        lambda chat_id: feedback_engine.build_adaptation(()),
    )
    monkeypatch.setattr(
        bot.style_engine,
        "choose_voice_pack",
        lambda ctx, **kwargs: bot.style_engine.VOICE_PACK_CHAT_NATIVE,
    )

    instruction = bot.build_full_system_instruction(
        "ну что там",
        chat_id=-555,
        chat_type="group",
        user_id=1,
    )

    assert "Речевой пакет этого ответа: chat_native." in instruction
    assert "Локальный материал:" in instruction
    assert instruction.count("Речевой пакет этого ответа:") == 1
    trace = feedback_engine.get_current_trace()
    assert trace is not None
    assert trace.voice_pack == "chat_native"
