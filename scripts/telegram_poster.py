#!/usr/bin/env python3
"""Telegram posting script.

Posts messages to a Telegram chat/channel via the Bot API.
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in secrets.env.

Setup:
  1. Create a bot with @BotFather → get the token
  2. Add the bot to your channel/group as admin
  3. Find the chat id (e.g. @yourchannel or a numeric id)
"""
import os
import argparse
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def post_message(text, chat_id=None, parse_mode="HTML"):
    """Send a message to a Telegram chat/channel."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set.")
        return None
    target = chat_id or TELEGRAM_CHAT_ID
    if not target:
        print("❌ TELEGRAM_CHAT_ID not set.")
        return None

    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": target,
            "text": text[:4096],  # Telegram message limit
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    result = resp.json()
    if result.get("ok"):
        print(f"✅ Posted to Telegram chat {target}")
        return result
    print(f"❌ Telegram error: {result}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post a message to Telegram")
    parser.add_argument("text", nargs="?", help="Message text")
    parser.add_argument("--chat", "-c", help="Chat/channel id override")
    args = parser.parse_args()
    if args.text:
        post_message(args.text, chat_id=args.chat)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
