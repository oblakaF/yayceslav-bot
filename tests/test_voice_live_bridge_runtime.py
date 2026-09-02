import asyncio
import json
from types import SimpleNamespace

import voice2_runtime
import voice_live_bootstrap_hook
import voice_live_bridge_runtime


def setup_function():
    voice_live_bridge_runtime._VOICE_CONTEXT.clear()
    voice_live_bridge_runtime._CURRENT_VOICE_CONTEXT.set("")


def test_voice_context_is_chat_local_bounded_and_expires():
    voice_live_bridge_runtime._remember_voice_turn(
        100,
        "распиши киновселенную Marvel по фазам",
        "Фазы 1–6 идут по порядку.",
        speaker="Серега",
        now=100.0,
    )
    voice_live_bridge_runtime._remember_voice_turn(
        100,
        "а теперь все фильмы по каждой фазе",
        "Держи список.",
        speaker="Серега",
        now=101.0,
    )

    same_chat = voice_live_bridge_runtime._recent_voice_context(100, now=102.0)
    other_chat = voice_live_bridge_runtime._recent_voice_context(200, now=102.0)
    expired = voice_live_bridge_runtime._recent_voice_context(
        100,
        now=101.0 + voice_live_bridge_runtime.VOICE_CONTEXT_TTL_SECONDS + 1,
    )

    assert "Marvel" in same_chat
    assert "все фильмы по каждой фазе" in same_chat
    assert other_chat == ""
    assert expired == ""


def test_live_rule_preserves_task_and_does_not_treat_profanity_as_hostility():
    normalized = " ".join(voice_live_bridge_runtime._VOICE_LIVE_RULE.split())
    assert "СНАЧАЛА выполни нормальный запрос" in normalized
    assert "САМИ ПО СЕБЕ НЕ ЯВЛЯЮТСЯ hostility" in normalized
    assert "Бля, посоветуй концерты в Саратове" in normalized
    assert "ТОЧНОЕ ИСПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ" in normalized
    assert "что бы ТЫ слушал?" in normalized
    assert "YAY_SELF_CANON" in normalized


def test_prompt_bridge_adds_recent_voice_context_only_to_voice_service_prompt():
    module = SimpleNamespace(
        build_full_system_instruction=lambda style_text, **kwargs: "BASE",
    )
    voice_live_bridge_runtime._install_prompt_bridge(module)
    voice_live_bridge_runtime._CURRENT_VOICE_CONTEXT.set(
        "VOICE CONTEXT — прошлый вопрос был про Marvel"
    )

    voice_instruction = module.build_full_system_instruction(
        "Прослушай сообщение пользователя",
        chat_id=100,
    )
    text_instruction = module.build_full_system_instruction(
        "обычный текстовый вопрос",
        chat_id=100,
    )

    assert "VOICE LIVE SEMANTICS" in voice_instruction
    assert "прошлый вопрос был про Marvel" in voice_instruction
    assert text_instruction == "BASE"


def test_live_normalizer_keeps_line_breaks_and_more_than_old_1000_chars():
    long_answer = "Фаза 1:\n" + ("Железный человек\n" * 90)
    decision = voice_live_bridge_runtime.VoiceLiveDecision(
        transcript="дай полный список фильмов по фазам",
        needs_search=False,
        answer=long_answer,
    )

    original_schema = voice2_runtime.VoiceDecision
    try:
        voice2_runtime.VoiceDecision = voice_live_bridge_runtime.VoiceLiveDecision
        normalized = voice_live_bootstrap_hook._normalize_live_decision(decision)
    finally:
        voice2_runtime.VoiceDecision = original_schema

    assert "\n" in normalized.answer
    assert len(normalized.answer) > 1000
    assert len(normalized.answer) <= voice_live_bridge_runtime.VOICE_LIVE_ANSWER_MAX_CHARS


def test_structured_bridge_strips_and_persists_voice_self_canon(monkeypatch):
    writes = []

    async def fake_structured(bot_module, contents, kwargs):
        return json.dumps(
            {
                "transcript": "если бы ты выбирал себе музыку, что бы слушал?",
                "needs_search": False,
                "search_query": "",
                "answer": (
                    "Я бы поставил экспериментальную электронику и дарквейв.\n"
                    '[[YAY_SELF_CANON {"set":{"music":"экспериментальная электроника и дарквейв"},"drop":[]}]]'
                ),
                "wants_voice": False,
                "memory_summary": "",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(voice2_runtime, "_structured_voice_decision", fake_structured)
    monkeypatch.setattr(
        voice_live_bridge_runtime.self_canon_runtime,
        "apply_canon_changes_sync",
        lambda bot_module, chat_id, updates, drops, source_excerpt: writes.append(
            (chat_id, updates, drops, source_excerpt)
        ),
    )

    voice_live_bridge_runtime._install_structured_bridge(SimpleNamespace())
    wrapped = voice2_runtime._structured_voice_decision
    raw = asyncio.run(
        wrapped(
            SimpleNamespace(),
            [object(), "Прослушай сообщение пользователя"],
            {"chat_id": -100, "user_name": "Серега", "max_output_tokens": 320},
        )
    )
    payload = json.loads(raw)

    assert "YAY_SELF_CANON" not in payload["answer"]
    assert payload["answer"].startswith("Я бы поставил")
    assert writes[0][0] == -100
    assert writes[0][1]["music"] == "экспериментальная электроника и дарквейв"
    context = voice_live_bridge_runtime._recent_voice_context(-100)
    assert "что бы слушал" in context
    assert "экспериментальную электронику" in context


def test_search_voice_context_keeps_current_corrected_entity(monkeypatch):
    async def fake_structured(bot_module, contents, kwargs):
        return json.dumps(
            {
                "transcript": "Нет, группа называется Drummatix, расскажи про неё",
                "needs_search": True,
                "search_query": "Drummatix российская исполнительница",
                "answer": "",
                "wants_voice": False,
                "memory_summary": "",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(voice2_runtime, "_structured_voice_decision", fake_structured)
    voice_live_bridge_runtime._install_structured_bridge(SimpleNamespace())
    raw = asyncio.run(
        voice2_runtime._structured_voice_decision(
            SimpleNamespace(),
            [object(), "Прослушай сообщение пользователя"],
            {"chat_id": 77, "user_name": "Серега"},
        )
    )
    payload = json.loads(raw)
    context = voice_live_bridge_runtime._recent_voice_context(77)

    assert payload["search_query"].startswith("Drummatix")
    assert "Drummatix" in context
    assert "[поиск: Drummatix" in context
