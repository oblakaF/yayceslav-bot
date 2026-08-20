import whoami_profile_v4_runtime as whoami


def test_relationship_is_exactly_neutral_only_at_zero():
    assert whoami._relationship_label(4, 0, 0) == "Нейтральный"
    assert whoami._relationship_label(0, 0, 1) == "Доброжелательный"
    assert whoami._relationship_label(4, 0, 9) == "Доброжелательный"
    assert whoami._relationship_label(4, 0, -1) == "Хейтерок"
    assert whoami._relationship_label(4, 0, -9) == "Хейтерок"


def test_familiarity_does_not_override_reputation_relationship():
    assert whoami._relationship_label(4, 0, 0) == "Нейтральный"
    assert whoami._relationship_label(0, 0, 40) == "Хороший знакомый"
    assert whoami._relationship_label(4, 0, -40) == "Мини-хейтер"
