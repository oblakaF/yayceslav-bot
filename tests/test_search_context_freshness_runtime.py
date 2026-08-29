import asyncio
from types import SimpleNamespace

import search_context_runtime


def test_relative_time_is_treated_as_freshness():
    for text in (
        "он вчера прилетел",
        "что сегодня произошло",
        "проверь свежие новости",
        "это только что случилось",
        "latest CIA Moscow visit",
    ):
        assert search_context_runtime.is_freshness_query(text)

    assert not search_context_runtime.is_freshness_query("как сварить рис")


def test_natural_explicit_search_and_proof_followups_are_routed():
    assert search_context_runtime.extract_natural_search_query(
        "Ну ты проверь а Интернете"
    ) == ""
    assert search_context_runtime.extract_natural_search_query(
        "Ну ты проверь в интернете курс биткоина"
    ) == "курс биткоина"
    assert search_context_runtime.extract_natural_search_query(
        "курс биткоина проверь в интернете"
    ) == "курс биткоина"
    assert search_context_runtime.extract_natural_search_query(
        "А по фактам ты проверил новости?"
    ) == ""
    assert search_context_runtime.extract_natural_search_query(
        "А ссылки где? Или ты сам придумал новости"
    ) == ""
    assert search_context_runtime.extract_natural_search_query(
        "покажи источники"
    ) == ""

    # Accountability alone must not silently spend a web-search request.
    assert search_context_runtime.extract_natural_search_query(
        "ты не проверяешь факты"
    ) is None


def test_weak_fresh_followup_reuses_previous_group_topic():
    class FakeModule:
        GROUP_MEMORY = {
            -100: [
                (1.0, "user", "Ross", "Там ЦРУ прилетало в Москву, зачем?"),
                (2.0, "assistant", None, "старый ответ"),
            ]
        }

        @staticmethod
        def extract_search_query(text):
            return None

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=-100, type="group"))
    context = SimpleNamespace(user_data={})

    combined = search_context_runtime._combine_with_previous_topic(
        FakeModule,
        update,
        context,
        "не вот прям вчера прилетел",
    )
    assert "ЦРУ прилетало в Москву" in combined
    assert "вчера прилетел" in combined


def test_search_source_proof_appends_real_urls_if_model_omits_them():
    async def original_ask(contents, *args, **kwargs):
        return "Короткая сводка без ссылок."

    fake_module = SimpleNamespace(ask_gemini=original_ask)
    search_context_runtime._install_search_source_proof(fake_module)

    prompt = """
Пользователь попросил найти актуальную информацию в интернете.
Результаты поиска:
Результат 1\nСсылка: https://example.com/one
Результат 2\nСсылка: https://example.org/two
Правила формата ответа:
- в конце добавь раздел «Источники»;
"""
    answer = asyncio.run(fake_module.ask_gemini(prompt))
    assert "Источники:" in answer
    assert "https://example.com/one" in answer
    assert "https://example.org/two" in answer


def test_search_source_proof_does_not_touch_voice_search_prompt():
    async def original_ask(contents, *args, **kwargs):
        return "Короткая устная сводка."

    fake_module = SimpleNamespace(ask_gemini=original_ask)
    search_context_runtime._install_search_source_proof(fake_module)

    prompt = """
Результаты поиска:
Ссылка: https://example.com/one
Ссылка: https://example.org/two
Не перечисляй ссылки и не произноси адреса сайтов.
"""
    answer = asyncio.run(fake_module.ask_gemini(prompt))
    assert answer == "Короткая устная сводка."


def test_no_fake_browsing_instruction_is_added_to_normal_model_calls():
    fake_module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE"
    )
    search_context_runtime._install_no_fake_browsing_instruction(fake_module)
    instruction = fake_module.build_full_system_instruction("че по крипте")
    assert "Не утверждай, что ты «проверил в интернете»" in instruction
    assert "Результаты поиска:" in instruction


def test_install_extends_news_gate_patches_extractor_and_passes_combined_query(monkeypatch):
    search_context_runtime._INSTALLED = False
    seen = []

    async def original_search(update, context, query, force_voice=False):
        seen.append(query)

    async def original_ask(contents, *args, **kwargs):
        return "ok"

    fake_module = SimpleNamespace(
        GROUP_MEMORY={
            -100: [
                (1.0, "user", "Ross", "Там ЦРУ прилетало в Москву глянь в инете зачем?"),
            ]
        },
        extract_search_query=lambda text: None,
        perform_web_search=original_search,
        is_news_query=lambda query: "новости" in query.lower(),
        enforce_rate_limit=None,
        ask_gemini=original_ask,
        build_full_system_instruction=lambda *args, **kwargs: "BASE",
    )

    assert search_context_runtime.install(fake_module) is True
    assert fake_module.is_news_query("он вчера прилетел") is True
    assert fake_module.is_news_query("обычный рецепт") is False
    assert fake_module.extract_search_query("Ну ты проверь а Интернете") == ""

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=-100, type="group"))
    context = SimpleNamespace(user_data={})
    asyncio.run(
        fake_module.perform_web_search(
            update,
            context,
            "не вот прям вчера прилетел",
        )
    )
    assert len(seen) == 1
    assert "ЦРУ прилетало в Москву" in seen[0]
    assert "Уточнение пользователя" in seen[0]
