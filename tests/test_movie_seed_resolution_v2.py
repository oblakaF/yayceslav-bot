import asyncio

import movie_recommendation_runtime as movie_runtime
import movie_seed_resolution_v2 as seed_v2


def setup_function():
    movie_runtime._CACHE.clear()


def test_russian_case_variants_cover_live_dune_and_matrix_forms():
    assert "Дюна" in seed_v2.title_variants("Дюны")
    assert "Матрица" in seed_v2.title_variants("Матрицу")


def test_director_genitive_variant_is_normalized():
    assert "Вильнев" in seed_v2.director_name_variants("Вильнева")
    assert "Нолан" in seed_v2.director_name_variants("Нолана")


def test_parse_seed_query_extracts_year_and_explicit_director():
    parsed = seed_v2.parse_seed_query("Дюна 2021 режиссера Дени Вильнева")
    assert parsed.title == "Дюна"
    assert parsed.year == 2021
    assert parsed.director_hint == "Дени Вильнева"


def test_inflected_dune_prefers_real_villeneuve_catalog_hit(monkeypatch):
    async def fake_tmdb(path, params=None):
        assert path == "search/movie"
        query = params["query"]
        if query == "Дюны":
            return {
                "results": [
                    {
                        "id": 99,
                        "title": "Дюны",
                        "original_title": "Dunes",
                        "release_date": "2021-04-01",
                        "genre_ids": [53, 18],
                        "vote_count": 5,
                        "vote_average": 4.0,
                        "popularity": 0.2,
                    }
                ]
            }
        if query == "Дюна":
            return {
                "results": [
                    {
                        "id": 438631,
                        "title": "Дюна",
                        "original_title": "Dune",
                        "release_date": "2021-09-15",
                        "genre_ids": [878, 12],
                        "vote_count": 14000,
                        "vote_average": 7.8,
                        "popularity": 55.0,
                    }
                ]
            }
        raise AssertionError(query)

    monkeypatch.setattr(movie_runtime, "_tmdb_get", fake_tmdb)
    result = asyncio.run(seed_v2.resolve_seed_movie("Дюны"))
    assert result["id"] == 438631
    assert result["original_title"] == "Dune"
    assert result["genre_ids"] == [878, 12]


def test_bare_villeneuve_qualifier_is_verified_through_person_and_credits(monkeypatch):
    async def fake_tmdb(path, params=None):
        params = params or {}
        if path == "search/movie":
            query = params["query"].casefold()
            if query == "дюна вильнева":
                return {"results": []}
            if query == "дюна":
                return {
                    "results": [
                        {
                            "id": 10,
                            "title": "Дюна",
                            "original_title": "Dune",
                            "release_date": "2021-09-15",
                            "genre_ids": [878, 12],
                            "vote_count": 14000,
                            "vote_average": 7.8,
                            "popularity": 55.0,
                        },
                        {
                            "id": 11,
                            "title": "Дюна",
                            "original_title": "Dune",
                            "release_date": "1984-12-14",
                            "genre_ids": [878, 12],
                            "vote_count": 3000,
                            "vote_average": 6.2,
                            "popularity": 20.0,
                        },
                    ]
                }
            raise AssertionError(query)
        if path == "search/person":
            assert params["query"].casefold() in {"вильнева", "вильнев"}
            return {
                "results": [
                    {
                        "id": 137427,
                        "name": "Denis Villeneuve",
                        "known_for_department": "Directing",
                    }
                ]
            }
        if path == "movie/10/credits":
            return {"crew": [{"id": 137427, "name": "Denis Villeneuve", "job": "Director"}]}
        if path == "movie/11/credits":
            return {"crew": [{"id": 5602, "name": "David Lynch", "job": "Director"}]}
        raise AssertionError(path)

    monkeypatch.setattr(movie_runtime, "_tmdb_get", fake_tmdb)
    result = asyncio.run(seed_v2.resolve_seed_movie("дюна вильнева"))
    assert result["id"] == 10
    assert result["year"] == 2021
    assert result["seed_director_hint"].casefold() == "вильнева"
    assert result["seed_director_verified"] is True


def test_year_qualifier_selects_requested_adaptation(monkeypatch):
    async def fake_tmdb(path, params=None):
        assert path == "search/movie"
        assert params["query"] == "Дюна"
        return {
            "results": [
                {
                    "id": 10,
                    "title": "Дюна",
                    "original_title": "Dune",
                    "release_date": "2021-09-15",
                    "genre_ids": [878, 12],
                    "vote_count": 14000,
                    "popularity": 55.0,
                },
                {
                    "id": 11,
                    "title": "Дюна",
                    "original_title": "Dune",
                    "release_date": "1984-12-14",
                    "genre_ids": [878, 12],
                    "vote_count": 3000,
                    "popularity": 20.0,
                },
            ]
        }

    monkeypatch.setattr(movie_runtime, "_tmdb_get", fake_tmdb)
    result = asyncio.run(seed_v2.resolve_seed_movie("Дюна 1984"))
    assert result["id"] == 11
    assert result["year"] == 1984


def test_weak_unrelated_title_is_rejected_instead_of_poisoning_recommendations(monkeypatch):
    async def fake_tmdb(path, params=None):
        assert path == "search/movie"
        return {
            "results": [
                {
                    "id": 77,
                    "title": "Прибрежные воспоминания",
                    "original_title": "Coastal Memories",
                    "release_date": "2021-01-01",
                    "genre_ids": [53, 18],
                    "vote_count": 20000,
                    "popularity": 90.0,
                }
            ]
        }

    monkeypatch.setattr(movie_runtime, "_tmdb_get", fake_tmdb)
    assert asyncio.run(seed_v2.resolve_seed_movie("Дюны")) is None


def test_imported_patch_is_production_resolver():
    assert movie_runtime.resolve_seed_movie is seed_v2.resolve_seed_movie
