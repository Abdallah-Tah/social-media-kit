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


def get_finished_matches(
    db_path: str = "pitch_agent.db",
    limit: int = 10,
    match_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return finished matches with non-NULL scores, newest first.

    Each dict has the same keys as :func:`get_fixtures`, plus
    ``home_score``, ``away_score``, ``result_source``.
    If *match_id* is given, only that match is returned (if finished).
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        query = (
            "SELECT match_id, date, stage, group_name, home_team_name, "
            "away_team_name, home_team_id, away_team_id, "
            "home_score, away_score, status, result_source, provider_name "
            "FROM matches "
            "WHERE status = 'FINISHED' AND home_score IS NOT NULL AND away_score IS NOT NULL"
        )
        params: list[Any] = []
        if match_id:
            query += " AND match_id = ?"
            params.append(match_id)
        query += " ORDER BY date DESC, match_id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return []

    results = []
    for row in rows:
        home = row["home_team_name"]
        away = row["away_team_name"]
        results.append({
            "match_id": row["match_id"],
            "date": row["date"],
            "stage": row["stage"],
            "group_name": row["group_name"],
            "home_team_name": home,
            "away_team_name": away,
            "home_team_id": row["home_team_id"] or "",
            "away_team_id": row["away_team_id"] or "",
            "home_score": row["home_score"],
            "away_score": row["away_score"],
            "status": row["status"],
            "result_source": row["result_source"],
            "provider_name": row["provider_name"],
            "match_label": f"{home} vs {away}" if home and away else "TBD",
        })
    return results
