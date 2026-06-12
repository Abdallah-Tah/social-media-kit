#!/usr/bin/env python3
"""Tier-1 World Cup Shorts generator — 100% original branded graphics.

Renders a deck of Build With Abdallah branded cards into a vertical 1080x1920
MP4 with an edge-tts voiceover. Same Playwright + ffmpeg engine as the Shorts
Visual Agent.

CONTENT SAFETY (enforced by design):
  * 100% original branded graphics — text + data cards only.
  * NO match footage, NO downloaded YouTube/TikTok clips, NO FIFA footage,
    NO reposted highlights → nothing to trigger Content ID.
  * NO betting / gambling / sportsbook / odds / wagering language.
  * Positioned as independent football analytics from Build With Abdallah,
    not affiliated with FIFA or any tournament organiser.

Run:   /usr/bin/python3 scripts/worldcup_short.py --standings A
List:  /usr/bin/python3 scripts/worldcup_short.py --list
Output is review-only — never auto-posted.
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

VOICE = "en-US-AndrewNeural"


def _logo_data_uri() -> str | None:
    """Transparent BWA logo as a base64 data-URI (white bg flood-filled away)."""
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
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


_LOGO_URI = _logo_data_uri()
WATERMARK = (f'<img class="wm-img" src="{_LOGO_URI}">' if _LOGO_URI
             else '<span class="wm-text">BWA</span>')
LOGO_IMG = (f'<img class="logo-mark" src="{_LOGO_URI}">' if _LOGO_URI
            else '<div class="logo-fallback">A</div>')


def _flag_data_uri(url: str) -> str:
    """Download a flagcdn flag (w320 for crispness) and return a data-URI."""
    import requests
    big = url.replace("/w80/", "/w320/")
    r = requests.get(big, timeout=15)
    r.raise_for_status()
    return "data:image/png;base64," + base64.b64encode(r.content).decode()


def _load_secrets_env() -> None:
    for f in (ROOT / "config" / "secrets.env",
              Path.home() / ".config" / "social-media-kit" / "secrets.env"):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                import os
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


# Pitch Agent model ratings (Elo-like, our own scale — not official rankings).
# Unknown teams default to 1700. Tune freely as the tournament unfolds.
TEAM_RATINGS = {
    "Argentina": 2100, "Spain": 2080, "France": 2060, "England": 2040,
    "Brazil": 2010, "Portugal": 2000, "Netherlands": 1980, "Belgium": 1960,
    "Germany": 1950, "Croatia": 1930, "Morocco": 1920, "Italy": 1910,
    "Colombia": 1900, "Uruguay": 1890, "USA": 1870, "United States": 1870,
    "Mexico": 1860, "Senegal": 1850, "Japan": 1840, "Switzerland": 1830,
    "Denmark": 1820, "Iran": 1810, "South Korea": 1800, "Ecuador": 1800,
    "Austria": 1790, "Australia": 1760, "Norway": 1750, "Turkey": 1750,
    "Canada": 1740, "Czech Republic": 1700, "Bosnia-H.": 1700, "Panama": 1700,
    "Egypt": 1700, "Algeria": 1690, "Scotland": 1680, "Paraguay": 1670,
    "Tunisia": 1660, "Ivory Coast": 1650, "South Africa": 1640, "Ghana": 1640,
    "Qatar": 1620, "Uzbekistan": 1600, "Saudi Arabia": 1590, "Jordan": 1560,
    "New Zealand": 1530, "Cape Verde": 1520, "Curacao": 1500, "Curaçao": 1500,
    "Haiti": 1480,
}


def _ratings_prediction(home: str, away: str, group: str) -> dict:
    """Deterministic Elo-style prediction from TEAM_RATINGS (no API needed)."""
    ra, rb = TEAM_RATINGS.get(home, 1700), TEAM_RATINGS.get(away, 1700)
    e = 1.0 / (1.0 + 10 ** (-(ra - rb) / 400.0))          # home win expectancy
    draw = max(0.12, 0.30 - abs(e - 0.5) * 0.40)
    hp = round(e * (1 - draw) * 100)
    dp = round(draw * 100)
    ap = 100 - hp - dp
    diff = abs(ra - rb)
    if diff < 60:
        score, winner = "1-1", (home if ra >= rb else away)
    elif diff < 150:
        score = "2-1"
        winner = home if ra > rb else away
    elif diff < 300:
        score = "2-0"
        winner = home if ra > rb else away
    else:
        score = "3-0"
        winner = home if ra > rb else away
    if score != "1-1" and winner == away:
        score = score[::-1]  # mirror for an away win (e.g. 2-1 → 1-2)
    fav, dog = (home, away) if ra >= rb else (away, home)
    return {
        "winner": winner, "score": score,
        "home_prob": hp, "draw_prob": dp, "away_prob": ap,
        "stats": [
            f"{fav} rate higher in our model",
            f"{dog} need a fast start to upset it",
            f"First points in Group {group} on the line",
        ],
        "vo": (f"Our ratings model makes {fav} the favourite at {max(hp, ap)} percent, "
               f"with the draw at {dp}. Most likely scoreline: {score.replace('-', ' ')}."
               if score != "1-1" else
               f"Our ratings model has this nearly level — {hp} percent {home}, "
               f"{ap} percent {away}. A draw is firmly in play."),
    }


def _predict_match(home: str, away: str, group: str) -> dict:
    """Ask Claude for an analysis-based prediction (winner, score, probs, stats).

    Falls back to a neutral too-close-to-call prediction without a key.
    Analytics language only — no betting/odds framing.
    """
    import os
    import requests as rq
    _load_secrets_env()
    key = os.environ.get("BWA_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    fallback = _ratings_prediction(home, away, group)
    if not key:
        return fallback
    try:
        resp = rq.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": key, "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={
            "model": "claude-3-5-haiku-latest", "max_tokens": 500,
            "messages": [{"role": "user", "content":
                f"You are an independent football analytics model. Predict {home} vs {away} "
                f"(2026 World Cup, Group {group}). Reply ONLY JSON: "
                '{"winner": str, "score": "N-N", "home_prob": int, "draw_prob": int, '
                '"away_prob": int (sum 100), "stats": [3 short factual analysis bullets, '
                'max 8 words each], "vo": "2-sentence spoken summary, analytics tone, '
                'no betting language"}'}],
        }, timeout=60)
        txt = resp.json()["content"][0]["text"].strip()
        txt = txt[txt.index("{"):txt.rindex("}") + 1]
        pred = json.loads(txt)
        for k in ("winner", "score", "home_prob", "draw_prob", "away_prob", "stats", "vo"):
            if k not in pred:
                return fallback
        return pred
    except Exception as e:
        print(f"⚠️  prediction model unavailable ({e}); using neutral fallback")
        return fallback


# ── Content decks ────────────────────────────────────────────────────────
# Each deck: {"slug", "title", "scenes": [...], "voiceover": "para per scene"}.
# Scene variable names match the shorts templates exactly:
#   title_card.html  -> title, caption, main_idea, progress, watermark
#   code_card.html   -> title, caption, code, takeaway, progress, watermark
#   cta_card.html    -> title, caption, cta, url, progress, watermark
DECKS = {
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

    for key in ("title", "caption", "main_idea", "takeaway", "cta", "url", "progress", "subtitle"):
        if key in scene:
            html_src = html_src.replace("{{" + key + "}}", scene[key])
    html_src = html_src.replace("{{watermark}}", WATERMARK)
    if "subtitle" in scene:
        html_src = html_src.replace("{{subtitle_meta}}", _meta_html(scene["subtitle"]))
    # pitch_card.html: header logo + raw HTML content slot.
    html_src = html_src.replace("{{logo}}", LOGO_IMG)
    if "content" in scene:
        html_src = html_src.replace("{{content}}", scene["content"])

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
        # -framerate 30 matches zoompan's 30fps output so durations are kept.
        inputs += ["-framerate", "30", "-loop", "1", "-t", f"{dur:.2f}", "-i", str(png)]

    # Per-scene: scale to frame, then a slow ken-burns zoom so cards aren't
    # static slides. Then crossfade the moving scenes together.
    kb = ("zoompan=z='min(zoom+0.0006,1.10)':d=1:"
          "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30")
    fc = [f"[{i}:v]{scale_vf},{kb}[s{i}]" for i in range(len(scene_paths))]

    if len(scene_paths) == 1:
        fc.append("[s0]null[vout]")
    else:
        cum, prev = 0.0, "[s0]"
        for i in range(1, len(scene_paths)):
            cum += scene_paths[i - 1][1] - xfade
            lbl = f"[v{i}]" if i < len(scene_paths) - 1 else "[vout]"
            fc.append(f"{prev}[s{i}]xfade=transition=fade:duration={xfade}:offset={cum:.3f}{lbl}")
            prev = lbl

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



def _meta_html(subtitle: str) -> str:
    """Split a '·'-separated subtitle into meta spans with blue dot separators."""
    parts = [s.strip() for s in (subtitle or "").split("·") if s.strip()]
    return '<span class="mdot"></span>'.join(f"<span>{html.escape(s)}</span>" for s in parts)


# ── Feed cards (horizontal 1200x628, same pitch-card brand family) ───────

def render_feed_card(title: str, subtitle: str, content_html: str, out_png: Path,
                      template: str = "pitch_card_wide.html") -> Path:
    """Render a LinkedIn/Facebook feed card from an HTML template."""
    html_src = (TEMPLATES_DIR / template).read_text()
    html_src = (html_src.replace("{{title}}", title)
                        .replace("{{subtitle_meta}}", _meta_html(subtitle))
                        .replace("{{content}}", content_html)
                        .replace("{{logo}}", LOGO_IMG))
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_png.with_suffix(".html")
    html_path.write_text(html_src)
    r = subprocess.run(
        ["node", str(SCRIPTS_DIR / "render_card.mjs"), str(html_path), str(out_png), "1200", "628"],
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0 or not out_png.exists():
        raise RuntimeError(f"feed card render failed: {r.stderr[-300:]}")
    return out_png


def feed_card_preview(when: str = "today", out_png: str | Path | None = None) -> Path:
    """Matchday Pack feed card: one row per match — teams, group, model call,
    win probability, kickoff."""
    import worldcup26_data as wc
    import datetime as dt
    day = dt.date.today() if when == "today" else dt.date.today() + dt.timedelta(days=1)
    matches = sorted(wc.today_matches(day), key=lambda x: x["date"])
    if not matches:
        raise SystemExit(f"No matches found for {day}")
    t = wc.teams()
    rows = []
    for m in matches[:5]:
        pred = _predict_match(m["home_team"], m["away_team"], m["group"])
        fav_prob = max(pred["home_prob"], pred["away_prob"])
        kickoff = m["date"].split(" ")[-1] if " " in m["date"] else ""
        try:
            hflag = f'<img class="flag" src="{_flag_data_uri(t[m["home_id"]]["flag"])}">'
            aflag = f'<img class="flag" src="{_flag_data_uri(t[m["away_id"]]["flag"])}">'
        except Exception:
            hflag = aflag = ""
        rows.append(
            f'<div class="row"><span class="dot"></span>{hflag}'
            f'<span class="label">{html.escape(m["home_team"])} vs {html.escape(m["away_team"])}</span>{aflag}'
            f'<span class="grp">Group {m["group"]}</span>'
            f'<span class="tag">Model: {pred["score"].replace("-", "–")} {html.escape(pred["winner"])}</span>'
            f'<span class="pct">{fav_prob}%</span>'
            f'<span class="meta2">{kickoff}</span></div>'
        )
    title = ("World Cup 2026 Kicks Off Today"
             if when == "today" and str(matches[0]["matchday"]) == "1"
             else f"Matchday {matches[0]['matchday']} Preview")
    out = Path(out_png) if out_png else SHORTS_DIR.parent / "feed" / f"wc-preview-{day.isoformat()}.png"
    return render_feed_card(
        title,
        f"{day.strftime('%B %d, %Y')} · model call + win probability for every game",
        f'<div class="rows">{"".join(rows)}</div>',
        out,
    )


def feed_card_standings(group_letter: str, out_png: str | Path | None = None) -> Path:
    """Group standings feed card in the same brand family."""
    import worldcup26_data as wc
    blocks = wc.standings(group_letter)
    if not blocks:
        raise SystemExit(f"No standings for group {group_letter}")
    block = blocks[0]
    rows = "".join(
        f'<div class="row"><span class="dot"></span>'
        f'<span class="label">{r["position"]}. {html.escape(r["team"])}</span>'
        f'<span class="tag">{r["points"]} pts</span>'
        f'<span class="grp">P{r["played"]}</span>'
        f'<span class="meta2">GD {r["goal_difference"]:+d}</span></div>'
        for r in block["table"]
    )
    out = Path(out_png) if out_png else SHORTS_DIR.parent / "feed" / f"wc-standings-{group_letter.lower()}.png"
    return render_feed_card(
        f"{block['group']} Standings",
        "2026 World Cup · latest table",
        f'<div class="rows">{rows}</div>',
        out,
    )


def feed_card_match_recap(matches: list[dict], model_record: str = "",
                            out_png: str | Path | None = None) -> Path:
    """Match Recap feed card in the same light-theme brand family.

    Each match dict has: label, context, prediction (str or None),
    key_factor (str), no_pred (bool).
    """
    rows_html = []
    for m in matches:
        # Main score row
        ctx = html.escape(m.get("context", ""))
        ctx_html = f'<span class="meta2">{ctx}</span>' if ctx else ''
        rows_html.append(
            f'<div class="row"><span class="dot"></span>'
            f'<span class="label">{html.escape(m["label"])}</span>'
            f'{ctx_html}</div>'
        )
        # Prediction or no-prediction sub-row
        if m.get("prediction"):
            pred_html = html.escape(m["prediction"])
            # Replace ✓/✗ with styled spans (AFTER escaping so entities stay)
            pred_html = pred_html.replace("\u2713", '<span class="correct">\u2713</span>')
            pred_html = pred_html.replace("\u2717", '<span class="wrong">\u2717</span>')
            kf = m.get("key_factor", "")
            kf_html = f'<div class="key-factor">{html.escape(kf)}</div>' if kf else ''
            rows_html.append(
                f'<div class="pred-row"><div class="pred-text">{pred_html}</div>{kf_html}</div>'
            )
        elif m.get("no_pred"):
            rows_html.append(
                '<div class="no-pred-row"><span class="no-pred-text">'
                '(No prediction on record)</span></div>'
            )

    # Model record bar
    is_no_data = '0 journaled' in (model_record or '') or not model_record
    rec_cls = 'record-bar no-data' if is_no_data else 'record-bar'
    rows_html.append(f'<div class="{rec_cls}">{html.escape(model_record)}</div>')

    import datetime as dt
    day = dt.date.today()
    out = Path(out_png) if out_png else SHORTS_DIR.parent / "feed" / f"wc-recap-{day.isoformat()}.png"
    return render_feed_card(
        "Match Recap",
        f"{day.strftime('%B %d, %Y')} \u2022 post-match results & model accountability",
        f'<div class="rows">{chr(10).join(rows_html)}</div>',
        out,
        template="match_recap_wide.html",
    )


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
    sub = "Latest table" if played else "Group preview · kicks off soon"
    table_html = '<div class="rows">' + "".join(
        f'<div class="row"><span class="dot"></span>'
        f'<span class="label">{r["position"]}. {html.escape(r["team"])}</span>'
        f'<span class="tag">{r["points"]} pts</span>'
        f'<span class="meta2">P{r["played"]} · GD {r["goal_difference"]:+d}</span></div>'
        for r in rows
    ) + ('<div class="row" style="border-bottom:none"><span class="dot"></span>'
         '<span class="label">Follow for every group, every day</span></div></div>')
    scenes = [
        {"template": "pitch_card.html", "title": f"{block['group']} Standings",
         "subtitle": f"2026 World Cup · {sub}", "content": table_html,
         "progress": "1/1", "duration_seconds": 14},
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
    matches = sorted(matches, key=lambda x: x["date"])[:4]
    t = wc.teams()
    scenes, vo_parts = [], []
    n = len(matches)
    for i, m in enumerate(matches, 1):
        try:
            hflag = _flag_data_uri(t[m["home_id"]]["flag"])
            aflag = _flag_data_uri(t[m["away_id"]]["flag"])
        except Exception:
            hflag = aflag = ""
        pred = _predict_match(m["home_team"], m["away_team"], m["group"])
        fav_prob = max(pred["home_prob"], pred["away_prob"])
        kickoff = m["date"].split(" ")[-1] if " " in m["date"] else ""
        content = (
            f'<div class="vs-wrap">'
            f'<div class="vs-team"><img src="{hflag}"><div class="nm">{m["home_team"]}</div></div>'
            f'<div class="vs-mid">VS</div>'
            f'<div class="vs-team"><img src="{aflag}"><div class="nm">{m["away_team"]}</div></div>'
            f'</div>'
            f'<div class="rows" style="margin-top:54px">'
            f'<div class="row"><span class="dot"></span><span class="label">Group {m["group"]} · Matchday {m["matchday"]}</span>'
            f'<span class="meta2">{kickoff}</span></div>'
            f'<div class="row"><span class="dot"></span><span class="label">Model call</span>'
            f'<span class="tag">{pred["score"].replace("-", "–")} · {pred["winner"]}</span></div>'
            f'<div class="row"><span class="dot"></span><span class="label">{pred["winner"]} win probability</span>'
            f'<span class="tag">{fav_prob}%</span></div>'
            f'<div class="row" style="border-bottom:none"><span class="dot"></span>'
            f'<span class="label">{html.escape(pred["stats"][0])}</span></div>'
            f'</div>'
        )
        scenes.append({"template": "pitch_card.html",
                       "title": f"{m['home_team']} vs {m['away_team']}",
                       "subtitle": f"{label}'s matches · {day.strftime('%b %d')} · {i} of {n}",
                       "content": content, "progress": f"{i}/{n}",
                       "duration_seconds": 10})
        vo_parts.append(f"{m['home_team']} against {m['away_team']}, Group {m['group']}. "
                        f"Our model says {pred['score'].replace('-', ' ')}, "
                        f"{pred['winner']} at {fav_prob} percent.")
    vo = (f"{label} at the 2026 World Cup — {n} match{'es' if n != 1 else ''}, "
          f"with our model's call for each. " + " ".join(vo_parts) +
          " Agree with the calls? Drop yours in the comments, and follow "
          "Build With Abdallah for every matchday.")
    return {"title": f"{label}'s Matches + Predictions", "scenes": scenes, "voiceover": vo}, \
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
    t = wc.teams()
    try:
        hflag = _flag_data_uri(t[m["home_id"]]["flag"])
        aflag = _flag_data_uri(t[m["away_id"]]["flag"])
    except Exception:
        hflag = aflag = ""
    scorer_rows = "".join(
        f'<div class="row"><span class="dot"></span><span class="label">⚽ {html.escape(s)}</span></div>'
        for s in scorers[:5])
    content = (
        f'<div class="vs-wrap" style="margin-top:0">'
        f'<div class="vs-team" style="width:220px"><img src="{hflag}" style="width:200px;height:133px"></div>'
        f'<div class="score-big" style="margin:0;flex:1;white-space:nowrap;font-size:170px">'
        f'{m["home_score"]}–{m["away_score"]}</div>'
        f'<div class="vs-team" style="width:220px"><img src="{aflag}" style="width:200px;height:133px"></div>'
        f'</div>'
        f'<div class="score-label">FULL TIME · GROUP {m["group"]}</div>'
        f'<div class="rows" style="margin-top:56px">'
        f'<div class="row"><span class="dot"></span><span class="label">{m["home_team"]}</span>'
        f'<span class="tag">{m["home_score"]}</span></div>'
        f'<div class="row"><span class="dot"></span><span class="label">{m["away_team"]}</span>'
        f'<span class="tag">{m["away_score"]}</span></div>'
        + scorer_rows +
        f'<div class="row" style="border-bottom:none"><span class="dot"></span>'
        f'<span class="label">{html.escape(result)}</span></div></div>'
    )
    scenes = [
        {"template": "pitch_card.html", "title": f"{m['home_team']} vs {m['away_team']}",
         "subtitle": "Full-time result · 2026 World Cup", "content": content,
         "progress": "FT", "duration_seconds": 14},
    ]
    vo_scorers = (" The goals came from " + ", ".join(scorers[:6]) + "." ) if scorers else ""
    vo = (f"Full time at the World Cup. {m['home_team']} {m['home_score']}, "
          f"{m['away_team']} {m['away_score']}. {result}.{vo_scorers} "
          f"Follow Build With Abdallah for every full-time recap.")
    return {"title": f"Full Time: {score}", "scenes": scenes, "voiceover": vo}, \
        f"recap-{m['id']}"


def deck_prediction(when: str = "today") -> tuple[dict, str]:
    """Prediction deck on the professional pitch card: match-up with flags,
    model prediction (winner + scoreline + win probabilities), stat bullets."""
    import worldcup26_data as wc
    import datetime as dt
    day = dt.date.today() if when == "today" else dt.date.today() + dt.timedelta(days=1)
    matches = sorted(wc.today_matches(day), key=lambda x: x["date"])
    if not matches:
        raise SystemExit(f"No matches found for {day}")
    m = matches[0]
    tie = f"{m['home_team']} vs {m['away_team']}"
    t = wc.teams()
    try:
        hflag = _flag_data_uri(t[m["home_id"]]["flag"])
        aflag = _flag_data_uri(t[m["away_id"]]["flag"])
    except Exception:
        hflag = aflag = ""
    pred = _predict_match(m["home_team"], m["away_team"], m["group"])

    matchup_html = (
        f'<div class="vs-wrap">'
        f'<div class="vs-team"><img src="{hflag}"><div class="nm">{m["home_team"]}</div></div>'
        f'<div class="vs-mid">VS</div>'
        f'<div class="vs-team"><img src="{aflag}"><div class="nm">{m["away_team"]}</div></div>'
        f'</div>'
        f'<div class="rows" style="margin-top:60px">'
        f'<div class="row"><span class="dot"></span><span class="label">Group {m["group"]} · Matchday {m["matchday"]}</span>'
        f'<span class="meta2">{day.strftime("%b %d")}</span></div>'
        + "".join(f'<div class="row"><span class="dot"></span><span class="label">{html.escape(s)}</span></div>'
                  for s in pred["stats"][:3])
        + '</div>'
    )
    pred_html = (
        f'<div class="vs-wrap" style="margin-top:0">'
        f'<div class="vs-team" style="width:220px"><img src="{hflag}" style="width:200px;height:133px"></div>'
        f'<div class="score-big" style="margin:0;flex:1;white-space:nowrap;font-size:170px">{pred["score"].replace("-", "–")}</div>'
        f'<div class="vs-team" style="width:220px"><img src="{aflag}" style="width:200px;height:133px"></div>'
        f'</div>'
        f'<div class="score-label">OUR MODEL\'S CALL</div>'
        f'<div class="bars">'
        f'<div class="bar-row"><span class="who">{m["home_team"][:14]}</span>'
        f'<span class="track"><span class="fill" style="width:{pred["home_prob"]}%;display:block"></span></span>'
        f'<span class="pct">{pred["home_prob"]}%</span></div>'
        f'<div class="bar-row"><span class="who">Draw</span>'
        f'<span class="track"><span class="fill" style="width:{pred["draw_prob"]}%;display:block;opacity:.55"></span></span>'
        f'<span class="pct">{pred["draw_prob"]}%</span></div>'
        f'<div class="bar-row"><span class="who">{m["away_team"][:14]}</span>'
        f'<span class="track"><span class="fill" style="width:{pred["away_prob"]}%;display:block"></span></span>'
        f'<span class="pct">{pred["away_prob"]}%</span></div>'
        f'</div>'
        f'<div class="rows" style="margin-top:64px"><div class="row" style="border-bottom:none">'
        f'<span class="dot"></span><span class="label">Agree? Drop your scoreline in the comments</span></div></div>'
    )
    scenes = [
        {"template": "pitch_card.html", "title": "Match Prediction",
         "subtitle": f"{tie} · 2026 World Cup", "content": matchup_html,
         "progress": "1/2", "duration_seconds": 9},
        {"template": "pitch_card.html", "title": tie,
         "subtitle": f"Predicted result · {pred['winner']} edge it" if pred["score"] != "1-1"
                     else f"Predicted result · too close to call",
         "content": pred_html, "progress": "2/2", "duration_seconds": 12},
    ]
    vo = (f"Match prediction. {m['home_team']} against {m['away_team']}, Group {m['group']}, "
          f"at the 2026 World Cup. {pred['vo']} Our predicted scoreline: "
          f"{pred['score'].replace('-', ' ')}. Agree? Drop yours in the comments, and follow "
          f"Build With Abdallah for every matchday.")
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
    ap.add_argument("--feed-preview", choices=["today", "tomorrow"],
                    help="Render a 1200x628 matchday feed card (LinkedIn/FB)")
    ap.add_argument("--feed-standings", metavar="GROUP",
                    help="Render a 1200x628 standings feed card (LinkedIn/FB)")
    ap.add_argument("--list", action="store_true", help="List static decks")
    args = ap.parse_args()

    if args.feed_preview:
        print(f"🖼  {feed_card_preview(args.feed_preview)}"); return
    if args.feed_standings:
        print(f"🖼  {feed_card_standings(args.feed_standings)}"); return
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
