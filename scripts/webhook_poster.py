#!/usr/bin/env python3
"""Generic webhook poster — publish to *any* platform with an HTTP endpoint.

This is the escape hatch that makes the kit work with channels we don't
ship a dedicated script for (Zapier, Make, n8n, Buffer, a custom CMS, an
internal microservice, etc.).

Set WEBHOOK_URL in secrets.env, or pass --url. The payload is JSON:
    {"text": "<message>", **extra}

Customize the JSON key with WEBHOOK_TEXT_KEY (default "text") to match
whatever your endpoint expects.
"""
import os
import json
import argparse
import requests

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
WEBHOOK_TEXT_KEY = os.environ.get("WEBHOOK_TEXT_KEY", "text")
WEBHOOK_AUTH_HEADER = os.environ.get("WEBHOOK_AUTH_HEADER", "")  # e.g. "Bearer xyz"


def post(text, url=None, extra=None):
    """POST a JSON payload to a generic webhook endpoint."""
    target = url or WEBHOOK_URL
    if not target:
        print("❌ WEBHOOK_URL not set (or pass --url).")
        return None

    payload = {WEBHOOK_TEXT_KEY: text}
    if extra:
        payload.update(extra)

    headers = {"Content-Type": "application/json"}
    if WEBHOOK_AUTH_HEADER:
        headers["Authorization"] = WEBHOOK_AUTH_HEADER

    resp = requests.post(target, json=payload, headers=headers, timeout=15)
    if resp.ok:
        print(f"✅ Posted to webhook ({resp.status_code})")
        return {"ok": True, "status": resp.status_code}
    print(f"❌ Webhook error ({resp.status_code}): {resp.text[:300]}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Post to a generic webhook")
    parser.add_argument("text", nargs="?", help="Message text")
    parser.add_argument("--url", "-u", help="Webhook URL override")
    parser.add_argument("--extra", "-e", help="Extra JSON to merge into payload")
    args = parser.parse_args()
    if args.text:
        extra = json.loads(args.extra) if args.extra else None
        post(args.text, url=args.url, extra=extra)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
