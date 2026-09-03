from pathlib import Path

import recommendation_followup_guard_runtime as followups
import self_development_runtime


ROOT = Path(__file__).resolve().parents[1]


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_roadmap_v2_has_no_remaining_travel_vertical():
    roadmap = _source("ROADMAP.md")
    assert "# P3 CHARACTER DEVELOPMENT — DONE" in roadmap
    assert "Travel/places recommendations were removed" in roadmap
    assert "## Places / travel vertical" not in roadmap
    assert "### Remaining vertical" not in roadmap


def test_polling_ownership_remains_centralized():
    bootstrap = _source("runtime_bootstrap.py")
    assert "original_run_polling = Application.run_polling" in bootstrap
    assert "Application.run_polling = run_polling_with_schema_preflight" in bootstrap

    specialist_files = (
        "music_recommendation_runtime.py",
        "book_recommendation_runtime.py",
        "movie_recommendation_runtime.py",
        "game_recommendation_runtime.py",
        "self_development_runtime.py",
        "recommendation_followup_guard_runtime.py",
    )
    for filename in specialist_files:
        assert ".run_polling(" not in _source(filename), filename


def test_all_recommendation_verticals_are_registered_without_polling_wrappers():
    identity_bootstrap = _source("identity_recommendation_bootstrap_patch.py")
    music_bootstrap = _source("music_recommendation_bootstrap_patch.py")
    rate_limit_bootstrap = _source("rate_limit_tlen_runtime.py")

    for runtime in (
        "book_recommendation_runtime",
        "movie_recommendation_runtime",
        "game_recommendation_runtime",
    ):
        assert f"{runtime}.prepare_application_runtime(application)" in identity_bootstrap
    assert "music_recommendation_runtime" in music_bootstrap
    assert "recommendation_followup_guard_runtime" in rate_limit_bootstrap


def test_specialist_handler_groups_are_distinct_and_early():
    sources = {
        "music": _source("music_recommendation_runtime.py"),
        "books": _source("book_recommendation_runtime.py"),
        "movies": _source("movie_recommendation_runtime.py"),
        "games": _source("game_recommendation_runtime.py"),
    }
    expected = {"music": -3, "books": -5, "movies": -6, "games": -7}
    for category, group in expected.items():
        assert f"group={group}" in sources[category] or f"group={group}," in sources[category]
    assert len(set(expected.values())) == len(expected)


def test_optional_provider_credentials_fail_open_to_normal_bot_route():
    movie = _source("movie_recommendation_runtime.py")
    game = _source("game_recommendation_runtime.py")

    assert "if not tmdb_api_token():\n        return" in movie
    assert "if not rawg_api_key():\n        return" in game


def test_personality_memory_install_order_keeps_evidence_before_development_and_multimodal_outermost():
    hook = _source("voice_live_bootstrap_hook.py")
    persistent = hook.index("persistent_tiered_memory_runtime.install")
    development = hook.index("self_development_runtime.install")
    multimodal = hook.index("unified_multimodal_context_runtime.install")
    assert persistent < development < multimodal


def test_autonomous_development_cannot_touch_high_inertia_identity():
    forbidden = {
        "embodiment",
        "ethnicity",
        "gender",
        "age_vibe",
        "height",
        "build",
        "face",
        "hair",
        "origin",
        "profession",
        "values",
        "political_taste",
    }
    assert self_development_runtime._ALLOWED_TRAITS.isdisjoint(forbidden)


def test_generic_followup_owner_is_bounded_and_chat_local_by_contract():
    assert followups.OWNER_TTL_SECONDS == 2 * 60 * 60
    assert followups.OWNER_MAX_CHATS <= 256
    assert followups.is_generic_followup("а ещё?")
    assert not followups.is_generic_followup("ещё игры")
