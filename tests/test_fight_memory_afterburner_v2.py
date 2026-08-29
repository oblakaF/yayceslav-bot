import fight_memory_afterburner_v2 as memory
import fight_routing_v3 as v3


def test_callback_uses_repeated_target_authored_word():
    texts = [
        "ты опять пиздабол",
        "пиздабол, я же сказал",
        "ну что, пиздабол?",
    ]
    assert memory.callback_token(texts).lower() == "пиздабол"


def test_sensitive_claim_is_excluded_wholesale():
    texts = [
        "собака умерла умерла",
        "ты опять пиздабол",
        "пиздабол и всё",
    ]
    safe = memory.safe_fight_texts(texts)
    assert all("умер" not in line.lower() for line in safe)
    assert memory.callback_token(texts).lower() == "пиздабол"


def test_bait_reveal_remembers_event_not_claim():
    texts = [
        "собака умерла",
        "ахах я тебя байтил, фотка двухнедельной давности",
    ]
    assert memory.fight_event(texts) == "bait_reveal"
    assert memory.callback_token(texts) == ""


def test_grounded_line_quotes_observed_repetition(monkeypatch):
    monkeypatch.setattr(memory.random, "choice", lambda items: items[0])
    state = v3.AfterburnerState(
        chat_id=-100,
        user_id=77,
        username="funnyelephant",
        fight_texts=["пиздабол опять", "ну ты пиздабол", "пиздабол и всё"],
    )
    line = memory.grounded_afterburner_line(state, lambda _state: "fallback")
    assert "@funnyelephant" in line
    assert "«пиздабол»" in line.lower()
    assert "fallback" not in line


def test_grounded_line_notices_target_talking_to_others(monkeypatch):
    monkeypatch.setattr(memory.random, "choice", lambda items: items[0])
    state = v3.AfterburnerState(
        chat_id=-100,
        user_id=77,
        username="funnyelephant",
        target_spoke_after=True,
        fight_texts=["нюхал хуй", "опять нюхал хуй"],
    )
    line = memory.grounded_afterburner_line(state, lambda _state: "fallback")
    assert "с остальными голос нашёлся" in line
    assert "нюхал" in line.lower()


def test_no_grounded_memory_preserves_existing_afterburner():
    state = v3.AfterburnerState(
        chat_id=-100,
        user_id=77,
        fight_texts=["одна уникальная реплика"],
    )
    assert memory.grounded_afterburner_line(state, lambda _state: "fallback") == "fallback"


def test_memory_is_scoped_by_existing_afterburner_state():
    first = v3.AfterburnerState(chat_id=-100, user_id=1, fight_texts=["первый первый"])
    second = v3.AfterburnerState(chat_id=-100, user_id=2, fight_texts=["второй второй"])
    assert memory.callback_token(first.fight_texts).lower() == "первый"
    assert memory.callback_token(second.fight_texts).lower() == "второй"
