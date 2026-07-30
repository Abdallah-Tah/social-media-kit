"""Tests for analytics dashboard integration: sync with date ranges and blog metrics rendering."""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent import dashboard
from agent import dashboard_auth
from agent.analytics_connectors.blog import _write_cache, BlogAnalytics

_ANALYTICS_PASSWORD = "analytics-test-password"
_SESSION_COOKIES: dict[str, str] = {}


def _start_server():
    os.environ[dashboard_auth.PASSWORD_ENV] = _ANALYTICS_PASSWORD
    srv = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard._make_handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv


def _session_cookie(url: str) -> str:
    """Log in once per server and cache the session cookie."""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _SESSION_COOKIES:
        body = json.dumps({"password": _ANALYTICS_PASSWORD}).encode("utf-8")
        req = urllib.request.Request(base + "/api/login", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            set_cookie = r.headers.get("Set-Cookie", "")
        _SESSION_COOKIES[base] = set_cookie.split(";")[0].strip()
    return _SESSION_COOKIES[base]


def _get(url, headers=None):
    headers = dict(headers or {})
    headers["Cookie"] = _session_cookie(url)
    req = urllib.request.Request(url, method="GET", headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read(), r.geturl()


def _post(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, method="POST", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Cookie": _session_cookie(url)})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _patch_cache_dir(tmp_path):
    import agent.analytics_connectors.blog as blog_module
    blog_module.CACHE_DIR = tmp_path / "cache"
    blog_module.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return blog_module


def test_sync_receives_selected_date_range(tmp_path):
    blog_module = _patch_cache_dir(tmp_path)
    from agent import drafts
    drafts.DRAFTS_DIR = tmp_path / "drafts"
    drafts.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    draft = {
        "draft_id": "d-1",
        "title": "My Post",
        "status": "published",
        "blog_url": "https://example.com/tutorials/my-post",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    drafts.DRAFTS_DIR.joinpath("d-1.json").write_text(json.dumps(draft))

    captured = {}

    def fake_get(url, **kwargs):
        captured["params"] = kwargs.get("params")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": "connected", "metrics": {"page_views": 1}}
        return resp

    base_url, srv = _start_server()
    try:
        with patch("agent.analytics_connectors.blog._load_credentials", return_value=("https://example.com/api/v1", "token")):
            with patch("requests.get", side_effect=fake_get):
                status, data = _post(f"{base_url}/api/analytics/sync", {"from": "2026-06-10", "to": "2026-07-10"})

        assert status == 200
        assert data["ok"] is True
        assert captured["params"] == {"from": "2026-06-10", "to": "2026-07-10"}
    finally:
        srv.shutdown()


def test_sync_all_time_sends_no_range(tmp_path):
    blog_module = _patch_cache_dir(tmp_path)
    from agent import drafts
    drafts.DRAFTS_DIR = tmp_path / "drafts"
    drafts.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    draft = {
        "draft_id": "d-1",
        "title": "My Post",
        "status": "published",
        "blog_url": "https://example.com/tutorials/my-post",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    drafts.DRAFTS_DIR.joinpath("d-1.json").write_text(json.dumps(draft))

    captured = {}

    def fake_get(url, **kwargs):
        captured["params"] = kwargs.get("params")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": "connected", "metrics": {"page_views": 1}}
        return resp

    base_url, srv = _start_server()
    try:
        with patch("agent.analytics_connectors.blog._load_credentials", return_value=("https://example.com/api/v1", "token")):
            with patch("requests.get", side_effect=fake_get):
                status, data = _post(f"{base_url}/api/analytics/sync", {})

        assert status == 200
        assert data["ok"] is True
        assert captured["params"] == {}
    finally:
        srv.shutdown()


def test_date_specific_cache_appears_in_matching_analytics_window(tmp_path):
    blog_module = _patch_cache_dir(tmp_path)
    from agent import analytics, drafts
    analytics.DRAFTS_DIR = tmp_path / "drafts"
    analytics.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    draft = {
        "draft_id": "d-1",
        "title": "My Post",
        "status": "published",
        "blog_url": "https://example.com/tutorials/my-post",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    analytics.DRAFTS_DIR.joinpath("d-1.json").write_text(json.dumps(draft))

    _write_cache(
        draft["blog_url"],
        BlogAnalytics(
            blog_url=draft["blog_url"],
            status="connected",
            page_views=123,
            unique_visitors=100,
            clicks=5,
            average_read_time_seconds=60,
            referrers=[{"source": "google", "visits": 80}],
            period={"from": week_ago, "to": today},
            last_sync_at=datetime.now(timezone.utc).isoformat(),
        ),
        from_date=week_ago,
        to_date=today,
    )

    snapshot = analytics.compute_analytics(days=7)
    assert len(snapshot.performance["blog_metrics"]) == 1
    assert snapshot.performance["blog_metrics"][0]["page_views"] == 123


def test_date_specific_cache_does_not_appear_in_different_window(tmp_path):
    blog_module = _patch_cache_dir(tmp_path)
    from agent import analytics, drafts
    analytics.DRAFTS_DIR = tmp_path / "drafts"
    analytics.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    days_ago_60 = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")

    draft = {
        "draft_id": "d-1",
        "title": "My Post",
        "status": "published",
        "blog_url": "https://example.com/tutorials/my-post",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    analytics.DRAFTS_DIR.joinpath("d-1.json").write_text(json.dumps(draft))

    _write_cache(
        draft["blog_url"],
        BlogAnalytics(
            blog_url=draft["blog_url"],
            status="connected",
            page_views=123,
            period={"from": days_ago_60, "to": days_ago_60},
            last_sync_at=datetime.now(timezone.utc).isoformat(),
        ),
        from_date=days_ago_60,
        to_date=days_ago_60,
    )

    snapshot = analytics.compute_analytics(days=7)
    assert snapshot.performance["blog_metrics"] == []


def test_external_performance_renders_connected_blog_metrics(tmp_path):
    blog_module = _patch_cache_dir(tmp_path)
    from agent import analytics, drafts
    analytics.DRAFTS_DIR = tmp_path / "drafts"
    analytics.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    draft = {
        "draft_id": "d-1",
        "title": "My Post",
        "status": "published",
        "blog_url": "https://example.com/tutorials/my-post",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    analytics.DRAFTS_DIR.joinpath("d-1.json").write_text(json.dumps(draft))

    _write_cache(
        draft["blog_url"],
        BlogAnalytics(
            blog_url=draft["blog_url"],
            status="connected",
            page_views=555,
            unique_visitors=333,
            clicks=22,
            average_read_time_seconds=120,
            referrers=[{"source": "linkedin", "visits": 200}],
            period={"from": week_ago, "to": today},
            last_sync_at=datetime.now(timezone.utc).isoformat(),
        ),
        from_date=week_ago,
        to_date=today,
    )

    base_url, srv = _start_server()
    try:
        status, body, _ = _get(f"{base_url}/api/analytics?days=7")
        assert status == 200
        data = json.loads(body)
        assert len(data["performance"]["blog_metrics"]) == 1
        bm = data["performance"]["blog_metrics"][0]
        assert bm["status"] == "connected"
        assert bm["page_views"] == 555
        assert bm["referrers"] == [{"source": "linkedin", "visits": 200}]
    finally:
        srv.shutdown()


def test_external_performance_empty_state(tmp_path):
    from agent import analytics
    analytics.DRAFTS_DIR = tmp_path / "drafts"
    analytics.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    base_url, srv = _start_server()
    try:
        status, body, _ = _get(f"{base_url}/api/analytics?days=7")
        assert status == 200
        data = json.loads(body)
        assert data["performance"]["blog_metrics"] == []
    finally:
        srv.shutdown()


def test_external_performance_error_state(tmp_path):
    blog_module = _patch_cache_dir(tmp_path)
    from agent import analytics, drafts
    analytics.DRAFTS_DIR = tmp_path / "drafts"
    analytics.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    draft = {
        "draft_id": "d-1",
        "title": "My Post",
        "status": "published",
        "blog_url": "https://example.com/tutorials/my-post",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    analytics.DRAFTS_DIR.joinpath("d-1.json").write_text(json.dumps(draft))

    _write_cache(
        draft["blog_url"],
        BlogAnalytics(
            blog_url=draft["blog_url"],
            status="error",
            error="timeout",
            period={"from": week_ago, "to": today},
            last_sync_at=datetime.now(timezone.utc).isoformat(),
        ),
        from_date=week_ago,
        to_date=today,
    )

    snapshot = analytics.compute_analytics(days=7)
    assert len(snapshot.performance["blog_metrics"]) == 1
    assert snapshot.performance["blog_metrics"][0]["status"] == "error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
