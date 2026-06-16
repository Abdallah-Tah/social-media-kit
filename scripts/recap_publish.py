#!/usr/bin/env python3
"""Auto match-recap → YouTube. Builds an animated recap for the most recent
finished match and (optionally) publishes it.

Goal events (scorers + minutes) are read from
``content/recaps/<match_id>.json`` when present:
    {"goals": [{"min": 7, "scorer": "Bobadilla", "team": "PAR", "og": true}, ...],
     "stat": "Balogun: 2 goals"}
When absent, a clean scoreline recap is built (no goal-by-goal).

  /usr/bin/python3 scripts/recap_publish.py --latest [--publish]
  /usr/bin/python3 scripts/recap_publish.py --match 537345 --publish
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

KIT = Path(os.path.expanduser("~/social-media-kit"))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402
load_env()
from worldcup_atmosphere_short import build_atmosphere_short  # noqa: E402

RECAP_DIR = KIT / "content" / "recaps"
RECAP_DIR.mkdir(parents=True, exist_ok=True)
LOG = KIT / "content" / "recap_posts.json"


def _posted(mid):
    try:
        return mid in json.loads(LOG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def _mark(mid):
    try:
        seen = json.loads(LOG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        seen = []
    if mid not in seen:
        seen.append(mid)
        LOG.write_text(json.dumps(seen[-200:]))


def _latest_finished(db_path):
    from pitch_agent.db import get_connection
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT match_id, home_team_name, away_team_name, home_score, away_score, group_name "
        "FROM matches WHERE status='FINISHED' AND home_score IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _goal_rows(goals):
    out = []
    for g in goals:
        og = " og" if g.get("og") else ""
        who = f' <span class="who">({g["team"]})</span>' if g.get("team") and not g.get("og") else (
            ' <span class="who">(own goal)</span>' if g.get("og") else "")
        out.append(f'<div class="goal{og}"><span class="min">{g["min"]}\'</span>'
                   f'<span class="scorer">{g["scorer"]}{who}</span></div>')
    return '<div class="timeline">' + "".join(out) + "</div>"


def build_recap(match, db_path):
    mid = match["match_id"]
    h, a = match["home_team_name"], match["away_team_name"]
    hs, as_ = match["home_score"], match["away_score"]
    grp = match.get("group_name", "") or ""

    extra = {}
    ev_file = RECAP_DIR / f"{mid}.json"
    if ev_file.exists():
        extra = json.loads(ev_file.read_text())
    goals = extra.get("goals", [])

    winner = h if hs > as_ else (a if as_ > hs else None)
    verdict = f"{winner} take it" if winner else "Honours even"

    scoreboard = (
        '<div class="scoreboard">'
        f'<div class="team"><div class="name">{h}</div></div>'
        f'<div class="score">{hs} <span class="dash">-</span> {as_}</div>'
        f'<div class="team"><div class="name">{a}</div></div></div>'
        f'<div style="text-align:center"><span class="ft-badge">FULL TIME{" · " + grp if grp else ""}</span></div>'
    )

    # Dialogue: 1-line intro, goals (if any), verdict + CTA.
    dialogue = [("host", f"Full time. {h} {hs}, {a} {as_}. {verdict}.")]
    scenes = [{"segments": (0, 0), "title": "FULL TIME",
               "caption": f"How {h} vs {a} unfolded", "rows": scoreboard,
               "stat": "", "sfx": [(0.5, "ding")]}]

    if goals:
        dialogue.append(("analyst",
                         "Here's how the goals went in. " +
                         ", ".join(f"{g['min']} minutes, {g['scorer']}" for g in goals[:5]) + "."))
        scenes.append({"segments": (1, 1), "title": "The Goals", "caption": "",
                       "rows": _goal_rows(goals),
                       "stat": extra.get("stat", ""), "sfx": [(1.0, "ding")]})
        cta_seg = 2
    else:
        cta_seg = 1

    dialogue.append(("host",
                     f"{winner or 'Both sides'} will be happy with that. "
                     "What did you make of it? Drop it in the comments."))
    scenes.append({"segments": (cta_seg, cta_seg), "title": "FULL TIME",
                   "caption": "Daily World Cup recaps — every result, every day.",
                   "rows": "",
                   "stat": "▶ buildwithabdallah.com/newsletter"})

    return build_atmosphere_short(
        f"recap-{mid}", dialogue, scenes,
        f"{h} {hs}-{as_} {a} — World Cup 2026 Recap",
        atmosphere_query="football stadium crowd night celebration",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--db", default=str(KIT / "pitch_agent.db"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.match:
        from pitch_agent.db import get_connection
        conn = get_connection(args.db)
        row = conn.execute(
            "SELECT match_id, home_team_name, away_team_name, home_score, away_score, group_name "
            "FROM matches WHERE match_id=?", (args.match,)).fetchone()
        conn.close()
        match = dict(row) if row else None
    else:
        match = _latest_finished(args.db)

    if not match:
        print("No finished match found", file=sys.stderr)
        return 1
    mid = match["match_id"]
    print(f"→ Recap: {match['home_team_name']} {match['home_score']}-{match['away_score']} {match['away_team_name']}")

    if args.publish and not args.force and _posted(mid):
        print(f"⏭  Already published recap for {mid} — skipping.")
        return 0

    video = build_recap(match, args.db)
    print(f"✅ {video}")

    if not args.publish:
        print("Built only (use --publish to upload to YouTube).")
        return 0

    import youtube_shorts_publisher as YT
    h, a = match["home_team_name"], match["away_team_name"]
    hs, as_ = match["home_score"], match["away_score"]
    # Proven high-view title format (Mexico vs South Africa — AI Prediction
    # 🏆 World Cup 2026 → 564 views). Keep the matchup + "AI Prediction" +
    # the trending "World Cup 2026" tag; no score in the title (curiosity).
    title = f"{h} vs {a} — AI Prediction 🏆 World Cup 2026"
    desc = (f"{h} vs {a} — The Pitch Agent's AI prediction vs the real result.\n\n"
            "Our AI predicts every World Cup 2026 match and grades itself — "
            "daily picks, recaps, and the running record.\n\n"
            "#WorldCup2026 #WorldCup #Football #Soccer #FIFAWorldCup "
            "#AIPredictions #footballpredictions #Shorts\n\n"
            "Independent football content. Not affiliated with FIFA.\n"
            "https://buildwithabdallah.com/newsletter")
    sys.argv = ["yt", "upload", "--video", str(video), "--title", title[:99],
                "--description", desc, "--privacy", "public",
                "--tags", "WorldCup2026,WorldCup,football,soccer,FIFAWorldCup,AIpredictions,recap",
                "--category-id", "17"]
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        YT.main()
    out = buf.getvalue()
    print(out, end="")
    _mark(mid)

    # Cross-post the recap to Facebook + LinkedIn with the YouTube link.
    import re as _re
    m = _re.search(r"https://www\.youtube\.com/shorts/[\w-]+", out)
    yt_url = m.group(0) if m else ""
    try:
        from football_crosspost import crosspost
        verdict = f"{h} take it" if hs > as_ else (f"{a} take it" if as_ > hs else "Honours even")
        caption = (f"Full time: {h} {hs}-{as_} {a}. {verdict}.\n"
                   "Our AI's World Cup recap — every result, every day.")
        crosspost(caption, youtube_url=yt_url, title=f"{h} {hs}-{as_} {a} recap")
    except Exception as exc:  # noqa: BLE001
        print(f"[recap] crosspost failed (non-fatal): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
