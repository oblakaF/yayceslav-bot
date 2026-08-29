import re

import conflict_fsm_runtime as fsm
import hostile_streak_engine


def setup_function():
    hostile_streak_engine.reset()


def test_phase_boundaries_are_explicit():
    assert fsm.phase_from_heat(0) is fsm.ConflictPhase.NORMAL
    assert fsm.phase_from_heat(1) is fsm.ConflictPhase.WARNING
    assert fsm.phase_from_heat(2) is fsm.ConflictPhase.RAGE
    assert fsm.phase_from_heat(4) is fsm.ConflictPhase.RAGE


def test_extra_hostility_is_direct_not_generic_profanity():
    for text in (
        "Говна поел?",
        "Хуесос",
        "Пес ебливый",
        "Ты ишак",
        "Нюхай хуй",
        "Слился дно",
        "Нищий безмозглый ебанат",
    ):
        assert fsm.is_extra_hostile(text), text

    assert not fsm.is_extra_hostile("бля, пробки заебали")
    assert not fsm.is_extra_hostile("на работе полный пиздец")


def test_first_hit_warning_second_hit_replaces_normal_prompt_with_rage():
    class FakeBot:
        HOSTILE_RE = re.compile(r"^иди нахуй$", re.IGNORECASE)

        @staticmethod
        def current_msk_datetime():
            from datetime import datetime
            return datetime(2026, 8, 28, 12, 0)

        @staticmethod
        def build_full_system_instruction(*args, **kwargs):
            text = kwargs.get("style_text", args[0] if args else "")
            hostile = fsm.is_extra_hostile(text) or bool(FakeBot.HOSTILE_RE.search(text))
            hostile_streak_engine.observe(1, 2, hostile=hostile)
            return "NORMAL SOCIAL PROMPT"

    bot = FakeBot()
    fsm._install_instruction_router(bot)

    first = bot.build_full_system_instruction(
        style_text="иди нахуй",
        chat_id=1,
        chat_type="group",
        user_id=2,
    )
    assert "NORMAL SOCIAL PROMPT" in first
    assert "CONFLICT FSM = WARNING" in first
    assert hostile_streak_engine.current(1, 2) == 1

    second = bot.build_full_system_instruction(
        style_text="Хуесос",
        chat_id=1,
        chat_type="group",
        user_id=2,
        user_name="Ross",
        recent_messages=["Ross: иди нахуй", "Яйцеслав: полегче"],
    )
    assert hostile_streak_engine.current(1, 2) == 2
    assert "CONFLICT FSM = RAGE" in second
    assert "NORMAL SOCIAL PROMPT" not in second
    assert "relationship/mood/humor/roughness" in second
    assert "1–3 коротких предложения" in second


def test_rage_question_prioritizes_factual_answer_and_search_results():
    class FakeBot:
        HOSTILE_RE = re.compile(r"^иди нахуй$", re.IGNORECASE)

        @staticmethod
        def current_msk_datetime():
            from datetime import datetime
            return datetime(2026, 8, 28, 12, 0)

    prompt = fsm.build_rage_system_prompt(
        FakeBot(),
        current_text="Сколько длится новый ролик?",
        current_hostile=False,
        user_name="Ross",
        recent_messages=["Ross: иди нахуй", "Ross: хуесос"],
    )
    lowered = prompt.lower()
    assert "сначала дай точный" in lowered
    assert "результаты поиска" in lowered
    assert "важнее твоих прошлых утверждений" in lowered
    assert "одну короткую злую колкость" in lowered


def test_external_evidence_path_can_advance_same_fsm_once():
    class FakeBot:
        HOSTILE_RE = re.compile(r"$a")

    assert fsm.observe_external_text(FakeBot(), 10, 20, "Ты ишак") == 1
    assert fsm.phase(10, 20) is fsm.ConflictPhase.WARNING
    assert fsm.observe_external_text(FakeBot(), 10, 20, "Хуесос") == 2
    assert fsm.phase(10, 20) is fsm.ConflictPhase.RAGE


def test_rage_reply_cap_stays_compact():
    source = (
        "Первый точный панч. Второй панч по противоречию. "
        "Третий короткий добивающий панч. Четвёртая лишняя лекция. "
        + "Хвост " * 100
    )
    result = fsm.compact_text(
        source,
        max_chars=fsm.RAGE_MAX_CHARS,
        max_sentences=fsm.RAGE_MAX_SENTENCES,
    )
    assert len(result) <= fsm.RAGE_MAX_CHARS
    assert "Четвёртая" not in result
