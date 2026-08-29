import verdict_engine


class ZeroRng:
    @staticmethod
    def random():
        return 0.0

    @staticmethod
    def choice(seq):
        return seq[0]


class HighRng:
    @staticmethod
    def random():
        return 0.99

    @staticmethod
    def choice(seq):
        return seq[0]


def setup_function():
    verdict_engine.reset_recent()


def test_verdict_chance_is_thirty_percent():
    assert verdict_engine.VERDICT_CHANCE == 0.30


def test_pool_is_large_and_varied():
    assert len(verdict_engine.VERDICTS) >= 50
    assert len(set(verdict_engine.VERDICTS)) == len(verdict_engine.VERDICTS)
    assert "дебилы, бля." in verdict_engine.VERDICTS
    assert "минус аура, без обид." in verdict_engine.VERDICTS


def test_no_verdict_outside_conflict_modes():
    assert verdict_engine.choose_verdict("normal", rng=ZeroRng()) is None
    assert verdict_engine.choose_verdict("greeting", rng=ZeroRng()) is None


def test_high_roll_skips_verdict():
    assert verdict_engine.choose_verdict("hostile", rng=HighRng()) is None


def test_low_roll_selects_verdict():
    verdict = verdict_engine.choose_verdict("challenge", rng=ZeroRng())
    assert verdict in verdict_engine.VERDICTS


def test_taunt_suppresses_verdict():
    assert verdict_engine.choose_verdict(
        "hostile",
        taunt_already_selected=True,
        rng=ZeroRng(),
    ) is None


def test_recent_verdict_is_not_immediately_repeated():
    first = verdict_engine.choose_verdict("hostile", rng=ZeroRng())
    second = verdict_engine.choose_verdict("hostile", rng=ZeroRng())
    assert first != second
