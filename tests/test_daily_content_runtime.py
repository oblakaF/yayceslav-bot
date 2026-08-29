import asyncio
from datetime import date, datetime

import requests

import daily_content_runtime as runtime
import whoami_dynamic_verdict


def test_daily_times_msk_boundaries():
    assert runtime.joke_due(datetime(2026, 8, 19, 19, 29)) is False
    assert runtime.joke_due(datetime(2026, 8, 19, 19, 30)) is True
    assert runtime.news_due(datetime(2026, 8, 19, 19, 59)) is False
    assert runtime.news_due(datetime(2026, 8, 19, 20, 0)) is True


def test_jokeapi_single_and_twopart_are_external_text():
    single, single_key = runtime._joke_text_from_payload(
        {"error": False, "id": 101, "type": "single", "joke": "A sufficiently long external joke lives here."}
    )
    assert single == "A sufficiently long external joke lives here."
    assert single_key == "jokeapi:101"

    twopart, twopart_key = runtime._joke_text_from_payload(
        {
            "error": False,
            "id": 102,
            "type": "twopart",
            "setup": "Why did the external joke cross the road?",
            "delivery": "Because the API told it to.",
        }
    )
    assert twopart == "Why did the external joke cross the road?\nBecause the API told it to."
    assert twopart_key == "jokeapi:102"


_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Sample feed</title>
<item>
<title>Реальная новость с достаточно длинным заголовком</title>
<link>https://example.com/news/1</link>
</item>
<item>
<title>короткая</title>
<link>https://example.com/news/2</link>
</item>
<item>
<title></title>
<link>https://example.com/news/3</link>
</item>
</channel>
</rss>"""


def test_rss_parser_accepts_valid_items_and_skips_junk():
    items = runtime._parse_rss_items(_SAMPLE_RSS)
    assert items == [
        (
            "Реальная новость с достаточно длинным заголовком",
            "https://example.com/news/1",
        )
    ]


def test_rss_parser_handles_malformed_xml():
    assert runtime._parse_rss_items("not xml at all <<<") == []


def test_rss_parser_respects_limit():
    many_items = "".join(
        f"<item><title>Заголовок номер {i} длиной побольше</title>"
        f"<link>https://example.com/{i}</link></item>"
        for i in range(10)
    )
    xml_text = f"<rss><channel>{many_items}</channel></rss>"
    assert len(runtime._parse_rss_items(xml_text, limit=3)) == 3


def test_news_source_logs_when_zero_items_match(caplog):
    import logging as logging_module

    original_fetch = runtime._fetch_html_sync
    runtime._fetch_html_sync = lambda url: "<rss><channel></channel></rss>"
    try:
        with caplog.at_level(logging_module.WARNING):
            candidates = runtime._fetch_news_candidates_sync()
    finally:
        runtime._fetch_html_sync = original_fetch

    assert candidates == []
    assert any("zero usable items" in record.message for record in caplog.records)


def test_news_sources_no_longer_reference_government_sites():
    for _name, url in runtime.NEWS_RSS_SOURCES:
        assert "government.ru" not in url
        assert "kremlin.ru" not in url


def test_fetch_news_candidates_aggregates_across_sources(monkeypatch):
    monkeypatch.setattr(runtime, "_fetch_html_sync", lambda url: _SAMPLE_RSS)
    candidates = runtime._fetch_news_candidates_sync()
    assert len(candidates) == len(runtime.NEWS_RSS_SOURCES)
    for source_name, title, link in candidates:
        assert source_name in {name for name, _url in runtime.NEWS_RSS_SOURCES}
        assert title == "Реальная новость с достаточно длинным заголовком"
        assert link == "https://example.com/news/1"


def test_broken_whoami_fragment_is_rejected():
    assert whoami_dynamic_verdict._clean_verdict("набра") is None
    assert whoami_dynamic_verdict._clean_verdict("Ну и хуй с ним.") == "Ну и хуй с ним."


def test_scheduler_appends_daily_content_once(monkeypatch):
    calls = []

    class FakeBotModule:
        _yayceslav_daily_content_patch = False

        async def run_due_daily_titles(self, application):
            del application
            calls.append("existing")

    fake = FakeBotModule()

    async def fake_daily_content(application):
        del application
        calls.append("content")

    monkeypatch.setattr(runtime, "run_daily_content_if_due", fake_daily_content)

    runtime._patch_scheduler(fake)
    wrapped = fake.run_due_daily_titles
    runtime._patch_scheduler(fake)

    assert fake.run_due_daily_titles is wrapped
    asyncio.run(fake.run_due_daily_titles(object()))
    assert calls == ["existing", "content"]


def test_daily_content_must_wrap_final_unified_scheduler(monkeypatch):
    calls = []

    class FakeBotModule:
        _yayceslav_daily_content_patch = False

    fake = FakeBotModule()

    async def final_unified_scheduler(application):
        del application
        calls.append("unified")

    async def fake_daily_content(application):
        del application
        calls.append("daily_content")

    fake.run_due_daily_titles = final_unified_scheduler
    monkeypatch.setattr(runtime, "run_daily_content_if_due", fake_daily_content)
    runtime._patch_scheduler(fake)
    asyncio.run(fake.run_due_daily_titles(object()))

    assert calls == ["unified", "daily_content"]


def test_prepare_application_initializes_once(monkeypatch):
    class FakeBotModule:
        _yayceslav_daily_content_patch = False

        async def run_due_daily_titles(self, application):
            del application

    fake = FakeBotModule()
    init_calls = []
    monkeypatch.setattr(runtime, "_find_bot_module", lambda: fake)
    monkeypatch.setattr(runtime, "_initialize_tables", lambda bot: init_calls.append(bot))

    application = object()
    runtime._PREPARED_APPLICATION_IDS.discard(id(application))
    runtime._prepare_application(application)
    runtime._prepare_application(application)

    assert init_calls == [fake]
    assert not hasattr(runtime, "install_runtime_hook")


def test_looks_like_complete_joke_checks_sentence_boundary():
    assert runtime._looks_like_complete_joke("Панч в конце шутки.") is True
    assert runtime._looks_like_complete_joke("Шутка обрывается на полусл") is False
    assert runtime._looks_like_complete_joke("") is False
    assert runtime._looks_like_complete_joke("   ") is False


class _FakeBotModuleForTranslate:
    GEMINI_API_KEY = "fake-key"
    MODEL_NAME = "gemini-3.6-flash"


def _install_fake_translation(monkeypatch, text):
    class FakeResponse:
        pass

    FakeResponse.text = text

    class FakeModels:
        async def generate_content(self, **kwargs):
            del kwargs
            return FakeResponse()

    class FakeAio:
        models = FakeModels()

    class FakeClient:
        def __init__(self, api_key):
            del api_key
            self.aio = FakeAio()

    monkeypatch.setattr(runtime.genai, "Client", FakeClient)


def test_translate_joke_discards_truncated_translation(monkeypatch):
    _install_fake_translation(monkeypatch, "Штирлиц вошёл в комнату и увидел на столе")
    result = asyncio.run(
        runtime._translate_joke(_FakeBotModuleForTranslate(), "Some english joke.")
    )
    assert result is None


def test_translate_joke_keeps_complete_translation(monkeypatch):
    _install_fake_translation(
        monkeypatch,
        "Штирлиц вошёл в комнату и увидел на столе чемодан.",
    )
    result = asyncio.run(
        runtime._translate_joke(_FakeBotModuleForTranslate(), "Some english joke.")
    )
    assert result == "Штирлиц вошёл в комнату и увидел на столе чемодан."


def test_translate_joke_discards_meta_commentary_seen_in_production(monkeypatch):
    _install_fake_translation(
        monkeypatch,
        'лифчик). Wait! "Альга" = водоросль (from Latin/scientific, though standard Russian is "водоросли").',
    )
    result = asyncio.run(
        runtime._translate_joke(_FakeBotModuleForTranslate(), "Some english joke.")
    )
    assert result is None


def test_jokeapi_rejects_unsupported_ru_without_network(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime.requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)))
    try:
        runtime._fetch_external_joke_sync("ru", set())
    except ValueError as error:
        assert "Unsupported JokeAPI joke language" in str(error)
    else:
        raise AssertionError("ru must be rejected before a network request")
    assert calls == []


def test_jokeapi_4xx_is_not_retried(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 400

        def raise_for_status(self):
            error = requests.HTTPError("400 Bad Request")
            error.response = self
            raise error

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr(runtime.requests, "get", fake_get)
    try:
        runtime._fetch_external_joke_sync("en", set())
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("expected HTTPError")
    assert len(calls) == 1


def test_joke_build_persists_local_fallback_after_external_failure(monkeypatch):
    saved = []

    monkeypatch.setattr(runtime, "_load_item_sync", lambda bot, day, kind: None)
    monkeypatch.setattr(runtime, "_recent_item_keys_sync", lambda bot, kind, limit: set())

    def fail_external(language, recent):
        del language, recent
        raise RuntimeError("source down")

    monkeypatch.setattr(runtime, "_fetch_external_joke_sync", fail_external)
    monkeypatch.setattr(
        runtime,
        "_save_item_sync",
        lambda bot, day, item: saved.append((day, item)),
    )

    item = asyncio.run(runtime._build_joke_item(object(), date(2026, 8, 27)))
    assert item is not None
    assert item.source_name == "Yayceslav local fallback"
    assert item.rendered_text.startswith("🥚 ВНИМАНИЕ, АНЕКДОТ:")
    assert runtime._looks_like_complete_joke(item.raw_text)
    assert len(saved) == 1
    assert saved[0][0] == "2026-08-27"
    assert saved[0][1] is item
