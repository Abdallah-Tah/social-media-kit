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
import base64
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTS_DIR = ROOT / "content" / "assets" / "shorts"
TEMPLATES_DIR = ROOT / "templates" / "shorts"
SCRIPTS_DIR = ROOT / "scripts"
LOGO_SRC = ROOT / "content" / "assets" / "brand" / "bwa-youtube-watermark.png"

VOICE = "en-US-GuyNeural"


def _watermark_html() -> str:
    """Use the real BWA logo as the corner watermark instead of a text badge.

    The tracked logo has a white background; make the surrounding white
    transparent (corner flood-fill keeps the logo interior) and embed it as a
    base64 data-URI so the Playwright render needs no external file. Falls back
    to the blue "BWA" text badge if the logo or Pillow is unavailable.
    """
    try:
        from PIL import Image
        from collections import deque

        img = Image.open(LOGO_SRC).convert("RGBA")
        px = img.load()
        w, h = img.size
        seen = set()
        q = deque([(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)])
        while q:
            x, y = q.popleft()
            if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
                continue
            seen.add((x, y))
            r, g, b, a = px[x, y]
            if r > 225 and g > 225 and b > 225 and a > 0:
                px[x, y] = (r, g, b, 0)
                q.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
        from io import BytesIO
        buf = BytesIO()
        img.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'<img class="wm-img" src="data:image/png;base64,{b64}">'
    except Exception:
        return '<span class="wm-text">BWA</span>'


WATERMARK = _watermark_html()


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
    if has_voice:
        cmd += ["-map", f"{len(scene_paths)}:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_video)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-700:]}")


def build(deck: dict, slug: str) -> Path:
    deck_slug = slug
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


# ── Live-data deck builders (worldcup26.ir) ──────────────────────────────

def deck_standings(group_letter: str) -> tuple[dict, str]:
    """Build a Group Standings deck from live worldcup26.ir data."""
    import worldcup26_data as wc
    blocks = wc.standings(group_letter)
    if not blocks:
        raise SystemExit(f"No standings for group {group_letter}")
    block = blocks[0]
    rows = block["table"]
    header = "Pos Team             P  W  D  L  Pts"
    sep = "-" * len(header)
    lines = [header, sep]
    for r in rows:
        lines.append(f"{r['position']:<3} {r['team'][:15]:<15} {r['played']:>2} "
                     f"{r['won']:>2} {r['draw']:>2} {r['lost']:>2} {r['points']:>4}")
    leader = rows[0]["team"]
    played = sum(r["played"] for r in rows)
    sub = "Latest table" if played else "Group preview — kicks off soon"
    scenes = [
        {"template": "title_card.html", "title": f"{block['group']} Standings",
         "caption": "2026 FIFA World Cup",
         "main_idea": f"Here's how {block['group']} is shaping up at the 2026 World Cup.",
         "progress": "1/3", "duration_seconds": 7},
        {"template": "code_card.html", "title": block["group"], "caption": sub,
         "code": "\n".join(lines),
         "takeaway": (f"{leader} lead the group" if played else f"All eyes on {leader} and co."),
         "progress": "2/3", "duration_seconds": 14},
        {"template": "cta_card.html", "title": "Follow For Every Group",
         "caption": "Daily World Cup breakdowns", "cta": "Follow Build With Abdallah",
         "url": "buildwithabdallah.com", "progress": "3/3", "duration_seconds": 6},
    ]
    team_list = ", ".join(r["team"] for r in rows)
    if played:
        vo_table = ". ".join(f"{r['team']}, {r['points']} points" for r in rows)
        vo = (f"Here's the latest {block['group']} table at the World Cup. {vo_table}. "
              f"{leader} sit top. Follow Build With Abdallah for every group, every day.")
    else:
        vo = (f"{block['group']} at the 2026 World Cup features {team_list}. "
              f"The group is about to kick off. Follow Build With Abdallah for "
              f"previews and full-time tables for every group, every day.")
    return {"title": f"{block['group']} Standings", "scenes": scenes, "voiceover": vo}, \
        f"standings-{group_letter.lower()}"


def deck_preview(when: str = "today") -> tuple[dict, str]:
    """Build a fixtures preview deck from live worldcup26.ir data."""
    import worldcup26_data as wc
    import datetime as dt
    day = dt.date.today() if when == "today" else dt.date.today() + dt.timedelta(days=1)
    matches = wc.today_matches(day)
    if not matches:
        raise SystemExit(f"No matches found for {day}")
    label = "Today" if when == "today" else "Tomorrow"
    lines = [f"{m['home_team']} vs {m['away_team']}  (Group {m['group']})" for m in matches]
    scenes = [
        {"template": "title_card.html", "title": f"{label}'s World Cup Matches",
         "caption": day.strftime("%b %d, 2026"),
         "main_idea": f"{len(matches)} match{'es' if len(matches) != 1 else ''} on the World Cup "
                      f"calendar {label.lower()}. Here's who's playing.",
         "progress": "1/2", "duration_seconds": 8},
        {"template": "cta_card.html", "title": "\n".join(lines[:5]),
         "caption": f"{label}'s fixtures", "cta": "Who's your pick?",
         "url": "buildwithabdallah.com", "progress": "2/2", "duration_seconds": 10},
    ]
    vo_matches = ". ".join(f"{m['home_team']} versus {m['away_team']}" for m in matches)
    vo = (f"{label} at the 2026 World Cup: {len(matches)} to watch. {vo_matches}. "
          f"Who are you backing? Follow Build With Abdallah for every matchday.")
    return {"title": f"{label}'s Matches", "scenes": scenes, "voiceover": vo}, \
        f"preview-{day.isoformat()}"


def deck_recap(match_id: str | None = None) -> tuple[dict, str]:
    """Build a full-time recap deck from the latest finished match (live data)."""
    import worldcup26_data as wc
    finished = wc.finished_matches()
    if not finished:
        raise SystemExit("No finished matches yet — recap activates once a match ends.")
    m = next((x for x in finished if x["id"] == match_id), finished[-1])
    score = f"{m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}"
    if m["home_score"] > m["away_score"]:
        result = f"{m['home_team']} win it"
    elif m["home_score"] < m["away_score"]:
        result = f"{m['away_team']} take all three points"
    else:
        result = "Honours even — a point apiece"
    scorers = (m["home_scorers"] or []) + (m["away_scorers"] or [])
    code_lines = [f"FULL TIME", "-" * 28, f"{m['home_team']}  {m['home_score']}",
                  f"{m['away_team']}  {m['away_score']}"]
    if scorers:
        code_lines += ["", "Scorers:"] + [f"  {s}" for s in scorers[:6]]
    scenes = [
        {"template": "title_card.html", "title": "Full Time ⏱️", "caption": f"Group {m['group']}",
         "main_idea": score, "progress": "1/3", "duration_seconds": 8},
        {"template": "code_card.html", "title": "The Result", "caption": "Final score",
         "code": "\n".join(code_lines), "takeaway": result,
         "progress": "2/3", "duration_seconds": 13},
        {"template": "cta_card.html", "title": "Every Result, Every Day",
         "caption": "World Cup full-time recaps", "cta": "Follow Build With Abdallah",
         "url": "buildwithabdallah.com", "progress": "3/3", "duration_seconds": 6},
    ]
    vo_scorers = (" The goals came from " + ", ".join(scorers[:6]) + "." ) if scorers else ""
    vo = (f"Full time at the World Cup. {m['home_team']} {m['home_score']}, "
          f"{m['away_team']} {m['away_score']}. {result}.{vo_scorers} "
          f"Follow Build With Abdallah for every full-time recap.")
    return {"title": f"Full Time: {score}", "scenes": scenes, "voiceover": vo}, \
        f"recap-{m['id']}"


def deck_prediction(when: str = "today") -> tuple[dict, str]:
    """Build an engagement-first prediction deck for the next match (opinion)."""
    import worldcup26_data as wc
    import datetime as dt
    day = dt.date.today() if when == "today" else dt.date.today() + dt.timedelta(days=1)
    matches = wc.today_matches(day)
    if not matches:
        raise SystemExit(f"No matches found for {day}")
    m = matches[0]
    tie = f"{m['home_team']} vs {m['away_team']}"
    scenes = [
        {"template": "title_card.html", "title": f"Prediction 🔮", "caption": f"Group {m['group']} · {day.strftime('%b %d')}",
         "main_idea": f"{tie}. The big question — who comes out on top?",
         "progress": "1/2", "duration_seconds": 8},
        {"template": "cta_card.html", "title": tie, "caption": "Drop your scoreline 👇",
         "cta": "Who wins? Comment your score", "url": "buildwithabdallah.com",
         "progress": "2/2", "duration_seconds": 9},
    ]
    vo = (f"Prediction time. {m['home_team']} take on {m['away_team']} in Group {m['group']}. "
          f"It's set up to be a close one. Who's your pick, and what's your scoreline? "
          f"Drop it in the comments, and follow Build With Abdallah for every matchday call.")
    return {"title": f"Prediction: {tie}", "scenes": scenes, "voiceover": vo}, \
        f"prediction-{m['id']}"


def main():
    ap = argparse.ArgumentParser(description="Tier-1 World Cup Shorts generator (no footage, copyright-safe)")
    ap.add_argument("--deck", help="Static deck slug to build")
    ap.add_argument("--standings", metavar="GROUP", help="Build a live Group Standings short (e.g. A)")
    ap.add_argument("--preview", choices=["today", "tomorrow"], help="Build a live fixtures preview short")
    ap.add_argument("--recap", nargs="?", const="latest", metavar="MATCH_ID",
                    help="Build a full-time recap short (latest finished match, or a match id)")
    ap.add_argument("--prediction", choices=["today", "tomorrow"], help="Build a prediction short")
    ap.add_argument("--list", action="store_true", help="List static decks")
    args = ap.parse_args()

    if args.standings:
        deck, slug = deck_standings(args.standings)
        build(deck, slug); return
    if args.preview:
        deck, slug = deck_preview(args.preview)
        build(deck, slug); return
    if args.recap:
        deck, slug = deck_recap(None if args.recap == "latest" else args.recap)
        build(deck, slug); return
    if args.prediction:
        deck, slug = deck_prediction(args.prediction)
        build(deck, slug); return
    if args.deck:
        if args.deck not in DECKS:
            print(f"Unknown deck '{args.deck}'. Use --list.", file=sys.stderr)
            sys.exit(1)
        build(DECKS[args.deck], args.deck); return

    print("Static decks:")
    for slug, d in DECKS.items():
        print(f"  {slug:22s} — {d['title']} ({len(d['scenes'])} scenes)")
    print("\nLive (worldcup26.ir): --standings A | --preview today|tomorrow")


if __name__ == "__main__":
    main()
