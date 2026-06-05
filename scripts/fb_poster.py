#!/usr/bin/env python3
"""Facebook Page posting script.

Posts text, links, or photos to a Facebook Page using the Graph API.
Uses long-lived Page Access Token from secrets.env.

Setup: https://developers.facebook.com/
"""
import os
import sys
import json
import argparse
import requests

# ── Config ────────────────────────────────────────────────────────────────
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
FB_GRAPH_VERSION = os.environ.get("FB_GRAPH_VERSION", "v21.0")

import re as _re


def _strip_md(t):
    """Facebook doesn't render markdown — strip it to plain text."""
    if not t:
        return t
    t = _re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = _re.sub(r"__([^_]+)__", r"\1", t)
    t = _re.sub(r"\*([^*\n]+)\*", r"\1", t)
    t = _re.sub(r"`([^`]+)`", r"\1", t)
    t = _re.sub(r"^\s{0,3}#{1,6}\s+", "", t, flags=_re.M)
    t = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", t)
    return t


def post_text(message, link=None):
    """Post a text message (with optional link) to the Facebook Page."""
    if not FB_PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set. See docs/PLATFORM_SETUP.md")
        return None

    message = _strip_md(message)
    url = f"https://graph.facebook.com/{FB_GRAPH_VERSION}/{FB_PAGE_ID}/feed"
    data = {"message": message, "access_token": FB_PAGE_TOKEN}
    if link:
        data["link"] = link

    resp = requests.post(url, data=data)
    result = resp.json()

    if resp.ok and "id" in result:
        print(f"✅ Posted to Facebook: {result['id']}")
        return result
    else:
        print(f"❌ Facebook error: {json.dumps(result, indent=2)}")
        return None


def post_photo(image_path, caption="", link=None):
    """Post a photo (with optional caption) to the Facebook Page."""
    if not FB_PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set. See docs/PLATFORM_SETUP.md")
        return None

    caption = _strip_md(caption)
    url = f"https://graph.facebook.com/{FB_GRAPH_VERSION}/{FB_PAGE_ID}/photos"

    with open(image_path, "rb") as img_file:
        data = {"caption": caption, "access_token": FB_PAGE_TOKEN}
        if link:
            data["link"] = link
        files = {"source": img_file}

        resp = requests.post(url, data=data, files=files)
        result = resp.json()

    if resp.ok and "id" in result:
        print(f"✅ Photo posted to Facebook: {result['id']}")
        return result
    else:
        print(f"❌ Facebook error: {json.dumps(result, indent=2)}")
        return None


def delete_post(post_id):
    """Delete a post from the Facebook Page."""
    if not FB_PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set")
        return None

    url = f"https://graph.facebook.com/{FB_GRAPH_VERSION}/{post_id}"
    resp = requests.delete(url, params={"access_token": FB_PAGE_TOKEN})

    if resp.ok:
        print(f"✅ Deleted post: {post_id}")
        return True
    else:
        print(f"❌ Delete error: {resp.json()}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Post to Facebook Page")
    parser.add_argument("--message", "-m", help="Post message text")
    parser.add_argument("--link", "-l", help="URL to include")
    parser.add_argument("--image", "-i", help="Image file path")
    parser.add_argument("--delete", "-d", help="Post ID to delete")
    args = parser.parse_args()

    if args.delete:
        delete_post(args.delete)
    elif args.image:
        post_photo(args.image, caption=args.message or "", link=args.link)
    elif args.message:
        post_text(args.message, link=args.link)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()