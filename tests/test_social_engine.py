import random

import social_engine


def test_from_profile_maps_existing_fields_only():
    ctx = social_engine.from_profile(
        {
            "relationship_level": 3,
            "current_title": "Воевода споров",
            "joke_archetype": "вечный спорщик",
            "total_messages": 123,
        }
    )
    assert ctx.relationship_level == 3
    assert ctx.current_title == "Воевода споров"
    assert ctx.joke_archetype == "вечный спорщик"
    assert ctx.total_messages == 123


def test_missing_profile_is_neutral():
    ctx = social_engine.from_profile(None)
    assert ctx.relationship_level == 0
    assert ctx.current_title is None
    assert ctx.joke_archetype is None


def test_serious_topic_suppresses_social_jokes():
    ctx = social_engine.SocialContext(
        relationship_level=4,
        current_title="Лорд простыней",
        joke_archetype="душнила",
        chat_level=4,
        messages_month=700,
    )
    assert social_engine.build_social_instruction(
        ctx,
        serious_topic=True,
        rng=random.Random(1),
    ) == ""


def test_familiar_old_contact_and_monthly_oldtimer_get_warm_social_instruction():
    ctx = social_engine.SocialContext(
        relationship_level=3,
        current_title="Воевода споров",
        chat_level=3,
        messages_month=420,
    )
    instruction = social_engine.build_social_instruction(
        ctx,
        rng=random.Random(2),
    )
    assert "хорошо знакомый Яйцеславу участник" in instruction
    assert "старожил" in instruction.lower()
    assert "по-дружески фамильярен" in instruction


def test_archetype_is_explicitly_not_a_personality_fact_after_level_two_unlock():
    class AlwaysZero:
        @staticmethod
        def random():
            return 0.0

    ctx = social_engine.SocialContext(
        relationship_level=2,
        chat_level=2,
        messages_month=200,
        joke_archetype="диванный генерал",
    )
    instruction = social_engine.build_social_instruction(
        ctx,
        rng=AlwaysZero(),
    )
    assert "диванный генерал" in instruction
    assert "не факт о личности" in instruction


def test_level_zero_does_not_unlock_archetype_callback():
    class AlwaysZero:
        @staticmethod
        def random():
            return 0.0

    ctx = social_engine.SocialContext(
        relationship_level=3,
        chat_level=0,
        messages_month=20,
        joke_archetype="диванный генерал",
    )
    instruction = social_engine.build_social_instruction(ctx, rng=AlwaysZero())
    assert "диванный генерал" not in instruction
