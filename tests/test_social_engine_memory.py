import social_engine


class ZeroRng:
    def random(self):
        return 0.0

    def choice(self, values):
        return values[0]


def test_recent_topic_is_callback_not_biographical_fact_after_level_two_unlock(monkeypatch):
    reserved = []
    import member_profile_runtime

    monkeypatch.setattr(
        member_profile_runtime,
        "reserve_callback_term",
        lambda chat_id, user_id, term: reserved.append((chat_id, user_id, term)),
    )

    ctx = social_engine.SocialContext(
        relationship_level=2,
        chat_level=2,
        messages_month=200,
        user_id=77,
        memory_chat_id=-1001,
        callback_terms=("steam",),
    )
    instruction = social_engine.build_social_instruction(ctx, rng=ZeroRng())

    assert "steam" in instruction
    assert "НЕ доказательство" in instruction
    assert reserved == [(-1001, 77, "steam")]


def test_level_zero_does_not_use_old_callback_even_if_relationship_was_high(monkeypatch):
    reserved = []
    import member_profile_runtime

    monkeypatch.setattr(
        member_profile_runtime,
        "reserve_callback_term",
        lambda chat_id, user_id, term: reserved.append((chat_id, user_id, term)),
    )
    ctx = social_engine.SocialContext(
        relationship_level=4,
        chat_level=0,
        messages_month=10,
        user_id=77,
        memory_chat_id=-1001,
        callback_terms=("steam",),
    )
    instruction = social_engine.build_social_instruction(ctx, rng=ZeroRng())
    assert "недавно сам упоминал" not in instruction
    assert reserved == []


def test_explicit_remember_me_fact_can_be_used_as_fact():
    ctx = social_engine.SocialContext(
        relationship_level=2,
        chat_level=2,
        messages_month=200,
        self_reported_facts=("у меня лабрадор",),
    )
    instruction = social_engine.build_social_instruction(ctx, rng=ZeroRng())
    assert "сам раньше попросил запомнить факт" in instruction
    assert "лабрадор" in instruction


def test_serious_topic_disables_social_callbacks():
    ctx = social_engine.SocialContext(
        relationship_level=3,
        chat_level=3,
        messages_month=400,
        callback_terms=("steam",),
        self_reported_facts=("люблю рыбалку",),
    )
    assert social_engine.build_social_instruction(
        ctx, serious_topic=True, rng=ZeroRng()
    ) == ""
