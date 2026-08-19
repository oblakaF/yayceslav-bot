import reputation_engine as reputation


def test_everyone_starts_neutral_and_score_is_clamped():
    assert reputation.clamp_score(0) == 0
    assert reputation.reputation_label(0) == "нейтрально"
    assert reputation.reputation_label(1) == "нормальный"
    assert reputation.reputation_label(9) == "нормальный"
    assert reputation.reputation_label(-1) == "слегка настороженно"
    assert reputation.clamp_score(150) == 100
    assert reputation.clamp_score(-150) == -100


def test_negative_severity_uses_one_to_ten_scale():
    assert reputation.negative_delta("не беси") == -1
    assert reputation.negative_delta("иди нахер") == -5
    assert reputation.negative_delta("ты мудак") == -7
    assert reputation.negative_delta("пошёл нахуй") == -9
    assert reputation.negative_delta("я тебя обоссу") == -10


def test_positive_gratitude_uses_one_to_ten_scale():
    assert reputation.positive_delta("спс") == 1
    assert reputation.positive_delta("спасибо") == 3
    assert reputation.positive_delta("красава") == 5
    assert reputation.positive_delta("огромное спасибо") == 8
    assert reputation.positive_delta("обожаю тебя") == 10


def test_only_messages_directed_at_yayceslav_move_explicit_reputation():
    assert reputation.score_message("пошёл нахуй", directed_at_bot=False).delta == 0
    assert reputation.score_message("красава", directed_at_bot=False).delta == 0
    assert reputation.score_message("пошёл нахуй", directed_at_bot=True).delta == -9
    assert reputation.score_message("красава", directed_at_bot=True).delta == 5


def test_negative_wins_in_mixed_message():
    decision = reputation.score_message("спасибо, мудак", directed_at_bot=True)
    assert decision.delta == -7
    assert decision.reason == "negative"
