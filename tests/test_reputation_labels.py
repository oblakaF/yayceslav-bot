import whoami_profile_v4_runtime as whoami


def test_reputation_score_labels_across_scale():
    assert whoami._score_relationship_label(-100) == "Гига-хейтер"
    assert whoami._score_relationship_label(-75) == "Мега-хейтер"
    assert whoami._score_relationship_label(-50) == "Мини-хейтер"
    assert whoami._score_relationship_label(-25) == "Хейтерок"
    assert whoami._score_relationship_label(0) == "Нейтральный"
    assert whoami._score_relationship_label(25) == "Доброжелательный"
    assert whoami._score_relationship_label(50) == "Хороший знакомый"
    assert whoami._score_relationship_label(75) == "Друг"
    assert whoami._score_relationship_label(100) == "Союзник"


def test_reputation_line_matches_score_scale():
    assert whoami._reputation_line({"reputation_score": -50}) == "-50 (Мини-хейтер)"
    assert whoami._reputation_line({"reputation_score": 0}) == "0 (Нейтральный)"
    assert whoami._reputation_line({"reputation_score": 50}) == "50 (Хороший знакомый)"


def test_positive_line_labels_across_all_levels():
    assert whoami._positive_line({"positive_affinity_level": 0}) == "0 (Нейтральная)"
    assert whoami._positive_line({"positive_affinity_level": 1}) == "1 (Симпатия)"
    assert whoami._positive_line({"positive_affinity_level": 2}) == "2 (Хорошее отношение)"
    assert whoami._positive_line({"positive_affinity_level": 3}) == "3 (Доверие)"
    assert whoami._positive_line({"positive_affinity_level": 4}) == "4 (Близкий контакт)"


def test_friendliness_line_states():
    # Clean neutral day.
    assert whoami._friendliness_line(0, 0, 0, False) == "Нейтрально"
    # Reconciled after apologizing today.
    assert whoami._friendliness_line(0, 3, 1, False) == "Нейтрально — сегодня уже помирились"
    # Active hostility today.
    assert whoami._friendliness_line(1, 1, 0, False) == "Мини-хейтер — 1 наезд сегодня"
    assert whoami._friendliness_line(4, 4, 0, False) == "Мега-хейтер — 4 наезда сегодня"
    # Repeat offender awaiting amnesty.
    assert (
        whoami._friendliness_line(0, 0, 0, True)
        == "Нейтрально — рецидив, помилование через мемный ритуал"
    )
