"""Tests for the blog analytics connector.

All external API calls are mocked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.analytics_connectors.blog import (
    BlogAnalytics,
    fetch_blog_analytics,
    sync_blog_analytics,
)


def test_fetch_blog_analytics_ok_and_cache(tmp_path):
    from agent import analytics_connectors
    analytics_connectors.blog.CACHE_DIR = tmp_path / "cache"
    analytics_connectors.blog.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "page_views": 1200,
            "unique_visitors": 900,
            "clicks": 45,
            "average_read_time_seconds": 124,
            "referrers": {"google": 600, "linkedin": 300},
            "published_at": "2026-07-09T19:01:26Z",
        }
    }

    with patch("agent.analytics_connectors.blog._load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = fetch_blog_analytics("https://example.com/tutorials/my-post")

    assert result.status == "ok"
    assert result.page_views == 1200
    assert result.unique_visitors == 900
    assert result.clicks == 45
    assert result.average_read_time_seconds == 124
    assert result.referrers["google"] == 600
    assert result.publication_date == "2026-07-09T19:01:26Z"

    # Cache hit
    cached = fetch_blog_analytics("https://example.com/tutorials/my-post")
    assert cached.page_views == 1200
    assert cached.last_sync_at == result.last_sync_at


def test_fetch_blog_analytics_not_connected(tmp_path):
    from agent import analytics_connectors
    analytics_connectors.blog.CACHE_DIR = tmp_path / "cache"
    analytics_connectors.blog.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "not found"

    with patch("agent.analytics_connectors.blog._load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = fetch_blog_analytics("https://example.com/tutorials/my-post")

    assert result.status == "not_connected"
    assert result.page_views is None
    assert result.error == "Analytics endpoint not available for this post"


def test_fetch_blog_analytics_error(tmp_path):
    from agent import analytics_connectors
    analytics_connectors.blog.CACHE_DIR = tmp_path / "cache"
    analytics_connectors.blog.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    with patch("agent.analytics_connectors.blog._load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetch_blog_analytics("https://example.com/tutorials/my-post")

    assert result.status == "error"
    assert "timeout" in result.error
    assert result.page_views is None


def test_sync_blog_analytics_with_published_draft(tmp_path):
    from agent import analytics_connectors, drafts
    analytics_connectors.blog.CACHE_DIR = tmp_path / "cache"
    analytics_connectors.blog.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    drafts.DRAFTS_DIR = tmp_path / "drafts"
    drafts.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    draft = {
        "draft_id": "d-1",
        "title": "My Post",
        "status": "published",
        "blog_url": "https://example.com/tutorials/my-post",
        "created_at": "2026-07-09T00:00:00+00:00",
    }
    drafts.DRAFTS_DIR.joinpath("d-1.json").write_text(json.dumps(draft))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"page_views": 500}}

    with patch("agent.analytics_connectors.blog._load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = sync_blog_analytics(draft_dir=drafts.DRAFTS_DIR)

    assert result["ok"]
    assert result["synced"] == 1
    assert result["ok_count"] == 1
    assert result["results"][0]["page_views"] == 500


def test_sync_blog_analytics_ignores_unpublished_draft(tmp_path):
    from agent import analytics_connectors, drafts
    analytics_connectors.blog.CACHE_DIR = tmp_path / "cache"
    analytics_connectors.blog.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    drafts.DRAFTS_DIR = tmp_path / "drafts"
    drafts.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    draft = {
        "draft_id": "d-2",
        "title": "Draft Post",
        "status": "draft",
        "blog_url": "https://example.com/tutorials/draft-post",
        "created_at": "2026-07-09T00:00:00+00:00",
    }
    drafts.DRAFTS_DIR.joinpath("d-2.json").write_text(json.dumps(draft))

    result = sync_blog_analytics(draft_dir=drafts.DRAFTS_DIR)
    assert result["synced"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
