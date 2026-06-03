#!/usr/bin/env python3
"""Pinterest posting script (API v5).

Creates a Pin on a board. Set in secrets.env:
    PINTEREST_ACCESS_TOKEN, PINTEREST_BOARD_ID
A Pin needs an image — pass a PUBLIC image URL (the agent uses the cover URL).
"""
import os
import argparse

import requests

ACCESS_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
BOARD_ID = os.environ.get("PINTEREST_BOARD_ID", "")
BASE = "https://api.pinterest.com/v5"


def post(title, description="", image_url=None, link=None, board_id=None):
    """Create a Pin (requires a public image URL)."""
    board = board_id or BOARD_ID
    if not ACCESS_TOKEN or not board:
        print("❌ PINTEREST_ACCESS_TOKEN / PINTEREST_BOARD_ID not set.")
        return None
    if not image_url:
        print("❌ Pinterest needs a public image_url to create a Pin.")
        return None

    body = {
        "board_id": board,
        "title": title[:100],
        "description": description[:500],
        "media_source": {"source_type": "image_url", "url": image_url},
    }
    if link:
        body["link"] = link
    try:
        resp = requests.post(
            f"{BASE}/pins",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}",
                     "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"❌ Pinterest request failed: {e}")
        return None

    if resp.status_code in (200, 201):
        print(f"✅ Posted to Pinterest: Pin {resp.json().get('id', '')}")
        return resp.json()
    print(f"❌ Pinterest error ({resp.status_code}): {resp.text[:300]}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Create a Pinterest Pin")
    parser.add_argument("title", nargs="?", help="Pin title")
    parser.add_argument("--description", default="", help="Pin description")
    parser.add_argument("--image-url", help="Public image URL (required)")
    parser.add_argument("--link", help="Destination link")
    parser.add_argument("--board-id", help="Board id override")
    args = parser.parse_args()
    if args.title:
        post(args.title, description=args.description, image_url=args.image_url,
             link=args.link, board_id=args.board_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
