from types import SimpleNamespace

import url_content_fetcher as fetcher


def test_find_first_url_extracts_and_trims_trailing_punctuation():
    assert fetcher.find_first_url("глянь https://example.com/news/123?") == "https://example.com/news/123"
    assert fetcher.find_first_url("(см. https://example.com/x)") == "https://example.com/x"


def test_find_first_url_returns_none_without_a_url():
    assert fetcher.find_first_url("просто текст без ссылок") is None


def test_extract_readable_text_strips_scripts_and_styles():
    html = """
    <html><body>
      <script>alert('x')</script>
      <style>.a{color:red}</style>
      <p>Настоящий текст статьи про важное событие.</p>
    </body></html>
    """
    text = fetcher._extract_readable_text(html)
    assert "alert" not in text
    assert "color:red" not in text
    assert "Настоящий текст статьи" in text


class _FakeRaw:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, size, decode_content=True):
        return self._data[:size]


class _FakeResponse:
    def __init__(self, *, status=200, content_type="text/html; charset=utf-8", body=b"", encoding="utf-8"):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.raw = _FakeRaw(body)
        self.encoding = encoding

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


_LONG_ARTICLE_HTML = (
    "<html><body><p>" + ("Реальная статья с содержанием. " * 20) + "</p></body></html>"
).encode("utf-8")


def test_fetch_article_text_sync_returns_extracted_text(monkeypatch):
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(body=_LONG_ARTICLE_HTML),
    )
    text = fetcher.fetch_article_text_sync("https://example.com/article")
    assert text is not None
    assert "Реальная статья" in text


def test_fetch_article_text_sync_rejects_non_http_scheme(monkeypatch):
    called = []
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: called.append(1))
    assert fetcher.fetch_article_text_sync("ftp://example.com/x") is None
    assert not called


def test_fetch_article_text_sync_rejects_non_html_content_type(monkeypatch):
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(content_type="application/json", body=b'{"a":1}'),
    )
    assert fetcher.fetch_article_text_sync("https://example.com/api") is None


def test_fetch_article_text_sync_rejects_too_short_text(monkeypatch):
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(body=b"<html><body><p>too short</p></body></html>"),
    )
    assert fetcher.fetch_article_text_sync("https://example.com/thin") is None


def test_fetch_article_text_sync_truncates_to_max_chars(monkeypatch):
    huge_html = ("<html><body><p>" + ("а" * 20000) + "</p></body></html>").encode("utf-8")
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: _FakeResponse(body=huge_html))
    text = fetcher.fetch_article_text_sync("https://example.com/huge")
    assert text is not None
    assert len(text) == fetcher.MAX_ARTICLE_CHARS


def test_fetch_article_text_sync_returns_none_on_request_exception(monkeypatch):
    def raise_error(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(fetcher.requests, "get", raise_error)
    assert fetcher.fetch_article_text_sync("https://example.com/down") is None


def test_fetch_article_text_sync_returns_none_on_http_error_status(monkeypatch):
    monkeypatch.setattr(
        fetcher.requests,
        "get",
        lambda *a, **k: _FakeResponse(status=404, body=_LONG_ARTICLE_HTML),
    )
    assert fetcher.fetch_article_text_sync("https://example.com/missing") is None
