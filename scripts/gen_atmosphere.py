"""Football atmosphere clip fetcher — Pexels CC0 licensed, commercial safe.

Fetches a short (≤15s) football atmosphere clip from Pexels (stadium,
crowd, pitch aerials — no recognisable players, no team logos), trims and
scales it to 1080x1920 vertical, returns the path for use as a background
layer in the matchday video.

Usage:
    python3 gen_atmosphere.py [--query "football stadium night"] [--out clip.mp4]

Requires PEXELS_API_KEY in config/secrets.env.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "content" / "assets" / "atmosphere"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Safe search terms — generic football atmosphere, no real teams or FIFA branding.
DEFAULT_QUERIES = [
    "football stadium night lights",
    "soccer stadium crowd aerial",
    "football pitch green grass",
    "stadium lights atmosphere",
    "soccer ball grass field",
]

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"


def _load_key() -> str:
    for f in (ROOT / "config" / "secrets.env",
              Path.home() / ".config" / "social-media-kit" / "secrets.env"):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            m = re.match(r"^PEXELS_API_KEY=(.+)$", line.strip())
            if m:
                return m.group(1).strip().strip('"')
    return os.environ.get("PEXELS_API_KEY", "")


def _search(query: str, api_key: str, min_duration: int = 5, max_duration: int = 20) -> str | None:
    """Return a direct video URL for the best matching clip."""
    r = requests.get(
        PEXELS_VIDEO_SEARCH,
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 15, "orientation": "portrait", "size": "medium"},
        timeout=20,
    )
    if r.status_code != 200:
        print(f"⚠️  Pexels search failed ({r.status_code}): {r.text[:100]}", file=sys.stderr)
        return None

    videos = r.json().get("videos", [])
    for v in videos:
        dur = v.get("duration", 0)
        if not (min_duration <= dur <= max_duration):
            continue
        # Pick the HD file (prefer 1280+ wide or at least 720)
        files = sorted(v.get("video_files", []),
                       key=lambda f: f.get("width", 0), reverse=True)
        for f in files:
            if f.get("file_type", "").startswith("video/mp4") and f.get("width", 0) >= 640:
                return f["link"]
    return None


def fetch_atmosphere(query: str | None = None, out_path: str | None = None,
                     duration: float = 8.0) -> Path:
    """Download, trim and scale a Pexels clip to 1080x1920 vertical.

    Returns the path to the processed clip.
    Raises RuntimeError if no clip could be fetched or processed.
    """
    api_key = _load_key()
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not found in secrets.env")

    queries = [query] if query else DEFAULT_QUERIES

    url = None
    for q in queries:
        url = _search(q, api_key)
        if url:
            print(f"🎬 Pexels clip: {q} → {url[:60]}…")
            break

    if not url:
        raise RuntimeError("No suitable Pexels clip found for query")

    # Download to temp file
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        raw_path = tmp.name
    r = requests.get(url, stream=True, timeout=120)
    with open(raw_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)

    # Process: trim to `duration` seconds, scale/crop to 1080x1920 vertical,
    # add a subtle dark vignette so our brand cards read clearly on top.
    out = out_path or str(CACHE_DIR / f"atm_{hash(url) & 0xFFFFFF:06x}.mp4")
    vf = (
        f"trim=0:{duration:.2f},setpts=PTS-STARTPTS,"
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        # Dark vignette: 50% transparent black radial gradient to keep
        # the focus on our cards overlaid on top.
        "vignette=PI/4,"
        "colorchannelmixer=rr=0.75:gg=0.75:bb=0.75"  # slightly darken for readability
    )
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", raw_path, "-vf", vf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-an", "-r", "30", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    os.unlink(raw_path)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg trim/scale failed: {r.stderr[-300:]}")
    print(f"✅ Atmosphere clip: {out}")
    return Path(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--duration", type=float, default=8.0)
    args = ap.parse_args()
    try:
        print(fetch_atmosphere(args.query, args.out, args.duration))
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
