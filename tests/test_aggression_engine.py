import aggression_engine


class AlwaysZero:
    @staticmethod
    def random():
        return 0.0


class AlwaysOne:
    @staticmethod
    def random():
        return 0.999999


def fresh_cooldown():
    return aggression_engine.AggressionCooldown(cooldown_seconds=110.0)


def test_serious_topic_never_dokops():
    ctx = aggression_engine.AggressionContext(
        user_text="это точно факт",
        intent="serious_issue",
        chat_type="group",
        roughness="high",
        serious_topic=True,
        chat_id=1,
        user_id=2,
    )
    decision = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysZero(),
        cooldown=fresh_cooldown(),
    )
    assert not decision.active


def test_technical_help_is_not_targeted_by_proactive_aggression():
    ctx = aggression_engine.AggressionContext(
        user_text="почему код точно не работает",
        intent="technical_help",
        chat_type="group",
        roughness="high",
        chat_id=1,
        user_id=2,
    )
    decision = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysZero(),
        cooldown=fresh_cooldown(),
    )
    assert not decision.active


def test_low_roughness_disables_dokop():
    ctx = aggression_engine.AggressionContext(
        user_text="это очевидно и без вариантов",
        intent="provocation",
        chat_type="group",
        roughness="low",
        chat_id=1,
        user_id=2,
    )
    decision = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysZero(),
        cooldown=fresh_cooldown(),
    )
    assert not decision.active


def test_strong_claim_can_trigger_confidence_challenge():
    ctx = aggression_engine.AggressionContext(
        user_text="это абсолютно точно, все знают",
        intent="group_banter",
        chat_type="group",
        roughness="high",
        relationship_level=3,
        chat_id=10,
        user_id=20,
    )
    decision = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysZero(),
        cooldown=fresh_cooldown(),
    )
    assert decision.active
    assert decision.mode == "challenge_confidence"
    assert decision.reason == "strong_claim"


def test_disagreement_with_history_can_use_callback():
    ctx = aggression_engine.AggressionContext(
        user_text="нет, я передумал, всё наоборот",
        intent="disagreement",
        chat_type="group",
        roughness="high",
        recent_messages=("Иван: раньше я говорил другое",),
        chat_id=11,
        user_id=21,
    )
    decision = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysZero(),
        cooldown=fresh_cooldown(),
    )
    assert decision.active
    assert decision.mode == "callback_challenge"
    assert decision.callback_reference == "Иван: раньше я говорил другое"


def test_cooldown_prevents_repeated_targeting():
    cooldown = aggression_engine.AggressionCooldown(cooldown_seconds=110.0)
    ctx = aggression_engine.AggressionContext(
        user_text="это точно факт",
        intent="provocation",
        chat_type="group",
        roughness="high",
        chat_id=12,
        user_id=22,
    )
    first = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysZero(),
        cooldown=cooldown,
    )
    second = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysZero(),
        cooldown=cooldown,
    )
    assert first.active
    assert not second.active
    assert second.reason == "cooldown"


def test_probability_can_decline_to_dokop():
    ctx = aggression_engine.AggressionContext(
        user_text="ну и что",
        intent="group_banter",
        chat_type="group",
        roughness="high",
        chat_id=13,
        user_id=23,
    )
    decision = aggression_engine.decide_aggression(
        ctx,
        rng=AlwaysOne(),
        cooldown=fresh_cooldown(),
    )
    assert not decision.active
    assert decision.reason == "chance"


def test_aggression_instruction_does_not_create_second_style():
    decision = aggression_engine.AggressionDecision(
        active=True,
        mode="nitpick",
        reason="group_banter",
    )
    instruction = aggression_engine.build_aggression_instruction(decision)
    assert "ТОЛЬКО из уже выбранного voice pack" in instruction
    assert "одного слабого места" in instruction
