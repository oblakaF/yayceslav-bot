import whoami_profile_v4_runtime as whoami


def test_relationship_is_exactly_neutral_only_at_zero():
    assert whoami._relationship_label(4, 0, 0) == "Нейтрально"
    assert whoami._relationship_label(0, 0, 1) == "Нормально"
    assert whoami._relationship_label(4, 0, 9) == "Нормально"
    assert whoami._relationship_label(4, 0, -1) == "Слегка настороженно"
    assert whoami._relationship_label(4, 0, -9) == "Слегка настороженно"


def test_familiarity_does_not_override_reputation_relationship():
    assert whoami._relationship_label(4, 0, 0) == "Нейтрально"
    assert whoami._relationship_label(0, 0, 40) == "Свой"
    assert whoami._relationship_label(4, 0, -40) == "Негативный знакомый"
