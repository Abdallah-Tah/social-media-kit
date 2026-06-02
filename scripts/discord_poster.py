#!/usr/bin/env python3
"""Discord posting script.

Posts messages to a Discord channel via an Incoming Webhook.
Set DISCORD_WEBHOOK_URL in secrets.env.

Setup: Server Settings → Integrations → Webhooks → New Webhook → Copy URL
"""
import os
import argparse
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def post_message(content, username=None):
    """Post a message to a Discord channel via webhook."""
    if not DISCORD_WEBHOOK_URL:
        print("❌ DISCORD_WEBHOOK_URL not set.")
        return None

    payload = {"content": content[:2000]}  # Discord hard limit
    if username:
        payload["username"] = username

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    if resp.status_code in (200, 204):
        print("✅ Posted to Discord")
        return {"ok": True}
    print(f"❌ Discord error ({resp.status_code}): {resp.text}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post a message to Discord")
    parser.add_argument("text", nargs="?", help="Message text")
    parser.add_argument("--username", "-u", help="Override webhook username")
    args = parser.parse_args()
    if args.text:
        post_message(args.text, username=args.username)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
