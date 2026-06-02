#!/usr/bin/env python3
"""X (Twitter) posting script.

Posts tweets via the X API v2 using OAuth 1.0a.
Run x_oauth_exchange.py first to set up credentials.

Setup: https://developer.x.com/
"""
import os
import sys
import json
import argparse
import requests
from requests_oauthlib import OAuth1


def get_credentials():
    """Load X API credentials from environment or secrets file."""
    # Try environment first
    creds = {
        "consumer_key": os.environ.get("X_API_KEY", ""),
        "consumer_secret": os.environ.get("X_API_SECRET", ""),
        "access_token": os.environ.get("X_ACCESS_TOKEN", ""),
        "access_token_secret": os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
    }

    # Fall back to secrets.env
    if not all(creds.values()):
        secrets_path = os.environ.get(
            "SECRETS_PATH",
            os.path.expanduser("~/.config/social-media-kit/secrets.env"),
        )
        if os.path.exists(secrets_path):
            with open(secrets_path) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        if key == "X_API_KEY" and not creds["consumer_key"]:
                            creds["consumer_key"] = value
                        elif key == "X_API_SECRET" and not creds["consumer_secret"]:
                            creds["consumer_secret"] = value
                        elif key == "X_ACCESS_TOKEN" and not creds["access_token"]:
                            creds["access_token"] = value
                        elif key == "X_ACCESS_TOKEN_SECRET" and not creds["access_token_secret"]:
                            creds["access_token_secret"] = value

    missing = [k for k, v in creds.items() if not v]
    if missing:
        print(f"❌ Missing X credentials: {', '.join(missing)}")
        print("Run scripts/x_oauth_exchange.py --setup first.")
        return None

    return creds


def post_tweet(text, credentials=None):
    """Post a tweet using OAuth 1.0a."""
    if not credentials:
        credentials = get_credentials()
    if not credentials:
        return None

    oauth = OAuth1(
        credentials["consumer_key"],
        credentials["consumer_secret"],
        credentials["access_token"],
        credentials["access_token_secret"],
    )

    headers = {"Content-Type": "application/json"}
    payload = {"text": text}

    resp = requests.post(
        "https://api.x.com/2/tweets",
        auth=oauth,
        headers=headers,
        json=payload,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        tweet_id = data.get("data", {}).get("id", "unknown")
        print(f"✅ Tweet posted: https://x.com/user/status/{tweet_id}")
        return data
    else:
        print(f"❌ X API error ({resp.status_code}): {resp.text}")
        return None


def delete_tweet(tweet_id, credentials=None):
    """Delete a tweet by ID."""
    if not credentials:
        credentials = get_credentials()
    if not credentials:
        return None

    oauth = OAuth1(
        credentials["consumer_key"],
        credentials["consumer_secret"],
        credentials["access_token"],
        credentials["access_token_secret"],
    )

    resp = requests.delete(
        f"https://api.x.com/2/tweets/{tweet_id}",
        auth=oauth,
    )

    if resp.ok:
        print(f"✅ Tweet deleted: {tweet_id}")
        return True
    else:
        print(f"❌ Delete error: {resp.text}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Post to X (Twitter)")
    parser.add_argument("text", nargs="?", help="Tweet text")
    parser.add_argument("--delete", "-d", help="Tweet ID to delete")
    args = parser.parse_args()

    if args.delete:
        delete_tweet(args.delete)
    elif args.text:
        post_tweet(args.text)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()