#!/usr/bin/env python3
"""One-shot retry: upload an ALREADY-APPROVED daily slate to YouTube once the
daily upload cap resets. LinkedIn is skipped by the news-only daily policy.
Exits on success or after the max window. Not a recurring publisher — one video.

  /usr/bin/python3 scripts/retry_daily_youtube.py --video <mp4> [--day YYYY-MM-DD]
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402

INTERVAL = 1800      # 30 min between attempts
MAX_ATTEMPTS = 50    # ~25h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--day")
    args = ap.parse_args()
    load_env()
    video = args.video
    props_path = KIT / "content" / "assets" / "shorts" / "daily_slate" / "props.json"
    props = json.loads(props_path.read_text()) if props_path.exists() else {"date": "Today", "credits": []}
    title = f"World Cup 2026 Today — Matches & Model Picks ({props.get('date','Today')}) \U0001F3C6"[:100]
    credit = ("\n\nPhotos: " + "; ".join(props.get("credits", []))) if props.get("credits") else ""
    desc = ("Today at the World Cup 2026 — today's matches, our independent model's picks, and "
            "yesterday's graded results. Analytics only, not affiliated with FIFA.\n\n"
            "Comment your score predictions. Follow for daily World Cup model calls.\n\n"
            "#WorldCup2026 #WorldCup #Football #Soccer #FIFAWorldCup #AIPredictions #footballpredictions #Shorts"
            + credit)
    try:
        from worldcup_thumbnail import generate_thumbnail
        thumb = generate_thumbnail(
            KIT / "content" / "assets" / "shorts" / "daily_slate" / "retry_thumb.jpg",
            title=f"Today at the World Cup {props.get('date','Today')}",
            kind="TODAY'S MATCHES",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[retry-yt] thumbnail failed (non-fatal): {exc}", flush=True)
        thumb = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        up = subprocess.run(
            ["/usr/bin/python3", str(KIT / "scripts" / "youtube_shorts_publisher.py"), "upload",
             "--video", video, "--title", title, "--description", desc, "--privacy", "public",
             "--profile", "main", "--category-id", "17",
             "--tags", "WorldCup2026,WorldCup,football,soccer,FIFAWorldCup,AIpredictions,footballpredictions,shorts"]
            + (["--thumbnail", str(thumb)] if thumb else []),
            capture_output=True, text=True)
        out = up.stdout + up.stderr
        if up.returncode == 0 and "youtube.com/shorts/" in out:
            m = re.search(r"https://www\.youtube\.com/shorts/[\w-]+", out)
            yt = m.group(0) if m else ""
            print(f"[retry-yt] SUCCESS attempt {attempt}: {yt}", flush=True)
            print("[retry-yt] LinkedIn skipped: news-only daily policy", flush=True)
            # mark posted
            p = KIT / "content" / "daily_slate_posted.json"
            try:
                seen = set(json.loads(p.read_text())) if p.exists() else set()
            except Exception:
                seen = set()
            if args.day:
                seen.add(args.day)
            p.write_text(json.dumps(sorted(seen)[-90:]))
            return 0
        if "uploadLimitExceeded" in out:
            print(f"[retry-yt] attempt {attempt}: cap still hit, sleeping {INTERVAL}s", flush=True)
            time.sleep(INTERVAL)
            continue
        print(f"[retry-yt] attempt {attempt}: non-cap error, stopping:\n{out[-400:]}", flush=True)
        return 1
    print("[retry-yt] gave up after max attempts (cap never cleared)", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
