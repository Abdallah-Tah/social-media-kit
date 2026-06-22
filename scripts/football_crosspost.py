#!/usr/bin/env python3
"""Cross-post football content (preview / recap) to Facebook only,
with the YouTube URL embedded in the post.

LinkedIn is intentionally disabled for this pillar. The account policy is one
LinkedIn post per day, news only.

  python3 scripts/football_crosspost.py --text "..." \
      --youtube-url https://youtube.com/shorts/XXXX --image card.png
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402
load_env()

TAGS = "#WorldCup2026 #footballpredictions #ai #soccer"


def crosspost(text: str, youtube_url: str = "", image_path: str | None = None,
              title: str = "") -> dict:
    caption = text.strip()
    if youtube_url:
        caption += f"\n\n▶ Watch: {youtube_url}"
    caption += f"\n\n{TAGS}"
    img = image_path if (image_path and os.path.exists(image_path)) else None
    results = {}

    # ── Facebook ──────────────────────────────────────────────────────
    try:
        import fb_poster
        if img:
            r = fb_poster.post_photo(img, caption=caption, link=youtube_url or None)
        else:
            r = fb_poster.post_text(caption, link=youtube_url or None)
        results["facebook"] = bool(r)
        print(f"[crosspost] facebook: {'✅' if r else '❌'}")
    except Exception as exc:  # noqa: BLE001
        results["facebook"] = False
        print(f"[crosspost] facebook error: {exc}")

    results["linkedin"] = False
    print("[crosspost] linkedin skipped: news-only daily policy")

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--youtube-url", default="")
    ap.add_argument("--image", default="")
    ap.add_argument("--title", default="")
    args = ap.parse_args()
    crosspost(args.text, args.youtube_url, args.image or None, args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
