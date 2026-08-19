from types import SimpleNamespace

import dialogue_followup_mode_patch as followup


def test_followup_mode_promotes_only_short_banter(monkeypatch):
    fake_bot = SimpleNamespace(detect_conversation_mode=lambda text: "normal")
    monkeypatch.setattr(followup, "_PATCHED", False)
    monkeypatch.setattr(followup, "_find_bot_module", lambda: fake_bot)

    assert followup.install() is True
    assert fake_bot.detect_conversation_mode("нет ты") == "challenge"
    assert fake_bot.detect_conversation_mode("сам такой!") == "challenge"
    assert fake_bot.detect_conversation_mode("обычный разговор") == "normal"


def test_followup_mode_install_is_idempotent(monkeypatch):
    fake_bot = SimpleNamespace(detect_conversation_mode=lambda text: "normal")
    monkeypatch.setattr(followup, "_PATCHED", False)
    monkeypatch.setattr(followup, "_find_bot_module", lambda: fake_bot)

    assert followup.install() is True
    wrapped = fake_bot.detect_conversation_mode
    assert followup.install() is True

    assert fake_bot.detect_conversation_mode is wrapped
    assert fake_bot.detect_conversation_mode("ты сам") == "challenge"
