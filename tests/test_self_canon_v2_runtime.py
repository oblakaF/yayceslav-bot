from types import SimpleNamespace

import bot
import schema_migrations
import self_canon_runtime
import self_canon_v2_runtime


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "self_canon_v2.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    schema_migrations.run_pending(bot)
    self_canon_runtime._CANON_CACHE.clear()
    return db_path


def _install_guard_once(monkeypatch):
    self_canon_v2_runtime._INSTALLED = False
    original = self_canon_runtime.apply_canon_changes_sync
    while getattr(original, "__wrapped__", None) is not None and getattr(
        original, "_yayceslav_self_canon_v2_inertia", False
    ):
        original = original.__wrapped__
    monkeypatch.setattr(self_canon_runtime, "apply_canon_changes_sync", original)
    module = SimpleNamespace(
        get_db_connection=bot.get_db_connection,
        build_full_system_instruction=lambda style_text, **kwargs: "BASE",
    )
    assert self_canon_v2_runtime.install(module) is True
    return module


def test_unexplained_profession_flip_is_blocked(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _install_guard_once(monkeypatch)

    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"profession": "электрик"},
        source_excerpt="Я бы был электриком: люблю разбираться с реальным железом и проводкой.",
    )
    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"profession": "программист"},
        source_excerpt="Ну окей, тогда программистом.",
    )

    assert self_canon_runtime.load_canon_sync(bot, 100)["profession"] == "электрик"


def test_justified_profession_revision_is_accepted_and_reason_is_saved(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _install_guard_once(monkeypatch)

    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"profession": "электрик"},
        source_excerpt="Я бы был электриком, мне нравится чинить вещи руками.",
    )
    revision = (
        "Знаешь, я тут подумал и передумал: теперь выбрал бы инженера по автоматизации, "
        "потому что мне ближе сочетание железа, логики и настройки систем."
    )
    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"profession": "инженер по автоматизации"},
        source_excerpt=revision,
    )

    assert self_canon_runtime.load_canon_sync(bot, 100)["profession"] == "инженер по автоматизации"
    with bot.get_db_connection() as connection:
        reason, inertia, commitment = connection.execute(
            "SELECT reason, inertia, commitment FROM chat_self_canon_meta "
            "WHERE chat_id = 100 AND trait_key = 'profession'"
        ).fetchone()
    assert "потому что" in reason
    assert inertia == "high"
    assert commitment >= 3


def test_low_inertia_taste_can_expand_without_erasing_old_choice(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _install_guard_once(monkeypatch)

    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"music": "darkwave"},
        source_excerpt="Мне бы нравился darkwave за холодный звук и атмосферу.",
    )
    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"music": "darkwave, jazz"},
        source_excerpt="И джаз тоже зашёл бы — добавил бы его к тому, что уже слушаю.",
    )

    assert self_canon_runtime.load_canon_sync(bot, 100)["music"] == "darkwave, jazz"


def test_low_inertia_taste_still_cannot_silently_replace_itself(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _install_guard_once(monkeypatch)

    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"music": "darkwave"},
        source_excerpt="Мне бы нравился darkwave.",
    )
    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"music": "рэп"},
        source_excerpt="Сегодня пусть будет рэп.",
    )

    assert self_canon_runtime.load_canon_sync(bot, 100)["music"] == "darkwave"


def test_prompt_exposes_reasons_as_private_personality_logic(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    module = _install_guard_once(monkeypatch)

    self_canon_runtime.apply_canon_changes_sync(
        bot,
        100,
        {"profession": "электрик"},
        source_excerpt="Я бы был электриком, потому что мне нравится реальная работа руками.",
    )

    instruction = module.build_full_system_instruction("Кем бы ты работал?", chat_id=100)
    assert "SELF-CANON V2 — ИНЕРЦИЯ ЛИЧНОСТИ" in instruction
    assert "инерция=high" in instruction
    assert "потому что мне нравится реальная работа руками" in instruction
    assert "не меню настроек" in instruction


def test_trait_inertia_levels_match_personality_semantics():
    assert self_canon_v2_runtime.inertia_for_trait("profession") == "high"
    assert self_canon_v2_runtime.inertia_for_trait("residence") == "medium"
    assert self_canon_v2_runtime.inertia_for_trait("music") == "low"
    assert self_canon_v2_runtime.initial_commitment("profession") == 3
