"""CHARACTERIZATION tests — Phase 0.

These pin the EXACT request each publishing lane sends to the LLM today, before
the six hand-rolled callers are consolidated behind one client. They are not
aspirational: if a value here looks odd (auto_publish's 400-token ceiling,
version_sanity_check's KeyError-on-missing-key), that is the current production
behavior and the refactor must preserve it.

A failure here after the refactor means publishing behavior changed.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

from agent.llm_ops import requests as LLM_HTTP  # the one HTTP boundary now


class Captured:
    """Records the outbound request and returns a canned completion."""

    def __init__(self, content="RESPONSE", ok=True, status=200):
        self.calls = []
        self._content = content
        self._ok = ok
        self._status = status

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(self._content, self._ok, self._status)

    @property
    def last(self):
        return self.calls[-1]

    @property
    def payload(self):
        return self.last["json"]


class FakeResponse:
    def __init__(self, content, ok=True, status=200):
        self._content = content
        self.ok = ok
        self.status_code = status
        self.text = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}}

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self._status}")


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Keep test runs out of the real content/llm_usage.jsonl."""
    from agent import llm_ops
    monkeypatch.setattr(llm_ops, "USAGE_LEDGER", tmp_path / "llm_usage.jsonl")


MESSAGES = [{"role": "user", "content": "hello"}]


# ── Lane 1: enforce_published_quality (the two-halves tutorial writer) ──────

def test_enforce_published_quality_chat_request_shape(monkeypatch):
    import enforce_published_quality as E

    cap = Captured()
    monkeypatch.setattr(LLM_HTTP, "post", cap)
    out = E._chat(MESSAGES)

    assert out == "RESPONSE"
    assert cap.last["url"] == OPENAI_URL
    assert cap.payload["model"] == "gpt-4o"
    assert cap.payload["temperature"] == 0.5
    assert cap.payload["max_tokens"] == 8000
    assert cap.payload["messages"] == MESSAGES
    assert "response_format" not in cap.payload
    assert cap.last["timeout"] == 240
    assert cap.last["headers"]["Authorization"] == "Bearer test-key-123"
    assert cap.last["headers"]["Content-Type"] == "application/json"


def test_enforce_published_quality_chat_strips_and_raises(monkeypatch):
    import enforce_published_quality as E

    monkeypatch.setattr(LLM_HTTP, "post", Captured(content="  padded  "))
    assert E._chat(MESSAGES) == "padded"

    monkeypatch.setattr(LLM_HTTP, "post", Captured(ok=False, status=500))
    with pytest.raises(Exception):
        E._chat(MESSAGES)


# ── Lane 2: news_publish ───────────────────────────────────────────────────

def test_news_publish_chat_request_shape(monkeypatch):
    import news_publish as N

    cap = Captured()
    monkeypatch.setattr(LLM_HTTP, "post", cap)
    N._chat(MESSAGES)

    assert cap.payload["model"] == "gpt-4o"
    assert cap.payload["temperature"] == 0.35
    assert cap.payload["max_tokens"] == 1200
    assert "response_format" not in cap.payload
    assert cap.last["timeout"] == 120


def test_news_publish_chat_json_mode_sets_response_format(monkeypatch):
    import news_publish as N

    cap = Captured(content='{"ok": true}')
    monkeypatch.setattr(LLM_HTTP, "post", cap)
    N._chat(MESSAGES, json_mode=True)

    assert cap.payload["response_format"] == {"type": "json_object"}


def test_news_publish_chat_requires_an_api_key(monkeypatch):
    """The news lane is the only one that hard-fails on a missing key."""
    import news_publish as N

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        N._chat(MESSAGES)


# ── Lane 3: auto_publish (topic picker) ────────────────────────────────────

def test_auto_publish_chat_request_shape(monkeypatch):
    import auto_publish as A

    cap = Captured()
    monkeypatch.setattr(LLM_HTTP, "post", cap)
    A._chat(MESSAGES)

    assert cap.payload["model"] == "gpt-4o"
    assert cap.payload["temperature"] == 0.6
    assert cap.payload["max_tokens"] == 400
    assert cap.last["timeout"] == 120


# ── Lane 4: social_copy ────────────────────────────────────────────────────

def test_social_copy_generate_request_shape(monkeypatch):
    import social_copy as SC

    cap = Captured(content="A clean social post.")
    monkeypatch.setattr(LLM_HTTP, "post", cap)
    out = SC._generate("prompt", "gpt-4o-mini", temperature=0.7)

    assert out == "A clean social post."
    assert cap.payload["model"] == "gpt-4o-mini"
    assert cap.payload["temperature"] == 0.7
    assert cap.payload["max_tokens"] == 500
    assert cap.last["timeout"] == 60


def test_social_copy_generate_returns_none_without_key(monkeypatch):
    import social_copy as SC

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert SC._generate("prompt", "gpt-4o-mini") is None


def test_social_copy_generate_returns_none_on_http_failure(monkeypatch):
    import social_copy as SC

    monkeypatch.setattr(LLM_HTTP, "post", Captured(ok=False, status=429))
    assert SC._generate("prompt", "gpt-4o-mini") is None


def test_social_copy_generate_rejects_banned_phrases(monkeypatch):
    """The banned-phrase guard is a behavior the refactor must not drop."""
    import social_copy as SC

    monkeypatch.setattr(LLM_HTTP, "post", Captured(content="This is groundbreaking stuff."))
    assert SC._generate("prompt", "gpt-4o-mini") is None


# ── Lane 5: linkedin_from_article ──────────────────────────────────────────

def test_linkedin_from_article_request_shape(monkeypatch):
    import linkedin_from_article as LFA

    cap = Captured(content=json.dumps({"post": "Body text", "hashtags": ["#ai"]}))
    monkeypatch.setattr(LLM_HTTP, "post", cap)
    out = LFA.write_post("T", "E", "B", "https://example.com")

    assert cap.payload["model"] == "gpt-4o-mini"
    assert cap.payload["temperature"] == 0.6
    assert cap.payload["response_format"] == {"type": "json_object"}
    assert "max_tokens" not in cap.payload
    assert cap.last["timeout"] == 45
    assert "Body text" in out and "#BuildWithAbdallah" in out


def test_linkedin_from_article_falls_back_to_template(monkeypatch):
    import linkedin_from_article as LFA

    monkeypatch.setattr(LLM_HTTP, "post", Captured(ok=False, status=500))
    out = LFA.write_post("My Title", "E", "B", "https://example.com/x")
    assert "My Title" in out
    assert "https://example.com/x" in out
    assert "#BuildWithAbdallah" in out


# ── Lane 6: version_sanity_check ───────────────────────────────────────────

def test_version_sanity_check_request_shape(monkeypatch):
    import version_sanity_check as V

    cap = Captured(content=json.dumps({"issues": ["Laravel 99 is not released"]}))
    monkeypatch.setattr(LLM_HTTP, "post", cap)
    monkeypatch.setattr(V, "_extract_claims", lambda _t: [("Laravel", "99")])
    monkeypatch.setattr(V.CR, "web_search",
                        lambda *a, **k: [{"title": "Laravel 12 is current", "url": "https://laravel.com"}])

    issues = V.web_grounded_issues("Title", "body mentioning Laravel 99")

    assert issues == ["Laravel 99 is not released"]
    assert cap.payload["model"] == "gpt-4o"
    assert cap.payload["temperature"] == 0.0
    assert cap.payload["max_tokens"] == 400
    assert cap.payload["response_format"] == {"type": "json_object"}
    assert cap.last["timeout"] == 90


def test_version_sanity_check_swallows_errors_and_returns_empty(monkeypatch):
    """A failed sanity check must never block publishing — it returns []."""
    import version_sanity_check as V

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(LLM_HTTP, "post", boom)
    monkeypatch.setattr(V, "_extract_claims", lambda _t: [("Laravel", "99")])
    monkeypatch.setattr(V.CR, "web_search", lambda *a, **k: [{"title": "x", "url": "y"}])

    assert V.web_grounded_issues("T", "b") == []


def test_version_sanity_check_returns_empty_without_web_facts(monkeypatch):
    import version_sanity_check as V

    monkeypatch.setattr(V, "_extract_claims", lambda _t: [("Laravel", "99")])
    monkeypatch.setattr(V.CR, "web_search", lambda *a, **k: [])
    assert V.web_grounded_issues("T", "b") == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
