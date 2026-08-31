import asyncio

import live_chat_regression_runtime as live
import runtime_bootstrap


class _NoSearchBot:
    @staticmethod
    def extract_search_query(_text):
        return None

    @staticmethod
    def is_conversation_about_bot(_text):
        return False

    @staticmethod
    def should_auto_search(_text):
        return False


class _SearchBot(_NoSearchBot):
    @staticmethod
    def extract_search_query(text):
        return "telegram bot search" if "найди" in text.lower() else None


def test_live_exit_phrases_stop_fight_without_matching_directed_go_away():
    assert live.is_disengagement(
        "В пизду тебя, навёл тут суету без суеты, завтра обкашляем че по чем"
    )
    assert live.is_disengagement("Наверно да, пошёл я Люди Икс посмотрю")
    assert live.is_disengagement("Сказал бы что мамку твою ебал, но у тебя её нет, откисай")
    assert live.is_disengagement("до завтра, курва")

    # Directed abuse is not the speaker leaving the conversation.
    assert not live.is_disengagement("ты пошел нахуй")
    assert not live.is_disengagement("пошел нахуй отсюда")
    assert not live.is_disengagement("прожарь его я тебе говорю")


def test_casual_answer_cannot_invent_sources_or_urls():
    answer = (
        "Опять ты со своим стандартным набором оскорблений.\n\n"
        "Источники:\n"
        "* https://neolurk.org/wiki/example\n"
        "* https://genius.com/example\n"
        "* https://music.apple.com/example"
    )

    cleaned = live.strip_ungrounded_sources(
        answer,
        "А там ты себе титул уже самому себе придумал или нет?",
        _NoSearchBot(),
    )

    assert cleaned == "Опять ты со своим стандартным набором оскорблений."
    assert "http" not in cleaned
    assert "Источники" not in cleaned


def test_real_search_request_keeps_sources():
    answer = "Нашёл.\n\nИсточники:\n- https://example.com/source"
    source = "найди в интернете источник по этой теме"

    assert live.strip_ungrounded_sources(answer, source, _SearchBot()) == answer


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
    assert "НЕ является причиной" in fake.seen
    assert "Не переноси" in fake.seen


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
    assert "максимум одна короткая" in instruction


def test_live_chat_guard_is_last_cross_runtime_arbiter():
    assert runtime_bootstrap.RUNTIME_LOAD_ORDER[-1] == "live_chat_regression_runtime"
