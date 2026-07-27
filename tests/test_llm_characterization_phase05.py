"""CHARACTERIZATION tests — Phase 0.5 (agent/feed.py, agent/shorts.py).

Written BEFORE these two call sites are instrumented. They pin the exact wire
request each one makes today, including the values that are easy to lose in a
migration: shorts.py's response_format=json_object (without it the planner gets
prose, json.loads raises, and it silently degrades to the deterministic plan),
and each site's distinct model/base_url resolution.

A failure here after migration means generated content or provider selection
changed — both explicitly out of scope for Phase 0.5.
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class Captured:
    def __init__(self, content="RESPONSE", ok=True, status=200, usage=True):
        self.calls = []
        self._content, self._ok, self._status, self._usage = content, ok, status, usage

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(self._content, self._ok, self._status, self._usage)

    @property
    def last(self):
        return self.calls[-1]

    @property
    def payload(self):
        return self.last["json"]


class FakeResponse:
    def __init__(self, content, ok=True, status=200, usage=True):
        self._content, self.ok, self.status_code = content, ok, status
        self.text = content
        self._usage = usage

    def json(self):
        body = {"choices": [{"message": {"content": self._content}}]}
        if self._usage:
            body["usage"] = {"prompt_tokens": 40, "completion_tokens": 12}
        return body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Never write the real ledger from a test."""
    from agent import llm_ops
    monkeypatch.setattr(llm_ops, "USAGE_LEDGER", tmp_path / "llm_usage.jsonl")


def _http():
    """The single HTTP boundary both call sites use (before or after migration)."""
    from agent import llm_ops
    return llm_ops.requests


# ── agent/feed.py::_llm_chat ───────────────────────────────────────────────

FEED_CONFIG = SimpleNamespace(
    api_key="feed-key",
    base_url="http://localhost:11434/v1",
    model="kimi-k2.7-code:cloud",
    provider="ollama",
)


def test_feed_llm_chat_request_shape(monkeypatch):
    from agent import feed

    cap = Captured(content="  a reason  ")
    monkeypatch.setattr(_http(), "post", cap)

    out = feed._llm_chat("why does this matter?", FEED_CONFIG)

    assert out == "a reason", "response is stripped"
    assert cap.last["url"] == "http://localhost:11434/v1/chat/completions"
    assert cap.payload["model"] == "kimi-k2.7-code:cloud"
    assert cap.payload["messages"] == [{"role": "user", "content": "why does this matter?"}]
    assert cap.payload["max_tokens"] == 256
    assert cap.payload["temperature"] == 0.4
    assert "response_format" not in cap.payload
    assert cap.last["timeout"] == 60
    assert cap.last["headers"]["Authorization"] == "Bearer feed-key"


def test_feed_llm_chat_defaults_to_openai_when_no_base_url(monkeypatch):
    from agent import feed

    cap = Captured()
    monkeypatch.setattr(_http(), "post", cap)
    cfg = SimpleNamespace(api_key="k", base_url=None, model="gpt-4o", provider="openai")

    feed._llm_chat("p", cfg)
    assert cap.last["url"] == OPENAI_URL


def test_feed_llm_chat_raises_on_http_error(monkeypatch):
    """Callers rely on this propagating; feed.py wraps it upstream."""
    from agent import feed

    cap = Captured(ok=False, status=500)
    monkeypatch.setattr(_http(), "post", cap)

    with pytest.raises(Exception):
        feed._llm_chat("p", FEED_CONFIG)


# ── agent/shorts.py::_llm_plan ─────────────────────────────────────────────

def _article():
    from agent.shorts import Article
    return Article(slug="a-specific-title", title="A specific title",
                   body="Body text.", url="https://e.com/p")


def test_shorts_llm_plan_request_shape(monkeypatch):
    from agent import shorts

    monkeypatch.setenv("OPENAI_API_KEY", "shorts-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("SHORTS_LLM_MODEL", raising=False)

    cap = Captured(content=json.dumps({"scenes": [{"kind": "title_card"}]}))
    monkeypatch.setattr(_http(), "post", cap)
    monkeypatch.setattr(shorts.requests, "post", cap, raising=False)

    plan = shorts._llm_plan(_article())

    assert plan == {"scenes": [{"kind": "title_card"}]}
    assert cap.last["url"] == OPENAI_URL
    assert cap.payload["model"] == "gpt-4o-mini"
    assert cap.payload["temperature"] == 0.35
    assert cap.payload["max_tokens"] == 1800
    # Load-bearing: without this the planner receives prose and silently
    # degrades to the deterministic fallback plan.
    assert cap.payload["response_format"] == {"type": "json_object"}
    assert cap.last["timeout"] == 90
    assert cap.last["headers"]["Authorization"] == "Bearer shorts-key"


def test_shorts_llm_plan_honours_model_and_base_url_env(monkeypatch):
    from agent import shorts

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("SHORTS_LLM_MODEL", "openai/gpt-oss-120b")

    cap = Captured(content="{}")
    monkeypatch.setattr(_http(), "post", cap)
    monkeypatch.setattr(shorts.requests, "post", cap, raising=False)

    shorts._llm_plan(_article())

    assert cap.last["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert cap.payload["model"] == "openai/gpt-oss-120b"


def test_shorts_llm_plan_returns_none_without_key(monkeypatch):
    from agent import shorts

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert shorts._llm_plan(_article()) is None


def test_shorts_llm_plan_returns_none_on_http_failure(monkeypatch):
    """Must degrade to the deterministic plan, never raise into the pipeline."""
    from agent import shorts

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    cap = Captured(content="server error", ok=False, status=500)
    monkeypatch.setattr(_http(), "post", cap)
    monkeypatch.setattr(shorts.requests, "post", cap, raising=False)

    assert shorts._llm_plan(_article()) is None


def test_shorts_llm_plan_returns_none_on_bad_json(monkeypatch):
    from agent import shorts

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    cap = Captured(content="not json at all")
    monkeypatch.setattr(_http(), "post", cap)
    monkeypatch.setattr(shorts.requests, "post", cap, raising=False)

    assert shorts._llm_plan(_article()) is None


def test_shorts_llm_plan_returns_none_on_network_error(monkeypatch):
    from agent import shorts

    monkeypatch.setenv("OPENAI_API_KEY", "k")

    def boom(*a, **k):
        raise ConnectionError("dns")

    monkeypatch.setattr(_http(), "post", boom)
    monkeypatch.setattr(shorts.requests, "post", boom, raising=False)

    assert shorts._llm_plan(_article()) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
