import asyncio

import entity_continuity_runtime
import music_runtime as music


def setup_function():
    music._CACHE.clear()
    entity_continuity_runtime._ENTITY_BY_CHAT.clear()


def test_track_intent_extracts_song_title():
    assert music.classify_music_intent("кто поёт Enjoy the Silence?") == (
        "track",
        "Enjoy the Silence",
    )
    assert music.classify_music_intent("что за песня Personal Jesus") == (
        "track",
        "Personal Jesus",
    )


def test_artist_intent_is_conservative():
    assert music.classify_music_intent("кто такой Дженсен Хуанг?") is None
    assert music.classify_music_intent("дискография Depeche Mode") == (
        "artist",
        "Depeche Mode",
    )
    assert music.classify_music_intent("альбомы Massive Attack") == (
        "artist",
        "Massive Attack",
    )


def test_music_followup_reuses_chat_entity():
    entity_continuity_runtime.remember_topic(-100, "Enjoy the Silence", now=100.0)
    state = entity_continuity_runtime._ENTITY_BY_CHAT[-100]
    entity_continuity_runtime._ENTITY_BY_CHAT[-100] = entity_continuity_runtime.EntityState(
        state.topic,
        music.time.monotonic(),
    )
    assert music.classify_music_intent("а из какого она альбома?", chat_id=-100) == (
        "track",
        "Enjoy the Silence",
    )


def test_recording_summary_keeps_artist_date_and_release_group():
    raw = {
        "id": "recording-id",
        "title": "Enjoy the Silence",
        "first-release-date": "1990-02-05",
        "score": 100,
        "artist-credit": [
            {"name": "Depeche Mode", "artist": {"name": "Depeche Mode"}}
        ],
        "releases": [
            {
                "title": "Violator",
                "release-group": {
                    "title": "Violator",
                    "primary-type": "Album",
                },
            },
            {
                "title": "Enjoy the Silence",
                "release-group": {
                    "title": "Enjoy the Silence",
                    "primary-type": "Single",
                },
            },
        ],
    }
    result = music._recording_summary(raw)
    assert result["mbid"] == "recording-id"
    assert result["artist"] == "Depeche Mode"
    assert result["first_release_date"] == "1990-02-05"
    assert result["releases"][0] == {"title": "Violator", "type": "Album"}


def test_artist_summary_normalizes_core_identity():
    raw = {
        "id": "artist-id",
        "name": "Depeche Mode",
        "sort-name": "Depeche Mode",
        "type": "Group",
        "country": "GB",
        "area": {"name": "United Kingdom"},
        "life-span": {"begin": "1980"},
        "disambiguation": "English electronic music band",
        "score": 100,
    }
    result = music._artist_summary(raw)
    assert result["name"] == "Depeche Mode"
    assert result["country"] == "GB"
    assert result["begin"] == "1980"
    assert "electronic" in result["disambiguation"]


def test_cache_is_bounded_and_returns_fresh_value(monkeypatch):
    monkeypatch.setattr(music, "CACHE_MAX_ENTRIES", 2)
    music._cache_put("a", {"value": 1})
    music._cache_put("b", {"value": 2})
    assert music._cache_get("a") == {"value": 1}
    music._cache_put("c", {"value": 3})
    assert len(music._CACHE) == 2
    assert music._cache_get("c") == {"value": 3}


def test_lookup_track_uses_top_musicbrainz_recording(monkeypatch):
    async def fake_get(path, params):
        assert path == "recording/"
        assert params["limit"] == 5
        return {
            "recordings": [
                {
                    "id": "r1",
                    "title": "Enjoy the Silence",
                    "score": 100,
                    "first-release-date": "1990-02-05",
                    "artist-credit": [{"name": "Depeche Mode"}],
                    "releases": [],
                }
            ]
        }

    monkeypatch.setattr(music, "_musicbrainz_get", fake_get)
    result = asyncio.run(music.lookup_track("Enjoy the Silence"))
    assert result["title"] == "Enjoy the Silence"
    assert result["artist"] == "Depeche Mode"


def test_music_context_keeps_catalog_separate_from_self_canon():
    prompt, source = music._music_context(
        "track",
        {
            "mbid": "r1",
            "title": "Enjoy the Silence",
            "artist": "Depeche Mode",
            "first_release_date": "1990-02-05",
            "releases": [{"title": "Violator", "type": "Album"}],
        },
        "кто поёт Enjoy the Silence?",
    )
    assert "Depeche Mode" in prompt
    assert "Violator" in prompt
    assert "Не переписывай self-canon.music" in prompt
    assert source.endswith("/recording/r1")
