import random

import bot
import feedback_engine
import humanizer_engine
import personality


def _trace(mode="normal", intent_name="group_banter"):
    return feedback_engine.ResponseTrace(
        chat_id=1,
        chat_type="group",
        conversation_mode=mode,
        message_intent=intent_name,
    )


def test_live_short_insults_are_hostile():
    for text in ("Сучка", "еблан", "долбоеб", "нахуй мне гугл если ты сучка"):
        assert personality.detect_conversation_mode(text) == "hostile"


def test_live_wall_of_text_complaints_are_challenge():
    for text in ("ебать опять простыня", "душный хуй", "много текста", "короче отвечай"):
        assert personality.detect_conversation_mode(text) in {"challenge", "hostile"}


def test_raw_conflict_is_compacted_even_if_trace_was_wrongly_normal():
    long_answer = (
        "Гугл тебе затем, чтобы ты мысли формулировать научился. "
        "А теперь начинается второй абзац с ненужной лекцией про аргументы и воспитание. "
        "И третий абзац тоже не нужен."
    )
    plan = humanizer_engine.humanize_reply(
        long_answer,
        user_text="нахуй мне гугл если ты сучка",
        trace=_trace("normal", "group_banter"),
        rng=random.Random(3),
    )
    assert len(" ".join(plan.messages)) <= 95
    assert "третий абзац" not in " ".join(plan.messages)


def test_lazy_never_fires_on_insult_even_with_zero_rng():
    class ZeroRng:
        def random(self):
            return 0.0
        def uniform(self, a, b):
            return a
        def choice(self, seq):
            return seq[0]

    plan = humanizer_engine.humanize_reply(
        "Сам ты сучка.",
        user_text="сучка",
        trace=_trace("normal", "group_banter"),
        rng=ZeroRng(),
    )
    assert "гугл" not in " ".join(plan.messages).lower()
    assert not plan.effect.startswith("lazy")


def test_lazy_is_still_possible_on_real_small_question():
    class ZeroRng:
        def random(self):
            return 0.0
        def uniform(self, a, b):
            return a
        def choice(self, seq):
            return seq[0]

    plan = humanizer_engine.humanize_reply(
        "Потому что так быстрее.",
        user_text="кто победит?",
        trace=_trace("normal", "question"),
        rng=ZeroRng(),
    )
    assert plan.effect == "lazy_refusal"


def test_default_aggressive_instruction_in_group_and_private():
    group_instruction = bot.build_full_system_instruction(
        "привет",
        {"character": "classic", "response_style": "bold", "roughness": "high", "response_length": "normal"},
        chat_type="group",
    )
    assert "РЕЖИМ ПО УМОЛЧАНИЮ В ГРУППЕ: агрессивный Яйцеслав" in group_instruction

    private_instruction = bot.build_full_system_instruction(
        "привет",
        {"character": "classic", "response_style": "bold", "roughness": "high", "response_length": "normal"},
        chat_type="private",
    )
    assert "ХАРАКТЕР ПО УМОЛЧАНИЮ: агрессивный Яйцеслав" in private_instruction


def test_calm_setting_disables_default_aggressive_layer():
    instruction = bot.build_full_system_instruction(
        "привет",
        {"character": "calm", "response_style": "normal", "roughness": "low", "response_length": "normal"},
        chat_type="group",
    )
    assert "РЕЖИМ ПО УМОЛЧАНИЮ В ГРУППЕ: агрессивный Яйцеслав" not in instruction
