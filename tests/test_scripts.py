"""Tests for the standalone scripts — search parsers + poster guards (mocked)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import content_research as cr   # noqa: E402
import telegram_poster          # noqa: E402


def test_ddg_decode_unwraps_redirects():
    assert cr._ddg_decode(
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x"
    ) == "https://example.com/a"
    assert cr._ddg_decode("https://real.site/p") == "https://real.site/p"


def test_duckduckgo_parser_decodes_and_dedupes(monkeypatch):
    fixture = (
        '<a rel="nofollow" class="result__a" '
        'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com&rut=1">First &amp; A</a>'
        '<a rel="nofollow" class="result__a" '
        'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fb.com">Second <b>B</b></a>'
    )

    class R:
        ok = True
        status_code = 200
        text = fixture

    monkeypatch.setattr(cr.requests, "post", lambda *a, **k: R())
    res = cr._search_duckduckgo("q", count=5)
    assert [r["url"] for r in res] == ["https://a.com", "https://b.com"]
    assert res[0]["title"] == "First & A"          # entity unescaped
    assert "<b>" not in res[1]["title"]            # tags stripped


def test_wikipedia_parser(monkeypatch):
    class R:
        ok = True

        def json(self):
            return {"query": {"search": [
                {"title": "Laravel", "snippet": "<b>Laravel</b> is a PHP &amp; framework"}]}}

    monkeypatch.setattr(cr.requests, "get", lambda *a, **k: R())
    res = cr._search_wikipedia("laravel", 3)
    assert res[0]["url"] == "https://en.wikipedia.org/wiki/Laravel"
    assert "<b>" not in res[0]["description"] and "&amp;" not in res[0]["description"]


def test_searxng_disabled_without_url(monkeypatch):
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    assert cr._search_searxng("q", 3) == []


def test_search_provider_forced(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "wikipedia")
    called = {"wiki": False}

    def fake_wiki(q, c):
        called["wiki"] = True
        return [{"title": "x", "url": "http://x", "description": "", "source": "wikipedia"}]

    monkeypatch.setattr(cr, "_search_wikipedia", fake_wiki)
    monkeypatch.setattr(cr, "_search_brave", lambda q, c: [])
    out = cr.web_search("q", count=3)
    assert called["wiki"] and out[0]["source"] == "wikipedia"


def test_telegram_poster_accepts_openclaw_aliases(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "stale")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "stale-chat")
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "chat")
    captured = {}

    class Response:
        @staticmethod
        def json():
            return {"ok": True}

    def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return Response()

    monkeypatch.setattr(telegram_poster.requests, "post", fake_post)

    result = telegram_poster.post_message("hello")

    assert result == {"ok": True}
    assert captured["url"].endswith("/bottoken/sendMessage")
    assert captured["json"]["chat_id"] == "chat"


def test_telegram_poster_normalizes_tme_c_chat_url(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "https://t.me/c/3948211258/14119")
    monkeypatch.delenv("TELEGRAM_MESSAGE_THREAD_ID", raising=False)
    captured = {}

    class Response:
        @staticmethod
        def json():
            return {"ok": True}

    def fake_post(url, json=None, **kwargs):
        captured["json"] = json
        return Response()

    monkeypatch.setattr(telegram_poster.requests, "post", fake_post)

    telegram_poster.post_message("hello")

    assert captured["json"]["chat_id"] == "-1003948211258"
    assert captured["json"]["message_thread_id"] == "14119"


def test_telegram_poster_normalizes_bare_private_chat_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "3948211258")
    captured = {}

    class Response:
        @staticmethod
        def json():
            return {"ok": True}

    def fake_post(url, json=None, **kwargs):
        captured["json"] = json
        return Response()

    monkeypatch.setattr(telegram_poster.requests, "post", fake_post)

    telegram_poster.post_message("hello")

    assert captured["json"]["chat_id"] == "-1003948211258"
