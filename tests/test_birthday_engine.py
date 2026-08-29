from datetime import date

import birthday_engine


def test_parse_date_arg_accepts_common_separators():
    assert birthday_engine.parse_date_arg("05.09") == (5, 9)
    assert birthday_engine.parse_date_arg("5.9") == (5, 9)
    assert birthday_engine.parse_date_arg("05-09") == (5, 9)
    assert birthday_engine.parse_date_arg("05/09") == (5, 9)


def test_parse_date_arg_accepts_and_ignores_year():
    assert birthday_engine.parse_date_arg("05.09.1995") == (5, 9)
    assert birthday_engine.parse_date_arg("05.09.95") == (5, 9)


def test_parse_date_arg_accepts_leap_day():
    assert birthday_engine.parse_date_arg("29.02") == (29, 2)


def test_parse_date_arg_rejects_invalid_dates():
    assert birthday_engine.parse_date_arg("31.04") is None  # April has 30 days
    assert birthday_engine.parse_date_arg("32.01") is None
    assert birthday_engine.parse_date_arg("01.13") is None
    assert birthday_engine.parse_date_arg("00.01") is None


def test_parse_date_arg_rejects_garbage():
    assert birthday_engine.parse_date_arg("не дата") is None
    assert birthday_engine.parse_date_arg("") is None
    assert birthday_engine.parse_date_arg("завтра") is None


def test_is_birthday_today():
    today = date(2026, 9, 5)
    assert birthday_engine.is_birthday_today(5, 9, today) is True
    assert birthday_engine.is_birthday_today(6, 9, today) is False
    assert birthday_engine.is_birthday_today(5, 10, today) is False


def test_pick_congratulation_includes_name_and_is_plain_language():
    import random

    message = birthday_engine.pick_congratulation("Вася", rng=random.Random(1))
    assert "Вася" in message
    # Positive/neutral registers stay plain human language per the earlier
    # aggression-rebalance decision -- no skuf/zoomer slang here.
    lowered = message.lower()
    for banned in ("скуф", "бро", "нах", "дебил"):
        assert banned not in lowered


def test_pick_congratulation_is_deterministic_with_seeded_rng():
    import random

    first = birthday_engine.pick_congratulation("Аня", rng=random.Random(7))
    second = birthday_engine.pick_congratulation("Аня", rng=random.Random(7))
    assert first == second
