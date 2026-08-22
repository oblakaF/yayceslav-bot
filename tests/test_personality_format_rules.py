import personality


def test_brevity_rule_does_not_license_dropping_requested_list_items():
    # Regression: "краткость важнее полноты" made the model answer
    # "перечисли все планеты" with a single planet name instead of the
    # full list. The instruction must explicitly exempt requested
    # enumerations/full-list requests from the brevity push.
    instruction = personality.build_v2_base_instruction("расскажи", None)
    assert "перечислить, назвать все" in instruction
    assert "невыполненная просьба" in instruction


def test_brevity_rule_also_covers_explicit_item_counts():
    # Regression: "дай 4 цитаты" got a single incomplete item -- the
    # "list everything" wording alone didn't cover "give me N of X"
    # requests, a different phrasing for the same completeness demand.
    instruction = personality.build_v2_base_instruction("расскажи", None)
    assert "просит конкретное количество" in instruction
    assert "РОВНО столько" in instruction
