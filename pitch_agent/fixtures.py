"""Fixture queries — upcoming/known matches from the ``matches`` table.

Fixtures are useful before any player grades exist: they power the
``fixtures`` CLI command, the fixtures chart, and the ``matchday_preview``
content pillar.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def get_fixtures(
    db_path: str = "pitch_agent.db",
    competition_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return stored fixtures ordered by date (earliest first).

    Each fixture dict has: ``match_id``, ``date``, ``stage``, ``group_name``,
    ``home_team_name``, ``away_team_name``, ``status``, ``provider_name``, and a
    derived ``match_label`` (``Home vs Away`` or ``TBD`` when teams are unknown).
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        query = (
            "SELECT match_id, date, stage, group_name, home_team_name, "
            "away_team_name, home_score, away_score, status, provider_name "
            "FROM matches"
        )
        params: list[Any] = []
        if competition_id:
            query += " WHERE competition_id = ?"
            params.append(competition_id)
        query += " ORDER BY date ASC, match_id ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return []

    fixtures = []
    for row in rows:
        home = row["home_team_name"]
        away = row["away_team_name"]
        fixtures.append({
            "match_id": row["match_id"],
            "date": row["date"],
            "stage": row["stage"],
            "group_name": row["group_name"],
            "home_team_name": home,
            "away_team_name": away,
            "home_score": row["home_score"],
            "away_score": row["away_score"],
            "status": row["status"],
            "provider_name": row["provider_name"],
            "match_label": f"{home} vs {away}" if home and away else "TBD",
        })
    return fixtures
