#!/usr/bin/env python3
"""Journal model predictions for all matches kicking off soon.

THE accountability ledger fix: the preview pipeline only *displays*
predictions, it never records them — so most games had "(No prediction on
record)" and the public model record stayed tiny and noisy. This journals
a prediction for every upcoming match in the next N hours by calling the
tested `predict` CLI (which writes to the predictions table and grades
finished games). Pre-kickoff only — the immutability guard skips anything
already started, so this never backfills.

Local DB writes only. Publishes nothing.

  /usr/bin/python3 scripts/journal_upcoming.py            # next 18h
  /usr/bin/python3 scripts/journal_upcoming.py --hours 24
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
DB = KIT / "pitch_agent.db"


def upcoming_match_ids(hours: int) -> list[tuple[str, str]]:
    """(match_id, label) for non-finished matches kicking off within `hours` (UTC)."""
    now = datetime.datetime.utcnow()
    horizon = now + datetime.timedelta(hours=hours)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT match_id, home_team_name h, away_team_name a, date "
        "FROM matches WHERE status != 'FINISHED' AND date IS NOT NULL ORDER BY date"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            ko = datetime.datetime.fromisoformat(r["date"].replace("Z", "").replace("+00:00", ""))
        except ValueError:
            continue
        if now <= ko <= horizon:
            out.append((r["match_id"], f"{r['h']} vs {r['a']}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=18, help="kickoff horizon (default 18h)")
    args = ap.parse_args()

    games = upcoming_match_ids(args.hours)
    if not games:
        print(f"[journal] no upcoming matches in the next {args.hours}h")
        return 0
    journaled = 0
    for mid, label in games:
        res = subprocess.run(
            ["/usr/bin/python3", "-m", "pitch_agent.cli", "predict", "--match", mid],
            cwd=str(KIT), capture_output=True, text=True,
        )
        out = res.stdout + res.stderr
        if "Prediction stored" in out:
            journaled += 1
            print(f"[journal] ✓ {label} ({mid})")
        elif "kickoff has passed" in out:
            print(f"[journal] – {label} ({mid}) already started, skipped")
        else:
            print(f"[journal] ! {label} ({mid}) not journaled (no prior?)")
    print(f"[journal] done — {journaled}/{len(games)} predictions journaled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
