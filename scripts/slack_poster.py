#!/usr/bin/env python3
"""Slack posting script.

Posts messages to Slack via either:
  * Incoming Webhook  — set SLACK_WEBHOOK_URL  (simplest)
  * Bot token         — set SLACK_BOT_TOKEN + a target channel

Setup: https://api.slack.com/messaging/sending
"""
import os
import json
import argparse
import requests

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_DEFAULT_CHANNEL = os.environ.get("SLACK_CHANNEL", "")


def post_message(text, channel=None, blocks=None):
    """Post a message to Slack. Prefers webhook, falls back to bot token."""
    # ── Incoming webhook ────────────────────────────────────────────────
    if SLACK_WEBHOOK_URL:
        payload = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        try:
            resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=15)
        except requests.RequestException as e:
            print(f"❌ Slack webhook request failed: {e}")
            return None
        if resp.ok and resp.text in ("ok", ""):
            print("✅ Posted to Slack (webhook)")
            return {"ok": True, "via": "webhook"}
        print(f"❌ Slack webhook error ({resp.status_code}): {resp.text}")
        return None

    # ── Bot token (chat.postMessage) ────────────────────────────────────
    if SLACK_BOT_TOKEN:
        target = channel or SLACK_DEFAULT_CHANNEL
        if not target:
            print("❌ SLACK_CHANNEL not set (required with a bot token).")
            return None
        payload = {"channel": target, "text": text}
        if blocks:
            payload["blocks"] = blocks
        try:
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
                timeout=15,
            )
            result = resp.json()
        except requests.RequestException as e:
            print(f"❌ Slack request failed: {e}")
            return None
        if result.get("ok"):
            print(f"✅ Posted to Slack channel {target}: {result.get('ts')}")
            return result
        print(f"❌ Slack API error: {json.dumps(result, indent=2)}")
        return None

    print("❌ No Slack credentials. Set SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN.")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post a message to Slack")
    parser.add_argument("text", nargs="?", help="Message text")
    parser.add_argument("--channel", "-c", help="Channel (bot token mode)")
    args = parser.parse_args()

    if args.text:
        post_message(args.text, channel=args.channel)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
