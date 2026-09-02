import asyncio

import entity_continuity_runtime
import music_recommendation_runtime as rec


def setup_function():
    rec._CACHE.clear()
    entity_continuity_runtime._ENTITY_BY_CHAT.clear()


def test_recommendation_intent_supports_russian_and_english():
    assert rec.classify_recommendation_intent("что послушать если нравится Три дня дождя?") == "Три дня дождя"
    assert rec.classify_recommendation_intent("посоветуй 5 треков в духе MACAN") == "MACAN"
    assert rec.classify_recommendation_intent("artists like Depeche Mode") == "Depeche Mode"


def test_unrelated_music_question_is_not_recommendation():
    assert rec.classify_recommendation_intent("какого года песня Enjoy the Silence?") == ""
    assert rec.classify_recommendation_intent("кто поёт Отпускай?") == ""


def test_followup_reuses_current_entity():
    entity_continuity_runtime.remember_topic(-100, "Три дня дождя")
    assert rec.classify_recommendation_intent("а ещё?", chat_id=-100) == "Три дня дождя"


def test_radio_rows_accepts_list_and_nested_payload():
    rows = [{"recording_mbid": "r1"}]
    assert rec._radio_rows(rows) == rows
    assert rec._radio_rows({"payload": {"recordings": rows}}) == rows


def test_metadata_helpers_normalize_artist_recording_and_tags():
    meta = {
        "recording": {"name": "Новый трек"},
        "artist": {"name": "Другой артист"},
        "tag": {
            "recording": [
                {"tag": "alternative"},
                {"tag": "alternative"},
                {"tag": "indie"},
            ]
        },
    }
    assert rec._recording_name(meta) == "Новый трек"
    assert rec._artist_name(meta) == "Другой артист"
    assert rec._tags(meta) == ["alternative", "indie"]


def test_recommend_from_artist_filters_seed_and_sorts_by_listens(monkeypatch):
    async def fake_artist(query):
        assert query == "Три дня дождя"
        return {"mbid": "seed", "name": "Три дня дождя"}

    async def fake_lb(path, params=None):
        if path.startswith("lb-radio/artist/"):
            assert path.endswith("seed")
            return [
                {
                    "recording_mbid": "r-seed",
                    "similar_artist_name": "Три дня дождя",
                    "total_listen_count": 999,
                },
                {
                    "recording_mbid": "r2",
                    "similar_artist_name": "Другой артист",
                    "total_listen_count": 50,
                },
                {
                    "recording_mbid": "r1",
                    "similar_artist_name": "Ещё артист",
                    "total_listen_count": 100,
                },
            ]
        assert path == "metadata/recording/"
        return {
            "r-seed": {"recording": {"name": "Seed song"}, "artist": {"name": "Три дня дождя"}},
            "r2": {"recording": {"name": "Песня 2"}, "artist": {"name": "Другой артист"}},
            "r1": {
                "recording": {"name": "Песня 1"},
                "artist": {"name": "Ещё артист"},
                "tag": {"recording": [{"tag": "rock"}]},
            },
        }

    monkeypatch.setattr(rec.music_runtime, "lookup_artist", fake_artist)
    monkeypatch.setattr(rec, "_listenbrainz_get", fake_lb)
    result = asyncio.run(rec.recommend_from_artist("Три дня дождя"))
    assert [item["recording_mbid"] for item in result["candidates"]] == ["r1", "r2"]
    assert result["candidates"][0]["tags"] == ["rock"]


def test_context_uses_canon_as_lens_not_fact_source():
    prompt = rec.build_recommendation_context(
        {
            "seed": {"name": "Три дня дождя", "mbid": "seed"},
            "candidates": [
                {
                    "artist": "Другой артист",
                    "title": "Песня",
                    "listen_count": 123,
                    "tags": ["rock"],
                    "recording_mbid": "r1",
                }
            ],
        },
        user_text="что послушать если нравится Три дня дождя?",
        canon_music="darkwave, post-punk",
    )
    assert "darkwave, post-punk" in prompt
    assert "не меняет self_canon.music автоматически" in prompt
    assert "Другой артист — Песня" in prompt
