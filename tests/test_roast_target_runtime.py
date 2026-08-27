import pytest

from roast_target_runtime import extract_explicit_target, is_roast_request


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("прожарь @Dobry64", "@Dobry64"),
        ("ну ка оскорби его @Dobry64 че он тебя обижает", "@Dobry64"),
        ("разнеси Серегу", "Серегу"),
        ("отжарь Ross", "Ross"),
        ("обосри vasya_228", "vasya_228"),
        ("Яйцеслав @BOBR_KURWWA_bot прожарь @Dobry64", "@Dobry64"),
    ],
)
def test_explicit_target_is_stable(text, expected):
    assert extract_explicit_target(text, bot_username="BOBR_KURWWA_bot") == expected


@pytest.mark.parametrize(
    "text",
    [
        "оскорби его",
        "разнеси её",
        "пройдись по нему",
        "прожарь это",
        "подколи сообщение",
        "разнеси этот пост",
    ],
)
def test_pronoun_or_generic_target_is_not_guessed(text):
    assert extract_explicit_target(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "прожарь @sergey",
        "оскорби его @sergey",
        "отжарь Серегу",
        "разнеси его",
        "обосри @ross",
        "размажь этого типа",
        "пройдись по нему",
        "проедься по @nick",
    ],
)
def test_colloquial_roast_request_detection(text):
    assert is_roast_request(text)
