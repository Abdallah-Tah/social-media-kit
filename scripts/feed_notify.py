#!/usr/bin/env python3
"""Standalone notification script for smkit feed.

Reads the most recent feed snapshot and sends the top N items to the
configured notification channel (Telegram by default).

Usage:
    python3 scripts/feed_notify.py [--limit 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.feed import FeedItem, FEED_DIR, NOTIFY_TOP_N, load_profile_with_interests, notify_feed


def latest_snapshot() -> Path | None:
    snapshots = sorted(FEED_DIR.glob("*.json"))
    # Skip the seen.json store.
    snapshots = [p for p in snapshots if p.name != "seen.json"]
    return snapshots[-1] if snapshots else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Notify from latest smkit feed snapshot")
    parser.add_argument("--limit", type=int, default=NOTIFY_TOP_N, help="Number of items to include")
    parser.add_argument("--profile", default="default", help="Brand profile")
    parser.add_argument("--channel", help="Override notification channel")
    parser.add_argument("--dry-run", action="store_true", help="Print message instead of sending")
    parser.add_argument("--snapshot", help="Path to a specific snapshot JSON")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot) if args.snapshot else latest_snapshot()
    if not snapshot_path or not snapshot_path.exists():
        print("❌ No feed snapshot found. Run `smkit feed --save` first.")
        return 1

    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    items = [FeedItem.from_dict(i) for i in data.get("items", [])]
    items = items[: args.limit]

    profile = load_profile_with_interests(args.profile)
    channel = args.channel or profile.get("feed", {}).get("notification_channel")
    result = notify_feed(items, channel=channel, profile_name=args.profile, dry_run=args.dry_run)
    if result.get("dry_run"):
        print("🔮 Dry-run notification:\n")
        print(result["message"])
    elif result["ok"]:
        print(f"✅ Notified {result['channel']} with {result['sent']} items.")
    else:
        print(f"❌ Notify failed: {result.get('error')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
