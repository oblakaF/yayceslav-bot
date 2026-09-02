import asyncio

import book_recommendation_runtime as books
import entity_continuity_runtime
import identity_recommendation_runtime as identity


def setup_function():
    books._CACHE.clear()
    books._BOOK_TOPIC_BY_CHAT.clear()
    entity_continuity_runtime._ENTITY_BY_CHAT.clear()


def test_book_intent_supports_russian_and_english():
    assert books.classify_book_recommendation_intent(
        "что почитать если нравится Мастер и Маргарита?"
    ) == "Мастер и Маргарита"
    assert books.classify_book_recommendation_intent(
        "посоветуй 5 книг в духе Пикника на обочине"
    ) == "Пикника на обочине"
    assert books.classify_book_recommendation_intent("books like Dune") == "Dune"


def test_unrelated_question_is_not_book_recommendation():
    assert books.classify_book_recommendation_intent("кто написал Мастер и Маргарита?") == ""
    assert books.classify_book_recommendation_intent("что послушать если нравится MACAN?") == ""


def test_followup_uses_book_local_state_not_generic_entity():
    entity_continuity_runtime.remember_topic(-100, "MACAN")
    assert books.classify_book_recommendation_intent("а ещё?", chat_id=-100) == ""

    books.remember_book_topic(-100, "Мастер и Маргарита", now=100.0)
    state = books._BOOK_TOPIC_BY_CHAT[-100]
    books._BOOK_TOPIC_BY_CHAT[-100] = books.BookTopicState(
        state.title,
        books.time.monotonic(),
    )
    assert books.classify_book_recommendation_intent("а ещё?", chat_id=-100) == "Мастер и Маргарита"


def test_book_topic_state_is_chat_local_and_expires():
    books.remember_book_topic(1, "Dune", now=100.0)
    books.remember_book_topic(2, "Solaris", now=100.0)
    assert books.current_book_topic(1, now=101.0) == "Dune"
    assert books.current_book_topic(2, now=101.0) == "Solaris"
    assert books.current_book_topic(1, now=100.0 + books.BOOK_TOPIC_TTL_SECONDS + 1) == ""
    assert books.current_book_topic(2, now=101.0) == "Solaris"


def test_work_summary_filters_generic_subjects():
    result = books._work_summary(
        {
            "key": "/works/OL1W",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1965,
            "edition_count": 400,
            "subject": ["Fiction", "Science fiction", "Desert planets", "Accessible book"],
        }
    )
    assert result["title"] == "Dune"
    assert result["authors"] == ["Frank Herbert"]
    assert result["subjects"] == ["Science fiction", "Desert planets"]
    assert result["source_url"].endswith("/works/OL1W")


def test_recommend_from_book_ranks_subject_overlap_and_excludes_seed(monkeypatch):
    async def fake_seed(query):
        assert query == "Dune"
        return {
            "key": "/works/seed",
            "title": "Dune",
            "authors": ["Frank Herbert"],
            "first_publish_year": 1965,
            "edition_count": 400,
            "subjects": ["Science fiction", "Adventure", "Politics"],
            "source_url": "https://openlibrary.org/works/seed",
        }

    async def fake_get(path, params):
        assert path == "search.json"
        assert "subject:" in params["q"]
        return {
            "docs": [
                {
                    "key": "/works/seed",
                    "title": "Dune",
                    "author_name": ["Frank Herbert"],
                    "edition_count": 500,
                    "subject": ["Science fiction", "Adventure"],
                },
                {
                    "key": "/works/a",
                    "title": "Book A",
                    "author_name": ["Author A"],
                    "edition_count": 20,
                    "subject": ["Science fiction", "Adventure"],
                },
                {
                    "key": "/works/b",
                    "title": "Book B",
                    "author_name": ["Author B"],
                    "edition_count": 200,
                    "subject": ["Science fiction"],
                },
                {
                    "key": "/works/c",
                    "title": "Book C",
                    "author_name": ["Author C"],
                    "edition_count": 999,
                    "subject": ["Cooking"],
                },
            ]
        }

    monkeypatch.setattr(books, "resolve_seed_work", fake_seed)
    monkeypatch.setattr(books, "_openlibrary_get", fake_get)
    result = asyncio.run(books.recommend_from_book("Dune"))
    assert [item["key"] for item in result["candidates"]] == ["/works/a", "/works/b"]
    assert result["candidates"][0]["subject_overlap"] == 2
    assert result["candidates"][0]["matching_subjects"] == ["Science fiction", "Adventure"]


def test_context_keeps_provider_facts_separate_from_identity_lens():
    prompt = books.build_book_recommendation_context(
        {
            "seed": {"title": "Dune", "authors": ["Frank Herbert"]},
            "seed_subjects": ["Science fiction", "Adventure"],
            "candidates": [
                {
                    "title": "Book A",
                    "authors": ["Author A"],
                    "first_publish_year": 1970,
                    "edition_count": 40,
                    "matching_subjects": ["Science fiction"],
                    "source_url": "https://openlibrary.org/works/a",
                }
            ],
        },
        user_text="что почитать если нравится Dune?",
        identity_lens={"aesthetic": "мрачный индустриальный минимализм", "values": "самостоятельность"},
    )
    assert "Book A — Author A" in prompt
    assert "мрачный индустриальный минимализм" in prompt
    assert "Не добавляй кандидата" in prompt
    assert "не оценка качества" in prompt


def test_identity_lens_is_bounded_to_allowed_fields(monkeypatch):
    monkeypatch.setattr(
        identity.self_canon_runtime,
        "load_canon_sync",
        lambda module, chat_id: {
            "aesthetic": "industrial",
            "values": "independence",
            "profession": "engineer",
            "residence": "Moscow",
            "music": "post-punk",
        },
    )
    lens = identity.load_identity_lens(object(), 7)
    assert lens == {
        "aesthetic": "industrial",
        "values": "independence",
        "music": "post-punk",
    }
