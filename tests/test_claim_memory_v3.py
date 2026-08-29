from types import SimpleNamespace

import claim_memory_v3 as claim
import member_profile_runtime


def test_death_and_injury_terms_are_not_safe_callback_facts():
    assert not member_profile_runtime._safe_callback_term("смерть")
    assert not member_profile_runtime._safe_callback_term("сепсис")
    assert not member_profile_runtime._safe_callback_term("ветеринар")
    assert member_profile_runtime._safe_callback_term("steam")


def test_sensitive_message_detection_catches_live_bait_examples():
    assert claim.is_sensitive_claim_text("Собака уже умерла")
    assert claim.is_sensitive_claim_text("Собака лапу порезала, рана глубокая")
    assert claim.is_sensitive_claim_text("Кажется, начинается сепсис")
    assert not claim.is_sensitive_claim_text("В OBS всё настроил")


def test_short_term_history_labels_sensitive_claim_as_unverified(monkeypatch):
    captured = {}

    def remember_message(memory_store, memory_id, role, text, memory_seconds, max_messages, author_name=""):
        captured["role"] = role
        captured["text"] = text

    fake_bot = SimpleNamespace(
        remember_message=remember_message,
        is_serious_text=lambda text: "умерла" in text.lower(),
    )

    monkeypatch.setattr(claim, "_SHORT_TERM_INSTALLED", False)
    assert claim.install_short_term_guard(fake_bot)

    fake_bot.remember_message(
        {},
        1,
        "user",
        "Собака уже умерла",
        900,
        30,
        "Евгений",
    )

    assert captured["role"] == "user"
    assert captured["text"].startswith("[Чувствительная тема/утверждение пользователя;")
    assert captured["text"].endswith("Собака уже умерла")


def test_short_term_history_does_not_rewrite_normal_chat(monkeypatch):
    captured = {}

    def remember_message(memory_store, memory_id, role, text, memory_seconds, max_messages, author_name=""):
        captured["text"] = text

    fake_bot = SimpleNamespace(
        remember_message=remember_message,
        is_serious_text=lambda text: False,
    )

    monkeypatch.setattr(claim, "_SHORT_TERM_INSTALLED", False)
    assert claim.install_short_term_guard(fake_bot)
    fake_bot.remember_message({}, 1, "user", "OBS настроил", 900, 30, "Серега")

    assert captured["text"] == "OBS настроил"
