import bot


def test_token_limit_tiers_are_ordered():
    short = bot.get_response_token_limit(
        {"response_length": "short"}, normal_tokens=360
    )
    normal = bot.get_response_token_limit(
        {"response_length": "normal"}, normal_tokens=360
    )
    detailed = bot.get_response_token_limit(
        {"response_length": "detailed"}, normal_tokens=360
    )

    assert short < normal < detailed
    assert normal == 360


def test_token_limit_falls_back_to_normal_for_unknown_value():
    assert bot.get_response_token_limit(
        {"response_length": "made_up_value"}, normal_tokens=360
    ) == 360


def test_token_limit_handles_missing_settings():
    assert bot.get_response_token_limit(None, normal_tokens=360) == 360
