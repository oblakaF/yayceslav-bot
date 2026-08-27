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


def test_positive_line_is_human_readable_current_sympathy():
    assert whoami._positive_line({}) == "Нейтральная"
    assert whoami._positive_line({"reputation_score": 19}) == "Доброжелательная"
    assert whoami._positive_line({"positive_affinity_points_30d": 6}) == "Лёгкая симпатия"
    assert whoami._positive_line({"positive_affinity_points_30d": 12}) == "Тёплая"
    assert whoami._positive_line({"positive_affinity_points_30d": 30}) == "Очень тёплая"
    assert whoami._positive_line({"reputation_score": -40}) == "Холодная"


def test_friendliness_line_states():
    assert whoami._friendliness_line(0, 0, 0, False) == "Нейтрально"
    assert whoami._friendliness_line(0, 3, 1, False) == "Нейтрально — сегодня уже помирились"
    assert whoami._friendliness_line(1, 1, 0, False) == "Мини-хейтер — 1 наезд сегодня"
    assert whoami._friendliness_line(4, 4, 0, False) == "Мега-хейтер — 4 наезда сегодня"
    assert (
        whoami._friendliness_line(0, 0, 0, True)
        == "Нейтрально — рецидив, помилование через мемный ритуал"
    )
