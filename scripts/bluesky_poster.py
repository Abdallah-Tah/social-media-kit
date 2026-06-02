#!/usr/bin/env python3
"""Bluesky posting script (AT Protocol).

Posts to Bluesky via the AT Protocol XRPC API — no SDK needed.
Set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD in secrets.env
(create an app password at Settings → App Passwords, NOT your main password).

Optionally set BLUESKY_PDS (defaults to https://bsky.social).
"""
import os
import sys
import argparse
from datetime import datetime, timezone

import requests

PDS = os.environ.get("BLUESKY_PDS", "https://bsky.social").rstrip("/")
HANDLE = os.environ.get("BLUESKY_HANDLE", "")
APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")

# Bluesky counts text in graphemes; 300 is the limit.
BLUESKY_LIMIT = 300


def _session():
    """Create an authenticated session, returning (accessJwt, did)."""
    resp = requests.post(
        f"{PDS}/xrpc/com.atproto.server.createSession",
        json={"identifier": HANDLE, "password": APP_PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["accessJwt"], data["did"]


def _upload_blob(jwt, image_path):
    """Upload an image blob; returns the blob ref for an embed."""
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{PDS}/xrpc/com.atproto.repo.uploadBlob",
            headers={"Authorization": f"Bearer {jwt}", "Content-Type": mime},
            data=f.read(),
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["blob"]


def post(text, image_path=None, alt_text=""):
    """Create a Bluesky post, optionally with one image."""
    if not HANDLE or not APP_PASSWORD:
        print("❌ BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set.")
        return None
    try:
        jwt, did = _session()
        record = {
            "$type": "app.bsky.feed.post",
            "text": text[:BLUESKY_LIMIT],
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if image_path:
            blob = _upload_blob(jwt, image_path)
            record["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [{"alt": alt_text or "", "image": blob}],
            }
        resp = requests.post(
            f"{PDS}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {jwt}"},
            json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"❌ Bluesky request failed: {e}")
        return None

    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"✅ Posted to Bluesky: {data.get('uri', '')}")
        return data
    print(f"❌ Bluesky error ({resp.status_code}): {resp.text[:300]}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post to Bluesky")
    parser.add_argument("text", nargs="?", help="Post text")
    parser.add_argument("--image", "-i", help="Image path")
    parser.add_argument("--alt", help="Image alt text")
    args = parser.parse_args()
    if args.text:
        post(args.text, image_path=args.image, alt_text=args.alt or "")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
