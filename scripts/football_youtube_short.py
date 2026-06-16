#!/usr/bin/env python3
"""Matchday preview -> YouTube Short (animated brand card + optional TTS).

YouTube has no API for plain-text community posts, so "post text on YouTube"
means: render the matchday-preview card as a vertical Short and upload it
with the preview text as the title + description (real, searchable text).

Reuses the card the football pipeline already renders
(artifacts/pitch_agent/charts/fixtures.png) and the preview text from
generate_content (dry-run, publishes nothing). The only outward-facing step
is the final upload, gated behind --privacy and skipped entirely with
--dry-run.

  # render the Short only, no upload (safe):
  /usr/bin/python3 scripts/football_youtube_short.py --dry-run
  # render + upload (live):
  /usr/bin/python3 scripts/football_youtube_short.py --privacy public
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

CARD = KIT / "artifacts" / "pitch_agent" / "charts" / "fixtures.png"
OUT = KIT / "content" / "assets" / "football_yt_short.mp4"
FFMPEG = "/usr/bin/ffmpeg" if Path("/usr/bin/ffmpeg").exists() else "ffmpeg"


def build_text() -> str:
    """Generate today's matchday preview (dry-run) and return the post text.

    Side effect: renders the brand card to CARD. Publishes nothing.
    """
    from pitch_agent.content import generate_content
    result = generate_content(
        pillar="matchday_preview", mode="fan_mode", dry_run=True,
    )
    return (result or {}).get("content", "").strip()


_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_NAVY = "0x13294b"  # brand navy, on the mandated white light-theme background


def _media_duration(path: Path) -> float | None:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _voiceover(text: str, out: Path) -> Path | None:
    """ElevenLabs conversational voice first (brand standard), edge-tts only
    as an emergency fallback. Routes through reel_generator.tts which is
    ElevenLabs -> OpenAI -> edge-tts."""
    if not text.strip():
        return None
    try:
        sys.path.insert(0, str(KIT / "scripts"))
        import reel_generator  # type: ignore
        rendered = reel_generator.tts(text.strip(), str(out))
        if rendered and Path(rendered).exists():
            return Path(rendered)
    except Exception as exc:  # noqa: BLE001
        print(f"[football-yt] ElevenLabs TTS path failed: {exc}", file=sys.stderr)
    # last-resort: edge-tts directly
    edge_tts = shutil.which("edge-tts")
    if not edge_tts:
        return None
    r = subprocess.run(
        [
            edge_tts,
            "--voice", os.environ.get("PITCH_AGENT_TTS_VOICE", "en-US-AndrewNeural"),
            "--rate", os.environ.get("PITCH_AGENT_TTS_RATE", "+8%"),
            "--text", text.strip(),
            "--write-media", str(out),
        ],
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0:
        print(f"[football-yt] TTS failed, rendering visual-only: {r.stderr[-240:]}", file=sys.stderr)
        return None
    return out if out.exists() else None


def make_short(
    card: Path = CARD,
    out: Path = OUT,
    seconds: int = 16,
    voiceover: str = "",
    title: str = "AI WORLD CUP PICKS",
    cta: str = "Follow The Pitch Agent - daily AI calls",
) -> Path:
    """Animated 1080x1920 Short from a brand card, optionally with TTS.

    Same format used for the football prediction Shorts (card + headline + CTA
    + slow zoom + voiceover); title/cta are parametrized so news can reuse it.
    """
    if not card.exists():
        raise FileNotFoundError(f"card not found: {card}")
    out.parent.mkdir(parents=True, exist_ok=True)

    tmpdir = Path(tempfile.mkdtemp(prefix="pitch_agent_short_"))
    voice = _voiceover(voiceover, tmpdir / "voiceover.mp3") if voiceover else None
    duration = float(seconds)
    if voice:
        duration = max(duration, (_media_duration(voice) or duration) + 0.25)

    fc = (
        "[1:v]scale=1040:-1[c];"
        "[0:v][c]overlay=(W-w)/2:(H-h)/2[bg];"
        f"[bg]drawtext=fontfile={_FONT}:text='{title}':fontcolor={_NAVY}:"
        "fontsize=82:x=(w-text_w)/2:y=300[t];"
        f"[t]drawtext=fontfile={_FONT}:text='{cta}':fontcolor={_NAVY}:"
        "fontsize=46:x=(w-text_w)/2:y=h-360,"
        "zoompan=z='min(zoom+0.00045,1.055)':d=1:"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30[v]"
    )
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c=white:s=1080x1920:d={duration:.2f}",
        "-loop", "1", "-i", str(card),
    ]
    if voice:
        cmd += ["-i", str(voice)]
    cmd += ["-filter_complex", fc, "-map", "[v]"]
    if voice:
        cmd += ["-map", "2:a:0", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [
        "-t", f"{duration:.2f}", "-r", "30", "-pix_fmt", "yuv420p",
        "-c:v", "libx264", str(out),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out


def headline_match() -> str:
    """The marquee upcoming match today, as 'Home vs Away' (for the title)."""
    try:
        from pitch_agent.fixtures import get_upcoming_fixtures
        from pitch_agent.content import _upcoming_fixtures
        fx = _upcoming_fixtures(get_upcoming_fixtures(limit=12), limit=1, today_only=True)
        if fx:
            return f"{fx[0]['home_team_name']} vs {fx[0]['away_team_name']}"
    except Exception:
        pass
    return ""


def title_and_description(text: str) -> tuple[str, str]:
    # Proven high-view format: "{matchup} — AI Prediction 🏆 World Cup 2026".
    hm = headline_match()
    if hm:
        title = f"{hm} — AI Prediction \U0001F3C6 World Cup 2026"[:100]
    else:
        title = "AI Predictions \U0001F3C6 World Cup 2026"
    tags = ("#WorldCup2026 #WorldCup #Football #Soccer #FIFAWorldCup "
            "#AIPredictions #footballpredictions #Shorts")
    desc = (text + "\n\n" + tags).strip()[:4900]
    return title, desc


def upload(video: Path, title: str, desc: str, privacy: str, profile: str = "main") -> tuple[int, str]:
    """Upload to YouTube; return (exit_code, video_url)."""
    cmd = [
        "/usr/bin/python3", str(KIT / "scripts" / "youtube_shorts_publisher.py"),
        "upload", "--video", str(video), "--title", title,
        "--description", desc, "--privacy", privacy, "--profile", profile,
        "--tags", "WorldCup2026,WorldCup,football,soccer,FIFAWorldCup,AIpredictions,footballpredictions,shorts",
        "--category-id", "17",  # 17 = Sports
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout, end="")
    if res.stderr:
        print(res.stderr, end="", file=sys.stderr)
    m = re.search(r"https://www\.youtube\.com/shorts/[\w-]+", res.stdout)
    return res.returncode, (m.group(0) if m else "")


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # keep cron logs in order
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="render the Short, do NOT upload")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    ap.add_argument("--profile", default="main")
    args = ap.parse_args()

    text = build_text()
    if not text:
        print("[football-yt] no preview text (no matches today?) — nothing to post")
        return 0
    video = make_short()
    title, desc = title_and_description(text)
    print(f"[football-yt] rendered {video} ({video.stat().st_size//1024} KB)")
    print(f"[football-yt] title: {title}")
    if args.dry_run:
        print("[football-yt] DRY RUN — not uploading.")
        return 0
    rc, yt_url = upload(video, title, desc, args.privacy, args.profile)
    print(f"[football-yt] upload exit {rc} (privacy={args.privacy}) {yt_url}")

    # Cross-post the preview to Facebook + LinkedIn with the YouTube link.
    if rc == 0 and args.privacy == "public":
        try:
            from football_crosspost import crosspost
            crosspost(text, youtube_url=yt_url,
                      image_path=str(CARD) if CARD.exists() else None,
                      title="AI World Cup predictions")
        except Exception as exc:  # noqa: BLE001
            print(f"[football-yt] crosspost failed (non-fatal): {exc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
