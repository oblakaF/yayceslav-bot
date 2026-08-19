from collections import deque

import dialogue_guard_runtime as guard


def test_exact_hostile_repeat_is_rejected():
    recent = deque(["Сам иди нахуй."], maxlen=8)
    assert guard._too_similar("Сам иди нахуй.", recent)


def test_repeated_central_attack_theme_is_rejected():
    recent = deque(
        [
            "Стрелки переводить — предел твоих интеллектуальных возможностей?",
            "Ты чат уже пугаешь своим интеллектом.",
        ],
        maxlen=8,
    )
    assert guard._too_similar(
        "Интеллекта здесь хватает только на повтор одной и той же ерунды.",
        recent,
    )


def test_different_short_counterpunch_is_allowed():
    recent = deque(
        [
            "Сам иди нахуй.",
            "Стрелки переводить — предел твоих интеллектуальных возможностей?",
        ],
        maxlen=8,
    )
    assert not guard._too_similar("Заело пластинку. Следующую мысль рожай.", recent)
