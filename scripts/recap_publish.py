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
from football_prediction_shorts import compute_ledger, FLAG  # noqa: E402

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


_FLAG_URI_CACHE: dict[str, str] = {}


def _flag_uri(code):
    """Download a flag and inline it as a base64 data URI.

    The frame renderer loads the panel with waitUntil=networkidle, so a remote
    <img> can hang the headless browser. Embedding the bytes removes all
    browser-side network for flags.
    """
    if code in _FLAG_URI_CACHE:
        return _FLAG_URI_CACHE[code]
    import base64
    import urllib.request
    try:
        req = urllib.request.Request(f"https://flagcdn.com/w160/{code}.png",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            uri = "data:image/png;base64," + base64.b64encode(r.read()).decode()
    except Exception:  # noqa: BLE001
        uri = ""
    _FLAG_URI_CACHE[code] = uri
    return uri


def _flag_img(team_name):
    """Real flag (base64-embedded) for the scoreboard, or '' if unavailable."""
    code = FLAG.get(team_name, "")
    if not code:
        return ""
    uri = _flag_uri(code)
    if not uri:
        return ""
    return (f'<img src="{uri}" '
            'style="width:150px;height:auto;border-radius:12px;'
            'box-shadow:0 10px 24px rgba(8,42,96,.20);margin:0 auto 16px;display:block">')


def _outcome_label(outcome, h, a):
    return {"home": f"{h} to win", "away": f"{a} to win", "draw": "a draw"}.get(outcome, "")


def _prediction(mid, db_path):
    """The model's own pre-match call + grade for this match (or None).

    Read-only from the IMMUTABLE predictions/prediction_results tables — never
    backfilled. Returns {"predicted_outcome", "correct"} for the latest
    prediction on this match that has been graded.
    """
    from pitch_agent.db import get_connection
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT p.predicted_outcome AS predicted_outcome, pr.correct AS correct "
            "FROM predictions p JOIN prediction_results pr ON pr.prediction_id = p.id "
            "WHERE p.match_id = ? ORDER BY p.id DESC LIMIT 1", (str(mid),)).fetchone()
    finally:
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

    # ── Scene 1 — full-time scoreboard with flags + group badge ──
    scoreboard = (
        '<div class="scoreboard">'
        f'<div class="team">{_flag_img(h)}<div class="name">{h}</div></div>'
        f'<div class="score">{hs} <span class="dash">-</span> {as_}</div>'
        f'<div class="team">{_flag_img(a)}<div class="name">{a}</div></div></div>'
        f'<div style="text-align:center"><span class="ft-badge">FULL TIME{" · " + grp if grp else ""}</span></div>'
    )
    dialogue = [("host", f"Full time at the World Cup. {h} {hs}, {a} {as_}. {verdict}.")]
    scenes = [{"segments": (0, 0), "title": "FULL TIME",
               "caption": f"How {h} vs {a} unfolded", "rows": scoreboard,
               "stat": "", "sfx": [(0.5, "ding")]}]
    idx = 1  # next free dialogue segment / scene index

    # ── Scene 2 — goal timeline (needs per-match minutes from content/recaps/<id>.json;
    #    the free API tier exposes scorers/counts but not minutes or cards) ──
    if goals:
        dialogue.append(("analyst",
                         "Here's how the goals went in. " +
                         ", ".join(f"{g['min']} minutes, {g['scorer']}" for g in goals[:5]) + "."))
        scenes.append({"segments": (idx, idx), "title": "The Goals", "caption": "",
                       "rows": _goal_rows(goals),
                       "stat": extra.get("stat", ""), "sfx": [(1.0, "ding")]})
        idx += 1

    # ── Scene 3 — the model's call vs the result + running ledger (the
    #    self-grading loop; real data only, never backfilled) ──
    pred = _prediction(mid, db_path)
    if pred and pred.get("predicted_outcome") and pred.get("correct") is not None:
        pred_label = _outcome_label(pred["predicted_outcome"], h, a)
        ok = bool(pred["correct"])
        result_label = f"{winner} won" if winner else "It finished level"
        rows = (
            '<div class="timeline">'
            '<div class="goal"><span class="min">CALL</span>'
            f'<span class="scorer">{pred_label}<span class="who">  the model\'s pick</span></span></div>'
            f'<div class="goal{"" if ok else " og"}"><span class="min">{"✓" if ok else "✗"}</span>'
            f'<span class="scorer">{result_label}<span class="who">  full-time result</span></span></div>'
            '</div>'
        )
        dialogue.append(("analyst",
                         (f"And the model called it. We backed {pred_label}, and that's exactly how it finished."
                          if ok else
                          f"The model backed {pred_label}. It didn't land this time — and that goes on the record too.")))
        led = compute_ledger()
        if led:
            wins, losses = led["correct"], led["total"] - led["correct"]
            dialogue.append(("host",
                             f"That puts our record at {wins} and {losses}, "
                             f"{led['pct']} percent across the tournament."))
            scenes.append({"segments": (idx, idx + 1), "title": "THE MODEL'S CALL",
                           "caption": "AI prediction vs the real result", "rows": rows,
                           "stat": f"Model record now {wins}-{losses} · {led['pct']}%",
                           "sfx": [(0.4, "ding")]})
            idx += 2
        else:
            scenes.append({"segments": (idx, idx), "title": "THE MODEL'S CALL",
                           "caption": "AI prediction vs the real result", "rows": rows,
                           "stat": "", "sfx": [(0.4, "ding")]})
            idx += 1

    # ── Final scene — CTA tied to the self-grading loop ──
    dialogue.append(("host",
                     "We grade every single call, win or lose. "
                     "Follow to see if the model gets the next one right."))
    scenes.append({"segments": (idx, idx), "title": "EVERY CALL, GRADED",
                   "caption": "Daily World Cup predictions & recaps",
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
    from worldcup_thumbnail import generate_thumbnail
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
    thumb = generate_thumbnail(
        video.parent / f"{mid}_thumb.jpg",
        title=f"{h} {hs}-{as_} {a}",
        kind="MATCH RECAP",
    )
    sys.argv = ["yt", "upload", "--video", str(video), "--title", title[:99],
                "--description", desc, "--privacy", "public",
                "--tags", "WorldCup2026,WorldCup,football,soccer,FIFAWorldCup,AIpredictions,recap",
                "--category-id", "17", "--thumbnail", str(thumb)]
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
