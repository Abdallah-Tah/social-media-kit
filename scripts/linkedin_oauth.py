#!/usr/bin/env python3
"""LinkedIn OAuth2 flow to mint an access token.

Two non-interactive steps, so this works over SSH on a headless box:

    /usr/bin/python3 scripts/linkedin_oauth.py auth-url
    /usr/bin/python3 scripts/linkedin_oauth.py exchange-code --code '<code>'

LinkedIn member tokens last ~60 days and there is no refresh token unless the
app is approved for one, so this is a recurring manual step. `status` reports
how long the current token has left.

Setup: https://www.linkedin.com/developers/
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "config" / "secrets.env"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from agent.config import load_env  # noqa: E402

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
DEFAULT_REDIRECT_URI = "https://www.linkedin.com/developers/tools/oauth/redirect"

# r_liteprofile / r_emailaddress were retired when LinkedIn moved to OpenID
# Connect; requesting them now fails the consent screen outright.
# w_member_social is the one that actually authorises posting.
DEFAULT_SCOPES = "openid profile w_member_social"


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set in config/secrets.env")
    return value


def _upsert_secret(key: str, value: str) -> None:
    """Replace one line in place.

    Rewriting the file as parsed key=value pairs would drop comments and mangle
    the multi-line JSON credentials that live alongside these tokens.
    """
    lines = SECRETS.read_text().splitlines() if SECRETS.exists() else []
    out, done = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    SECRETS.write_text("\n".join(out) + "\n")
    os.chmod(SECRETS, 0o600)


def auth_url(args) -> None:
    params = {
        "response_type": "code",
        "client_id": _require("LINKEDIN_CLIENT_ID"),
        "redirect_uri": args.redirect_uri,
        "scope": args.scopes,
    }
    print(f"{AUTH_URL}?{urllib.parse.urlencode(params)}")
    print("\nApprove in a browser, then copy the code= value from the redirect URL.")
    print("The code expires in ~30 seconds — exchange it immediately.")


def exchange_code(args) -> None:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": args.code,
            "redirect_uri": args.redirect_uri,
            "client_id": _require("LINKEDIN_CLIENT_ID"),
            "client_secret": _require("LINKEDIN_CLIENT_SECRET"),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if not resp.ok:
        raise SystemExit(f"token exchange failed ({resp.status_code}): {resp.text[:400]}")
    result = resp.json()
    token = result.get("access_token")
    if not token:
        raise SystemExit(f"no access_token in response: {str(result)[:300]}")

    _upsert_secret("LINKEDIN_ACCESS_TOKEN", token)
    print(f"✅ LINKEDIN_ACCESS_TOKEN saved to {SECRETS.relative_to(ROOT)} "
          f"(expires in {result.get('expires_in', 0) // 86400} days)")
    _verify(token)


def _verify(token: str) -> bool:
    r = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.ok:
        print(f"   verified as: {r.json().get('name', '?')}")
        return True
    # w_member_social alone still posts; userinfo needs openid+profile.
    print(f"   ⚠️  userinfo returned {r.status_code}: {r.text[:200]}")
    return False


def status(args) -> None:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("LINKEDIN_ACCESS_TOKEN is not set")
    print(f"token length: {len(token)}")
    raise SystemExit(0 if _verify(token) else 1)


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="LinkedIn OAuth2 token tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_auth = sub.add_parser("auth-url", help="Print the LinkedIn consent URL")
    p_auth.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    p_auth.add_argument("--scopes", default=os.environ.get("LINKEDIN_SCOPES", DEFAULT_SCOPES))
    p_auth.set_defaults(func=auth_url)

    p_code = sub.add_parser("exchange-code", help="Exchange the code for an access token")
    p_code.add_argument("--code", required=True)
    p_code.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    p_code.set_defaults(func=exchange_code)

    p_stat = sub.add_parser("status", help="Check whether the stored token still works")
    p_stat.set_defaults(func=status)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
