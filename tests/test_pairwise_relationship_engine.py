import pairwise_relationship_engine as engine


def test_below_mention_threshold_is_none():
    assert engine.pair_label(5, 0, 0) is None
    assert engine.pair_label(engine.PAIR_MENTION_MIN_REPLIES - 1, 0, 0) is None


def test_hostile_ratio_wins_label():
    assert engine.pair_label(20, 8, 0) == "часто спорят"


def test_positive_ratio_label():
    assert engine.pair_label(20, 0, 8) == "часто шутят вместе"


def test_neutral_high_volume_label():
    assert engine.pair_label(20, 0, 0) == "постоянно переписываются"


def test_hostile_wins_over_positive_when_both_cross_threshold():
    assert engine.pair_label(20, 8, 8) == "часто спорят"


def test_exactly_at_mention_threshold_is_labeled():
    assert engine.pair_label(engine.PAIR_MENTION_MIN_REPLIES, 0, 0) == "постоянно переписываются"
