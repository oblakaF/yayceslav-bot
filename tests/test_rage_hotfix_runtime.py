import re

import hostile_streak_engine
import rage_hotfix_runtime as rage


def setup_function():
    hostile_streak_engine.reset()


def test_live_short_insults_from_telegram_are_hostile():
    samples = (
        "Пес ебливый",
        "Нюхай хуй",
        "Хуй нюхай",
        "Психоза",
        "Слился маленький",
        "Слился дно",
        "Поплачь",
        "Проебал слабость обоссанная",
        "Ущербна только твоя мамаша тут",
        "Говна поел?",
        "Обоссан",
        "Нищий безмозглый ебанат",
    )
    for text in samples:
        assert rage.is_extra_hostile(text), text


def test_neutral_profanity_does_not_start_a_bot_fight():
    assert not rage.is_extra_hostile("бля, пробки заебали")
    assert not rage.is_extra_hostile("на работе сегодня полный пиздец")
    assert not rage.is_extra_hostile("кот опять насрал на ковёр")


def test_first_attack_is_warning_second_attack_is_full_rage_without_double_count():
    class FakeBot:
        HOSTILE_RE = re.compile(r"^иди нахуй$", re.IGNORECASE)

        @staticmethod
        def is_serious_text(_text):
            return False

        @staticmethod
        def build_full_system_instruction(*args, **kwargs):
            text = kwargs.get("style_text", args[0] if args else "")
            hostile = rage.is_extra_hostile(text) or bool(FakeBot.HOSTILE_RE.search(text))
            hostile_streak_engine.observe(1, 2, hostile=hostile)
            return "BASE"

    bot = FakeBot()
    rage._install_instruction_patch(bot)

    first = bot.build_full_system_instruction(
        style_text="Говна поел?",
        chat_id=1,
        chat_type="group",
        user_id=2,
    )
    assert hostile_streak_engine.current(1, 2) == 1
    assert "HIT #1" in first
    assert "LIVE RAGE LATCH" not in first

    second = bot.build_full_system_instruction(
        style_text="Хуесос",
        chat_id=1,
        chat_type="group",
        user_id=2,
    )
    assert hostile_streak_engine.current(1, 2) == 2
    assert "LIVE RAGE LATCH" in second
    assert "АБСОЛЮТНЫЙ ПРИОРИТЕТ" in second
    assert "ПРИОСТАНОВИ" in second


def test_hot_neutral_turn_still_gets_hard_rage_override():
    class FakeBot:
        HOSTILE_RE = re.compile(r"^иди нахуй$", re.IGNORECASE)

        @staticmethod
        def is_serious_text(_text):
            return False

        @staticmethod
        def build_full_system_instruction(*args, **kwargs):
            text = kwargs.get("style_text", args[0] if args else "")
            hostile = rage.is_extra_hostile(text) or bool(FakeBot.HOSTILE_RE.search(text))
            hostile_streak_engine.observe(1, 2, hostile=hostile)
            return "BASE"

    bot = FakeBot()
    rage._install_instruction_patch(bot)
    bot.build_full_system_instruction(style_text="иди нахуй", chat_id=1, chat_type="group", user_id=2)
    bot.build_full_system_instruction(style_text="Хуесос", chat_id=1, chat_type="group", user_id=2)

    neutral = bot.build_full_system_instruction(
        style_text="ладно, а сколько будет 17 на 8?",
        chat_id=1,
        chat_type="group",
        user_id=2,
    )
    assert hostile_streak_engine.current(1, 2) == 2
    assert "LIVE RAGE LATCH" in neutral
    assert "Текущая реплика — нормальный вопрос" in neutral


def test_rage_instruction_suspends_soft_tone_layers_not_safety():
    instruction = rage.rage_instruction(2)
    lowered = instruction.lower()
    assert "приостанови" in lowered
    assert "relationship" in lowered
    assert "не деэскалируй" not in lowered or "не становись" in lowered
    assert "контратакуй" in lowered
    assert "псевдодиагноз" in lowered
    assert "реальный медицинский" in lowered
    assert "без реальных угроз" in lowered


def test_deescalation_lecture_is_detected_and_stripped():
    text = (
        "Я не собираюсь продолжать этот разговор. "
        "Ты второй раз повторяешь один и тот же высер. "
        "Давай перейдём к конструктивному диалогу."
    )
    assert rage.contains_deescalation(text)
    stripped = rage.strip_deescalation_sentences(text)
    assert "не собираюсь" not in stripped.lower()
    assert "конструктив" not in stripped.lower()
    assert "второй раз" in stripped.lower()


def test_hot_reply_hard_cap_is_three_sentences_and_240_chars():
    source = (
        "Первый удар по реплике. Второй удар по повтору. "
        "Третий удар по противоречию. Четвёртый уже лишний. "
        + "Очень длинный хвост " * 30
    )
    result = rage.compact_rage_text(source)
    assert len(result) <= rage.RAGE_MAX_CHARS
    assert result.count(".") <= rage.RAGE_MAX_SENTENCES
    assert "Четвёртый" not in result


def test_question_cap_is_larger_but_still_not_a_wall():
    source = "Факт один. Факт два. Факт три. Осадка в конце. Лишняя простыня."
    result = rage.compact_rage_text(
        source,
        max_chars=rage.RAGE_QUESTION_MAX_CHARS,
        max_sentences=rage.RAGE_QUESTION_MAX_SENTENCES,
    )
    assert len(result) <= rage.RAGE_QUESTION_MAX_CHARS
    assert "Лишняя простыня" not in result
