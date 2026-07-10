#!/usr/bin/env python3
"""Approval-gated auto-drafter for the ML/Elo build-in-public posts.

Runs on a schedule and DRAFTS (to Telegram) — never publishes:
  * prediction draft for each of today's upcoming matches (before kickoff)
  * result draft for each finished + graded match

Dedupe ledger (content/pitch_post_drafts.json) ensures each match is drafted at
most once per kind. Publishing stays manual: `smkit pitch-post ... --publish`.

  /usr/bin/python3 scripts/pitch_post_auto.py --mode both [--dry-run]
"""
import argparse
import datetime as _dt
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import os  # noqa: E402

KIT = Path(__file__).resolve().parents[1]
os.chdir(KIT)  # run as if from the kit dir (cron starts in $HOME; load_env/fixtures are cwd-relative)
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402
load_env()

LEDGER = KIT / "content" / "pitch_post_drafts.json"
DB = str(KIT / "pitch_agent.db")
PY = "/usr/bin/python3"


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _read() -> dict:
    try:
        return json.loads(LEDGER.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(d: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, indent=2, sort_keys=True))


def _draft(match: str, kind: str, dry: bool) -> bool:
    if dry:
        print(f"[dry-run] would draft {kind}: {match}")
        return True
    r = subprocess.run([PY, "-m", "agent.cli", "pitch-post", "--match", match, "--kind", kind],
                       cwd=str(KIT))
    return r.returncode == 0


def _upcoming():
    import football_prediction_shorts as F
    return [(m.get("home_team_name"), m.get("away_team_name")) for m in F.todays_upcoming()]


def _finished_graded(window_hours: int = 24):
    """Recently finished + graded matches (within the window) — 'after full-time',
    not a backfill of the whole history."""
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT m.home_team_name h, m.away_team_name a "
        "FROM matches m JOIN predictions p ON p.match_id = m.match_id "
        "JOIN prediction_results pr ON pr.prediction_id = p.id "
        "WHERE m.status = 'FINISHED' AND pr.correct IS NOT NULL "
        "AND m.date >= datetime('now', ?) "
        "ORDER BY m.date DESC LIMIT 12", (f"-{int(window_hours)} hours",)).fetchall()
    c.close()
    return [(r["h"], r["a"]) for r in rows]


def run(mode: str, dry: bool, window_hours: int = 24, seed: bool = False) -> int:
    led = _read()
    jobs = []
    if mode in ("predictions", "both"):
        jobs += [("prediction", h, a) for (h, a) in _upcoming()]
    if mode in ("results", "both"):
        jobs += [("result", h, a) for (h, a) in _finished_graded(window_hours)]

    drafted = 0
    for kind, h, a in jobs:
        if not h or not a:
            continue
        key = f"{h} vs {a}"
        if led.get(key, {}).get(kind):
            continue  # already drafted this kind
        if seed:
            # Mark the current backlog as drafted WITHOUT sending — clean start.
            led.setdefault(key, {})[kind] = "seeded"
            _write(led)
            drafted += 1
            continue
        if _draft(key, kind, dry):
            if not dry:
                led.setdefault(key, {})[kind] = _now()
                _write(led)
            drafted += 1
    verb = "seeded" if seed else "new draft(s)"
    print(f"[pitch-post-auto] {mode}: {drafted} {verb}{' (dry-run)' if dry else ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["predictions", "results", "both"], default="both")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--window-hours", type=int, default=24, help="Results recency window")
    ap.add_argument("--seed", action="store_true",
                    help="Mark current backlog as drafted without sending (clean first start)")
    args = ap.parse_args()
    return run(args.mode, args.dry_run, args.window_hours, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
