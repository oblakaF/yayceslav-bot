from telegram.ext import Application, CommandHandler

import daily_content_runtime as daily_content
import dialogue_guard_runtime as dialogue_guard
import member_profile_runtime as member_profile
import monthly_social_runtime as monthly
import relationship_experience_runtime as relationship
import runtime_bootstrap
import unified_daily_title_runtime as unified_titles
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
    monkeypatch.setattr(v3, "_prepare_application", lambda app: calls.append(("v3", app)))
    monkeypatch.setattr(v4, "_prepare_application", lambda app: calls.append(("v4", app)))
    monkeypatch.setattr(dialogue_guard, "_prepare", lambda: calls.append(("dialogue", None)))
    monkeypatch.setattr(
        daily_content,
        "_prepare_application",
        lambda app: calls.append(("daily_content", app)),
    )

    runtime_bootstrap.prepare_application_runtime(application)

    assert calls == [
        ("unified", None),
        ("monthly", application),
        ("relationship", application),
        ("member_profile", application),
        ("v3", application),
        ("v4", application),
        ("dialogue", None),
        ("daily_content", application),
    ]
    assert not hasattr(unified_titles, "install_runtime_hook")
    assert not hasattr(monthly, "install_runtime_hook")
    assert not hasattr(relationship, "install_runtime_hook")
    assert not hasattr(member_profile, "install_runtime_hook")
    assert not hasattr(v3, "install_runtime_hook")
    assert not hasattr(v4, "install_runtime_hook")
    assert not hasattr(dialogue_guard, "install_runtime_hook")
    assert not hasattr(daily_content, "install_runtime_hook")
