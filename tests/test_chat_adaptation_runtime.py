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


def test_trim_to_sentence_boundary_cuts_back_to_last_full_sentence():
    text = "Первое предложение. Второе предложение. Третье оборв"
    assert bot._trim_to_sentence_boundary(text) == "Первое предложение. Второе предложение."


def test_trim_to_sentence_boundary_keeps_text_when_break_is_too_early():
    # If the last sentence break is very early, trimming would throw away
    # most of the answer -- a slightly abrupt full answer beats a stub.
    text = "Ок. " + "продолжение без точек и очень длинное " * 10
    assert bot._trim_to_sentence_boundary(text) == text.strip()


def test_trim_to_sentence_boundary_handles_no_punctuation():
    text = "просто оборванный текст без точек"
    assert bot._trim_to_sentence_boundary(text) == text


def test_trim_to_sentence_boundary_handles_empty_text():
    assert bot._trim_to_sentence_boundary("") == ""
    assert bot._trim_to_sentence_boundary("   ") == ""


def test_ask_gemini_trims_truncated_answer_after_exhausting_retries():
    source = inspect.getsource(bot.ask_gemini)
    assert "_trim_to_sentence_boundary(answer)" in source
    assert "if hit_max_tokens:" in source


def test_voice_handler_keeps_typing_indicator_alive_during_processing():
    # Telegram's own "typing..." fades after ~5s; a 20-30s video/voice
    # reply needs it refreshed or the bot looks like it silently stopped
    # reacting long before the actual answer arrives.
    source = inspect.getsource(bot.answer_voice_or_audio)
    assert "keep_alive_task = asyncio.create_task(" in source
    assert "_keep_chat_action_alive(" in source
    assert "keep_alive_task.cancel()" in source


def test_voice_handler_forces_low_thinking_for_latency():
    source = inspect.getsource(bot.answer_voice_or_audio)
    assert 'thinking_level="low"' in source


def test_voice_handler_also_understands_video_notes():
    source = inspect.getsource(bot.answer_voice_or_audio)
    assert "update.message.video_note" in source
    assert '"video/mp4"' in source


def test_voice_and_video_note_replies_are_a_voice_text_coin_flip():
    source = inspect.getsource(bot.answer_voice_or_audio)
    assert "random.random() < 0.5" in source
    assert "disable_voice=not reply_as_voice" in source


def test_undirected_video_notes_can_get_a_proactive_comment():
    source = inspect.getsource(bot.answer_voice_or_audio)
    assert "proactive_comment = False" in source
    assert "video_note" in source
    assert "group_random_reply_allowed(update.effective_chat.id, now)" in source
    assert "random.random() < VIDEO_NOTE_PROACTIVE_COMMENT_CHANCE" in source
    assert "record_group_random_reply(update.effective_chat.id, now)" in source


def test_proactive_video_note_comment_is_text_only_and_does_not_ask_questions():
    source = inspect.getsource(bot.answer_voice_or_audio)
    assert "if proactive_comment:" in source
    assert "disable_voice=True" in source
    assert "не задавай встречных вопросов" in source


def test_proactive_comment_chance_is_a_moderate_constant():
    assert 0.05 <= bot.VIDEO_NOTE_PROACTIVE_COMMENT_CHANCE <= 0.35


def test_answer_text_message_attaches_linked_article_text():
    source = inspect.getsource(bot.answer_text_message)
    assert "url_content_fetcher.find_first_url(user_text)" in source
    assert "url_content_fetcher.fetch_article_text_sync" in source
    # Wired into the actual outgoing request, appended after it's resolved.
    assert source.index("linked_url = url_content_fetcher") < source.rindex("ask_gemini(")


def test_entertainment_commands_share_a_rate_limit():
    # /roast, /judge, /argument, /debate, /meme, /recap, /anti_advice,
    # /translate_yayceslav, /explain_like_* all route through this helper.
    source = inspect.getsource(bot._reply_with_gemini_feature)
    assert 'enforce_rate_limit(update, "general")' in source


def test_story_command_is_rate_limited():
    source = inspect.getsource(bot.story_command)
    assert 'enforce_rate_limit(update, "general")' in source


def test_fact_or_bayan_command_is_rate_limited():
    source = inspect.getsource(bot.fact_or_bayan_command)
    assert 'enforce_rate_limit(update, "general")' in source


def test_button_callback_actions_are_rate_limited():
    # answer_more/answer_shorter/answer_voice had no limit at all; button
    # mashing could fire unlimited Gemini/TTS calls.
    source = inspect.getsource(bot.answer_button_callback)
    assert 'enforce_rate_limit(update, "general")' in source


def test_send_answer_disable_voice_overrides_force_voice_and_voice_mode():
    source = inspect.getsource(bot.send_answer)
    assert "disable_voice: bool = False" in source
    assert "not disable_voice and (force_voice or voice_mode_enabled(context))" in source


def test_main_registers_video_note_on_the_voice_handler():
    source = inspect.getsource(bot.main)
    assert "filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE" in source


def test_chat_native_is_exclusive_voice_pack(monkeypatch):
    feedback_engine.reset_current_trace()
    bot.adaptation_cache.clear()
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


def test_runtime_caches_adaptation_and_invalidates_on_fresh_feedback():
    instruction_source = inspect.getsource(bot.build_full_system_instruction)
    reaction_source = inspect.getsource(bot.message_reaction_feedback_handler)
    refresh_source = inspect.getsource(bot.refresh_due_chat_native_profiles_sync)

    assert 'adaptation_cache.get_or_load(\n                "feedback"' in instruction_source
    assert 'ttl_seconds=45.0' in instruction_source
    assert 'adaptation_cache.get_or_load(\n                "native"' in instruction_source
    assert 'ttl_seconds=300.0' in instruction_source
    assert 'adaptation_cache.invalidate("feedback", reaction.chat.id)' in reaction_source
    assert 'adaptation_cache.invalidate("native", refreshed_chat_id)' in refresh_source
