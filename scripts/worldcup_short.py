#!/usr/bin/env python3
"""Tier-1 World Cup Shorts generator — 100% original branded graphics.

Renders a deck of branded cards (no match footage → no Content ID risk) into a
vertical 1080x1920 MP4 with an edge-tts voiceover. Same Playwright + ffmpeg
engine as the Shorts Visual Agent.

Content is static/data-driven (API-free). Edit the DECKS below or pass your own.
Run:   /usr/bin/python3 scripts/worldcup_short.py --deck group-a
List:  /usr/bin/python3 scripts/worldcup_short.py --list
Output is review-only — never auto-posted. Send to YouTube/TikTok manually.
"""

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTS_DIR = ROOT / "content" / "assets" / "shorts"
TEMPLATES_DIR = ROOT / "templates" / "shorts"
SCRIPTS_DIR = ROOT / "scripts"

WATERMARK = '<span class="wm-text">BWA</span>'
VOICE = "en-US-GuyNeural"


# ── Content decks ────────────────────────────────────────────────────────
# Each deck: {"slug", "title", "scenes": [...], "voiceover": "para per scene"}.
# Scene variable names match the shorts templates exactly:
#   title_card.html  -> title, caption, main_idea, progress, watermark
#   code_card.html   -> title, caption, code, takeaway, progress, watermark
#   cta_card.html    -> title, caption, cta, url, progress, watermark
DECKS = {
    "group-a": {
        "title": "Group A — Final Standings",
        "scenes": [
            {
                "template": "title_card.html",
                "title": "Group A Is Decided 🏆",
                "caption": "2026 FIFA World Cup",
                "main_idea": "Three matchdays, one clear winner, and a heavyweight "
                             "crashing out. Here's the final table — and what it means.",
                "progress": "1/6",
                "duration_seconds": 8,
            },
            {
                "template": "code_card.html",
                "title": "The Final Table",
                "caption": "Group A · after Matchday 3",
                "code": (
                    "Pos  Team         P  W  D  L  Pts\n"
                    "---------------------------------\n"
                    "1    Argentina    3  3  0  0   9\n"
                    "2    Brazil       3  2  1  0   7\n"
                    "3    France       3  1  1  1   4\n"
                    "4    Morocco      3  0  0  3   0"
                ),
                "takeaway": "Argentina top the group with a perfect 9 points",
                "progress": "2/6",
                "duration_seconds": 13,
            },
            {
                "template": "title_card.html",
                "title": "Group Top Scorer ⚽",
                "caption": "Golden Boot race",
                "main_idea": "4 goals in 3 games — the Argentine captain is setting "
                             "the pace and dragging his side through the group.",
                "progress": "3/6",
                "duration_seconds": 11,
            },
            {
                "template": "title_card.html",
                "title": "The Shock 😱",
                "caption": "Morocco out",
                "main_idea": "Semi-finalists last time, home of the 2022 fairytale — "
                             "Morocco leave with zero points. The group of death bit hard.",
                "progress": "4/6",
                "duration_seconds": 12,
            },
            {
                "template": "title_card.html",
                "title": "What's Next 🔜",
                "caption": "Round of 16",
                "main_idea": "Argentina avoid the big guns and get a favourable draw. "
                             "Brazil land the tougher side of the bracket. Advantage Albiceleste.",
                "progress": "5/6",
                "duration_seconds": 11,
            },
            {
                "template": "cta_card.html",
                "title": "Follow For Every Group",
                "caption": "Daily World Cup breakdowns",
                "cta": "Follow Build With Abdallah",
                "url": "buildwithabdallah.com",
                "progress": "6/6",
                "duration_seconds": 6,
            },
        ],
        "voiceover": (
            "Group A is decided, and it delivered. Three matchdays, one dominant "
            "winner, and a heavyweight going home early. Here's the final table.\n\n"
            "Argentina, a perfect three wins from three, nine points, top of the "
            "group. Brazil follow on seven. France squeeze through third on four. "
            "And Morocco, rooted to the bottom with zero.\n\n"
            "The Golden Boot race already has a leader. The Argentine captain, four "
            "goals in three games, setting the pace and carrying his side.\n\n"
            "But the story is the shock. Morocco, semi-finalists just one cycle ago, "
            "the home of the 2022 fairytale, crash out without a single point. The "
            "group of death bit hard.\n\n"
            "So what's next? Argentina avoid the big guns and land a favourable "
            "round of sixteen tie. Brazil get the tougher half of the bracket. "
            "Advantage Albiceleste.\n\n"
            "Follow Build With Abdallah for a breakdown of every group, every day "
            "of the World Cup."
        ),
    },
    "on-this-day-1970": {
        "title": "On This Day — 1970",
        "scenes": [
            {
                "template": "title_card.html",
                "title": "The Greatest Team Ever? 🇧🇷",
                "caption": "On This Day · 1970",
                "main_idea": "Mexico 1970. Pelé, Jairzinho, Carlos Alberto. Many still "
                             "call this Brazil side the most beautiful team in history.",
                "progress": "1/4",
                "duration_seconds": 9,
            },
            {
                "template": "code_card.html",
                "title": "Brazil 1970 — By The Numbers",
                "caption": "Road to the title",
                "code": (
                    "Games played .......... 6\n"
                    "Games won ............. 6\n"
                    "Goals scored ......... 19\n"
                    "Jairzinho ... scored in EVERY game\n"
                    "Final ......... Brazil 4-1 Italy"
                ),
                "takeaway": "Six games, six wins — the only team to win it all in style",
                "progress": "2/4",
                "duration_seconds": 13,
            },
            {
                "template": "title_card.html",
                "title": "That Carlos Alberto Goal",
                "caption": "The perfect team goal",
                "main_idea": "Nine players touched the ball. It ended with the captain "
                             "thundering it home. Still the greatest team goal ever scored.",
                "progress": "3/4",
                "duration_seconds": 11,
            },
            {
                "template": "cta_card.html",
                "title": "More Football History",
                "caption": "On This Day, every day",
                "cta": "Follow Build With Abdallah",
                "url": "buildwithabdallah.com",
                "progress": "4/4",
                "duration_seconds": 6,
            },
        ],
        "voiceover": (
            "Was this the greatest team that ever played? Mexico, 1970. Pelé, "
            "Jairzinho, Carlos Alberto — for many, the most beautiful side in the "
            "history of the game.\n\n"
            "By the numbers it's staggering. Six games, six wins. Nineteen goals "
            "scored. Jairzinho found the net in every single match. And a final "
            "won four-one against Italy.\n\n"
            "And then, that goal. Carlos Alberto. Nine players touched the ball in "
            "the build-up before the captain thundered it home. Still, fifty years "
            "on, the greatest team goal ever scored.\n\n"
            "Follow Build With Abdallah for football history, on this day, every day."
        ),
    },
}


def render_scene(scene: dict, index: int, out_dir: Path) -> Path:
    """Render one scene HTML to a 1080x1920 PNG via render_card.mjs."""
    html_src = (TEMPLATES_DIR / scene["template"]).read_text()

    for key in ("title", "caption", "main_idea", "takeaway", "cta", "url", "progress"):
        if key in scene:
            html_src = html_src.replace("{{" + key + "}}", scene[key])
    html_src = html_src.replace("{{watermark}}", WATERMARK)

    if scene["template"] == "code_card.html":
        lines = scene["code"].split("\n")
        code_html = "".join(f"<div>{html.escape(line) or '&nbsp;'}</div>" for line in lines)
        html_src = html_src.replace("{{code}}", code_html)

    # Drop any unfilled placeholders so they never show.
    while "{{" in html_src and "}}" in html_src:
        s = html_src.index("{{"); e = html_src.index("}}", s) + 2
        html_src = html_src[:s] + html_src[e:]

    html_path = out_dir / f"scene_{index:02d}.html"
    html_path.write_text(html_src)
    png_path = out_dir / f"scene_{index:02d}.png"
    r = subprocess.run(
        ["node", str(SCRIPTS_DIR / "render_card.mjs"), str(html_path), str(png_path), "1080", "1920"],
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0:
        print(f"⚠️  Scene {index} render issue: {r.stderr[-300:]}", file=sys.stderr)
    if not png_path.exists():
        raise RuntimeError(f"Scene {index} PNG not generated")
    return png_path


def generate_voiceover(text: str, out_path: Path) -> Path | None:
    import shutil
    if not shutil.which("edge-tts"):
        print("⚠️  edge-tts not found — visual-only")
        return None
    r = subprocess.run(["edge-tts", "--voice", VOICE, "--text", text, "--write-media", str(out_path)],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"⚠️  edge-tts failed: {r.stderr[-200:]}", file=sys.stderr)
        return None
    return out_path


def assemble_video(scene_paths, voice_path, out_video):
    """Crossfade scene PNGs into a vertical MP4, muxing the voiceover."""
    has_voice = bool(voice_path and voice_path.exists())
    xfade = 0.4
    scale_vf = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
    inputs = []
    for png, dur in scene_paths:
        inputs += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(png)]

    fc, cum, prev = [], 0.0, "[0:v]"
    for i in range(1, len(scene_paths)):
        cum += scene_paths[i - 1][1] - xfade
        lbl = f"[v{i}]" if i < len(scene_paths) - 1 else "[voutscale]"
        fc.append(f"{prev}[{i}:v]xfade=transition=fade:duration={xfade}:offset={cum:.3f}{lbl}")
        prev = lbl
    fc.append(f"[voutscale]{scale_vf}[vout]")

    cmd = ["ffmpeg", "-y"] + inputs
    if has_voice:
        cmd += ["-stream_loop", "-1", "-i", str(voice_path)]
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-700:]}")


def build(deck_slug: str) -> Path:
    deck = DECKS[deck_slug]
    out_dir = SHORTS_DIR / f"worldcup-{deck_slug}"
    scenes_dir = out_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎬 Rendering {len(deck['scenes'])} scenes for '{deck_slug}'...")
    scene_paths = []
    for i, sc in enumerate(deck["scenes"], 1):
        print(f"   {i}/{len(deck['scenes'])}: {sc['template']:18s} — {sc.get('title','')[:42]}")
        scene_paths.append((render_scene(sc, i, scenes_dir), float(sc["duration_seconds"])))

    print("🎙️  Voiceover...")
    voice = generate_voiceover(deck["voiceover"], out_dir / "voiceover.mp3")

    total = sum(d for _, d in scene_paths)
    print(f"🎞️  Assembling vertical 1080x1920 ({total:.0f}s)...")
    out_video = out_dir / f"worldcup-{deck_slug}.mp4"
    assemble_video(scene_paths, voice, out_video)

    probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                            "-show_format", str(out_video)], capture_output=True, text=True, timeout=15)
    dur = json.loads(probe.stdout or "{}").get("format", {}).get("duration", "?")
    (out_dir / "metadata.json").write_text(json.dumps({
        "slug": f"worldcup-{deck_slug}", "title": deck["title"],
        "scenes": len(deck["scenes"]), "duration_seconds": dur, "voiceover": bool(voice),
        "vertical": "1080x1920", "copyright_safe": True,
    }, indent=2))
    print(f"\n✅ {out_video}\n   {dur}s · {len(deck['scenes'])} scenes · vertical · voiceover: {'yes' if voice else 'no'}")
    print("📤 Review-only. Send to YouTube/TikTok manually.")
    return out_video


def main():
    ap = argparse.ArgumentParser(description="Tier-1 World Cup Shorts generator (no footage, copyright-safe)")
    ap.add_argument("--deck", help="Deck slug to build")
    ap.add_argument("--list", action="store_true", help="List available decks")
    args = ap.parse_args()
    if args.list or not args.deck:
        print("Available decks:")
        for slug, d in DECKS.items():
            print(f"  {slug:22s} — {d['title']} ({len(d['scenes'])} scenes)")
        return
    if args.deck not in DECKS:
        print(f"Unknown deck '{args.deck}'. Use --list.", file=sys.stderr)
        sys.exit(1)
    build(args.deck)


if __name__ == "__main__":
    main()
