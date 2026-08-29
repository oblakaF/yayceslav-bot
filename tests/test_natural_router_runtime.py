import pytest

from natural_router_runtime import classify_action


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Яйцеслав, что я пропустил?", "recap"),
        ("че было в чате?", "recap"),
        ("о чем базар был?", "recap"),
        ("про что вы тут базарили", "recap"),
        ("что сегодня обсуждали?", "recap"),
        ("о чем мы сегодня разговаривали?", "recap"),
        ("о нифига вы тут насрали в чат", "recap"),
        ("что за движ тут", "recap"),
        ("введите в курс дел", "recap"),
        ("кто самый активный на этой неделе", "leaderboard"),
        ("кто тут главный болтун", "leaderboard"),
        ("рассуди нас", "judge"),
        ("разрули спор", "judge"),
        ("это правда или нет?", "fact_or_bayan"),
        ("правда или пиздеж", "fact_or_bayan"),
        ("прожарь это", "roast"),
        ("прожарь @sergey", "roast"),
        ("прожарь Серегу", "roast"),
        ("прожарка для @ross", "roast"),
        ("ну ка оскорби его @Dobry64 че он тебя обижает", "roast"),
        ("отжарь Серегу", "roast"),
        ("разнеси его", "roast"),
        ("обосри @ross", "roast"),
        ("размажь этого типа", "roast"),
        ("пройдись по нему", "roast"),
        ("проедься по @ross", "roast"),
        ("аргументы за и против", "debate"),
        ("приведи аргумент", "argument"),
        ("сделай из этого мем", "meme"),
        ("дай отчёт за неделю", "week"),
        ("итоги недели", "week"),
        ("награды недели", "awards"),
        ("кому награды дали", "awards"),
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
        "базар сегодня странный",
        "насрали конечно знатно",
        "серега опять что-то пишет",
        "разнеси вещи по комнатам",
        "оскорбление было лишним",
    ],
)
def test_ambiguous_or_normal_text_falls_through(text):
    assert classify_action(text) is None
