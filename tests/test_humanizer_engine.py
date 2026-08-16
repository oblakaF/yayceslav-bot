import humanizer_engine


class Trace:
    chat_type = "group"
    serious_topic = False
    conversation_mode = "normal"
    message_intent = "technical_help"


class SeqRng:
    def __init__(self, values):
        self.values = iter(values)

    def random(self):
        return next(self.values)

    def choice(self, seq):
        return seq[0]

    def uniform(self, a, b):
        return (a + b) / 2


def test_split_can_make_two_messages_without_other_effects():
    text = (
        "Первая нормальная мысль уже закончилась и содержит достаточно текста. "
        "Вторая мысль идёт отдельно и тоже выглядит как самостоятельное сообщение."
    )
    result = humanizer_engine.humanize_reply(
        text,
        user_text="как исправить ошибку",
        trace=Trace(),
        rng=SeqRng([0.9, 0.0]),
    )
    assert result.effect == "split"
    assert len(result.messages) == 2


def test_typo_is_followed_by_star_correction():
    result = humanizer_engine.humanize_reply(
        "сегодня нормальное сообщение получилось достаточно длинным",
        user_text="как исправить ошибку",
        trace=Trace(),
        rng=SeqRng([0.0]),
    )
    assert result.effect == "typo_correction"
    assert len(result.messages) == 2
    assert result.messages[1].startswith("*")


def test_serious_reply_is_never_humanized():
    class SeriousTrace(Trace):
        serious_topic = True
        conversation_mode = "serious"

    result = humanizer_engine.humanize_reply(
        "Очень важный ответ. Его нельзя портить искусственными эффектами.",
        user_text="помоги",
        trace=SeriousTrace(),
        rng=SeqRng([0.0]),
    )
    assert result.effect == "none"
    assert len(result.messages) == 1
