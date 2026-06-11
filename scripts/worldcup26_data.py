#!/usr/bin/env python3
"""Keyless World Cup 2026 data client (worldcup26.ir).

A free, no-auth REST source for the 2026 tournament: fixtures, live scores,
scorers, group standings, teams (names + flags). Used as the primary data
source for the Pitch Agent's World Cup content (football-data.org is the
fallback when a key is configured).

Endpoints (HTTP 200, no auth):
    GET /get/games   — fixtures + live scores + scorers + finished/time_elapsed
    GET /get/groups  — group standings (mp, w/d/l, pts, gf/ga/gd) by team_id
    GET /get/teams   — team_id → name (en/fa), flag URL, fifa_code, group

Quick check:
    python3 scripts/worldcup26_data.py today
    python3 scripts/worldcup26_data.py standings A
    python3 scripts/worldcup26_data.py finished
"""
from __future__ import annotations

import datetime as _dt
import sys
from typing import Any

import requests

BASE_URL = "https://worldcup26.ir"
TIMEOUT = 20
_UA = {"User-Agent": "buildwithabdallah-pitch-agent/1.0"}

# Cache teams within a process run (id → team dict).
_TEAMS_CACHE: dict[str, dict[str, Any]] | None = None


def _get(path: str) -> dict[str, Any]:
    r = requests.get(f"{BASE_URL}{path}", headers=_UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def teams() -> dict[str, dict[str, Any]]:
    """Return {team_id: {name, flag, code, iso2, group}} (cached per run)."""
    global _TEAMS_CACHE
    if _TEAMS_CACHE is None:
        out: dict[str, dict[str, Any]] = {}
        for t in _get("/get/teams").get("teams", []):
            out[str(t.get("id", ""))] = {
                "name": t.get("name_en", ""),
                "name_fa": t.get("name_fa", ""),
                "flag": t.get("flag", ""),
                "code": t.get("fifa_code", ""),
                "iso2": t.get("iso2", ""),
                "group": t.get("groups", ""),
            }
        _TEAMS_CACHE = out
    return _TEAMS_CACHE


def _team_name(team_id: str, fallback: str = "") -> str:
    return teams().get(str(team_id), {}).get("name") or fallback


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def games() -> list[dict[str, Any]]:
    """All games, normalised. status ∈ {notstarted, live, finished}."""
    raw = _get("/get/games").get("games", [])
    out = []
    for g in raw:
        finished = str(g.get("finished", "")).upper() == "TRUE"
        elapsed = str(g.get("time_elapsed", "")).strip().lower()
        if finished:
            status = "finished"
        elif elapsed and elapsed != "notstarted":
            status = "live"
        else:
            status = "notstarted"
        out.append({
            "id": str(g.get("id", "")),
            "home_id": str(g.get("home_team_id", "")),
            "away_id": str(g.get("away_team_id", "")),
            "home_team": g.get("home_team_name_en") or _team_name(g.get("home_team_id", "")),
            "away_team": g.get("away_team_name_en") or _team_name(g.get("away_team_id", "")),
            "home_score": _to_int(g.get("home_score")),
            "away_score": _to_int(g.get("away_score")),
            "home_scorers": _clean_scorers(g.get("home_scorers")),
            "away_scorers": _clean_scorers(g.get("away_scorers")),
            "group": g.get("group", ""),
            "matchday": g.get("matchday", ""),
            "date": g.get("local_date", ""),
            "stadium_id": str(g.get("stadium_id", "")),
            "type": g.get("type", ""),
            "status": status,
            "time_elapsed": g.get("time_elapsed", ""),
        })
    return out


def _clean_scorers(value: Any) -> list[str]:
    s = str(value or "").strip()
    if not s or s.lower() == "null":
        return []
    # Scorers may be comma/semicolon separated names.
    return [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]


def _parse_date(date_str: str) -> _dt.date | None:
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return _dt.datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def today_matches(today: _dt.date | None = None) -> list[dict[str, Any]]:
    today = today or _dt.date.today()
    return [g for g in games() if _parse_date(g["date"]) == today]


def finished_matches() -> list[dict[str, Any]]:
    return [g for g in games() if g["status"] == "finished"]


def live_matches() -> list[dict[str, Any]]:
    return [g for g in games() if g["status"] == "live"]


def standings(group: str | None = None) -> list[dict[str, Any]]:
    """Group standings as [{group, table:[rows]}], rows sorted by position.

    Each row: {position, team, code, flag, played, won, draw, lost,
    goals_for, goals_against, goal_difference, points}.
    """
    tmap = teams()
    out = []
    for grp in _get("/get/groups").get("groups", []):
        name = grp.get("name", "")
        if group and name.upper() != group.upper():
            continue
        rows = []
        for row in grp.get("teams", []):
            tid = str(row.get("team_id", ""))
            t = tmap.get(tid, {})
            rows.append({
                "team_id": tid,
                "team": t.get("name", tid),
                "code": t.get("code", ""),
                "flag": t.get("flag", ""),
                "played": _to_int(row.get("mp")),
                "won": _to_int(row.get("w")),
                "draw": _to_int(row.get("d")),
                "lost": _to_int(row.get("l")),
                "goals_for": _to_int(row.get("gf")),
                "goals_against": _to_int(row.get("ga")),
                "goal_difference": _to_int(row.get("gd")),
                "points": _to_int(row.get("pts")),
            })
        # Sort by points, then goal difference, then goals for.
        rows.sort(key=lambda r: (r["points"], r["goal_difference"], r["goals_for"]), reverse=True)
        for i, r in enumerate(rows, 1):
            r["position"] = i
        out.append({"group": f"Group {name}", "table": rows})
    return out


def _demo() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    if cmd == "today":
        ms = today_matches()
        print(f"{len(ms)} match(es) today:")
        for m in ms:
            print(f"  {m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}"
                  f"  [{m['status']}] {m['date']} (Group {m['group']})")
    elif cmd == "finished":
        for m in finished_matches():
            print(f"  FT: {m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}")
    elif cmd == "live":
        for m in live_matches():
            print(f"  LIVE {m['time_elapsed']}: {m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}")
    elif cmd == "standings":
        grp = sys.argv[2] if len(sys.argv) > 2 else None
        for block in standings(grp):
            print(f"\n{block['group']}")
            for r in block["table"]:
                print(f"  {r['position']}. {r['team']:<16} {r['played']} {r['won']}-{r['draw']}-{r['lost']}  {r['points']} pts")
    else:
        print(__doc__)


if __name__ == "__main__":
    _demo()
