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
        "Поплачь",
        "Проебал слабость обоссанная",
        "Ущербна только твоя мамаша тут",
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
        style_text="Пес ебливый",
        chat_id=1,
        chat_type="group",
        user_id=2,
    )
    assert hostile_streak_engine.current(1, 2) == 1
    assert "первый прямой наезд" in first.lower()
    assert "LIVE RAGE OVERRIDE" not in first

    second = bot.build_full_system_instruction(
        style_text="Хуесос",
        chat_id=1,
        chat_type="group",
        user_id=2,
    )
    assert hostile_streak_engine.current(1, 2) == 2
    assert "LIVE RAGE OVERRIDE" in second
    assert "НЕ ДЕЭСКАЛИРУЙ" in second
    assert "последнее слово" in second


def test_rage_instruction_is_compact_counterattack_not_surrender_policy():
    instruction = rage.rage_instruction(2)
    lowered = instruction.lower()
    assert "контекст" in lowered
    assert "не деэскалируй" in lowered
    assert "не сливайся" in lowered
    assert "псевдодиагноз" in lowered
    assert "реальный медицинский" in lowered
    assert "280 знаков" in lowered


def test_deescalation_lecture_is_detected():
    assert rage.contains_deescalation("Я не собираюсь продолжать этот разговор.")
    assert rage.contains_deescalation("Давай перейдём к конструктивному диалогу.")
    assert rage.contains_deescalation("Этот диалог окончен.")
    assert not rage.contains_deescalation("Ты второй раз повторяешь один и тот же высер.")


def test_hot_reply_hard_cap_is_three_sentences_and_280_chars():
    source = (
        "Первый удар по реплике. Второй удар по повтору. "
        "Третий удар по противоречию. Четвёртый уже лишний. "
        + "Очень длинный хвост " * 30
    )
    result = rage.compact_rage_text(source)
    assert len(result) <= rage.RAGE_MAX_CHARS
    assert result.count(".") <= rage.RAGE_MAX_SENTENCES
    assert "Четвёртый" not in result
