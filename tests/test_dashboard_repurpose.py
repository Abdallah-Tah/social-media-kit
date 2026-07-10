"""Tests for Reddit/Pinterest tools, repurpose mode, and the dashboard API."""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agent.config import AgentConfig, load_profile          # noqa: E402
from agent.tools import ToolBox, TOOL_SCHEMAS               # noqa: E402
from agent.prompts import build_repurpose_goal, PLATFORM_TOOLS  # noqa: E402
from agent import cli, history, repurpose, dashboard        # noqa: E402


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
def server(tmp_path, monkeypatch):
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id=\"root\"></div></body></html>",
        encoding="utf-8",
    )
    (dist / "favicon.svg").write_text(
        "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    monkeypatch.setattr(dashboard, "FRONTEND_DIST_DIR", dist)
    monkeypatch.setattr(dashboard, "FRONTEND_INDEX", dist / "index.html")
    srv = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard._make_handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read(), r.headers.get("Content-Type")


def _get_error(url):
    try:
        return _get(url)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type")


def test_dashboard_legacy_page_stays_under_legacy_path(server):
    status, body, ctype = _get(server + "/legacy/dashboard")
    assert status == 200 and b"Social Media Agent" in body
    assert ctype.startswith("text/html")


def test_dashboard_root_serves_react_spa(server):
    status, body, ctype = _get(server + "/")
    assert status == 200
    assert ctype.startswith("text/html")
    assert b'id="root"' in body


def test_dashboard_state_endpoint(server):
    status, body, _ctype = _get(server + "/api/state")
    data = json.loads(body)
    assert status == 200
    assert "profiles" in data and "history" in data and "drafts" in data


def test_dashboard_favicon_is_static_svg(server):
    status, body, ctype = _get(server + "/favicon.svg")
    assert status == 200
    assert ctype.startswith("image/svg+xml")
    assert body.startswith(b"<svg")


def test_dashboard_missing_file_like_path_is_404(server):
    status, _body, _ctype = _get_error(server + "/missing.js")
    assert status == 404


def test_dashboard_missing_asset_is_404(server):
    status, _body, _ctype = _get_error(server + "/assets/missing.js")
    assert status == 404


def test_dashboard_unknown_react_route_gets_index(server):
    status, body, ctype = _get(server + "/unknown-react-route")
    assert status == 200
    assert ctype.startswith("text/html")
    assert b'id="root"' in body


def test_dashboard_unknown_api_is_json_404(server):
    status, body, ctype = _get_error(server + "/api/unknown")
    assert status == 404
    assert ctype.startswith("application/json")
    assert json.loads(body)["error"] == "not found"


def test_dashboard_blocks_frontend_path_traversal(server):
    # If traversal were incorrectly allowed, this would be served from dist/.
    (dashboard.FRONTEND_DIST_DIR / "secret.js").write_text("secret", encoding="utf-8")
    status, _body, _ctype = _get_error(server + "/assets/../secret.js")
    assert status == 404


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
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
    # Empty input is rejected cleanly (no crash, structured error).
    assert data["ok"] is False and "topic" in data["error"].lower()
