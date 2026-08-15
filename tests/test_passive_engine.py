import passive_engine


class AlwaysZero:
    @staticmethod
    def random():
        return 0.0

    @staticmethod
    def choice(seq):
        return seq[0]

    @staticmethod
    def shuffle(seq):
        return None


class AlwaysOne(AlwaysZero):
    @staticmethod
    def random():
        return 0.999999


def setup_function():
    passive_engine.reset_state()


def test_random_drop_cannot_create_its_own_message_slot():
    for _ in range(30):
        passive_engine.note_group_activity(1)
    decision = passive_engine.maybe_random_drop(
        1,
        existing_random_reply_slot_open=False,
        rng=AlwaysZero(),
    )
    assert not decision.active
    assert decision.reason == "no_existing_slot"


def test_random_drop_requires_activity_threshold():
    for _ in range(passive_engine.RANDOM_DROP_MIN_ACTIVITY - 1):
        passive_engine.note_group_activity(2)
    decision = passive_engine.maybe_random_drop(
        2,
        existing_random_reply_slot_open=True,
        rng=AlwaysZero(),
    )
    assert not decision.active
    assert decision.reason == "low_activity"


def test_random_drop_uses_exactly_one_pack():
    for _ in range(passive_engine.RANDOM_DROP_MIN_ACTIVITY):
        passive_engine.note_group_activity(3)
    decision = passive_engine.maybe_random_drop(
        3,
        existing_random_reply_slot_open=True,
        now=1000.0,
        rng=AlwaysZero(),
    )
    assert decision.active
    assert decision.pack_name
    assert decision.text
    assert decision.reason == "styled_drop"


def test_random_drop_resets_activity_and_has_cooldown():
    for _ in range(passive_engine.RANDOM_DROP_MIN_ACTIVITY):
        passive_engine.note_group_activity(4)
    first = passive_engine.maybe_random_drop(
        4,
        existing_random_reply_slot_open=True,
        now=1000.0,
        rng=AlwaysZero(),
    )
    assert first.active
    assert passive_engine._ACTIVITY_SINCE_DROP[4] == 0

    for _ in range(passive_engine.RANDOM_DROP_MIN_ACTIVITY):
        passive_engine.note_group_activity(4)
    second = passive_engine.maybe_random_drop(
        4,
        existing_random_reply_slot_open=True,
        now=1100.0,
        rng=AlwaysZero(),
    )
    assert not second.active
    assert second.reason == "cooldown"


def test_serious_messages_do_not_build_drop_activity():
    for _ in range(50):
        passive_engine.note_group_activity(5, serious_topic=True)
    assert passive_engine._ACTIVITY_SINCE_DROP.get(5, 0) == 0


def test_fatigue_starts_only_after_threshold():
    for i in range(passive_engine.FATIGUE_CALL_THRESHOLD - 1):
        decision = passive_engine.note_bot_call_and_maybe_fatigue(
            6,
            pack_name="blat",
            now=1000.0 + i,
            rng=AlwaysZero(),
        )
        assert not decision.active
    assert decision.reason == "below_threshold"


def test_fatigue_uses_same_voice_pack():
    decision = None
    for i in range(passive_engine.FATIGUE_CALL_THRESHOLD):
        decision = passive_engine.note_bot_call_and_maybe_fatigue(
            7,
            pack_name="blat",
            now=2000.0 + i,
            rng=AlwaysZero(),
        )
    assert decision is not None and decision.active
    assert decision.pack_name == "blat"
    assert decision.text


def test_fatigue_does_not_switch_classic_to_another_style():
    decision = None
    for i in range(passive_engine.FATIGUE_CALL_THRESHOLD):
        decision = passive_engine.note_bot_call_and_maybe_fatigue(
            8,
            pack_name="classic",
            now=3000.0 + i,
            rng=AlwaysZero(),
        )
    assert decision is not None
    assert not decision.active
    assert decision.pack_name == "classic"
    assert decision.reason == "pack_has_no_grumbling"


def test_fatigue_is_suppressed_on_serious_topic():
    for i in range(20):
        decision = passive_engine.note_bot_call_and_maybe_fatigue(
            9,
            pack_name="blat",
            serious_topic=True,
            now=4000.0 + i,
            rng=AlwaysZero(),
        )
    assert not decision.active
    assert decision.reason == "serious"
    assert not passive_engine._BOT_CALLS.get(9)


def test_fatigue_cooldown_prevents_repeated_grumbling():
    decision = None
    for i in range(passive_engine.FATIGUE_CALL_THRESHOLD):
        decision = passive_engine.note_bot_call_and_maybe_fatigue(
            10,
            pack_name="skoof",
            now=5000.0 + i,
            rng=AlwaysZero(),
        )
    assert decision and decision.active

    second = passive_engine.note_bot_call_and_maybe_fatigue(
        10,
        pack_name="skoof",
        now=5010.0,
        rng=AlwaysZero(),
    )
    assert not second.active
    assert second.reason == "cooldown"


def test_fatigue_instruction_keeps_answering_question():
    decision = passive_engine.FatigueDecision(
        active=True,
        pack_name="skoof",
        text="Ё-моё, опять всё руками объяснять.",
        call_count=8,
        reason="fatigue",
    )
    instruction = passive_engine.build_fatigue_instruction(decision)
    assert "только текущий voice pack" in instruction
    assert "Не отказывайся отвечать" in instruction
