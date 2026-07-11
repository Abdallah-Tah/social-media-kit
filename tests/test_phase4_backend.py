"""Phase 4 backend tests: connections, retry, sources config, analytics."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))


# ── Connections ──────────────────────────────────────────────────────────────

def test_check_connections_returns_all_platforms():
    from agent.connections import check_connections, PLATFORM_SPECS
    with patch.dict("os.environ", {}, clear=False):
        result = check_connections()
    ids = {r["id"] for r in result}
    expected = {s["id"] for s in PLATFORM_SPECS}
    assert ids == expected


def test_newsletter_always_connected():
    from agent.connections import check_connections
    result = check_connections()
    newsletter = next(r for r in result if r["id"] == "newsletter")
    assert newsletter["connected"] is True
    assert newsletter["missing_vars"] == []


def test_blog_disconnected_without_env():
    from agent.connections import check_connections
    import os
    # Patch load_env to be a no-op so secrets.env can't repopulate
    with patch("agent.connections.load_env"):
        env_without_blog = {k: v for k, v in os.environ.items()
                            if k not in ("BLOG_API_URL", "BLOG_API_TOKEN")}
        with patch.dict("os.environ", env_without_blog, clear=True):
            result = check_connections()
    blog = next(r for r in result if r["id"] == "blog")
    assert blog["connected"] is False
    assert len(blog["missing_vars"]) > 0


def test_blog_connected_with_env():
    from agent.connections import check_connections
    with patch.dict("os.environ", {"BLOG_API_URL": "https://blog.example.com", "BLOG_API_TOKEN": "tok"}):
        result = check_connections()
    blog = next(r for r in result if r["id"] == "blog")
    assert blog["connected"] is True
    assert blog["missing_vars"] == []


def test_connection_has_last_publish_fields(tmp_path, monkeypatch):
    from agent import connections
    # No social drafts dir → graceful fallback
    monkeypatch.setattr(connections, "ROOT", tmp_path)
    result = connections.check_connections()
    for conn in result:
        assert "last_publish_status" in conn
        assert "last_publish_at" in conn


# ── Social draft retry ────────────────────────────────────────────────────────

def test_retry_failed_draft(tmp_path, monkeypatch):
    from agent import social_drafts
    monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", tmp_path)
    sd = social_drafts.SocialDraft(platform="linkedin", title="T", status="failed", error="API down")
    social_drafts.save_social_draft(sd)
    result = social_drafts.retry_social_draft(sd.draft_id)
    assert result["ok"] is True
    loaded = social_drafts.load_social_draft(sd.draft_id)
    assert loaded.status == "approved"
    assert loaded.error == ""
    assert any(h["from"] == "failed" and h["to"] == "approved" for h in loaded.history)


def test_retry_non_failed_draft_returns_error(tmp_path, monkeypatch):
    from agent import social_drafts
    monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", tmp_path)
    sd = social_drafts.SocialDraft(platform="x", title="T", status="draft")
    social_drafts.save_social_draft(sd)
    result = social_drafts.retry_social_draft(sd.draft_id)
    assert result["ok"] is False
    assert "failed" in result["error"]


def test_retry_unknown_draft_returns_error(tmp_path, monkeypatch):
    from agent import social_drafts
    monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", tmp_path)
    result = social_drafts.retry_social_draft("nonexistent")
    assert result["ok"] is False
    assert "not found" in result["error"]


# ── Intelligence config store ─────────────────────────────────────────────────

def test_load_empty_config_returns_defaults(tmp_path, monkeypatch):
    from agent import intelligence_config_store as store
    monkeypatch.setattr(store, "CONFIG_FILE", tmp_path / "cfg.json")
    cfg = store.get_intelligence_config_dict()
    assert "enable_reddit" in cfg
    assert "reddit_subreddits" in cfg
    assert isinstance(cfg["reddit_subreddits"], list)


def test_save_and_reload_config_override(tmp_path, monkeypatch):
    from agent import intelligence_config_store as store
    monkeypatch.setattr(store, "CONFIG_FILE", tmp_path / "cfg.json")
    store.save_config_overrides({"enable_reddit": False, "reddit_subreddits": ["python"]})
    cfg = store.get_intelligence_config_dict()
    assert cfg["enable_reddit"] is False
    assert cfg["reddit_subreddits"] == ["python"]


def test_config_ignores_disallowed_fields(tmp_path, monkeypatch):
    from agent import intelligence_config_store as store
    monkeypatch.setattr(store, "CONFIG_FILE", tmp_path / "cfg.json")
    store.save_config_overrides({"top_n": 999, "report_path": "/etc/passwd"})
    overrides = store.load_config_overrides()
    assert "top_n" not in overrides
    assert "report_path" not in overrides


# ── Analytics funnel with new statuses ───────────────────────────────────────

def test_editorial_funnel_counts_new_statuses():
    from agent.analytics import _editorial_funnel
    drafts = [
        {"status": "idea"},
        {"status": "draft"},
        {"status": "needs_review"},
        {"status": "approved"},
        {"status": "published"},
        {"status": "published"},
    ]
    result = _editorial_funnel(drafts)
    assert result["drafts_created"] == 6
    assert result["blogs_published"] == 2
    assert result["drafts_approved"] == 3  # approved + published*2
    sc = result["status_counts"]
    assert sc.get("idea", 0) == 1
    assert sc.get("needs_review", 0) == 1


def test_editorial_funnel_legacy_reviewed_counted(tmp_path):
    from agent.analytics import _editorial_funnel
    drafts = [{"status": "reviewed"}, {"status": "approved"}]
    result = _editorial_funnel(drafts)
    assert result["drafts_reviewed"] == 2


# ── Campaign analytics ────────────────────────────────────────────────────────

def test_campaign_analytics_empty_when_no_campaigns(tmp_path, monkeypatch):
    from agent import analytics
    monkeypatch.setattr(analytics, "ROOT", tmp_path)
    result = analytics.campaign_analytics()
    assert result == []


def test_campaign_analytics_returns_linked_data(tmp_path, monkeypatch):
    from agent import analytics
    monkeypatch.setattr(analytics, "ROOT", tmp_path)
    # Create campaign + draft structure
    (tmp_path / "content" / "campaigns").mkdir(parents=True)
    (tmp_path / "content" / "drafts").mkdir(parents=True)
    draft_id = "abc123"
    campaign = {
        "campaign_id": "camp1",
        "headline": "AI Topic",
        "created_at": "2026-07-01T00:00:00Z",
        "content_draft_id": draft_id,
        "social_draft_ids": {"linkedin": "sd1"},
        "source_card": {"cluster": {"headline": "AI Topic"}},
    }
    draft = {"draft_id": draft_id, "status": "published", "blog_url": "https://blog.example.com/ai"}
    (tmp_path / "content" / "campaigns" / "camp1.json").write_text(json.dumps(campaign))
    (tmp_path / "content" / "drafts" / f"{draft_id}.json").write_text(json.dumps(draft))
    result = analytics.campaign_analytics()
    assert len(result) == 1
    assert result[0]["headline"] == "AI Topic"
    assert result[0]["content_status"] == "published"
    assert result[0]["blog_url"] == "https://blog.example.com/ai"
    assert result[0]["platforms"] == ["linkedin"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
