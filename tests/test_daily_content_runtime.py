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
