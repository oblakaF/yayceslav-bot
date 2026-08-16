import random

import humanizer_engine


class Trace:
    chat_type = "group"
    serious_topic = False
    conversation_mode = "hostile"
    message_intent = "unknown"


def test_first_hostile_turn_keeps_only_one_punchline():
    reply = humanizer_engine.humanize_reply(
        "Слышь, лопух, ты зеркало с чатом перепутал? Ты с батей-то посдержаннее общайся.",
        user_text="еблан",
        trace=Trace(),
        hostile_streak=1,
        rng=random.Random(1),
    )
    assert reply.messages == ("Слышь, лопух, ты зеркало с чатом перепутал?",)
    assert reply.effect == "hostile_compact"


def test_second_hostile_turn_does_not_get_typo_or_split():
    reply = humanizer_engine.humanize_reply(
        "Иди нахуй. А теперь я ещё долго объясню, почему ты неправ.",
        user_text="хуятей",
        trace=Trace(),
        hostile_streak=2,
        rng=random.Random(0),
    )
    assert reply.messages == ("Иди нахуй.",)
    assert reply.effect == "hostile_compact"


def test_third_hostile_turn_is_not_forcibly_compacted():
    text = "Первое предложение. Второе предложение. Третье предложение."
    reply = humanizer_engine.humanize_reply(
        text,
        user_text="охуел",
        trace=Trace(),
        hostile_streak=3,
        rng=random.Random(999),
    )
    assert reply.messages[0] == text
    assert reply.effect == "none"


def test_hostile_one_liner_has_hard_character_cap():
    text = (
        "Это очень длинная первая фраза без нормальной остановки которая продолжает тянуться "
        "и тянуться потому что модель решила опять написать целый трактат вместо огрызка"
    )
    reply = humanizer_engine.humanize_reply(
        text,
        user_text="пошел нахуй",
        trace=Trace(),
        hostile_streak=1,
        rng=random.Random(4),
    )
    assert len(reply.messages[0]) <= 120
    assert len(reply.messages) == 1
