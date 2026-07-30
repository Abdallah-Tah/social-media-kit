"""Tests for dashboard session authentication (agent/dashboard_auth.py + wiring).

Spins up the real dashboard HTTP handler on an ephemeral port and exercises the
login handshake, session enforcement, logout, and the public SPA/login routes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from agent import dashboard
from agent import dashboard_auth

TEST_PASSWORD = "test-dashboard-password-123"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, TEST_PASSWORD)
    srv = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard._make_handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _request(url, method="GET", payload=None, cookie=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def _login(base, password):
    status, _, headers = _request(base + "/api/login", "POST", {"password": password})
    return status, headers.get("Set-Cookie", "")


def _cookie(set_cookie):
    # "smkit_session=xyz; Path=/; HttpOnly; ..." -> "smkit_session=xyz"
    return set_cookie.split(";")[0].strip() if set_cookie else ""


# ── Unit tests for the auth primitives ──────────────────────────────────────

def test_password_check(monkeypatch):
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, "s3cret")
    assert dashboard_auth.check_password("s3cret") is True
    assert dashboard_auth.check_password("nope") is False


def test_token_roundtrip(monkeypatch):
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, "s3cret")
    tok = dashboard_auth.create_session_token()
    assert dashboard_auth.verify_session_token(tok) is True
    assert dashboard_auth.verify_session_token("garbage") is False
    assert dashboard_auth.verify_session_token(None) is False


def test_tampered_token_rejected(monkeypatch):
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, "s3cret")
    tok = dashboard_auth.create_session_token()
    expiry, _, _ = tok.partition(".")
    assert dashboard_auth.verify_session_token(f"{expiry}.deadbeef") is False


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, "s3cret")
    expiry = int(time.time()) - 100  # already in the past
    sig = hmac.new(dashboard_auth._signing_key(), str(expiry).encode(), hashlib.sha256).hexdigest()
    assert dashboard_auth.verify_session_token(f"{expiry}.{sig}") is False


def test_password_rotation_invalidates_sessions(monkeypatch):
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, "first")
    tok = dashboard_auth.create_session_token()
    assert dashboard_auth.verify_session_token(tok) is True
    monkeypatch.setenv(dashboard_auth.PASSWORD_ENV, "second")
    assert dashboard_auth.verify_session_token(tok) is False


# ── HTTP-level tests ────────────────────────────────────────────────────────

def test_api_requires_auth(server):
    status, body, _ = _request(server + "/api/state")
    assert status == 401
    assert json.loads(body)["error"] == "unauthorized"


def test_login_wrong_password(server):
    status, set_cookie = _login(server, "wrong-password")
    assert status == 401
    assert "smkit_session=" not in set_cookie


def test_login_correct_password_sets_httponly_cookie(server):
    status, set_cookie = _login(server, TEST_PASSWORD)
    assert status == 200
    assert "smkit_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie


def test_authenticated_request_succeeds(server):
    _, set_cookie = _login(server, TEST_PASSWORD)
    status, body, _ = _request(server + "/api/state", cookie=_cookie(set_cookie))
    assert status == 200
    assert "profiles" in json.loads(body)


def test_auth_check_reflects_session(server):
    # Unauthenticated.
    status, body, _ = _request(server + "/api/auth/check")
    assert status == 200
    assert json.loads(body)["authenticated"] is False
    # Authenticated.
    _, set_cookie = _login(server, TEST_PASSWORD)
    status, body, _ = _request(server + "/api/auth/check", cookie=_cookie(set_cookie))
    assert status == 200
    assert json.loads(body)["authenticated"] is True


def test_logout_clears_cookie(server):
    _, set_cookie = _login(server, TEST_PASSWORD)
    status, _, headers = _request(server + "/api/logout", "POST", {}, cookie=_cookie(set_cookie))
    assert status == 200
    assert "Max-Age=0" in headers.get("Set-Cookie", "")


def test_tampered_cookie_rejected_over_http(server):
    status, _, _ = _request(server + "/api/state", cookie="smkit_session=9999999999.deadbeef")
    assert status == 401


def test_spa_index_is_public(server):
    # The SPA (and therefore the login screen) must load without a session.
    # 200 when the build is present, 503 when absent — never 401.
    status, _, _ = _request(server + "/")
    assert status in (200, 503)


def test_login_route_is_public(server):
    status, _, _ = _request(server + "/login")
    assert status in (200, 503)


def test_editorial_api_is_protected(server):
    # The Stage 7D endpoint is behind auth like every other API route.
    status, _, _ = _request(server + "/api/editorial/stage7d-status")
    assert status == 401
