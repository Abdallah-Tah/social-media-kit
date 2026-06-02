#!/usr/bin/env python3
"""Threads posting script (Meta Threads API).

Posts to Threads via the official Graph API (two-step: create a media
container, then publish it). Set THREADS_USER_ID and THREADS_ACCESS_TOKEN
in secrets.env.

Get them at https://developers.facebook.com/ (Threads API product).
Image posts require a PUBLIC image URL (Threads fetches it server-side).
"""
import os
import sys
import time
import argparse

import requests

THREADS_USER_ID = os.environ.get("THREADS_USER_ID", "")
THREADS_ACCESS_TOKEN = os.environ.get("THREADS_ACCESS_TOKEN", "")
BASE = "https://graph.threads.net/v1.0"

THREADS_LIMIT = 500


def post(text, image_url=None):
    """Publish a Threads post (text, or image+caption via a public URL)."""
    if not THREADS_USER_ID or not THREADS_ACCESS_TOKEN:
        print("❌ THREADS_USER_ID / THREADS_ACCESS_TOKEN not set.")
        return None

    params = {"access_token": THREADS_ACCESS_TOKEN, "text": text[:THREADS_LIMIT]}
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"

    try:
        # 1) Create the media container.
        create = requests.post(
            f"{BASE}/{THREADS_USER_ID}/threads", params=params, timeout=30
        )
        if not create.ok:
            print(f"❌ Threads create error ({create.status_code}): {create.text[:300]}")
            return None
        creation_id = create.json().get("id")
        if not creation_id:
            return None
        # Threads recommends a brief pause before publishing.
        time.sleep(2)
        # 2) Publish it.
        publish = requests.post(
            f"{BASE}/{THREADS_USER_ID}/threads_publish",
            params={"access_token": THREADS_ACCESS_TOKEN, "creation_id": creation_id},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"❌ Threads request failed: {e}")
        return None

    if publish.ok:
        print(f"✅ Posted to Threads: {publish.json().get('id', '')}")
        return publish.json()
    print(f"❌ Threads publish error ({publish.status_code}): {publish.text[:300]}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post to Threads")
    parser.add_argument("text", nargs="?", help="Post text")
    parser.add_argument("--image-url", help="Public image URL")
    args = parser.parse_args()
    if args.text:
        post(args.text, image_url=args.image_url)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
