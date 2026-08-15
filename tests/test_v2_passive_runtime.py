import passive_engine
import bot


def test_build_instruction_can_add_same_pack_fatigue(monkeypatch):
    passive_engine.reset_state()
    monkeypatch.setattr(
        bot.style_engine, "choose_voice_pack", lambda ctx: "blat"
    )
    monkeypatch.setattr(
        bot.passive_engine,
        "note_bot_call_and_maybe_fatigue",
        lambda *args, **kwargs: passive_engine.FatigueDecision(
            active=True,
            pack_name="blat",
            text="Опять весь этот кипиш мне разгребать.",
            call_count=8,
            reason="fatigue",
        ),
    )
    instruction = bot.build_full_system_instruction(
        "ну ответь", chat_id=881, chat_type="group", bot_was_mentioned=True
    )
    assert "V2 fatigue" in instruction
    assert "Речевой пакет этого ответа: blat" in instruction
    assert instruction.count("Речевой пакет этого ответа:") == 1


def test_private_chat_does_not_run_group_fatigue(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("fatigue should not run in private chat")
    monkeypatch.setattr(bot.passive_engine, "note_bot_call_and_maybe_fatigue", fail)
    bot.build_full_system_instruction(
        "привет", chat_id=882, chat_type="private", bot_was_mentioned=True
    )


def test_passive_drop_module_never_opens_extra_random_slot():
    passive_engine.reset_state()
    for _ in range(30):
        passive_engine.note_group_activity(883)
    decision = passive_engine.maybe_random_drop(
        883, existing_random_reply_slot_open=False
    )
    assert not decision.active
    assert decision.reason == "no_existing_slot"
