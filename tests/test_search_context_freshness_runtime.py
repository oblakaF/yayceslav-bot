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


def test_install_extends_existing_news_gate_and_passes_combined_query(monkeypatch):
    search_context_runtime._INSTALLED = False
    seen = []

    async def original_search(update, context, query, force_voice=False):
        seen.append(query)

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
    )

    assert search_context_runtime.install(fake_module) is True
    assert fake_module.is_news_query("он вчера прилетел") is True
    assert fake_module.is_news_query("обычный рецепт") is False

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
