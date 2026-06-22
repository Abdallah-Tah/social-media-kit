#!/usr/bin/env python3
"""Daily rules-explainer runner (Phase 4 — SCAFFOLD, disarmed).

Picks the next un-posted, VETTED topic by `priority`, renders it via the
existing explainer pipeline, and (Phase A) queues it to Telegram for one-tap
approval. It does NOT publish and is NOT wired to cron yet.

  /usr/bin/python3 scripts/rules_daily.py            # next topic -> render -> Telegram
  /usr/bin/python3 scripts/rules_daily.py --topic offside
  /usr/bin/python3 scripts/rules_daily.py --dry-run  # pick only, no render
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402

TOPICS = KIT / "content" / "explainers" / "topics.json"
POSTED = KIT / "content" / "explainers" / "explainer_posts.json"
OUT_DIR = KIT / "content" / "assets" / "shorts" / "explainers"


def _posted() -> set:
    try:
        return set(json.loads(POSTED.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def pick_topic(explicit: str | None) -> dict | None:
    topics = json.loads(TOPICS.read_text()).get("topics", [])
    if explicit:
        return next((t for t in topics if t["id"] == explicit), None)
    posted = _posted()
    # vetted + un-posted, lowest priority number first; recycle if all posted
    cand = [t for t in topics if t.get("vetted") is True and t["id"] not in posted]
    if not cand:
        cand = [t for t in topics if t.get("vetted") is True]
    cand.sort(key=lambda t: t.get("priority", 999))
    return cand[0] if cand else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()

    topic = pick_topic(args.topic)
    if not topic:
        print("[rules-daily] no vetted topic available"); return 0
    print(f"[rules-daily] today's topic: {topic['id']} (priority {topic.get('priority')})")
    if args.dry_run:
        return 0

    # Render AND publish via the existing explainer pipeline (refuses unless
    # vetted; publishes to the channel in config/explainer.yaml). Auto-publish
    # enabled (Abdallah 2026-06-16). To revert to approve-first, drop --publish.
    r = subprocess.run(["/usr/bin/python3", str(KIT / "scripts" / "explainer_short.py"),
                        "--topic", topic["id"], "--approve", "--publish"], cwd=str(KIT))
    mp4 = OUT_DIR / f"{topic['id']}.mp4"
    published = r.returncode == 0

    # Post-publish notification to Telegram (so a bad render can be pulled down).
    try:
        tok = Path(os.path.expanduser("~/.telegram-bot-token"))
        if tok.exists():
            t = tok.read_text().strip(); os.environ["TELEGRAM_BOT_TOKEN"] = t; os.environ["TELEGRAM_TOKEN"] = t
        os.environ.setdefault("TELEGRAM_CHAT_ID", "-1003948211258")
        os.environ.setdefault("TELEGRAM_MESSAGE_THREAD_ID", "14119")
        import telegram_poster as TG
        status = "✅ PUBLISHED" if published else "⚠️ render/publish FAILED (will retry next run)"
        if mp4.exists():
            TG.post_video(str(mp4), caption=f"📚 Daily rules explainer — {topic['title']} ({topic['id']}): {status}")
    except Exception as exc:  # noqa: BLE001
        print(f"[rules-daily] telegram failed (non-fatal): {exc}")
    print(f"[rules-daily] {topic['id']}: {'published' if published else 'failed (retry next run)'}.")
    return 0 if published else 1


if __name__ == "__main__":
    raise SystemExit(main())
