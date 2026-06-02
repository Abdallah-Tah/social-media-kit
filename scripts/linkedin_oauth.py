#!/usr/bin/env python3
"""LinkedIn OAuth2 flow to get an access token.

Run this script once to authorize your app and save the token.

Setup: https://www.linkedin.com/developers/
"""
import os
import sys
import json
import webbrowser
import urllib.parse
import requests

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URI", "https://www.linkedin.com/developers/tools/oauth/redirect")
SCOPES = os.environ.get("LINKEDIN_SCOPES", "w_member_social r_liteprofile r_emailaddress")

SECRETS_PATH = os.environ.get(
    "SECRETS_PATH",
    os.path.expanduser("~/.config/social-media-kit/secrets.env"),
)


def run_oauth_flow():
    """Full OAuth2 flow for LinkedIn."""
    global CLIENT_ID, CLIENT_SECRET

    if not CLIENT_ID:
        CLIENT_ID = input("Enter your LinkedIn Client ID: ").strip()
    if not CLIENT_SECRET:
        CLIENT_SECRET = input("Enter your LinkedIn Client Secret: ").strip()

    # Step 1: Build auth URL
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization?"
        f"response_type=code&"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        f"scope={urllib.parse.quote(SCOPES)}"
    )

    print("=" * 60)
    print("LINKEDIN OAUTH TOKEN GENERATOR")
    print("=" * 60)
    print()
    print("Step 1: Open this URL in your browser and authorize:")
    print()
    print(auth_url)
    print()

    webbrowser.open(auth_url)

    # Step 2: Get authorization code
    code = input("Paste the authorization code from the redirect URL: ").strip()

    # Step 3: Exchange code for token
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    resp = requests.post(
        token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    result = resp.json()

    if "access_token" in result:
        expires_days = result.get("expires_in", 0) // 86400
        print()
        print("✅ Token obtained!")
        print(f"   Expires in: {expires_days} days")
        print()

        # Save to secrets.env
        save_token(result["access_token"], CLIENT_ID, CLIENT_SECRET)
    else:
        print()
        print("❌ Error:")
        print(json.dumps(result, indent=2))


def save_token(access_token, client_id, client_secret):
    """Save LinkedIn token to secrets.env."""
    os.makedirs(os.path.dirname(SECRETS_PATH), exist_ok=True)

    secrets = {}
    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    secrets[key.strip()] = value.strip()

    secrets.update({
        "LINKEDIN_ACCESS_TOKEN": access_token,
        "LINKEDIN_CLIENT_ID": client_id,
        "LINKEDIN_CLIENT_SECRET": client_secret,
    })

    with open(SECRETS_PATH, "w") as f:
        for key, value in secrets.items():
            f.write(f"{key}={value}\n")

    print(f"✅ Token saved to {SECRETS_PATH}")


if __name__ == "__main__":
    run_oauth_flow()