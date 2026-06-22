#!/usr/bin/env python3
"""World Cup Survival Lab renderer/review/publisher."""
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
TOPICS = KIT / "content" / "survival_lab" / "topics.json"
POSTED = KIT / "content" / "survival_lab" / "posted.json"
OUT_DIR = KIT / "content" / "assets" / "shorts" / "survival_lab"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"

BLOCKED_TERMS = {
    "bet", "bets", "betting", "odds", "gamble", "gambling", "wager", "wagering",
    "sportsbook", "bookmaker", "parlay", "lock", "locks", "free money",
    "easy money", "guarantee", "guaranteed", "risk-free", "sure thing",
}


def _topics() -> list[dict]:
    return json.loads(TOPICS.read_text()).get("topics", [])


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


def pick_topic(explicit: str | None) -> dict | None:
    topics = _topics()
    if explicit:
        return next((t for t in topics if t["id"] == explicit), None)
    posted = _posted()
    fresh = [t for t in topics if t["id"] not in posted]
    return (fresh or topics)[0] if topics else None


def validate_topic(topic: dict) -> list[str]:
    issues: list[str] = []
    text_blob = json.dumps(topic, ensure_ascii=False).lower()
    for term in sorted(BLOCKED_TERMS):
        if re.search(rf"\b{re.escape(term)}\b", text_blob):
            issues.append(f"blocked term: {term}")
    lines = [str(x).strip() for x in topic.get("title_lines", []) if str(x).strip()]
    if not (1 <= len(lines) <= 3):
        issues.append("title_lines must contain 1-3 lines")
    for line in lines:
        if len(line) > 28:
            issues.append(f"title line too long: {line}")
    hook = str(topic.get("hook", ""))
    if len(hook) > 58:
        issues.append("hook too long for safe layout")
    subtitle = str(topic.get("subtitle", ""))
    if len(subtitle) > 88:
        issues.append("subtitle too long for safe layout")
    groups = topic.get("scenes", {}).get("groups", [])
    if len(groups) != 12:
        issues.append("first Survival Lab format expects exactly 12 group cards")
    danger = topic.get("scenes", {}).get("danger_examples", [])
    if len(danger) != 3:
        issues.append("danger_examples must contain exactly 3 items")
    for item in danger:
        if len(str(item)) > 48:
            issues.append(f"danger example too long: {item}")
    return issues


def build_props(topic: dict) -> dict:
    return {
        "title": topic["title"],
        "titleLines": topic["title_lines"],
        "hook": topic["hook"],
        "subtitle": topic["subtitle"],
        "groups": topic["scenes"]["groups"],
        "dangerExamples": topic["scenes"]["danger_examples"],
        "cta": "Follow BuildWithAbdallah for daily World Cup survival math.",
        "durations": [3, 5, 7, 8, 6, 3],
        "hasAudio": False,
        "audioFile": "voiceover.mp3",
    }


def voiceover_text(topic: dict) -> str:
    return " ".join(topic.get("voiceover", []))


def render(topic: dict) -> tuple[Path, Path, Path, list[str]]:
    issues = validate_topic(topic)
    if issues:
        raise SystemExit("[survival-lab] validation failed:\n - " + "\n - ".join(issues))
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
        print(f"[survival-lab] voiceover failed (non-fatal): {exc}")
        vo = None

    video = OUT_DIR / f"{slug}.mp4"
    cmd = [NODE, str(REMOTION / "render.mjs"), "--id", "SurvivalLab", "--props", str(props_path), "--out", str(video)]
    if vo:
        cmd += ["--audio", str(vo)]
    if subprocess.run(cmd, cwd=str(REMOTION)).returncode != 0:
        raise SystemExit("[survival-lab] render failed")

    from worldcup_survival_thumbnail import generate_thumbnail
    thumb = generate_thumbnail(
        OUT_DIR / f"{slug}_thumb.jpg",
        title=topic.get("thumbnail_title") or topic["title"],
        badge=topic.get("thumbnail_badge", "SURVIVAL LAB"),
    )
    package = OUT_DIR / f"{slug}_idea.json"
    package.write_text(json.dumps({
        "id": topic["id"],
        "title": topic["title"],
        "hook": topic["hook"],
        "caption": topic["caption"],
        "templates_next": topic.get("templates_next", []),
        "video": str(video),
        "thumbnail": str(thumb),
        "validation": {"ok": True, "issues": []},
    }, indent=2))
    return video, thumb, package, issues


def publish(topic: dict, video: Path, thumb: Path, privacy: str) -> str:
    caption = topic["caption"]
    up = subprocess.run(
        ["/usr/bin/python3", str(KIT / "scripts" / "youtube_shorts_publisher.py"), "upload",
         "--video", str(video), "--title", topic["title"][:100],
         "--description", caption, "--privacy", privacy, "--profile", "main",
         "--category-id", "17",
         "--tags", "WorldCup2026,FootballAnalytics,SoccerData,BuildWithAbdallah,ThePitchAgent,shorts",
         "--thumbnail", str(thumb)],
        capture_output=True, text=True,
    )
    print(up.stdout[-500:])
    if up.returncode != 0:
        print(f"[survival-lab] upload failed: {up.stderr[-500:]}")
        raise SystemExit(1)
    m = re.search(r"https://www\.youtube\.com/shorts/[\w-]+", up.stdout)
    return m.group(0) if m else ""


def _telegram_env() -> None:
    tok = Path(os.path.expanduser("~/.telegram-bot-token"))
    if tok.exists():
        token = tok.read_text().strip()
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["TELEGRAM_TOKEN"] = token
    os.environ.setdefault("TELEGRAM_CHAT_ID", "-1003948211258")
    os.environ.setdefault("TELEGRAM_MESSAGE_THREAD_ID", "14119")


def send_review(topic: dict, video: Path, thumb: Path, package: Path, validation: list[str]) -> None:
    _telegram_env()
    import telegram_poster as TG
    publish_cmd = f"/usr/bin/python3 scripts/worldcup_survival_lab.py --topic {topic['id']} --publish --privacy public"
    status = "PASS" if not validation else "FAIL: " + "; ".join(validation)
    packet = (
        "World Cup Survival Lab review\n\n"
        f"Title: {topic['title']}\n"
        f"Video: {video}\n"
        f"Thumbnail: {thumb}\n"
        f"Idea JSON: {package}\n"
        f"Validation: {status}\n\n"
        f"Caption:\n{topic['caption']}\n\n"
        f"Publish after approval:\ncd {KIT}\n{publish_cmd}"
    )
    TG.post_video(str(video), caption=f"World Cup Survival Lab review\n{topic['title']}\nValidation: {status}")
    TG.post_photo(str(thumb), caption="Survival Lab thumbnail review")
    TG.post_message(packet)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    args = ap.parse_args()
    load_env()
    topic = pick_topic(args.topic)
    if not topic:
        print("[survival-lab] no topic available")
        return 0
    video, thumb, package, validation = render(topic)
    print(f"✅ [survival-lab] video: {video}")
    print(f"✅ [survival-lab] thumbnail: {thumb}")
    print(f"✅ [survival-lab] idea package: {package}")
    if args.review:
        send_review(topic, video, thumb, package, validation)
    if args.publish:
        yt = publish(topic, video, thumb, args.privacy)
        if args.privacy == "public":
            _mark(topic["id"])
        print(f"✅ [survival-lab] published: {yt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
