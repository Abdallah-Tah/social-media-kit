"""Tests for Tier 2: brand learning, history/dedupe, blog platform adapters."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agent import learn, history          # noqa: E402
import blog_publisher as bp               # noqa: E402


# ── learn: robust JSON extraction ────────────────────────────────────────
def test_extract_json_handles_code_fences_and_prose():
    raw = 'Here you go:\n```json\n{"name": "Acme", "tone": "bold"}\n```'
    data = learn._extract_json(raw)
    assert data["name"] == "Acme" and data["tone"] == "bold"


def test_extract_json_plain_object():
    assert learn._extract_json('{"a": 1}') == {"a": 1}


# ── history: dedupe normalization ────────────────────────────────────────
def test_history_record_and_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "published.json")
    assert not history.has_topic("Laravel 13 New Features")
    history.record({"topic": "Laravel 13 New Features", "channels": ["x"]})
    # Case/punctuation-insensitive match.
    assert history.has_topic("laravel 13   new features!")
    assert not history.has_topic("Totally different topic")
    assert len(history.load()) == 1


# ── Ghost JWT structure (no external jwt lib) ────────────────────────────
def test_ghost_jwt_has_three_parts_and_kid():
    import base64, json
    # id:hex-secret
    token = bp._ghost_jwt("64f0a:" + "ab" * 32)
    parts = token.split(".")
    assert len(parts) == 3
    header = json.loads(base64.urlsafe_b64decode(parts[0] + "=="))
    assert header["alg"] == "HS256" and header["kid"] == "64f0a"


# ── Blog platform dispatch routes to the right adapter ───────────────────
def test_blog_dispatch_wordpress(monkeypatch):
    monkeypatch.setenv("BLOG_PLATFORM", "wordpress")
    monkeypatch.setenv("BLOG_API_USER", "admin")
    monkeypatch.setattr(bp, "load_credentials", lambda: ("https://site.com", "apppass"))
    captured = {}

    class R:
        status_code = 201
        def json(self): return {"id": 7, "link": "https://s/p"}
    def fake_post(url, **kw):
        captured["url"] = url
        captured["auth"] = kw.get("auth")
        return R()
    monkeypatch.setattr(bp.requests, "post", fake_post)

    out = bp.publish_article("T", "t", "body")
    assert "/wp-json/wp/v2/posts" in captured["url"]
    assert captured["auth"] == ("admin", "apppass")
    assert out and out["id"] == 7


def test_blog_dispatch_generic(monkeypatch):
    monkeypatch.setenv("BLOG_PLATFORM", "generic")

    class R:
        status_code = 201
        def json(self): return {"data": {"id": 3, "slug": "t"}}
    monkeypatch.setattr(bp.requests, "post", lambda url, **kw: R())
    # Force credentials so the function proceeds.
    monkeypatch.setattr(bp, "load_credentials", lambda: ("https://api", "tok"))
    out = bp.publish_article("T", "t", "body")
    assert out and out["id"] == 3
