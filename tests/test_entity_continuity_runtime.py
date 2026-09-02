import asyncio
from types import SimpleNamespace

import entity_continuity_runtime as entity


def setup_function():
    entity._ENTITY_BY_CHAT.clear()
    entity._INSTALLED = False


def test_extracts_explicit_people_company_and_object_topics():
    assert entity.extract_explicit_topic("Кто такой Дженсен Хуанг?") == "Дженсен Хуанг"
    assert entity.extract_explicit_topic("расскажи про NVIDIA") == "NVIDIA"
    assert entity.extract_explicit_topic("что думаешь про фильм Интерстеллар?") == "Интерстеллар"


def test_anaphoric_followup_reuses_last_topic():
    entity.remember_topic(-100, "Дженсен Хуанг", now=100.0)
    resolved = entity.resolve_followup(-100, "а сколько ему лет?")
    assert resolved == "Дженсен Хуанг. Уточнение пользователя: а сколько ему лет?"


def test_new_explicit_topic_replaces_old_one():
    entity.remember_topic(-100, "Дженсен Хуанг")
    assert entity.resolve_followup(-100, "расскажи про Сэма Альтмана") == "расскажи про Сэма Альтмана"
    assert entity.current_topic(-100) == "Сэма Альтмана"


def test_unrelated_operational_question_does_not_reuse_entity():
    entity.remember_topic(-100, "Дженсен Хуанг")
    text = "как бы ты исправил этот код?"
    assert entity.is_anaphoric_followup(text) is False
    assert entity.resolve_followup(-100, text) == text


def test_topic_is_chat_local_and_expires():
    entity.remember_topic(-100, "NVIDIA", now=10.0)
    assert entity.current_topic(-200, now=20.0) == ""
    assert entity.current_topic(-100, now=20.0) == "NVIDIA"
    assert entity.current_topic(-100, now=10.0 + entity.ENTITY_TTL_SECONDS + 1) == ""


def test_ask_wrapper_injects_hint_only_for_anaphoric_followup():
    calls = []

    async def ask_gemini(contents, *args, **kwargs):
        calls.append((contents, kwargs))
        return "ok"

    async def perform_web_search(**kwargs):
        return kwargs

    module = SimpleNamespace(ask_gemini=ask_gemini, perform_web_search=perform_web_search)
    entity._patch_ask_gemini(module)

    asyncio.run(
        module.ask_gemini(
            "Кто такой Дженсен Хуанг?",
            chat_id=-100,
            user_id=42,
            recent_messages=[],
        )
    )
    asyncio.run(
        module.ask_gemini(
            "а где он сейчас работает?",
            chat_id=-100,
            user_id=42,
            recent_messages=["свежий контекст"],
        )
    )

    recent = calls[-1][1]["recent_messages"]
    assert recent[0] == "свежий контекст"
    assert any("Дженсен Хуанг" in item and "ENTITY CONTINUITY" in item for item in recent)


def test_ask_wrapper_does_not_mix_chats_or_internal_calls():
    calls = []

    async def ask_gemini(contents, *args, **kwargs):
        calls.append(kwargs)
        return "ok"

    module = SimpleNamespace(ask_gemini=ask_gemini, perform_web_search=lambda **kwargs: None)
    entity._patch_ask_gemini(module)
    entity.remember_topic(-100, "NVIDIA")

    asyncio.run(module.ask_gemini("а где она находится?", chat_id=-200, user_id=7, recent_messages=[]))
    asyncio.run(module.ask_gemini("а где она находится?", chat_id=-100, recent_messages=[]))

    assert calls[0]["recent_messages"] == []
    assert calls[1]["recent_messages"] == []


def test_search_wrapper_resolves_pronoun_before_existing_search_stack():
    seen = []

    async def ask_gemini(*args, **kwargs):
        return "ok"

    async def perform_web_search(update, context, query, force_voice=False):
        seen.append(query)

    module = SimpleNamespace(ask_gemini=ask_gemini, perform_web_search=perform_web_search)
    entity._patch_web_search(module)
    entity.remember_topic(-100, "OpenAI")

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=-100))
    asyncio.run(
        module.perform_web_search(
            update=update,
            context=SimpleNamespace(),
            query="а где она сейчас находится?",
        )
    )

    assert seen == ["OpenAI. Уточнение пользователя: а где она сейчас находится?"]
