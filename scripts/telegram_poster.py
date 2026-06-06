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
from urllib.parse import urlparse
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_MESSAGE_THREAD_ID = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "")


def _bot_token():
    return os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN


def _chat_id(chat_id=None):
    raw = chat_id or os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or TELEGRAM_CHAT_ID
    return _normalise_chat_id(raw)


def _message_thread_id():
    explicit = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID") or os.environ.get("TELEGRAM_THREAD_ID")
    if explicit:
        return explicit
    raw = os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or ""
    parsed = _parse_tme_c(raw)
    return parsed[1] if parsed else TELEGRAM_MESSAGE_THREAD_ID


def _normalise_chat_id(raw):
    if not raw:
        return raw
    parsed = _parse_tme_c(str(raw).strip())
    if parsed:
        return parsed[0]
    value = str(raw).strip()
    if value.isdigit() and len(value) == 10:
        return f"-100{value}"
    return value


def _parse_tme_c(raw):
    value = str(raw).strip()
    if not value.startswith(("http://", "https://")):
        return None
    parsed = urlparse(value)
    if parsed.netloc not in {"t.me", "telegram.me"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "c" or not parts[1].isdigit():
        return None
    chat_id = f"-100{parts[1]}"
    thread_id = parts[2] if len(parts) > 2 and parts[2].isdigit() else ""
    return chat_id, thread_id


def post_message(text, chat_id=None, parse_mode=None):
    """Send a message to a Telegram chat/channel.

    parse_mode defaults to None (plain text) — sending as HTML/Markdown by
    default makes messages with `<`, `>`, `&`, or `_` fail to send.
    """
    token = _bot_token()
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not set.")
        return None
    target = _chat_id(chat_id)
    if not target:
        print("❌ TELEGRAM_CHAT_ID not set.")
        return None

    payload = {
        "chat_id": target,
        "text": text[:4096],  # Telegram message limit
        "disable_web_page_preview": False,
    }
    thread_id = _message_thread_id()
    if thread_id:
        payload["message_thread_id"] = thread_id
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=15,
        )
        result = resp.json()
    except requests.RequestException as e:
        print(f"❌ Telegram request failed: {e}")
        return None
    if result.get("ok"):
        print(f"✅ Posted to Telegram chat {target}")
        return result
    print(f"❌ Telegram error: {result}")
    return None


def post_photo(image_path, caption="", chat_id=None, parse_mode=None):
    """Send a local image to a Telegram chat/channel."""
    token = _bot_token()
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not set.")
        return None
    target = _chat_id(chat_id)
    if not target:
        print("❌ TELEGRAM_CHAT_ID not set.")
        return None

    payload = {
        "chat_id": target,
        "caption": caption[:1024],
    }
    thread_id = _message_thread_id()
    if thread_id:
        payload["message_thread_id"] = thread_id
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        with open(image_path, "rb") as image_file:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data=payload,
                files={"photo": image_file},
                timeout=30,
            )
        result = resp.json()
    except (OSError, requests.RequestException) as e:
        print(f"❌ Telegram photo request failed: {e}")
        return None
    if result.get("ok"):
        print(f"✅ Posted photo to Telegram chat {target}")
        return result
    print(f"❌ Telegram photo error: {result}")
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
