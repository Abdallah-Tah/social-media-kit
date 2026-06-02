#!/usr/bin/env python3
"""X (Twitter) OAuth 1.0a Token Exchange.

Handles the full OAuth 1.0a flow for X API access:
1. Obtain request token
2. Authorize via browser
3. Exchange for access token
4. Save credentials

Setup: https://developer.x.com/
"""
import os
import sys
import json
import argparse
import webbrowser
from urllib.parse import parse_qs

import requests
from requests_oauthlib import OAuth1Session

# ── Config ────────────────────────────────────────────────────────────────
REQUEST_TOKEN_URL = "https://api.x.com/oauth/request_token"
AUTHORIZE_URL = "https://api.x.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://api.x.com/oauth/access_token"

SECRETS_PATH = os.environ.get(
    "SECRETS_PATH",
    os.path.expanduser("~/.config/social-media-kit/secrets.env"),
)
STATE_FILE = os.path.expanduser("~/.config/social-media-kit/.x_oauth_state.json")


def get_consumer_keys():
    """Read consumer key/secret from secrets or prompt."""
    consumer_key = os.environ.get("X_API_KEY", "")
    consumer_secret = os.environ.get("X_API_SECRET", "")

    if not consumer_key and os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("X_API_KEY="):
                    consumer_key = line.split("=", 1)[1]
                elif line.startswith("X_API_SECRET="):
                    consumer_secret = line.split("=", 1)[1]

    if not consumer_key:
        consumer_key = input("Enter your X API Key: ").strip()
    if not consumer_secret:
        consumer_secret = input("Enter your X API Secret: ").strip()

    return consumer_key, consumer_secret


def step1_request_token(consumer_key, consumer_secret):
    """Step 1: Get request token."""
    oauth = OAuth1Session(consumer_key, client_secret=consumer_secret)
    resp = oauth.post(REQUEST_TOKEN_URL)

    if resp.status_code != 200:
        print(f"❌ Request token error: {resp.text}")
        sys.exit(1)

    creds = parse_qs(resp.text)
    return creds["oauth_token"][0], creds["oauth_token_secret"][0]


def step2_authorize(oauth_token):
    """Step 2: Open browser for authorization."""
    url = f"{AUTHORIZE_URL}?oauth_token={oauth_token}"
    print(f"\n📱 Opening browser for X authorization...")
    print(f"If browser doesn't open, visit:\n{url}\n")
    webbrowser.open(url)


def step3_access_token(consumer_key, consumer_secret, oauth_token, oauth_token_secret, verifier):
    """Step 3: Exchange verifier for access token."""
    oauth = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=oauth_token,
        resource_owner_secret=oauth_token_secret,
        verifier=verifier,
    )
    resp = oauth.post(ACCESS_TOKEN_URL)

    if resp.status_code != 200:
        print(f"❌ Access token error: {resp.text}")
        sys.exit(1)

    creds = parse_qs(resp.text)
    return {
        "access_token": creds["oauth_token"][0],
        "access_token_secret": creds["oauth_token_secret"][0],
        "user_id": creds["user_id"][0],
        "screen_name": creds["screen_name"][0],
    }


def save_credentials(consumer_key, consumer_secret, access_result):
    """Save all credentials to secrets.env."""
    os.makedirs(os.path.dirname(SECRETS_PATH), exist_ok=True)

    # Load existing secrets
    secrets = {}
    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    secrets[key.strip()] = value.strip()

    # Update with new credentials
    secrets.update({
        "X_API_KEY": consumer_key,
        "X_API_SECRET": consumer_secret,
        "X_ACCESS_TOKEN": access_result["access_token"],
        "X_ACCESS_TOKEN_SECRET": access_result["access_token_secret"],
        "X_SCREEN_NAME": access_result["screen_name"],
    })

    # Write back
    with open(SECRETS_PATH, "w") as f:
        for key, value in secrets.items():
            f.write(f"{key}={value}\n")

    print(f"✅ Credentials saved to {SECRETS_PATH}")


def main():
    parser = argparse.ArgumentParser(description="X OAuth 1.0a Token Exchange")
    parser.add_argument("--setup", action="store_true", help="Run full OAuth setup flow")
    parser.add_argument("--verifier", "-v", help="OAuth verifier from callback")
    args = parser.parse_args()

    if args.setup or not args.verifier:
        # Full OAuth flow
        print("=" * 60)
        print("X (Twitter) OAuth 1.0a Setup")
        print("=" * 60)

        consumer_key, consumer_secret = get_consumer_keys()

        print("\nStep 1: Getting request token...")
        oauth_token, oauth_token_secret = step1_request_token(consumer_key, consumer_secret)

        # Save state for later
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({
                "consumer_key": consumer_key,
                "consumer_secret": consumer_secret,
                "oauth_token": oauth_token,
                "oauth_token_secret": oauth_token_secret,
            }, f, indent=2)

        print("\nStep 2: Authorize the app...")
        step2_authorize(oauth_token)

        verifier = input("\nEnter the PIN/verifier from the authorization page: ").strip()

        print("\nStep 3: Exchanging for access token...")
        result = step3_access_token(
            consumer_key, consumer_secret, oauth_token, oauth_token_secret, verifier
        )

        print(f"\n✅ Authenticated as @{result['screen_name']} (ID: {result['user_id']})")
        save_credentials(consumer_key, consumer_secret, result)

    elif args.verifier:
        # Resume with verifier
        if not os.path.exists(STATE_FILE):
            print("❌ No OAuth state found. Run with --setup first.")
            sys.exit(1)

        with open(STATE_FILE) as f:
            state = json.load(f)

        result = step3_access_token(
            state["consumer_key"], state["consumer_secret"],
            state["oauth_token"], state["oauth_token_secret"],
            args.verifier,
        )

        print(f"✅ Authenticated as @{result['screen_name']}")
        save_credentials(state["consumer_key"], state["consumer_secret"], result)


if __name__ == "__main__":
    main()