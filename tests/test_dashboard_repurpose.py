"""Tests for Reddit/Pinterest tools, repurpose mode, and the dashboard API."""
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agent.config import AgentConfig, load_profile          # noqa: E402
from agent.tools import ToolBox, TOOL_SCHEMAS               # noqa: E402
from agent.prompts import build_repurpose_goal, PLATFORM_TOOLS  # noqa: E402
from agent import cli, history, repurpose, dashboard, dashboard_auth  # noqa: E402

# Password used by the dashboard-API tests; the server fixture installs it so
# the helpers can log in and exercise the authenticated API.
_TEST_DASHBOARD_PASSWORD = "repurpose-test-password"


def _cfg(**kw):
    c = AgentConfig.load(dry_run=kw.pop("dry_run", True))
    c.api_key = "test"
    return c


# ── New platforms are registered + allowlisted ───────────────────────────
def test_reddit_pinterest_registered():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert {"post_reddit", "post_pinterest"} <= names
    assert PLATFORM_TOOLS["reddit"] == "post_reddit"
    assert PLATFORM_TOOLS["pinterest"] == "post_pinterest"


def test_reddit_blocked_unless_enabled():
    prof = load_profile("default")
    prof["platforms"] = ["x"]
    box = ToolBox(_cfg(), prof)
    assert "not enabled" in box.dispatch("post_reddit", {"title": "t", "text": "b"})


def test_pinterest_dry_run_when_enabled():
    prof = load_profile("default")
    prof["platforms"] = ["pinterest"]
    box = ToolBox(_cfg(dry_run=True), prof)
    out = box.dispatch("post_pinterest",
                       {"title": "t", "image_url": "https://x/i.png"})
    assert out.startswith("[DRY RUN]")


# ── Repurpose ─────────────────────────────────────────────────────────────
def test_repurpose_goal_is_source_locked():
    g = build_repurpose_goal("BODY TEXT", "notes.md", {"platforms": ["x", "bluesky"]})
    assert "REPURPOSE MODE" in g and "do not" in g.lower()
    assert "x, bluesky" in g and "BODY TEXT" in g


def test_repurpose_loads_local_file(tmp_path):
    f = tmp_path / "src.md"
    f.write_text("# My article\nLots of insight here.")
    text, ref = repurpose.load_source(str(f))
    assert "insight" in text and ref == "src.md"


def test_repurpose_rejects_missing_source():
    with pytest.raises(ValueError):
        repurpose.load_source("/no/such/file.txt")


def test_repurpose_live_records_history(tmp_path, monkeypatch):
    source = tmp_path / "src.md"
    source.write_text("# Source\nBody")
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "published.json")

    class Result:
        ok = True
        steps = 3
        summary = "published"

    monkeypatch.setattr(repurpose, "repurpose", lambda *a, **kw: Result())
    args = cli.build_parser().parse_args([
        "repurpose", str(source), "--profile", "default", "--yes"
    ])

    assert cli.cmd_repurpose(args) == 0
    entries = history.load()
    assert len(entries) == 1
    assert entries[0]["topic"] == "Repurpose: src.md"
    assert entries[0]["channels"] == load_profile("default")["platforms"]


# ── Dashboard HTTP API (real server, localhost) ──────────────────────────
@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, _TEST_DASHBOARD_PASSWORD)
    srv = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard._make_handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


_SESSION_COOKIES = {}


def _session_cookie(url):
    """Log in once per server and cache the session cookie for API calls."""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _SESSION_COOKIES:
        data = json.dumps({"password": _TEST_DASHBOARD_PASSWORD}).encode("utf-8")
        req = urllib.request.Request(base + "/api/login", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as r:
            set_cookie = r.headers.get("Set-Cookie", "")
        _SESSION_COOKIES[base] = set_cookie.split(";")[0].strip()
    return _SESSION_COOKIES[base]


def _get(url, follow_redirects=False):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "text/html")
    req.add_header("Cookie", _session_cookie(url))
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            final_url = r.geturl()
            return r.status, r.read(), final_url
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), url


def _get_with_headers(url):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Cookie", _session_cookie(url))
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read(), dict(r.headers)

def _post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", _session_cookie(url))
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


def _patch_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PATCH")
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", _session_cookie(url))
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


def test_dashboard_root_serves_react_spa(server):
    status, body, _ = _get(server + "/")
    assert status == 200
    assert b"SMKit Content OS" in body or b"root" in body.lower() or b"<div id=\"root\"></div>" in body


def test_dashboard_react_route_fallback(server):
    status, body, _ = _get(server + "/drafts")
    assert status == 200
    assert b"SMKit Content OS" in body or b"<div id=\"root\"></div>" in body


def test_dashboard_unknown_react_route_falls_back(server):
    status, body, _ = _get(server + "/unknown/react/path")
    assert status == 200
    assert b"SMKit Content OS" in body or b"<div id=\"root\"></div>" in body


def test_dashboard_intelligence_legacy_page_still_serves(server):
    status, body, _ = _get(server + "/legacy/intelligence")
    assert status == 200
    assert b"smkit Intelligence" in body or b"AI Content Operating System" in body


def test_dashboard_legacy_repurpose_page_still_serves(server):
    status, body, _ = _get(server + "/legacy/dashboard")
    assert status == 200
    assert b"Social Media Agent" in body or b"Repurpose" in body




def test_dashboard_root_frontend_asset_serves_or_404s(server):
    for asset in ["/favicon.svg", "/robots.txt", "/manifest.webmanifest"]:
        status, body, _ = _get(server + asset)
        assert status in {200, 404}
        if status == 200:
            assert body
            assert b"<!doctype html" not in body.lower()
        else:
            assert json.loads(body)["error"] == "not found"


def test_dashboard_missing_file_like_path_returns_404(server):
    status, body, _ = _get(server + "/missing.js")
    assert status == 404
    assert json.loads(body)["error"] == "not found"

def test_dashboard_assets_serve_static_content(server):
    # Ensure build exists; skip if not.
    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    assets = list(dist.glob("assets/*.*"))
    if not assets:
        pytest.skip("no built frontend assets")
    asset = assets[0]
    status, body, headers = _get_with_headers(server + "/assets/" + asset.name)
    assert status == 200
    assert len(body) > 0
    assert headers["Content-Type"]


def test_dashboard_api_remains_json(server):
    status, body, _ = _get(server + "/api/state")
    data = json.loads(body)
    assert status == 200
    assert "profiles" in data and "history" in data and "drafts" in data


def test_dashboard_unknown_api_returns_json_404(server):
    status, body, _ = _get(server + "/api/unknown")
    data = json.loads(body)
    assert status == 404
    assert data["error"] == "not found"


def test_dashboard_intelligence_snapshots_api_remains_json(server):
    status, body, _ = _get(server + "/api/intelligence/snapshots")
    data = json.loads(body)
    assert status == 200
    assert data["ok"] is True
    assert "snapshots" in data


def test_dashboard_missing_frontend_build_returns_setup_message(server, monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "FRONTEND_DIST", tmp_path / "no_dist")
    status, body, _ = _get(server + "/")
    assert status == 503
    data = json.loads(body)
    assert "npm ci" in data.get("message", "")


def test_dashboard_root_redirects_to_intelligence(server):
    status, body, final_url = _get(server + "/")
    assert status == 200, f"expected 200, got {status}"
    assert b"SMKit Content OS" in body or b"<div id=\"root\"></div>" in body


def test_dashboard_intelligence_serves_page(server):
    status, body, _ = _get(server + "/intelligence")
    assert status == 200
    assert b"SMKit Content OS" in body or b"<div id=\"root\"></div>" in body


def test_dashboard_legacy_dashboard_redirect_or_serve(server):
    status, body, _ = _get(server + "/dashboard")
    assert status == 200


def test_dashboard_state_endpoint(server):
    status, body, _ = _get(server + "/api/state")
    data = json.loads(body)
    assert status == 200
    assert "profiles" in data and "history" in data and "drafts" in data


def test_dashboard_port_in_use_is_friendly(capsys):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    port = s.getsockname()[1]
    try:
        # Must return cleanly (not raise, not block) when the port is taken.
        dashboard.serve(host="127.0.0.1", port=port)
        out = capsys.readouterr().out
        assert "in use" in out
    finally:
        s.close()


def test_dashboard_run_dry(server):
    payload = json.dumps({"mode": "run", "input": "", "dry_run": True}).encode()
    req = urllib.request.Request(server + "/api/run", data=payload,
                                 headers={"Content-Type": "application/json",
                                          "Cookie": _session_cookie(server + "/api/run")})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
    # Empty input is rejected cleanly (no crash, structured error).
    assert data["ok"] is False and "topic" in data["error"].lower()


def test_dashboard_drafts_api_is_exposed(server, monkeypatch, tmp_path):
    from agent import drafts

    original_dir = drafts.DRAFTS_DIR
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    draft = drafts.ContentDraft(title="Dashboard Draft", body="Body")
    drafts.save_draft(draft)
    try:
        status, body, _ = _get(server + "/api/drafts")
        data = json.loads(body)
        assert status == 200
        assert data["ok"] is True
        assert data["drafts"][0]["title"] == "Dashboard Draft"
    finally:
        monkeypatch.setattr(drafts, "DRAFTS_DIR", original_dir)


def test_dashboard_patch_draft_api_is_exposed(server, monkeypatch, tmp_path):
    from agent import drafts

    original_dir = drafts.DRAFTS_DIR
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    draft = drafts.ContentDraft(title="Needs Review", body="Body")
    drafts.save_draft(draft)
    try:
        status, body = _patch_json(server + f"/api/drafts/{draft.draft_id}", {"status": "approved"})
        data = json.loads(body)
        assert status == 200
        assert data["ok"] is True
        assert data["draft"]["status"] == "approved"
    finally:
        monkeypatch.setattr(drafts, "DRAFTS_DIR", original_dir)


def test_dashboard_social_drafts_api_and_publish_due_are_exposed(server, monkeypatch, tmp_path):
    from agent import social_drafts

    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", tmp_path)
    created = social_drafts.create_social_drafts_from_blog(
        "source",
        "https://example.com/blog",
        "Rate limiting Laravel queues without losing jobs",
        (
        "Laravel queue workers will happily run the same job twice when a worker is "
        "restarted mid-execution, because the reserved_at timestamp is cleared "
        "before the handler finishes. That double execution stays invisible until "
        "it charges a customer twice.\n\nWrap the handler in an atomic Redis lock "
        "keyed on the job payload hash and release it after the transaction commits."
        ),
        ["linkedin"],
    )[0]
    created.status = "approved"
    social_drafts.save_social_draft(created)
    try:
        status, body, _ = _get(server + "/api/social_drafts")
        data = json.loads(body)
        assert status == 200
        assert data["ok"] is True
        assert data["drafts"][0]["title"] == "Rate limiting Laravel queues without losing jobs"

        when = "2000-01-01T00:00:00+00:00"
        status, body = _post_json(server + "/api/social_drafts/schedule", {"ids": [created.draft_id], "scheduled_at": when})
        data = json.loads(body)
        assert status == 200
        assert data["results"][created.draft_id]["ok"] is True

        status, body = _post_json(server + "/api/social_drafts/publish_due", {"dry_run": True})
        data = json.loads(body)
        assert status == 200
        assert data["ok"] is True
        assert data["results"][created.draft_id]["ok"] is True
    finally:
        monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", original_dir)


def test_dashboard_intelligence_save_requires_run(server, monkeypatch):
    from agent import dashboard_intelligence

    monkeypatch.setattr(dashboard_intelligence, "_LAST_RUN_CARDS", [])
    status, body = _post_json(server + "/api/intelligence/save", {})
    data = json.loads(body)
    assert status == 200
    assert data["ok"] is False
    assert "no intelligence run" in data["error"]
