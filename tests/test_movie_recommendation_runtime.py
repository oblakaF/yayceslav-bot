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


def test_keyword_helpers_support_movie_and_alternate_shapes():
    assert rec._keyword_ids({"keywords": [{"id": 10, "name": "space"}]}) == [10]
    assert rec._keyword_ids({"results": [{"id": 11, "name": "future"}]}) == [11]
    assert rec._keyword_names({"keywords": [{"id": 10, "name": " space travel "}]}) == ["space travel"]


def test_relation_merge_preserves_both_provider_signals():
    rows = rec._merge_relation_candidates(
        1,
        {"results": [{"id": 2, "title": "Arrival", "genre_ids": [878]}]},
        {"results": [{"id": 2, "title": "Arrival", "genre_ids": [878]}]},
    )
    assert len(rows) == 1
    assert set(rows[0]["tmdb_relations"]) == {"recommendations", "similar"}
    assert rows[0]["source_count"] == 2


def test_discover_merge_adds_third_candidate_pool():
    rows = rec._merge_relation_candidates(
        1,
        {"results": []},
        {"results": []},
        discover_genres_payload={"results": [{"id": 2, "title": "Genre Match", "genre_ids": [878, 12]}]},
        discover_keywords_payload={"results": [{"id": 3, "title": "Keyword Match", "genre_ids": [878, 12]}]},
    )
    by_id = {item["id"]: item for item in rows}
    assert "discover_genres" in by_id[2]["tmdb_relations"]
    assert "discover_keywords" in by_id[3]["tmdb_relations"]


def test_discover_params_require_seed_genres_and_or_keywords():
    params = rec._discover_params([878, 12], [101, 102], keyword_mode=True)
    assert params["with_genres"] == "878,12"
    assert params["with_keywords"] == "101|102"
    assert params["vote_count.gte"] == 50


def test_similarity_score_beats_raw_popularity():
    seed_genres = [878, 12]
    seed_keywords = [101, 102]
    relevant = rec._apply_similarity_features(
        {
            "id": 2,
            "title": "Relevant",
            "genre_ids": [878, 12],
            "keyword_ids": [101, 102],
            "keyword_names": ["space opera", "desert planet"],
            "tmdb_relations": ["similar", "recommendations"],
            "relation_ranks": {"similar": 4, "recommendations": 8},
            "vote_count": 900,
            "vote_average": 7.1,
            "popularity": 8.0,
        },
        seed_genres=seed_genres,
        seed_keywords=seed_keywords,
    )
    popular_but_weak = rec._apply_similarity_features(
        {
            "id": 3,
            "title": "Popular but weak",
            "genre_ids": [18],
            "keyword_ids": [],
            "keyword_names": [],
            "tmdb_relations": ["recommendations"],
            "relation_ranks": {"recommendations": 2},
            "vote_count": 30000,
            "vote_average": 8.7,
            "popularity": 100.0,
        },
        seed_genres=seed_genres,
        seed_keywords=seed_keywords,
    )
    assert relevant["relevance_score"] > popular_but_weak["relevance_score"]
    assert relevant["genre_overlap_ids"] == [878, 12]
    assert relevant["keyword_overlap_ids"] == [101, 102]
    assert relevant["passes_genre_gate"] is True
    assert popular_but_weak["passes_genre_gate"] is False


def test_generic_keyword_cannot_bypass_genre_gate():
    candidate = rec._apply_similarity_features(
        {
            "id": 99,
            "title": "Memento-like",
            "genre_ids": [53, 18],
            "keyword_ids": [777],
            "keyword_names": ["memory"],
            "tmdb_relations": ["recommendations"],
            "relation_ranks": {"recommendations": 1},
            "vote_count": 25000,
            "vote_average": 8.4,
            "popularity": 80,
        },
        seed_genres=[878, 12],
        seed_keywords=[777],
    )
    assert candidate["keyword_overlap_ids"] == [777]
    assert candidate["genre_overlap_ids"] == []
    assert candidate["passes_genre_gate"] is False


def test_recommend_from_movie_enriches_and_ranks_by_relevance(monkeypatch):
    async def fake_seed(query):
        assert query == "Дюна"
        return {"id": 10, "title": "Дюна", "year": 2021, "genre_ids": [878, 12]}

    async def fake_tmdb(path, params=None):
        if path == "movie/10":
            return {
                "genres": [{"id": 878, "name": "Science Fiction"}, {"id": 12, "name": "Adventure"}],
                "keywords": {"keywords": [{"id": 101, "name": "desert planet"}, {"id": 102, "name": "space opera"}, {"id": 777, "name": "memory"}]},
                "recommendations": {
                    "results": [
                        {"id": 11, "title": "Very Popular Thriller", "genre_ids": [53, 18], "vote_count": 30000, "vote_average": 8.8, "popularity": 100},
                        {"id": 12, "title": "Good Sci-Fi", "genre_ids": [878, 12], "vote_count": 1500, "vote_average": 7.4, "popularity": 8},
                    ]
                },
                "similar": {
                    "results": [
                        {"id": 12, "title": "Good Sci-Fi", "genre_ids": [878, 12], "vote_count": 1500, "vote_average": 7.4, "popularity": 8},
                        {"id": 13, "title": "Other Sci-Fi", "genre_ids": [878], "vote_count": 800, "vote_average": 7.0, "popularity": 5},
                    ]
                },
            }
        if path == "discover/movie":
            if params and params.get("with_keywords"):
                return {"results": [{"id": 14, "title": "Discover Keyword Sci-Fi", "genre_ids": [878, 12], "vote_count": 600, "vote_average": 7.2, "popularity": 4}]}
            return {"results": [{"id": 15, "title": "Discover Genre Sci-Fi", "genre_ids": [878, 12], "vote_count": 700, "vote_average": 7.0, "popularity": 4}]}
        if path == "movie/12/keywords":
            return {"keywords": [{"id": 101, "name": "desert planet"}, {"id": 102, "name": "space opera"}]}
        if path == "movie/13/keywords":
            return {"keywords": [{"id": 102, "name": "space opera"}]}
        if path == "movie/14/keywords":
            return {"keywords": [{"id": 101, "name": "desert planet"}]}
        if path == "movie/15/keywords":
            return {"keywords": []}
        if path == "movie/11/keywords":
            return {"keywords": [{"id": 777, "name": "memory"}]}
        raise AssertionError(path)

    monkeypatch.setattr(rec, "resolve_seed_movie", fake_seed)
    monkeypatch.setattr(rec, "_tmdb_get", fake_tmdb)
    result = asyncio.run(rec.recommend_from_movie("Дюна"))
    ids = [item["id"] for item in result["candidates"]]
    assert ids[0] == 12
    assert 11 not in ids
    assert 14 in ids
    assert 15 in ids
    assert result["candidates"][0]["keyword_overlap_names"] == ["desert planet", "space opera"]
    assert "recommendations" in result["candidates"][0]["tmdb_relations"]
    assert "similar" in result["candidates"][0]["tmdb_relations"]


def test_context_keeps_provider_facts_separate_from_identity():
    prompt = rec.build_movie_recommendation_context(
        {
            "seed": {
                "title": "Интерстеллар",
                "year": 2014,
                "genre_ids": [878, 12],
                "keyword_names": ["space travel", "wormhole"],
            },
            "candidates": [
                {
                    "id": 11,
                    "title": "Arrival",
                    "year": 2016,
                    "tmdb_relation": "recommendations+similar",
                    "vote_average": 8.0,
                    "vote_count": 9000,
                    "popularity": 10.0,
                    "genre_overlap_ids": [878],
                    "keyword_overlap_names": ["space travel"],
                    "relevance_score": 120.5,
                    "overview": "First contact drama",
                    "source_url": "https://www.themoviedb.org/movie/11",
                }
            ],
        },
        user_text="что посмотреть если нравится Интерстеллар?",
        identity_lens={"aesthetic": "мрачный техно-минимализм", "values": "любопытство"},
    )
    assert "мрачный техно-минимализм" in prompt
    assert "в self-canon автоматически" in prompt
    assert "shared_genres=Science Fiction" in prompt
    assert "shared_keywords=space travel" in prompt
    assert "лучше назвать меньше" in prompt
    assert "один общий plot-keyword не считается достаточным" in prompt
    assert "Arrival" in prompt
