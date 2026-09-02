import asyncio

import game_recommendation_runtime as rec


def setup_function():
    rec._CACHE.clear()
    rec._GAME_TOPIC_BY_CHAT.clear()


def test_game_intent_supports_russian_and_english():
    assert rec.classify_game_recommendation_intent("во что поиграть если нравится Cyberpunk 2077?") == "Cyberpunk 2077"
    assert rec.classify_game_recommendation_intent("посоветуй 5 игр в духе Disco Elysium") == "Disco Elysium"
    assert rec.classify_game_recommendation_intent("games like Elden Ring") == "Elden Ring"


def test_unrelated_categories_do_not_route_to_games():
    assert rec.classify_game_recommendation_intent("что посмотреть если нравится Интерстеллар?") == ""
    assert rec.classify_game_recommendation_intent("что почитать если нравится Дюна?") == ""
    assert rec.classify_game_recommendation_intent("что послушать если нравится MACAN?") == ""


def test_game_followup_is_category_local_and_expires():
    assert rec.classify_game_recommendation_intent("а ещё?", chat_id=-100) == ""
    rec.remember_game_topic(-100, "Cyberpunk 2077", 1091500, now=100.0)
    assert rec.current_game_topic(-100, now=101.0).name == "Cyberpunk 2077"
    assert rec.current_game_topic(-200, now=101.0) is None
    assert rec.current_game_topic(-100, now=100.0 + rec.GAME_TOPIC_TTL_SECONDS + 1) is None


def test_missing_api_key_disables_provider(monkeypatch):
    monkeypatch.delenv("RAWG_API_KEY", raising=False)
    assert rec.rawg_api_key() == ""
    assert asyncio.run(rec._rawg_get("games", {"search": "Doom"})) is None


def test_game_summary_normalizes_provider_fields():
    item = rec._game_summary(
        {
            "id": 1,
            "name": "Cyberpunk 2077",
            "slug": "cyberpunk-2077",
            "released": "2020-12-10",
            "genres": [{"slug": "role-playing-games-rpg", "name": "RPG"}],
            "tags": [{"slug": "cyberpunk", "name": "Cyberpunk"}],
            "platforms": [{"platform": {"slug": "pc", "name": "PC"}}],
            "rating": 4.2,
            "ratings_count": 9000,
            "metacritic": 86,
        }
    )
    assert item["name"] == "Cyberpunk 2077"
    assert item["genres"] == ["role-playing-games-rpg"]
    assert item["tags"] == ["cyberpunk"]
    assert item["platforms"] == ["pc"]
    assert item["source_url"] == "https://rawg.io/games/cyberpunk-2077"


def test_documented_candidate_params_use_slugs_not_platform_ids():
    seed = {"genres": ["action", "rpg"], "tags": ["cyberpunk", "open-world"], "platforms": ["pc"]}
    genre_params = rec._genre_pool_params(seed)
    tag_params = rec._tag_pool_params(seed)
    assert genre_params["genres"] == "action,rpg"
    assert tag_params["tags"] == "cyberpunk,open-world"
    assert genre_params["ordering"] == "-rating"
    assert tag_params["ordering"] == "-rating"
    assert "platforms" not in genre_params
    assert "platforms" not in tag_params


def test_similarity_beats_catalog_popularity():
    seed = {"genres": ["rpg", "adventure"], "tags": ["story-rich", "choices-matter"], "platforms": ["pc"]}
    relevant = rec._candidate_score(
        {"genres": ["rpg", "adventure"], "tags": ["story-rich", "choices-matter"], "platforms": ["pc"], "ratings_count": 800, "rating": 4.0, "metacritic": 82},
        seed,
    )
    popular_weak = rec._candidate_score(
        {"genres": ["sports"], "tags": ["multiplayer"], "platforms": ["pc"], "ratings_count": 50000, "rating": 4.8, "metacritic": 95},
        seed,
    )
    assert relevant["relevance_score"] > popular_weak["relevance_score"]
    assert relevant["passes_genre_gate"] is True
    assert popular_weak["passes_genre_gate"] is False


def test_recommend_from_game_merges_genre_and_tag_pools(monkeypatch):
    async def fake_seed(query):
        assert query == "Cyberpunk 2077"
        return {
            "id": 10,
            "name": "Cyberpunk 2077",
            "genres": ["rpg", "action"],
            "genre_names": ["RPG", "Action"],
            "tags": ["cyberpunk", "open-world", "story-rich"],
            "tag_names": ["Cyberpunk", "Open World", "Story Rich"],
            "platforms": ["pc"],
        }

    async def fake_rawg(path, params=None):
        assert path == "games"
        if "genres" in (params or {}):
            return {
                "results": [
                    {"id": 11, "name": "Relevant RPG", "slug": "relevant-rpg", "genres": [{"slug": "rpg", "name": "RPG"}], "tags": [{"slug": "story-rich", "name": "Story Rich"}], "platforms": [{"platform": {"slug": "pc"}}], "ratings_count": 500, "rating": 4.0},
                    {"id": 12, "name": "Wrong Sport", "slug": "wrong-sport", "genres": [{"slug": "sports", "name": "Sports"}], "tags": [], "platforms": [{"platform": {"slug": "pc"}}], "ratings_count": 50000, "rating": 4.9},
                ]
            }
        return {
            "results": [
                {"id": 11, "name": "Relevant RPG", "slug": "relevant-rpg", "genres": [{"slug": "rpg", "name": "RPG"}], "tags": [{"slug": "cyberpunk", "name": "Cyberpunk"}, {"slug": "story-rich", "name": "Story Rich"}], "platforms": [{"platform": {"slug": "pc"}}], "ratings_count": 500, "rating": 4.0},
                {"id": 13, "name": "Other RPG", "slug": "other-rpg", "genres": [{"slug": "rpg", "name": "RPG"}], "tags": [{"slug": "open-world", "name": "Open World"}], "platforms": [{"platform": {"slug": "playstation5"}}], "ratings_count": 700, "rating": 4.1},
            ]
        }

    monkeypatch.setattr(rec, "resolve_seed_game", fake_seed)
    monkeypatch.setattr(rec, "_rawg_get", fake_rawg)
    result = asyncio.run(rec.recommend_from_game("Cyberpunk 2077"))
    ids = [item["id"] for item in result["candidates"]]
    assert ids[0] == 11
    assert 12 not in ids
    assert 13 in ids
    assert result["candidates"][0]["shared_tags"] == ["cyberpunk", "story-rich"]


def test_prompt_keeps_provider_facts_separate_from_identity():
    prompt = rec.build_game_recommendation_context(
        {
            "seed": {"name": "Disco Elysium", "genre_names": ["RPG"], "tag_names": ["Choices Matter"]},
            "candidates": [
                {"name": "Pentiment", "released": "2022-11-15", "shared_genres": ["rpg"], "shared_tags": ["choices-matter"], "shared_platforms": ["pc"], "rating": 4.2, "ratings_count": 1000, "metacritic": 86, "relevance_score": 120.0, "source_url": "https://rawg.io/games/pentiment"}
            ],
        },
        user_text="посоветуй игры в духе Disco Elysium",
        identity_lens={"aesthetic": "мрачный техно-минимализм", "values": "любопытство"},
    )
    assert "мрачный техно-минимализм" in prompt
    assert "в self-canon автоматически" in prompt
    assert "RAWG" in prompt
    assert "https://rawg.io" in prompt
    assert "shared_genres=rpg" in prompt
    assert "Pentiment" in prompt
