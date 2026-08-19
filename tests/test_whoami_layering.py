from telegram.ext import Application, CommandHandler

import relationship_experience_runtime as relationship
import runtime_bootstrap
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
        relationship,
        "_prepare_application",
        lambda app: calls.append(("relationship", app)),
    )
    monkeypatch.setattr(v3, "_prepare_application", lambda app: calls.append(("v3", app)))
    monkeypatch.setattr(v4, "_prepare_application", lambda app: calls.append(("v4", app)))

    runtime_bootstrap.prepare_application_runtime(application)

    assert calls == [
        ("relationship", application),
        ("v3", application),
        ("v4", application),
    ]
    assert not hasattr(relationship, "install_runtime_hook")
    assert not hasattr(v3, "install_runtime_hook")
    assert not hasattr(v4, "install_runtime_hook")
