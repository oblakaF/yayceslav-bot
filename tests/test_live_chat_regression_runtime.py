import asyncio

import live_chat_regression_runtime as live
import runtime_bootstrap


def test_real_live_chat_exit_phrases_stop_the_fight():
    samples = [
        "В пизду тебя, навёл тут суету без суеты, завтра обкашляем че по чем",
        "Наверно да, или в пизду, пошёл я Люди Икс посмотрю",
        "Сказал бы что мамку твою ебал, но у тебя её нет, откисай",
        "всё, я пошёл спать",
        "до завтра, курва",
        "на сегодня хватит",
    ]
    for text in samples:
        assert live.is_disengagement(text), text


def test_directed_abuse_and_normal_fight_lines_are_not_exit_signals():
    samples = [
        "ты пошел нахуй",
        "пошел нахуй отсюда",
        "Нет, ты просто сыкло и не можешь сказать ничего против него",
        "Прожарь его я те говорю",
        "Ну в отличие от тебя есть",
    ]
    for text in samples:
        assert not live.is_disengagement(text), text


def test_fake_sources_from_casual_turn_are_removed():
    answer = (
        "Опять ты со своим стандартным набором оскорблений.\n\n"
        "Источники:\n"
        "* [https://neolurk.org/wiki/example](https://neolurk.org/wiki/example)\n"
        "* https://genius.com/example\n"
        "* https://music.apple.com/example"
    )
    cleaned = live.strip_ungrounded_source_block(
        answer,
        "А там ты себе титул уже самому себе придумал или нет?",
    )
    assert cleaned == "Опять ты со своим стандартным набором оскорблений."
    assert "Источники" not in cleaned
    assert "http" not in cleaned


def test_real_search_turn_keeps_sources_untouched():
    answer = (
        "Вот что нашлось.\n\n"
        "Источники:\n"
        "- https://example.com/a\n"
        "- https://example.com/b"
    )
    prompt = (
        "Проверь факт.\n\n"
        "Результаты поиска:\n"
        "1. https://example.com/a\n"
        "2. https://example.com/b"
    )
    assert live.strip_ungrounded_source_block(answer, prompt) == answer


def test_explicit_third_party_roast_gets_final_action_override():
    class FakeBot:
        def __init__(self):
            self.seen = ""

        async def _reply_with_gemini_feature(self, _update, prompt, *args, **kwargs):
            self.seen = prompt
            return "ok"

    fake = FakeBot()
    live._install_explicit_roast_override(fake)

    asyncio.run(
        fake._reply_with_gemini_feature(
            object(),
            "Пользователь просит прожарить ИМЕННО @funnyelephant. Контекст просьбы.",
        )
    )

    assert "ЯВНАЯ КОМАНДА ПРОЖАРКИ" in fake.seen
    assert "НЕ является причиной отказаться" in fake.seen
    assert "не требуй, чтобы цель сначала сама напала" in fake.seen
    assert "Не переноси прожарку на заказчика" in fake.seen


def test_disengagement_prompt_is_appended_after_existing_social_stack():
    class FakeBot:
        @staticmethod
        def build_full_system_instruction(*args, **kwargs):
            return "BASE"

    fake = FakeBot()
    live._install_disengagement_prompt(fake)

    instruction = fake.build_full_system_instruction(
        "Новое сообщение пользователя: пошёл я Люди Икс посмотрю"
    )

    assert instruction.startswith("BASE")
    assert "ЯВНЫЙ ВЫХОД ИЗ СРАЧА" in instruction
    assert "максимум" in instruction
    assert "одна короткая" in instruction
    assert "НЕ открывай новый раунд" in instruction


def test_live_chat_guard_is_last_cross_runtime_arbiter():
    assert runtime_bootstrap.RUNTIME_LOAD_ORDER[-1] == "live_chat_regression_runtime"
