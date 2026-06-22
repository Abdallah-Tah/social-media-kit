#!/usr/bin/env python3
"""Daily "Today at the World Cup" image-rich Short — auto-published.

Gathers today's matches + the model's picks + yesterday's graded results, pulls
copyright-safe imagery (flags, Pexels atmosphere, free Wikimedia photos, AI
fallback), renders the full-screen Remotion "DailySlate" composition with the
Jarnathan voice, and publishes to YouTube + Facebook + LinkedIn. Deduped by date.

  /usr/bin/python3 scripts/daily_wc_short.py --dry-run --no-telegram
  /usr/bin/python3 scripts/daily_wc_short.py --privacy unlisted --no-telegram
  /usr/bin/python3 scripts/daily_wc_short.py --privacy public
"""
from __future__ import annotations

import argparse
import datetime as dt
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
PUBLIC = REMOTION / "public"
OUT_DIR = KIT / "content" / "assets" / "shorts" / "daily_slate"
POSTED = KIT / "content" / "daily_slate_posted.json"
NODE = "/home/linuxbrew/.linuxbrew/bin/node" if Path("/home/linuxbrew/.linuxbrew/bin/node").exists() else "node"


def _posted() -> set:
    try:
        return set(json.loads(POSTED.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _mark(day: str) -> None:
    seen = _posted(); seen.add(day)
    POSTED.write_text(json.dumps(sorted(seen)[-90:]))


def _ny_date(iso: str, tz) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(tz).date()
    except (ValueError, TypeError):
        return None


def _flag_for(team: str, wc_images) -> str | None:
    from football_prediction_shorts import FLAG
    code = FLAG.get(team)
    if not code:
        return None
    name = f"flag_{code}.png"
    return name if wc_images.flag(team, name) else None


def _lean(fx) -> tuple[str, dict | None]:
    """Short lean line + raw predict() dict for a fixture."""
    import football_prediction_shorts as FP
    data = FP.predict(fx)
    if not data:
        return "", None
    out = data["outcome"]
    if out == "draw":
        return "Lean: Draw — too even to split", data
    winner = data["home"] if out == "home" else data["away"]
    return f"Lean: {winner} {data['scoreline']}", data


def gather(wc_images) -> dict:
    from pitch_agent.fixtures import get_upcoming_fixtures, get_finished_matches
    from pitch_agent.content import _upcoming_fixtures, _build_match_recap_data, NY_TZ
    from pitch_agent.config import PitchAgentConfig

    cfg = PitchAgentConfig.load()
    today = dt.datetime.now(NY_TZ).date()
    yest = today - dt.timedelta(days=1)
    date_label = today.strftime("%B %-d")

    # today's matches
    raw_today = _upcoming_fixtures(get_upcoming_fixtures(cfg.db_path, limit=24), limit=12, today_only=True)
    matches, teams_seen, credits, best = [], {}, [], None
    for fx in raw_today:
        h, a = fx.get("home_team_name"), fx.get("away_team_name")
        hf, af = _flag_for(h, wc_images), _flag_for(a, wc_images)
        if not (hf and af):
            continue
        teams_seen[h] = hf; teams_seen[a] = af
        # kickoff ET
        try:
            ko = dt.datetime.fromisoformat(str(fx.get("date")).replace("Z", "+00:00")).astimezone(NY_TZ)
            time_s = ko.strftime("%-I:%M %p ET")
        except (ValueError, TypeError):
            time_s = ""
        lean, data = _lean(fx)
        matches.append({"home": h, "away": a, "homeFlag": hf, "awayFlag": af, "time": time_s, "lean": lean})
        if data and (best is None or data["lead_prob"] > best[1]):
            best = (fx, data["lead_prob"], data, h, a, hf, af)

    # headline = most confident call of the day
    headline = None
    if best:
        _, _, data, h, a, hf, af = best
        out = data["outcome"]
        if out == "draw":
            score, text = data["scoreline"], "Too even to split — a real draw chance"
        else:
            winner = h if out == "home" else a
            score = f"{h} {data['scoreline']}" if out == "home" else f"{a} {data['scoreline']}"
            text = f"Slight {winner} edge in a close one"
        # one free-licensed photo for the headline backdrop (dimmed) + credit
        img = None
        ph, cr = wc_images.commons_photo(f"{h} national football team", "headline_bg.jpg")
        if not ph:
            ph, cr = wc_images.commons_photo(f"{a} national football team", "headline_bg.jpg")
        if ph:
            img = "headline_bg.jpg"; credits.append(cr)
        headline = {"home": h, "away": a, "homeFlag": hf, "awayFlag": af,
                    "scoreline": score, "text": text, "image": img}

    # yesterday's graded results
    results, model_record = [], ""
    finished = [m for m in get_finished_matches(cfg.db_path, limit=30)
                if _ny_date(m.get("date"), NY_TZ) == yest]
    if finished:
        recap = _build_match_recap_data(finished, cfg.db_path)
        model_record = recap.get("model_record", "")
        for m in recap.get("matches", [])[:4]:
            pred = m.get("prediction", "") or ""
            correct = True if "✓" in pred else False if "✗" in pred else None
            clean = pred.replace("✓", "").replace("✗", "").strip()
            results.append({"label": m.get("label", ""), "prediction": clean, "correct": correct})

    # atmosphere b-roll
    atmo = wc_images.atmosphere("world cup soccer stadium crowd", duration=8.0)
    teams_today = [{"name": n, "flag": f} for n, f in teams_seen.items()]
    return {
        "date": date_label, "teamsToday": teams_today, "results": results,
        "matches": matches, "headline": headline, "modelRecord": model_record,
        "credits": credits, "atmosphere": "atmosphere.mp4" if atmo else None,
    }


def build_durations(props: dict) -> list[int]:
    secs = [5]  # intro
    if props["results"]:
        secs.append(7)
    if props["matches"]:
        secs.append(8)
    if props["headline"]:
        secs.append(6)
    secs.append(5)  # outro
    return secs


def voiceover_script(props: dict) -> str:
    parts = [f"Here is today at the World Cup, {props['date']}."]
    if props["modelRecord"]:
        parts.append(f"First, the model's report card. {props['modelRecord'].replace('Model record:', 'So far,')}.")
    if props["matches"]:
        n = len(props["matches"])
        sample = props["matches"][0]
        parts.append(f"Today we have {n} {'match' if n == 1 else 'matches'} on the slate, "
                     f"including {sample['home']} versus {sample['away']}.")
    if props["headline"]:
        h = props["headline"]
        parts.append(f"The model's call of the day: {h['home']} versus {h['away']}. "
                     f"It leans {h['scoreline']} — {h['text'].lower()}.")
    parts.append("Comment your score predictions, and follow for daily World Cup model calls. "
                 "Independent analytics, not affiliated with FIFA.")
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="render only, no upload")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    args = ap.parse_args()
    load_env()

    import wc_images
    from pitch_agent.content import NY_TZ
    day = dt.datetime.now(NY_TZ).date().isoformat()
    if day in _posted() and not args.dry_run:
        print(f"[daily-wc] already posted today ({day})")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    props = gather(wc_images)
    if not props["matches"] and not props["results"]:
        print("[daily-wc] no matches or results today — skipping")
        return 0

    props["durations"] = build_durations(props)
    props["hasAudio"] = True
    props["audioFile"] = "voiceover.mp3"
    props_path = OUT_DIR / "props.json"
    props_path.write_text(json.dumps(props, indent=2))

    # Jarnathan voiceover
    import reel_generator
    vo = OUT_DIR / "voiceover.mp3"
    rendered = reel_generator.tts(voiceover_script(props), str(vo))
    has_vo = bool(rendered and Path(rendered).exists())
    print(f"[daily-wc] voiceover: {'ElevenLabs ok' if has_vo else 'none'}")

    out = OUT_DIR / f"daily_{day}.mp4"
    cmd = [NODE, str(REMOTION / "render.mjs"), "--id", "DailySlate",
           "--props", str(props_path), "--out", str(out)]
    if has_vo:
        cmd += ["--audio", str(vo)]
    if subprocess.run(cmd, cwd=str(REMOTION)).returncode != 0:
        print("[daily-wc] render failed")
        return 1
    print(f"✅ [daily-wc] {out} ({out.stat().st_size // 1024} KB)")

    if args.dry_run:
        print("[daily-wc] DRY RUN — not uploading.")
        return 0

    title = f"World Cup 2026 Today — Matches & Model Picks ({props['date']}) \U0001F3C6"[:100]
    credit_line = ("\n\nPhotos: " + "; ".join(props["credits"])) if props["credits"] else ""
    desc = ("Today at the World Cup 2026 — today's matches, our independent model's picks, "
            "and yesterday's graded results. Analytics only, not affiliated with FIFA.\n\n"
            "Comment your score predictions. Follow for daily World Cup model calls.\n\n"
            "#WorldCup2026 #WorldCup #Football #Soccer #FIFAWorldCup #AIPredictions #footballpredictions #Shorts"
            + credit_line)
    try:
        from worldcup_thumbnail import generate_thumbnail
        thumb = generate_thumbnail(
            OUT_DIR / f"daily_{day}_thumb.jpg",
            title=f"Today at the World Cup {props['date']}",
            kind="TODAY'S MATCHES",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[daily-wc] thumbnail failed (non-fatal): {exc}")
        thumb = None
    up = subprocess.run(
        ["/usr/bin/python3", str(KIT / "scripts" / "youtube_shorts_publisher.py"), "upload",
         "--video", str(out), "--title", title, "--description", desc,
         "--privacy", args.privacy, "--profile", "main", "--category-id", "17",
         "--tags", "WorldCup2026,WorldCup,football,soccer,FIFAWorldCup,AIpredictions,footballpredictions,shorts"]
        + (["--thumbnail", str(thumb)] if thumb else []),
        capture_output=True, text=True)
    print(up.stdout[-300:])
    if up.returncode != 0:
        print(f"[daily-wc] upload failed: {up.stderr[-300:]}")
        return 1
    m = re.search(r"https://www\.youtube\.com/shorts/[\w-]+", up.stdout)
    yt = m.group(0) if m else ""
    _mark(day)

    if args.privacy == "public":
        try:
            frame = OUT_DIR / "fb_frame.png"
            subprocess.run(["/usr/bin/ffmpeg", "-y", "-ss", "2", "-i", str(out), "-frames:v", "1", str(frame)], capture_output=True)
            from football_crosspost import crosspost
            crosspost("🌍 Today at the World Cup 2026 — today's matches, the model's picks, and "
                      "yesterday's results. What are your score predictions?",
                      youtube_url=yt, image_path=str(frame) if frame.exists() else None,
                      title=title)
        except Exception as exc:  # noqa: BLE001
            print(f"[daily-wc] crosspost failed (non-fatal): {exc}")

    if not args.no_telegram:
        try:
            tok = Path(os.path.expanduser("~/.telegram-bot-token"))
            if tok.exists():
                t = tok.read_text().strip(); os.environ["TELEGRAM_BOT_TOKEN"] = t; os.environ["TELEGRAM_TOKEN"] = t
            os.environ.setdefault("TELEGRAM_CHAT_ID", "-1003948211258")
            os.environ.setdefault("TELEGRAM_MESSAGE_THREAD_ID", "14119")
            import telegram_poster as TG
            TG.post_video(str(out), caption=f"📅 Daily World Cup slate published: {yt}")
        except Exception as exc:  # noqa: BLE001
            print(f"[daily-wc] telegram failed (non-fatal): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
