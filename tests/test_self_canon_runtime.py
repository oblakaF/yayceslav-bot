from types import SimpleNamespace

import bot
import schema_migrations
import self_canon_runtime


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "self_canon.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    schema_migrations.run_pending(bot)
    self_canon_runtime._CANON_CACHE.clear()
    return db_path


def test_marker_is_hidden_and_payload_is_bounded():
    answer = (
        "Тогда я бы был японцем-технократом.\n"
        '[[YAY_SELF_CANON {"set":{"ethnicity":"японец","aesthetic":"минимализм и технологии","unknown":"nope"},"drop":[]}]]'
    )
    clean, updates, drops = self_canon_runtime.strip_and_parse_canon_marker(answer)

    assert clean == "Тогда я бы был японцем-технократом."
    assert updates == {
        "ethnicity": "японец",
        "aesthetic": "минимализм и технологии",
    }
    assert drops == ()


def test_chat_local_canons_do_not_leak_between_chats(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)

    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"ethnicity": "японец", "aesthetic": "минимализм"},
        source_excerpt="я бы был японцем",
    )
    self_canon_runtime.apply_canon_changes_sync(
        bot,
        200,
        {"ethnicity": "итальянец"},
        source_excerpt="а тут итальянец",
    )

    assert self_canon_runtime.load_canon_sync(bot, 100)["ethnicity"] == "японец"
    assert self_canon_runtime.load_canon_sync(bot, 200)["ethnicity"] == "итальянец"
    assert self_canon_runtime.load_canon_sync(bot, 200).get("aesthetic") is None


def test_revising_one_trait_keeps_other_traits_and_history(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)

    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"ethnicity": "японец", "aesthetic": "минимализм"},
        source_excerpt="first",
    )
    revised = self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"ethnicity": "кореец"},
        source_excerpt="changed my mind",
    )

    assert revised["ethnicity"] == "кореец"
    assert revised["aesthetic"] == "минимализм"

    with bot.get_db_connection() as connection:
        rows = connection.execute(
            "SELECT old_value, new_value FROM chat_self_canon_history "
            "WHERE chat_id = 100 AND trait_key = 'ethnicity' ORDER BY id"
        ).fetchall()
    assert rows[-1] == ("японец", "кореец")


def test_prompt_injects_only_current_chat_canon_and_update_protocol(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"ethnicity": "японец", "profession": "инженер"},
        source_excerpt="canon",
    )

    module = SimpleNamespace(
        get_db_connection=bot.get_db_connection,
        build_full_system_instruction=lambda style_text, user_settings=None, voice_style=False, chat_id=None, chat_type="private", user_name="", recent_messages=None, bot_was_mentioned=True, member_profile=None, user_id=None: "BASE",
        ask_gemini=lambda *args, **kwargs: None,
    )
    self_canon_runtime._install_prompt_memory(module)

    instruction = module.build_full_system_instruction(
        "Гипотетически, кем бы ты работал?",
        chat_id=100,
        recent_messages=[],
    )
    other_chat = module.build_full_system_instruction(
        "Гипотетически, кем бы ты работал?",
        chat_id=200,
        recent_messages=[],
    )

    assert "CHAT-LOCAL SELF CANON" in instruction
    assert "этничность/внешний тип: японец" in instruction
    assert "профессия: инженер" in instruction
    assert "SELF-CANON UPDATE PROTOCOL" in instruction
    assert "CHAT-LOCAL SELF CANON" not in other_chat
    assert "этничность/внешний тип: японец" not in other_chat
    assert "SELF-CANON UPDATE PROTOCOL" in other_chat


def test_trait_registry_has_24_independent_slots():
    assert len(self_canon_runtime.TRAIT_KEYS) == 24
    assert len(set(self_canon_runtime.TRAIT_KEYS)) == 24
