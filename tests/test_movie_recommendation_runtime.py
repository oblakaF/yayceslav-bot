import asyncio

import movie_recommendation_runtime as rec


def setup_function():
    rec._CACHE.clear()
    rec._MOVIE_TOPIC_BY_CHAT.clear()


def test_movie_intent_supports_russian_and_english():
    assert rec.classify_movie_recommendation_intent("что посмотреть если нравится Интерстеллар?") == "Интерстеллар"
    assert rec.classify_movie_recommendation_intent("посоветуй 5 фильмов в духе Дюна") == "Дюна"
    assert rec.classify_movie_recommendation_intent("movies like Blade Runner 2049") == "Blade Runner 2049"


def test_unrelated_requests_do_not_route_to_movies():
    assert rec.classify_movie_recommendation_intent("что почитать если нравится Дюна?") == ""
    assert rec.classify_movie_recommendation_intent("что послушать если нравится MACAN?") == ""


def test_movie_followup_is_category_local_and_expires():
    assert rec.classify_movie_recommendation_intent("а ещё?", chat_id=-100) == ""
    rec.remember_movie_topic(-100, "Интерстеллар", 157336, now=100.0)
    assert rec.current_movie_topic(-100, now=101.0).title == "Интерстеллар"
    assert rec.current_movie_topic(-200, now=101.0) is None
    assert rec.current_movie_topic(-100, now=100.0 + rec.MOVIE_TOPIC_TTL_SECONDS + 1) is None


def test_token_absent_disables_provider(monkeypatch):
    monkeypatch.delenv("TMDB_API_TOKEN", raising=False)
    assert rec.tmdb_api_token() == ""
    assert asyncio.run(rec._tmdb_get("search/movie", {"query": "Dune"})) is None


def test_movie_summary_normalizes_catalog_fields():
    item = rec._movie_summary(
        {
            "id": 1,
            "title": "Дюна",
            "original_title": "Dune",
            "release_date": "2021-09-15",
            "overview": "  sci-fi   story  ",
            "genre_ids": [12, 878],
            "vote_average": 8.1,
            "vote_count": 5000,
            "popularity": 42.5,
        }
    )
    assert item["title"] == "Дюна"
    assert item["year"] == 2021
    assert item["overview"] == "sci-fi story"
    assert item["source_url"].endswith("/movie/1")


def test_recommend_from_movie_merges_recommendations_and_similar(monkeypatch):
    async def fake_seed(query):
        assert query == "Интерстеллар"
        return {"id": 10, "title": "Интерстеллар", "year": 2014}

    async def fake_tmdb(path, params=None):
        if path.endswith("/recommendations"):
            return {
                "results": [
                    {"id": 11, "title": "Arrival", "release_date": "2016-01-01", "vote_average": 8, "vote_count": 9000, "popularity": 10},
                    {"id": 12, "title": "Moon", "release_date": "2009-01-01", "vote_average": 7.6, "vote_count": 4000, "popularity": 8},
                ]
            }
        return {
            "results": [
                {"id": 11, "title": "Arrival", "release_date": "2016-01-01", "vote_average": 8, "vote_count": 9000, "popularity": 10},
                {"id": 13, "title": "Contact", "release_date": "1997-01-01", "vote_average": 7.4, "vote_count": 7000, "popularity": 6},
            ]
        }

    monkeypatch.setattr(rec, "resolve_seed_movie", fake_seed)
    monkeypatch.setattr(rec, "_tmdb_get", fake_tmdb)
    result = asyncio.run(rec.recommend_from_movie("Интерстеллар"))
    ids = [item["id"] for item in result["candidates"]]
    assert ids == [11, 13, 12]
    assert result["candidates"][0]["tmdb_relation"] == "recommendations"


def test_context_keeps_provider_facts_separate_from_identity():
    prompt = rec.build_movie_recommendation_context(
        {
            "seed": {"title": "Интерстеллар", "year": 2014},
            "candidates": [
                {
                    "id": 11,
                    "title": "Arrival",
                    "year": 2016,
                    "tmdb_relation": "recommendations",
                    "vote_average": 8.0,
                    "vote_count": 9000,
                    "popularity": 10.0,
                    "overview": "First contact drama",
                    "source_url": "https://www.themoviedb.org/movie/11",
                }
            ],
        },
        user_text="что посмотреть если нравится Интерстеллар?",
        identity_lens={"aesthetic": "мрачный техно-минимализм", "values": "любопытство"},
    )
    assert "мрачный техно-минимализм" in prompt
    assert "не меняет self-canon" in prompt
    assert "Arrival" in prompt
