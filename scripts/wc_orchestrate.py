#!/usr/bin/env python3
"""World Cup content orchestrator: live data → branded Short → route → distribute.

Generates a vertical Short for a pillar from live worldcup26.ir data, builds a
growth-oriented caption (hook + hashtags), then routes it:

  * factual pillars (standings, preview, recap, stat)  → auto-publish to the
    enabled, configured video platforms (YouTube Shorts, FB Reels, IG Reels,
    TikTok). Skips any platform without credentials.
  * opinion pillars (prediction, hot_take)             → Telegram review only;
    you approve, then publish manually.

Safety: without --publish it ALWAYS just sends a Telegram review (nothing posts).
--publish enables auto-publish for factual pillars only; opinion always waits.

  python3 scripts/wc_orchestrate.py --pillar standings --group A
  python3 scripts/wc_orchestrate.py --pillar preview --when tomorrow --publish \
      --platforms yt,fb
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

PILLAR_SAFETY = {
    "standings": "factual",
    "preview": "factual",
    "recap": "factual",
    "stat": "factual",
    "prediction": "opinion",
    "hot_take": "opinion",
}

BASE_TAGS = "#WorldCup2026 #FIFAWorldCup #WorldCup #Football #Soccer #BuildWithAbdallah"
PILLAR_HOOK = {
    "standings": "📊 The {title} — how the group stands.",
    "preview": "🗓️ {title} at the 2026 World Cup. Who's your pick?",
    "recap": "⏱️ FULL TIME — {title}.",
    "stat": "🤯 Stat of the day — {title}.",
    "prediction": "🔮 Prediction: {title}. Agree?",
}


def _ensure_telegram_token() -> None:
    """Point the telegram helper at the valid bot token (secrets.env one is stale)."""
    tok_file = Path.home() / ".telegram-bot-token"
    if tok_file.exists():
        tok = tok_file.read_text().strip()
        os.environ["TELEGRAM_TOKEN"] = tok
        os.environ["TELEGRAM_BOT_TOKEN"] = tok
    os.environ.setdefault("TELEGRAM_CHAT_ID", "-1003948211258")
    os.environ.setdefault("TELEGRAM_MESSAGE_THREAD_ID", "14119")


def build_short(pillar: str, group: str | None, when: str) -> tuple[Path, dict]:
    """Generate the Short and return (mp4_path, deck)."""
    import worldcup_short as ws
    if pillar == "standings":
        deck, slug = ws.deck_standings(group or "A")
    elif pillar == "preview":
        deck, slug = ws.deck_preview(when)
    else:
        raise SystemExit(f"Pillar '{pillar}' has no live deck builder yet "
                         "(standings, preview are wired). Add it in worldcup_short.py.")
    path = ws.build(deck, slug)
    return path, deck


def build_caption(pillar: str, deck: dict) -> str:
    hook = PILLAR_HOOK.get(pillar, "{title}").format(title=deck["title"])
    return f"{hook}\n\n{BASE_TAGS}"


def review_via_telegram(video: Path, caption: str, safety: str) -> None:
    _ensure_telegram_token()
    import telegram_poster
    note = ("✅ FACTUAL — eligible for auto-publish with --publish."
            if safety == "factual" else
            "🔒 OPINION — reply 'approve' before this goes out.")
    msg = f"Pitch Agent review\n\n{caption}\n\n{note}\nLocal: {video}"
    if hasattr(telegram_poster, "post_video"):
        telegram_poster.post_video(str(video), caption=msg)
    else:
        telegram_poster.post_message(msg)
    print("📨 Sent to Telegram for review.")


def distribute(video: Path, caption: str, platforms: list[str]) -> dict:
    """Auto-publish to the requested platforms; skip unconfigured ones."""
    import subprocess
    results = {}
    title = caption.splitlines()[0][:90]

    if "fb" in platforms:
        try:
            import fb_reels_publisher
            r = fb_reels_publisher.publish_reel(str(video), description=caption)
            results["fb_reels"] = "ok" if r else "skipped/failed"
        except Exception as e:
            results["fb_reels"] = f"error: {e}"

    if "ig" in platforms:
        try:
            import instagram_reels_publisher
            r = instagram_reels_publisher.publish_reel(str(video), caption=caption)
            results["ig_reels"] = "ok" if r else "skipped/failed"
        except Exception as e:
            results["ig_reels"] = f"error: {e}"

    if "tiktok" in platforms:
        try:
            import tiktok_upload
            r = tiktok_upload.post_video(str(video), title, privacy="SELF_ONLY")
            results["tiktok"] = "ok" if r else "skipped/failed"
        except SystemExit as e:
            results["tiktok"] = f"needs auth: {e}"
        except Exception as e:
            results["tiktok"] = f"error: {e}"

    if "yt" in platforms:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "youtube_shorts_publisher.py"),
             "upload", "--video", str(video), "--title", title, "--description", caption],
            capture_output=True, text=True, timeout=600,
        )
        results["youtube_shorts"] = "ok" if r.returncode == 0 else f"failed: {r.stderr[-160:]}"

    return results


def main():
    ap = argparse.ArgumentParser(description="World Cup content orchestrator")
    ap.add_argument("--pillar", required=True, choices=sorted(PILLAR_SAFETY))
    ap.add_argument("--group", help="Group letter for the standings pillar (e.g. A)")
    ap.add_argument("--when", default="today", choices=["today", "tomorrow"])
    ap.add_argument("--publish", action="store_true",
                    help="Auto-publish factual pillars (opinion always goes to review)")
    ap.add_argument("--platforms", default="yt,fb,ig,tiktok",
                    help="Comma list for auto-publish (default all configured)")
    args = ap.parse_args()

    safety = PILLAR_SAFETY[args.pillar]
    print(f"🎬 Pillar '{args.pillar}' ({safety}) — generating Short…")
    video, deck = build_short(args.pillar, args.group, args.when)
    caption = build_caption(args.pillar, deck)

    auto = args.publish and safety == "factual"
    if auto:
        platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
        print(f"🚀 Auto-publishing FACTUAL pillar to: {', '.join(platforms)}")
        results = distribute(video, caption, platforms)
        for plat, status in results.items():
            print(f"   {plat}: {status}")
        # Mirror a copy to Telegram so you see what went out.
        review_via_telegram(video, caption, safety)
    else:
        why = "opinion pillar" if safety == "opinion" else "no --publish"
        print(f"🔒 Review-only ({why}) — sending to Telegram, nothing published.")
        review_via_telegram(video, caption, safety)


if __name__ == "__main__":
    main()
