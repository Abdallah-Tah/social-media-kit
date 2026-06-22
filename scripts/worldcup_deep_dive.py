#!/usr/bin/env python3
"""Daily World Cup data-deep-dive idea + Short renderer.

Produces a video-ready package: titles, hooks, outline, thumbnail ideas,
metadata JSON, thumbnail, MP4, and optional YouTube upload.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402

REMOTION = KIT / "remotion"
TOPICS = KIT / "content" / "deep_dives" / "topics.json"
POSTED = KIT / "content" / "deep_dives" / "posted.json"
OUT_DIR = KIT / "content" / "assets" / "shorts" / "deep_dives"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"


def _posted() -> set[str]:
    try:
        return set(json.loads(POSTED.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _mark(tid: str) -> None:
    seen = _posted()
    seen.add(tid)
    POSTED.parent.mkdir(parents=True, exist_ok=True)
    POSTED.write_text(json.dumps(sorted(seen), indent=2))


def _topics() -> list[dict]:
    return json.loads(TOPICS.read_text()).get("topics", [])


def pick_topic(explicit: str | None) -> dict | None:
    topics = _topics()
    if explicit:
        return next((t for t in topics if t["id"] == explicit), None)
    posted = _posted()
    fresh = [t for t in topics if t["id"] not in posted]
    return (fresh or topics)[0] if topics else None


def layout_title_lines(topic: dict) -> list[str]:
    explicit = [str(x).strip() for x in topic.get("title_lines", []) if str(x).strip()]
    if explicit:
        if len(explicit) > 3:
            raise SystemExit(f"[deep-dive] title_lines for {topic['id']} must be 3 lines max")
        if any(len(line) > 30 for line in explicit):
            raise SystemExit(f"[deep-dive] title line too long for safe layout: {explicit}")
        return explicit

    words = topic["title"].split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if len(trial) <= 26:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > 3 or any(len(line) > 30 for line in lines):
        raise SystemExit(
            "[deep-dive] title does not fit the safe 3-line layout; "
            f"add title_lines to {TOPICS} for topic {topic['id']}"
        )
    return lines


def build_props(topic: dict) -> dict:
    return {
        "title": topic["title"],
        "titleLines": layout_title_lines(topic),
        "hook": topic["hook"],
        "beats": topic["beats"],
        "statCards": topic["stat_cards"],
        "finalCall": topic["final_call"],
        "cta": "Follow for daily World Cup data dives",
        "durations": [6, 8, 7, 6],
        "hasAudio": False,
        "audioFile": "voiceover.mp3",
    }


def voiceover_text(topic: dict) -> str:
    return " ".join([
        topic["hook"],
        "We are running a data deep dive on the World Cup.",
        *topic["beats"],
        topic["final_call"],
        "This is independent simulation analysis, not a guarantee.",
        "Follow for daily World Cup data dives.",
    ])


def render(topic: dict) -> tuple[Path, Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = topic["id"]
    props = build_props(topic)
    props_path = OUT_DIR / f"{slug}_props.json"
    props_path.write_text(json.dumps(props, indent=2))

    try:
        import reel_generator
        vo = OUT_DIR / f"{slug}_vo.mp3"
        rendered = str(vo) if vo.exists() else reel_generator.tts(voiceover_text(topic), str(vo))
        if rendered and Path(rendered).exists():
            props["hasAudio"] = True
            props["audioFile"] = f"{slug}_vo.mp3"
            props_path.write_text(json.dumps(props, indent=2))
        else:
            vo = None
    except Exception as exc:  # noqa: BLE001
        print(f"[deep-dive] voiceover failed (non-fatal): {exc}")
        vo = None

    out = OUT_DIR / f"{slug}.mp4"
    cmd = [NODE, str(REMOTION / "render.mjs"), "--id", "DataDive", "--props", str(props_path), "--out", str(out)]
    if vo:
        cmd += ["--audio", str(vo)]
    if subprocess.run(cmd, cwd=str(REMOTION)).returncode != 0:
        raise SystemExit("[deep-dive] render failed")

    from worldcup_thumbnail import generate_thumbnail
    thumb = generate_thumbnail(
        OUT_DIR / f"{slug}_thumb.jpg",
        title=topic.get("thumbnail_title") or topic["title"],
        kind=topic.get("kind", "DATA DIVE"),
    )

    package = OUT_DIR / f"{slug}_idea.json"
    package.write_text(json.dumps({
        "id": topic["id"],
        "title": topic["title"],
        "titles": topic["titles"],
        "hook": topic["hook"],
        "outline": topic["outline"],
        "thumbnail_ideas": topic["thumbnail_ideas"],
        "video": str(out),
        "thumbnail": str(thumb),
    }, indent=2))
    return out, thumb, package


def publish(topic: dict, video: Path, thumb: Path, privacy: str) -> str:
    title = topic["titles"][0][:100]
    desc = (
        f"{topic['hook']}\n\n"
        "Independent World Cup 2026 simulation analysis. These are model scenarios, not guarantees.\n\n"
        "#WorldCup2026 #WorldCup #Football #Soccer #DataScience #AIPredictions #Shorts"
    )
    up = subprocess.run(
        ["/usr/bin/python3", str(KIT / "scripts" / "youtube_shorts_publisher.py"), "upload",
         "--video", str(video), "--title", title, "--description", desc,
         "--privacy", privacy, "--profile", "main", "--category-id", "17",
         "--tags", "WorldCup2026,WorldCup,football,soccer,data science,simulation,AIpredictions,shorts",
         "--thumbnail", str(thumb)],
        capture_output=True, text=True,
    )
    print(up.stdout[-500:])
    if up.returncode != 0:
        print(f"[deep-dive] upload failed: {up.stderr[-500:]}")
        raise SystemExit(1)
    m = re.search(r"https://www\.youtube\.com/shorts/[\w-]+", up.stdout)
    return m.group(0) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    args = ap.parse_args()
    load_env()

    topic = pick_topic(args.topic)
    if not topic:
        print("[deep-dive] no topics available")
        return 0

    print(f"[deep-dive] idea: {topic['title']}")
    print("hooks/titles/outline package will be written with the render.")
    if args.dry_run:
        print(json.dumps({k: topic[k] for k in ("titles", "hook", "outline", "thumbnail_ideas")}, indent=2))
        return 0

    video, thumb, package = render(topic)
    print(f"✅ [deep-dive] video: {video}")
    print(f"✅ [deep-dive] thumbnail: {thumb}")
    print(f"✅ [deep-dive] idea package: {package}")

    if args.publish:
        yt = publish(topic, video, thumb, args.privacy)
        if args.privacy == "public":
            _mark(topic["id"])
        print(f"✅ [deep-dive] published: {yt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
