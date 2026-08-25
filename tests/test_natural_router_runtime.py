import pytest

from natural_router_runtime import classify_action


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Яйцеслав, что я пропустил?", "recap"),
        ("кто самый активный на этой неделе", "leaderboard"),
        ("рассуди нас", "judge"),
        ("это правда или нет?", "fact_or_bayan"),
        ("прожарь это", "roast"),
        ("аргументы за и против", "debate"),
        ("приведи аргумент", "argument"),
        ("сделай из этого мем", "meme"),
        ("дай отчёт за неделю", "week"),
        ("награды недели", "awards"),
    ],
)
def test_high_confidence_routes(text, expected):
    assert classify_action(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "как дела",
        "расскажи про квантовую механику",
        "кто такой Ньютон",
        "проверь в интернете погоду",
        "что думаешь об этом",
        "сделай красиво",
    ],
)
def test_ambiguous_or_normal_text_falls_through(text):
    assert classify_action(text) is None
