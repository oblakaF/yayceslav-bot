from telegram.ext import Application, CommandHandler

import accountability_runtime as accountability
import chat_digest_runtime as chat_digest
import daily_content_runtime as daily_content
import daily_mood_runtime as daily_mood
import date_grounding_runtime as date_grounding
import dialogue_guard_runtime as dialogue_guard
import episodic_memory_runtime as episodic_memory
import initiative_runtime as initiative
import member_profile_runtime as member_profile
import natural_router_runtime as natural_router
import pairwise_relationship_runtime as pairwise_relationship
import monthly_social_runtime as monthly
import positive_runtime as positive
import reputation_daily_runtime as reputation_daily
import reputation_decay_runtime as reputation_decay
import reputation_runtime as reputation
import relationship_experience_runtime as relationship
import runtime_bootstrap
import scoped_help_runtime
import search_context_runtime as search_context
import search_enrichment_runtime as search_enrichment
import sticker_post_runtime
import sticker_runtime
import unified_daily_title_runtime as unified_titles
import voice2_runtime as voice2
import whoami_profile_v3_runtime as v3
import whoami_profile_v4_runtime as v4


def test_v3_prepares_data_observer_without_registering_legacy_whoami(monkeypatch):
    fake_bot_module = object()
    monkeypatch.setattr(v3, "_find_bot_module", lambda: fake_bot_module)
    monkeypatch.setattr(v3, "_initialize_tables", lambda bot_module: None)

    application = Application.builder().token("123456:TESTTOKEN").build()
    v3._PREPARED_APPLICATION_IDS.discard(id(application))
    v3._prepare_application(application)

    assert not application.handlers.get(-20)
    assert len(application.handlers.get(6, ())) == 1


def test_v4_is_the_only_runtime_whoami_command_owner(monkeypatch):
    fake_bot_module = object()
    monkeypatch.setattr(v4, "_find_bot_module", lambda: fake_bot_module)

    application = Application.builder().token("123456:TESTTOKEN").build()
    v4._PREPARED_APPLICATION_IDS.discard(id(application))
    v4._prepare_application(application)

    handlers = application.handlers.get(-30, ())
    assert len(handlers) == 1
    assert isinstance(handlers[0], CommandHandler)
    assert handlers[0].callback is v4._whoami_v4


def test_application_preparation_is_centralized_in_bootstrap(monkeypatch):
    application = object()
    calls = []
    monkeypatch.setattr(
        runtime_bootstrap,
        "_prepare_sticker_menu_runtime",
        lambda app: calls.append(("sticker_menu", app)),
    )
    monkeypatch.setattr(unified_titles, "_prepare", lambda: calls.append(("unified", None)))
    monkeypatch.setattr(
        monthly,
        "_prepare_application",
        lambda app: calls.append(("monthly", app)),
    )
    monkeypatch.setattr(
        relationship,
        "_prepare_application",
        lambda app: calls.append(("relationship", app)),
    )
    monkeypatch.setattr(
        member_profile,
        "_prepare_application",
        lambda app: calls.append(("member_profile", app)),
    )
    monkeypatch.setattr(
        episodic_memory,
        "_prepare_application",
        lambda app: calls.append(("episodic_memory", app)),
    )
    monkeypatch.setattr(
        pairwise_relationship,
        "_prepare_application",
        lambda app: calls.append(("pairwise_relationship", app)),
    )
    monkeypatch.setattr(v3, "_prepare_application", lambda app: calls.append(("v3", app)))
    monkeypatch.setattr(v4, "_prepare_application", lambda app: calls.append(("v4", app)))
    monkeypatch.setattr(dialogue_guard, "_prepare", lambda: calls.append(("dialogue", None)))
    monkeypatch.setattr(accountability, "install", lambda: calls.append(("accountability", None)))
    monkeypatch.setattr(
        positive,
        "_prepare_application",
        lambda app: calls.append(("positive", app)),
    )
    monkeypatch.setattr(
        reputation,
        "_prepare_application",
        lambda app: calls.append(("reputation", app)),
    )
    monkeypatch.setattr(
        reputation_daily,
        "_prepare_application",
        lambda app: calls.append(("reputation_daily", app)),
    )
    monkeypatch.setattr(
        reputation_decay, "_prepare", lambda: calls.append(("reputation_decay", None))
    )
    monkeypatch.setattr(
        daily_mood,
        "_prepare_application",
        lambda app: calls.append(("daily_mood", app)),
    )
    monkeypatch.setattr(
        daily_content,
        "_prepare_application",
        lambda app: calls.append(("daily_content", app)),
    )
    monkeypatch.setattr(
        initiative,
        "_prepare_application",
        lambda app: calls.append(("initiative", app)),
    )
    monkeypatch.setattr(
        date_grounding,
        "install",
        lambda: calls.append(("date_grounding", None)) or True,
    )
    monkeypatch.setattr(
        voice2,
        "install",
        lambda: calls.append(("voice2", None)) or True,
    )
    monkeypatch.setattr(
        search_enrichment,
        "install",
        lambda: calls.append(("search_enrichment", None)),
    )
    monkeypatch.setattr(
        search_context,
        "install",
        lambda: calls.append(("search_context", None)) or True,
    )
    monkeypatch.setattr(
        chat_digest,
        "prepare_application_runtime",
        lambda app: calls.append(("chat_digest", app)),
    )
    monkeypatch.setattr(
        natural_router,
        "prepare_application_runtime",
        lambda app: calls.append(("natural_router", app)),
    )

    runtime_bootstrap.prepare_application_runtime(application)

    assert calls == [
        ("sticker_menu", application),
        ("unified", None),
        ("monthly", application),
        ("relationship", application),
        ("member_profile", application),
        ("episodic_memory", application),
        ("pairwise_relationship", application),
        ("v3", application),
        ("v4", application),
        ("dialogue", None),
        ("accountability", None),
        ("positive", application),
        ("reputation", application),
        ("reputation_daily", application),
        ("reputation_decay", None),
        ("daily_mood", application),
        ("daily_content", application),
        ("initiative", application),
        ("date_grounding", None),
        ("voice2", None),
        ("search_enrichment", None),
        ("search_context", None),
        ("chat_digest", application),
        ("natural_router", application),
    ]
    assert not hasattr(unified_titles, "install_runtime_hook")
    assert not hasattr(monthly, "install_runtime_hook")
    assert not hasattr(relationship, "install_runtime_hook")
    assert not hasattr(member_profile, "install_runtime_hook")
    assert not hasattr(v3, "install_runtime_hook")
    assert not hasattr(v4, "install_runtime_hook")
    assert not hasattr(dialogue_guard, "install_runtime_hook")
    assert not hasattr(accountability, "install_runtime_hook")
    assert not hasattr(positive, "install_runtime_hook")
    assert not hasattr(reputation, "install_runtime_hook")
    assert not hasattr(reputation_daily, "install_runtime_hook")
    assert not hasattr(daily_content, "install_runtime_hook")
    assert not hasattr(scoped_help_runtime, "install_runtime_hook")
    assert not hasattr(sticker_post_runtime, "install_runtime_hook")
    assert not hasattr(sticker_runtime, "install_runtime_hooks")


def test_bootstrap_is_the_only_active_polling_wrapper():
    assert getattr(Application, "_yayceslav_schema_preflight_installed", False) is True
    assert Application.run_polling.__name__ == "run_polling_with_schema_preflight"
