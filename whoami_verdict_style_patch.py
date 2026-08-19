from __future__ import annotations

import random

import whoami_profile_v3_runtime as profile_v3


def _contains(themes: list[str], *stems: str) -> bool:
    text = " ".join(profile_v3._normalize_word(item) for item in themes)
    return any(stem in text for stem in stems)


def spicy_topical_verdict(
    themes: list[str],
    *,
    fallback_level: int = 0,
    rng=random,
) -> str:
    """Short, topical and recognisably Yayceslav — not corporate filler."""

    # Strong combinations first.
    if _contains(themes, "милф") and _contains(themes, "steam", "стим"):
        return rng.choice((
            "Милфы и Steam. Человек ебёт жизнь сразу на двух фронтах.",
            "Милфы, Steam — остальное ему, видимо, нахуй не надо.",
        ))

    if _contains(themes, "гараж", "машин", "авто", "тачк", "двиг", "мотор"):
        return rng.choice((
            "«Ща, блядь, заведётся» — его семейный девиз.",
            "Если не чинится — значит, ещё мало пиздили ключом.",
            "Ебёт железо, пока железо не сдастся.",
            "Машина сломалась. Заебись: появился план на выходные.",
        ))

    if _contains(themes, "милф"):
        return rng.choice((
            "По милфам у него научная степень. Остальное — хуйня.",
            "Милфы — его культурное наследие.",
            "Любитель милф. Или сама милфа — Яйцеслав пока не разобрался.",
        ))

    if _contains(themes, "steam", "стим"):
        return rng.choice((
            "Steam открыт чаще, чем окно. Воздух ему нахуй не нужен.",
            "Живёт в Steam. В реальность выходит по техническим причинам.",
            "Цифровой бомж с пропиской в библиотеке Steam.",
        ))

    if _contains(themes, "дота", "dota", "кс", "counter", "игр", "game"):
        return rng.choice((
            "Жмёт кнопки так, будто там премию дадут.",
            "Игры — работа. Только зарплату опять проебали.",
            "Геймер, сука. Снаружи взрослый, внутри катка до трёх ночи.",
        ))

    if _contains(themes, "пив", "водк", "вино", "бух", "алко", "коньяк", "виск"):
        return rng.choice((
            "По алкоголю не эксперт. Просто практика ебать какая богатая.",
            "Организм просит воды. Он трактует это по-своему.",
            "Печень ведёт переговоры. Пока безуспешно.",
        ))

    if _contains(themes, "код", "python", "питон", "github", "гитхаб", "программ"):
        return rng.choice((
            "Пишет код, потом героически чинит то, что сам нахуевертил.",
            "Если работает — не трогает. Поэтому постоянно трогает.",
            "Багов не делает. Они, сука, сами заводятся.",
        ))

    if themes:
        topic = themes[0]
        return rng.choice((
            f"Опять про «{topic}». У человека, блядь, стабильность.",
            f"Тема месяца — «{topic}». Остальное пока идёт нахуй.",
            f"Зацепился за «{topic}» и тащит это через весь чат как знамя.",
        ))

    if fallback_level >= 4:
        return "Царь чата. Уже можно не здороваться — всё равно тут живёт."
    if fallback_level >= 3:
        return "Старожил. Знает, где тут срач, и приходит заранее."
    if fallback_level >= 2:
        return "Местный. Уже поздно делать вид, что зашёл случайно."
    if fallback_level >= 1:
        return "Прижился. Компромат растёт быстрее авторитета."
    return "Пока хуй пойми кто. Но Яйцеслав наблюдает."


def install() -> None:
    profile_v3.topical_verdict = spicy_topical_verdict


install()
