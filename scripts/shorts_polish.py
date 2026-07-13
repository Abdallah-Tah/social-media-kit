#!/usr/bin/env python3
"""Polish a rendered Short with freecut (word-synced subtitles + fades + grade).

Uses the freecut helpers (~/Developer/freecut) to:
  1. transcribe the video locally (faster-whisper, cached per source)
  2. build a single-segment EDL covering the whole clip
  3. render with word-timed 2-word UPPERCASE burned subtitles applied last,
     30ms audio fades, and an optional color grade

Output: <video_dir>/edit/<stem>_polished.mp4 (also returned on stdout as JSON).

Usage:
    /usr/bin/python3 scripts/shorts_polish.py <video.mp4> [--grade subtle] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

FREECUT = Path.home() / "Developer" / "freecut" / "helpers"
PY = "/usr/bin/python3"

# The linuxbrew ffmpeg on this Pi lacks libass (no `subtitles` filter) and
# drawtext; /usr/bin/ffmpeg has both. Put /usr/bin first so freecut's bare
# `ffmpeg`/`ffprobe` calls resolve to the system build.
ENV = {**os.environ, "PATH": "/usr/bin:" + os.environ.get("PATH", "")}


def _duration(video: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        text=True,
    )
    return float(out.strip())


def polish(video: Path, grade: str = "subtle", force: bool = False) -> Path:
    if not FREECUT.exists():
        raise SystemExit(f"freecut helpers not found at {FREECUT} — clone Moh4696/freecut first")
    video = video.resolve()
    edit_dir = video.parent / "edit"
    edit_dir.mkdir(exist_ok=True)
    out_path = edit_dir / f"{video.stem}_polished.mp4"

    # Reuse a fresh polish (skip transcribe+render) unless forced.
    if not force and out_path.exists() and out_path.stat().st_mtime >= video.stat().st_mtime:
        return out_path

    # 1. Transcribe (freecut caches per source in edit/transcripts/).
    transcript = edit_dir / "transcripts" / f"{video.stem}.json"
    if force and transcript.exists():
        transcript.unlink()
    subprocess.run(
        [PY, str(FREECUT / "transcribe.py"), str(video),
         "--backend", "whisper", "--model", "base", "--language", "en",
         "--edit-dir", str(edit_dir)],
        check=True, env=ENV,
    )
    if not transcript.exists():
        raise SystemExit(f"transcription produced no {transcript}")

    # 2. Single-segment EDL: keep the whole clip, no cuts.
    edl = {
        "sources": {video.stem: str(video)},
        "ranges": [{"source": video.stem, "start": 0.0, "end": _duration(video)}],
        "grade": grade,
    }
    edl_path = edit_dir / "edl.json"
    edl_path.write_text(json.dumps(edl, indent=2), encoding="utf-8")

    # 3. Render: extract+fades → concat → burned word-timed subtitles (last).
    subprocess.run(
        [PY, str(FREECUT / "render.py"), str(edl_path),
         "-o", str(out_path), "--build-subtitles"],
        check=True, env=ENV,
    )
    if not out_path.exists():
        raise SystemExit("freecut render produced no output")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", type=Path)
    ap.add_argument("--grade", default="subtle",
                    help="freecut grade preset or raw ffmpeg filter (default: subtle)")
    ap.add_argument("--force", action="store_true", help="re-transcribe and re-render")
    args = ap.parse_args()
    out = polish(args.video, grade=args.grade, force=args.force)
    print(json.dumps({"ok": True, "video": str(out)}))


if __name__ == "__main__":
    main()
