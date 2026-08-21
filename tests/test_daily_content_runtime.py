import asyncio
from datetime import datetime

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


def test_official_news_parser_accepts_only_article_links():
    sample = """
    <html><body>
      <a href="/news/12345/">Правительство утвердило важное решение по инфраструктуре</a>
      <a href="/news/">Новости</a>
      <a href="/other/999/">Не новость</a>
    </body></html>
    """
    links = runtime._extract_official_news_links(
        sample,
        base_url="https://government.ru/news/",
        href_pattern=r"^/news/\d+/?$",
    )
    assert links == [
        (
            "Правительство утвердило важное решение по инфраструктуре",
            "https://government.ru/news/12345/",
        )
    ]


def test_official_news_parser_accepts_absolute_hrefs_too():
    # Regression: the source site can emit an absolute href for the same
    # link instead of a relative one; matching only the raw href against a
    # relative-path pattern silently dropped every link that day.
    sample = """
    <html><body>
      <a href="https://government.ru/news/12345/">Правительство утвердило важное решение по инфраструктуре</a>
    </body></html>
    """
    links = runtime._extract_official_news_links(
        sample,
        base_url="https://government.ru/news/",
        href_pattern=r"^/news/\d+/?$",
    )
    assert links == [
        (
            "Правительство утвердило важное решение по инфраструктуре",
            "https://government.ru/news/12345/",
        )
    ]


def test_official_news_source_logs_when_zero_links_match(caplog):
    # Regression: a fetch that succeeds (200 OK) but matches zero links --
    # e.g. after a markup/anti-bot change -- previously left no trace and
    # would repeat silently on every retry for the rest of the day.
    import logging as logging_module

    original_fetch = runtime._fetch_html_sync
    runtime._fetch_html_sync = lambda url: "<html><body>no matching links here</body></html>"
    try:
        with caplog.at_level(logging_module.WARNING):
            candidates = runtime._fetch_official_news_candidates_sync()
    finally:
        runtime._fetch_html_sync = original_fetch

    assert candidates == []
    assert any("zero matching links" in record.message for record in caplog.records)


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
    """Regression for the old wrapper-order bug that silently killed delivery.

    The pre-centralized runtime could prepare daily content first and then let
    unified titles overwrite ``run_due_daily_titles``. Centralized startup must
    do the opposite: finalize unified titles first, then append daily content.
    """
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

    # This assignment represents unified_daily_title_runtime._prepare() having
    # already finalized the title scheduler.
    fake.run_due_daily_titles = final_unified_scheduler
    monkeypatch.setattr(runtime, "run_daily_content_if_due", fake_daily_content)

    # Daily content MUST be the later/final scheduler patch.
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
