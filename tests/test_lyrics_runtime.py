import asyncio

import lyrics_runtime as lyrics


def setup_function():
    lyrics._CACHE.clear()


def test_russian_lyrics_intent_and_followup():
    assert lyrics.classify_lyrics_intent("о чём песня MACAN Заново?") == (
        "meaning",
        "MACAN Заново",
    )
    assert lyrics.classify_lyrics_intent("текст песни Три дня дождя Отпускай") == (
        "lyrics",
        "Три дня дождя Отпускай",
    )
    assert lyrics.classify_lyrics_intent("а о чём она?", current_topic="MACAN — Заново") == (
        "meaning",
        "MACAN — Заново",
    )


def test_lrclib_normalizes_cyrillic_track():
    result = lyrics._normalize_lrclib(
        {
            "id": 101,
            "trackName": "Заново",
            "artistName": "MACAN",
            "albumName": "12",
            "duration": 173.2,
            "plainLyrics": "Первая строка\nВторая строка",
            "syncedLyrics": "",
            "instrumental": False,
        }
    )
    assert result["track_name"] == "Заново"
    assert result["artist_name"] == "MACAN"
    assert result["plain_lyrics"].startswith("Первая")
    assert result["provider"] == "LRCLIB"


def test_lrclib_synced_text_can_supply_plain_analysis_text():
    result = lyrics._normalize_lrclib(
        {
            "id": 102,
            "trackName": "Отпускай",
            "artistName": "Три дня дождя",
            "albumName": "",
            "duration": 200,
            "plainLyrics": "",
            "syncedLyrics": "[00:01.00]Строка один\n[00:04.20]Строка два",
            "instrumental": False,
        }
    )
    assert result["plain_lyrics"] == "Строка один\nСтрока два"


def test_best_lrclib_accepts_russian_artist_track_query():
    rows = [
        {
            "id": 1,
            "trackName": "Заново",
            "artistName": "Другой артист",
            "plainLyrics": "wrong",
        },
        {
            "id": 2,
            "trackName": "Заново",
            "artistName": "MACAN",
            "plainLyrics": "right",
        },
    ]
    result = lyrics._best_lrclib(rows, raw_query="MACAN Заново")
    assert result["provider_id"] == "2"
    assert result["artist_name"] == "MACAN"


def test_ambiguous_one_word_raw_query_is_rejected_without_artist():
    rows = [
        {
            "id": 1,
            "trackName": "Отпускай",
            "artistName": "Три дня дождя",
            "plainLyrics": "lyrics",
        }
    ]
    assert lyrics._best_lrclib(rows, raw_query="Отпускай") is None


def test_exact_lrclib_lookup_uses_catalog_metadata_when_available(monkeypatch):
    calls = []

    async def fake_get(path, params):
        calls.append((path, params))
        if path == "get":
            return {
                "id": 77,
                "trackName": "Заново",
                "artistName": "MACAN",
                "albumName": "12",
                "duration": 173.0,
                "plainLyrics": "lyrics",
            }
        return None

    monkeypatch.setattr(lyrics, "_lrclib_get", fake_get)
    result = asyncio.run(
        lyrics.lookup_lrclib(
            "MACAN Заново",
            track_name="Заново",
            artist_name="MACAN",
            album_name="12",
            duration=173,
        )
    )
    assert result["track_name"] == "Заново"
    assert calls[0][0] == "get"
    assert calls[0][1]["artist_name"] == "MACAN"


def test_raw_lrclib_search_does_not_require_musicbrainz(monkeypatch):
    async def fake_get(path, params):
        assert path == "search"
        assert params == {"q": "MACAN Заново"}
        return [
            {
                "id": 88,
                "trackName": "Заново",
                "artistName": "MACAN",
                "plainLyrics": "lyrics",
            }
        ]

    monkeypatch.setattr(lyrics, "_lrclib_get", fake_get)
    result = asyncio.run(lyrics.lookup_lrclib("MACAN Заново"))
    assert result["artist_name"] == "MACAN"


def test_lookup_lyrics_uses_musixmatch_only_after_lrclib(monkeypatch):
    calls = []

    async def no_lrclib(*args, **kwargs):
        calls.append("lrclib")
        return None

    async def yes_musixmatch(*args, **kwargs):
        calls.append("musixmatch")
        return {"provider": "Musixmatch", "track_name": "Заново"}

    monkeypatch.setattr(lyrics, "lookup_lrclib", no_lrclib)
    monkeypatch.setattr(lyrics, "lookup_musixmatch", yes_musixmatch)
    result = asyncio.run(lyrics.lookup_lyrics("MACAN Заново"))
    assert result["provider"] == "Musixmatch"
    assert calls == ["lrclib", "musixmatch"]


def test_musixmatch_is_optional_without_api_key(monkeypatch):
    monkeypatch.delenv("MUSIXMATCH_API_KEY", raising=False)
    assert asyncio.run(lyrics.lookup_musixmatch("MACAN Заново")) is None


def test_lyrics_prompt_is_analysis_only_and_copyright_bounded():
    prompt, source = lyrics.build_lyrics_context(
        {
            "provider": "LRCLIB",
            "track_name": "Заново",
            "artist_name": "MACAN",
            "album_name": "",
            "plain_lyrics": "строка один\nстрока два",
            "instrumental": False,
            "source_url": "https://lrclib.net/api/get/88",
        },
        user_text="о чём песня MACAN Заново?",
        mode="meaning",
    )
    assert "ДЛЯ АНАЛИЗА" in prompt
    assert "Не копируй полный текст песни" in prompt
    assert "до 80 символов" in prompt
    assert "MACAN" in prompt
    assert source.endswith("/88")
