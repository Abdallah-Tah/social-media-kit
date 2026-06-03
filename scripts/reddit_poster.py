#!/usr/bin/env python3
"""Reddit posting script (script-app OAuth).

Submits a self (text) post to a subreddit. Create a "script" app at
https://www.reddit.com/prefs/apps and set in secrets.env:
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD
    REDDIT_SUBREDDIT   (default target, e.g. "test")
    REDDIT_USER_AGENT  (e.g. "social-media-agent by u/you")
"""
import os
import argparse

import requests

CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
USERNAME = os.environ.get("REDDIT_USERNAME", "")
PASSWORD = os.environ.get("REDDIT_PASSWORD", "")
SUBREDDIT = os.environ.get("REDDIT_SUBREDDIT", "")
USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "social-media-agent/1.0")


def _token():
    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "password", "username": USERNAME, "password": PASSWORD},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def post(title, text="", subreddit=None, url=None):
    """Submit a self post (or link post if `url` is given) to a subreddit."""
    sr = subreddit or SUBREDDIT
    if not (CLIENT_ID and CLIENT_SECRET and USERNAME and PASSWORD):
        print("❌ Reddit credentials not set.")
        return None
    if not sr:
        print("❌ No subreddit (set REDDIT_SUBREDDIT or pass --subreddit).")
        return None
    try:
        token = _token()
        data = {"sr": sr, "title": title[:300], "api_type": "json"}
        if url:
            data["kind"] = "link"
            data["url"] = url
        else:
            data["kind"] = "self"
            data["text"] = text
        resp = requests.post(
            "https://oauth.reddit.com/api/submit",
            headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
            data=data,
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"❌ Reddit request failed: {e}")
        return None

    if resp.ok:
        payload = resp.json()
        errors = payload.get("json", {}).get("errors", [])
        if errors:
            print(f"❌ Reddit error: {errors}")
            return None
        link = payload.get("json", {}).get("data", {}).get("url", "")
        print(f"✅ Posted to r/{sr}: {link}")
        return payload
    print(f"❌ Reddit error ({resp.status_code}): {resp.text[:300]}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post to Reddit")
    parser.add_argument("title", nargs="?", help="Post title")
    parser.add_argument("--text", default="", help="Self-post body (markdown)")
    parser.add_argument("--subreddit", help="Target subreddit (no r/)")
    parser.add_argument("--url", help="Submit a link post instead of a self post")
    args = parser.parse_args()
    if args.title:
        post(args.title, text=args.text, subreddit=args.subreddit, url=args.url)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
