from datetime import datetime
from types import SimpleNamespace

import monthly_theme_quality_patch as themes


def test_topic_word_rejects_fragment_noise():
    for value in (
        "другой стороны",
        "кота ответ",
        "ответ него",
        "ответ",
        "вроде",
        "починил",
        "проверил",
    ):
        assert themes._topic_word_ok(value) is False


def test_topic_word_keeps_real_atomic_subjects():
    for value in ("крипта", "котята", "Steam", "Abaqus", "тренировки", "Python"):
        assert themes._topic_word_ok(value) is True


def test_monthly_themes_do_not_fill_slots_with_garbage():
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            assert "occurrences >= 4" in query
            return SimpleNamespace(
                fetchall=lambda: [
                    ("другой стороны", 12, "2026-08-27"),
                    ("кота ответ", 11, "2026-08-27"),
                    ("ответ него", 10, "2026-08-27"),
                    ("крипта", 8, "2026-08-27"),
                    ("котята", 6, "2026-08-27"),
                    ("починил", 20, "2026-08-27"),
                ]
            )

    bot = SimpleNamespace(
        current_msk_datetime=lambda: datetime(2026, 8, 27, 12, 0, 0),
        get_db_connection=lambda: Connection(),
    )

    assert themes._themes_monthly_ranked(bot, 1, 2) == ["крипта", "котята"]


def test_monthly_themes_can_be_empty():
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            return SimpleNamespace(
                fetchall=lambda: [
                    ("другой стороны", 12, "2026-08-27"),
                    ("ответ него", 10, "2026-08-27"),
                    ("вроде", 9, "2026-08-27"),
                ]
            )

    bot = SimpleNamespace(
        current_msk_datetime=lambda: datetime(2026, 8, 27, 12, 0, 0),
        get_db_connection=lambda: Connection(),
    )

    assert themes._themes_monthly_ranked(bot, 1, 2) == []
