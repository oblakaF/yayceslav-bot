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
