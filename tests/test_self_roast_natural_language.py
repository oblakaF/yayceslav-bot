import natural_router_runtime
import roast_target_runtime


def test_self_roast_phrases_route_to_roast():
    phrases = (
        "Обосри меня?",
        "Отжарь меня",
        "Курва отжарь меня",
        "Прожарь меня",
        "Разъеби меня",
        "Пройдись по мне",
        "Устрой мне прожарку",
    )
    for phrase in phrases:
        assert natural_router_runtime.classify_action(phrase) == "roast", phrase


def test_self_roast_is_explicit_self_not_named_target():
    for phrase in ("отжарь меня", "оскорби себя", "обосри меня"):
        assert roast_target_runtime.is_self_roast_request(phrase) is True
        assert roast_target_runtime.extract_explicit_target(phrase) is None


def test_explicit_username_still_wins_as_named_target():
    text = "Курва отжарь @Dobry64, а не меня"
    assert natural_router_runtime.classify_action(text) == "roast"
    assert roast_target_runtime.extract_explicit_target(text) == "@Dobry64"


def test_non_roast_object_guard_is_unchanged():
    assert natural_router_runtime.classify_action("разнеси вещи по комнатам") is None
