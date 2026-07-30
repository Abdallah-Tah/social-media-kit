"""Session authentication for the web dashboard.

The dashboard is exposed publicly (e.g. via a Cloudflare tunnel), so it is
gated behind a password login. A single shared password (``DASHBOARD_PASSWORD``,
read from ``config/secrets.env`` via ``agent.config.load_env``) authenticates the
operator; on success the server issues an HMAC-signed, HttpOnly session cookie.

Stateless by design: the server stores no sessions. A token is
``<expiry_unix>.<hmac_sha256(signing_key, expiry_unix)>`` and is verified by
re-deriving the signature and checking the expiry. The signing key is derived
from the password, so rotating the password invalidates every existing session.

Only the API is protected. Static assets and the SPA index are served without
auth so the login page itself can load; the frontend then checks auth and shows
the login screen or the app.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from http.cookies import CookieError, SimpleCookie

SESSION_COOKIE = "smkit_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days
PASSWORD_ENV = "DASHBOARD_PASSWORD"
_KEY_SALT = "smkit-dashboard-session-v1"


def get_password() -> str:
    """The configured dashboard password (empty string if unset)."""
    return os.environ.get(PASSWORD_ENV, "")


def ensure_password() -> str:
    """Return the dashboard password, generating and logging one if unset.

    The dashboard must never be left open when exposed. If no password is
    configured we mint a strong one and print it so the operator can retrieve
    it from the service log and persist it to config/secrets.env.
    """
    pw = get_password()
    if pw:
        return pw
    pw = secrets.token_urlsafe(18)
    os.environ[PASSWORD_ENV] = pw
    line = "=" * 70
    print(line)
    print("  DASHBOARD_PASSWORD was not set — generated a temporary password:")
    print(f"    {pw}")
    print("  Persist it by adding to config/secrets.env:")
    print(f"    DASHBOARD_PASSWORD={pw}")
    print(line, flush=True)
    return pw


def _signing_key() -> bytes:
    return hashlib.sha256((_KEY_SALT + "::" + ensure_password()).encode("utf-8")).digest()


def check_password(candidate: str) -> bool:
    """Constant-time comparison of the submitted password against the secret."""
    expected = ensure_password()
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def create_session_token() -> str:
    expiry = int(time.time()) + SESSION_TTL_SECONDS
    sig = hmac.new(_signing_key(), str(expiry).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expiry_s, _, sig = token.partition(".")
    try:
        expiry = int(expiry_s)
    except ValueError:
        return False
    if expiry < int(time.time()):
        return False
    expected = hmac.new(_signing_key(), expiry_s.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def session_cookie_header(token: str) -> str:
    # HttpOnly hides the token from JS (XSS); SameSite=Lax gives CSRF protection
    # for cross-site POSTs. Secure is intentionally omitted so the cookie also
    # works over plain-http localhost during development.
    return (
        f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
        f"Max-Age={SESSION_TTL_SECONDS}"
    )


def clear_cookie_header() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


def read_session_token(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(cookie_header)
    except CookieError:
        return None
    morsel = jar.get(SESSION_COOKIE)
    return morsel.value if morsel else None


def is_authenticated(cookie_header: str | None) -> bool:
    return verify_session_token(read_session_token(cookie_header))
