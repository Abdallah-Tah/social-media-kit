#!/usr/bin/env python3
"""Mastodon posting script.

Posts a status ("toot") to any Mastodon instance via the REST API.
Set MASTODON_BASE_URL (e.g. https://mastodon.social) and
MASTODON_ACCESS_TOKEN in secrets.env.

Setup: Preferences → Development → New application → copy the access token
"""
import os
import argparse
import requests

MASTODON_BASE_URL = os.environ.get("MASTODON_BASE_URL", "").rstrip("/")
MASTODON_ACCESS_TOKEN = os.environ.get("MASTODON_ACCESS_TOKEN", "")

# Most instances allow 500 chars; some allow more. 500 is the safe default.
try:
    MASTODON_LIMIT = int(os.environ.get("MASTODON_CHAR_LIMIT", "500"))
except ValueError:
    MASTODON_LIMIT = 500


def _upload_media(image_path):
    """Upload an image to Mastodon; returns the media id."""
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{MASTODON_BASE_URL}/api/v2/media",
            headers={"Authorization": f"Bearer {MASTODON_ACCESS_TOKEN}"},
            files={"file": f},
            timeout=60,
        )
    if resp.status_code in (200, 202):
        return resp.json().get("id")
    print(f"❌ Mastodon media error ({resp.status_code}): {resp.text[:200]}")
    return None


def post_status(text, visibility="public", image_path=None):
    """Post a status to Mastodon, optionally with an image."""
    if not MASTODON_BASE_URL or not MASTODON_ACCESS_TOKEN:
        print("❌ MASTODON_BASE_URL / MASTODON_ACCESS_TOKEN not set.")
        return None

    data = {"status": text[:MASTODON_LIMIT], "visibility": visibility}
    try:
        if image_path:
            media_id = _upload_media(image_path)
            if media_id:
                data["media_ids[]"] = media_id
        resp = requests.post(
            f"{MASTODON_BASE_URL}/api/v1/statuses",
            headers={"Authorization": f"Bearer {MASTODON_ACCESS_TOKEN}"},
            data=data,
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"❌ Mastodon request failed: {e}")
        return None
    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"✅ Posted to Mastodon: {data.get('url', '')}")
        return data
    print(f"❌ Mastodon error ({resp.status_code}): {resp.text}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post a status to Mastodon")
    parser.add_argument("text", nargs="?", help="Status text")
    parser.add_argument(
        "--visibility", "-v", default="public",
        choices=["public", "unlisted", "private", "direct"],
    )
    args = parser.parse_args()
    if args.text:
        post_status(args.text, visibility=args.visibility)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
