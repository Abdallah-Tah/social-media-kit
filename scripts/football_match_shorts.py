#!/usr/bin/env python3
"""Per-match AI-prediction Shorts — one Short per upcoming game.

This is the biggest view lever: instead of a single multi-match card, post one
Short per game so each captures that match's own search traffic. Title uses the
proven 564-view format: "{Home} vs {Away} — AI Prediction 🏆 World Cup 2026".

For each of today's upcoming matches (deduped via content/match_shorts_posted.json):
  render a single-match card → 9:16 Short → upload to YouTube → cross-post to
  Facebook + LinkedIn with the YouTube link.

  /usr/bin/python3 scripts/football_match_shorts.py            # publish (live)
  /usr/bin/python3 scripts/football_match_shorts.py --dry-run  # render only
  /usr/bin/python3 scripts/football_match_shorts.py --max 3    # cap per run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402
load_env()

POSTED = KIT / "content" / "match_shorts_posted.json"
CARD = KIT / "artifacts" / "pitch_agent" / "charts" / "match_short.png"


def _posted() -> set:
    try:
        return set(json.loads(POSTED.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _mark(mid: str) -> None:
    seen = _posted()
    seen.add(mid)
    POSTED.write_text(json.dumps(sorted(seen)[-300:]))


def todays_upcoming() -> list[dict]:
    from pitch_agent.fixtures import get_upcoming_fixtures
    from pitch_agent.content import _upcoming_fixtures
    return _upcoming_fixtures(get_upcoming_fixtures(limit=16), limit=10, today_only=True)


def build_card(fx: dict) -> Path:
    """Render a single-match prediction card."""
    from datetime import datetime
    from pitch_agent.content import _match_prediction, _fixture_context, NY_TZ
    from pitch_agent.html_cards import render_matchday_preview_html_card

    h, a = fx["home_team_name"], fx["away_team_name"]
    date_str = str(fx.get("date", ""))
    try:
        ko = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        when = ko.astimezone(NY_TZ).strftime("%-I:%M %p ET") if len(date_str) > 10 else ""
    except (ValueError, TypeError):
        when = ""
    pred = _match_prediction(fx) or ""
    if pred:
        pred = pred.split(" — ")[0].strip()
    group = _fixture_context(fx)
    if group and pred:
        pred = f"{group} · {pred}"
    row = {"label": f"{h} vs {a}", "context": when, "prediction": pred or group}
    from pitch_agent.db import get_connection, get_prediction_accuracy
    try:
        acc = get_prediction_accuracy(get_connection(str(KIT / "pitch_agent.db")))
        record = (f"Model record: {acc['correct']}/{acc['total']}"
                  if acc.get("total") else "The Pitch Agent — AI predicts every match")
    except Exception:
        record = "The Pitch Agent — AI predicts every match"
    render_matchday_preview_html_card(
        [row], output_path=str(CARD), title="AI PREDICTION",
        subtitle=f"{h} vs {a} · World Cup 2026", results=[], model_record=record,
    )
    return CARD


def analyst_voiceover(fx: dict) -> str:
    """Short spoken hook for the auto-uploaded prediction Short."""
    from pitch_agent.content import _match_prediction, _fixture_context

    h, a = fx["home_team_name"], fx["away_team_name"]
    pred = (_match_prediction(fx) or "").split(" — ")[0].strip()
    group = _fixture_context(fx)
    if pred:
        call = f"The model call is {pred}."
    elif group:
        call = f"This is a {group} match."
    else:
        call = "The model has this one close."
    return (
        f"Pitch Agent prediction. {h} against {a}. {call} "
        "After full time, follow to see if the AI nailed it."
    )


def publish_match(fx: dict, privacy: str, dry_run: bool) -> bool:
    import football_youtube_short as FY
    from football_crosspost import crosspost
    h, a = fx["home_team_name"], fx["away_team_name"]
    card = build_card(fx)
    video = FY.make_short(
        card=card,
        out=KIT / "content" / "assets" / "match_short.mp4",
        voiceover=analyst_voiceover(fx),
    )
    title = f"{h} vs {a} — AI Prediction \U0001F3C6 World Cup 2026"[:100]
    print(f"[match-short] {title}")
    if dry_run:
        print("[match-short] DRY RUN — not uploading.")
        return False
    desc = (f"{h} vs {a} — The Pitch Agent's AI prediction for this World Cup 2026 match.\n\n"
            "Our AI predicts every game and grades itself — daily picks + recaps.\n\n"
            "#WorldCup2026 #WorldCup #Football #Soccer #FIFAWorldCup "
            "#AIPredictions #footballpredictions #Shorts")
    rc, yt_url = FY.upload(video, title, desc, privacy, "main")
    if rc != 0:
        print(f"[match-short] upload failed rc={rc}")
        return False
    if privacy == "public":
        try:
            crosspost(f"🤖 AI prediction: {h} vs {a} — World Cup 2026. What does the model call?",
                      youtube_url=yt_url, image_path=str(card), title=title)
        except Exception as exc:  # noqa: BLE001
            print(f"[match-short] crosspost failed (non-fatal): {exc}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    ap.add_argument("--max", type=int, default=10, help="cap shorts per run")
    args = ap.parse_args()

    posted = _posted()
    matches = [m for m in todays_upcoming() if m["match_id"] not in posted]
    if not matches:
        print("[match-short] no new upcoming matches today")
        return 0
    n = 0
    for fx in matches[: args.max]:
        try:
            if publish_match(fx, args.privacy, args.dry_run) and not args.dry_run:
                _mark(fx["match_id"])
                n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[match-short] {fx.get('match_label')} failed (non-fatal): {exc}")
    print(f"[match-short] done — {n} posted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
