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


def _make_connector(tmp_path):
    from agent import analytics_connectors
    analytics_connectors.blog.CACHE_DIR = tmp_path / "cache"
    analytics_connectors.blog.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return analytics_connectors.blog


def test_fetch_blog_analytics_nested_metrics_and_cache(tmp_path):
    blog = _make_connector(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "connected",
        "slug": "my-post",
        "blog_url": "https://example.com/tutorials/my-post",
        "published_at": "2026-07-09T19:01:26Z",
        "period": {"from": "2026-07-01", "to": "2026-07-09"},
        "metrics": {
            "page_views": 1250,
            "unique_visitors": 930,
            "clicks": 145,
            "average_read_time_seconds": 224,
            "referrers": [
                {"source": "google", "visits": 410},
                {"source": "linkedin", "visits": 320},
            ],
        },
    }

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = fetch_blog_analytics("https://example.com/tutorials/my-post")

    assert result.status == "connected"
    assert result.page_views == 1250
    assert result.unique_visitors == 930
    assert result.clicks == 145
    assert result.average_read_time_seconds == 224
    assert result.referrers == [
        {"source": "google", "visits": 410},
        {"source": "linkedin", "visits": 320},
    ]
    assert result.period == {"from": "2026-07-01", "to": "2026-07-09"}

    # Cache hit
    cached = fetch_blog_analytics("https://example.com/tutorials/my-post")
    assert cached.page_views == 1250


def test_fetch_blog_analytics_flat_legacy_response(tmp_path):
    blog = _make_connector(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "connected",
        "page_views": 88,
        "unique_visitors": 77,
        "clicks": 5,
        "average_read_time_seconds": 60,
        "referrers": {"facebook": 30, "twitter": 7},
    }

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = fetch_blog_analytics("https://example.com/tutorials/legacy-post")

    assert result.status == "connected"
    assert result.page_views == 88
    assert result.referrers == [
        {"source": "facebook", "visits": 30},
        {"source": "twitter", "visits": 7},
    ]


def test_fetch_blog_analytics_not_connected_response(tmp_path):
    blog = _make_connector(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "not_connected",
        "slug": "my-post",
        "blog_url": "https://example.com/tutorials/my-post",
        "published_at": "2026-07-09T19:01:26Z",
        "period": {"from": "2026-07-01", "to": "2026-07-09"},
        "metrics": {
            "page_views": None,
            "unique_visitors": None,
            "clicks": None,
            "average_read_time_seconds": None,
            "referrers": [],
        },
    }

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = fetch_blog_analytics("https://example.com/tutorials/my-post")

    assert result.status == "not_connected"
    assert result.page_views is None
    assert result.referrers == []


def test_fetch_blog_analytics_not_found_404(tmp_path):
    blog = _make_connector(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "not found"

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = fetch_blog_analytics("https://example.com/tutorials/missing-post")

    assert result.status == "not_found"
    assert result.error == "Post not found"
    assert result.page_views is None


def test_fetch_blog_analytics_unauthorized_401(tmp_path):
    blog = _make_connector(tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthenticated"

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = fetch_blog_analytics("https://example.com/tutorials/my-post")

    assert result.status == "unauthorized"
    assert "token" in result.error.lower()


def test_fetch_blog_analytics_date_range_query_params(tmp_path):
    blog = _make_connector(tmp_path)
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": "connected", "metrics": {"page_views": 100}}
        return resp

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", side_effect=fake_get):
            fetch_blog_analytics("https://example.com/tutorials/dated-post", from_date="2026-07-01", to_date="2026-07-09")

    assert captured["params"] == {"from": "2026-07-01", "to": "2026-07-09"}


def test_separate_caches_for_different_date_ranges(tmp_path):
    blog = _make_connector(tmp_path)

    def make_resp(views):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": "connected", "metrics": {"page_views": views}}
        return resp

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", side_effect=[make_resp(100), make_resp(200)]):
            all_time = fetch_blog_analytics("https://example.com/tutorials/range-post")
            week = fetch_blog_analytics("https://example.com/tutorials/range-post", from_date="2026-07-01", to_date="2026-07-09")

    assert all_time.page_views == 100
    assert week.page_views == 200

    # Re-read both caches
    assert fetch_blog_analytics("https://example.com/tutorials/range-post").page_views == 100
    assert fetch_blog_analytics("https://example.com/tutorials/range-post", from_date="2026-07-01", to_date="2026-07-09").page_views == 200


def test_sync_blog_analytics_with_published_draft(tmp_path):
    from agent import drafts
    blog = _make_connector(tmp_path)
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
    mock_resp.json.return_value = {
        "status": "connected",
        "metrics": {"page_views": 500, "referrers": [{"source": "linkedin", "visits": 50}]},
    }

    with patch.object(blog, "_load_credentials", return_value=("https://example.com/api/v1", "token")):
        with patch("requests.get", return_value=mock_resp):
            result = sync_blog_analytics(draft_dir=drafts.DRAFTS_DIR)

    assert result["ok"]
    assert result["synced"] == 1
    assert result["connected_count"] == 1
    assert result["results"][0]["page_views"] == 500
    assert result["results"][0]["referrers"] == [{"source": "linkedin", "visits": 50}]


def test_sync_blog_analytics_ignores_unpublished_draft(tmp_path):
    from agent import drafts
    blog = _make_connector(tmp_path)
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
