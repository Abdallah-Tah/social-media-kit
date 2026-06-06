"""Leaderboard queries — daily, player-match, and tournament scopes.

Reads from ``form_index_scores`` joined with ``player_match_stats``
to produce ranked leaderboards.
"""
from __future__ import annotations

import sqlite3
from typing import Any

DAILY_SCOPE = "daily"
PLAYER_MATCH_SCOPE = "player_match"
TOURNAMENT_SCOPE = "tournament"


def normalize_scope(scope: str | None) -> str:
    """Normalize public scope aliases to internal identifiers."""
    value = (scope or DAILY_SCOPE).replace("-", "_").lower()
    if value == "match":
        return PLAYER_MATCH_SCOPE
    if value not in {DAILY_SCOPE, PLAYER_MATCH_SCOPE, TOURNAMENT_SCOPE}:
        raise ValueError(f"Unknown leaderboard scope: {scope}")
    return value


def get_leaderboard(
    db_path: str = "pitch_agent.db",
    position: str | None = None,
    limit: int = 10,
    model_version: str = "1.0.0-lite",
    scope: str = DAILY_SCOPE,
    match_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return a Form Index leaderboard for the requested scope.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database.
    position : str or None
        Filter by position (FWD, MID, DEF, GK).  None returns all.
    limit : int
        Maximum number of results.
    model_version : str
        Which model version to query.
    scope : str
        ``daily`` for one row per player using best score, ``player_match``
        for player-match rows, or ``tournament`` for cumulative scores.
    match_id : str or None
        Optional match filter for player-match scope.

    Returns
    -------
    list of dict
        Each dict has rank, player_id, player_name, team_name, position, score,
        scope, and scope-specific metadata such as match_id.
    """
    normalized = normalize_scope(scope)
    if normalized == PLAYER_MATCH_SCOPE:
        return get_match_leaderboard(
            db_path=db_path,
            match_id=match_id,
            position=position,
            limit=limit,
            model_version=model_version,
        )
    if normalized == TOURNAMENT_SCOPE:
        return get_tournament_leaderboard(
            db_path=db_path,
            position=position,
            limit=limit,
            model_version=model_version,
        )
    return get_daily_leaderboard(
        db_path=db_path,
        position=position,
        limit=limit,
        model_version=model_version,
    )


def get_daily_leaderboard(
    db_path: str = "pitch_agent.db",
    position: str | None = None,
    limit: int = 10,
    model_version: str = "1.0.0-lite",
) -> list[dict[str, Any]]:
    """Return one row per player using that player's best match score."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = """
        WITH ranked_scores AS (
            SELECT
                s.match_id,
                s.player_id,
                p.player_name,
                p.team_name,
                p.position,
                s.score,
                s.score_breakdown_json,
                row_number() OVER (
                    PARTITION BY s.player_id
                    ORDER BY s.score DESC, s.match_id ASC
                ) AS player_rank
            FROM form_index_scores s
            JOIN player_match_stats p
                ON s.match_id = p.match_id AND s.player_id = p.player_id
            WHERE s.model_version = ?
        )
        SELECT
            match_id,
            player_id,
            player_name,
            team_name,
            position,
            score,
            score_breakdown_json
        FROM ranked_scores
        WHERE player_rank = 1
    """
    params: list[Any] = [model_version]

    if position:
        query += " AND position = ?"
        params.append(position.upper())

    query += " ORDER BY score DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for i, row in enumerate(rows, 1):
        results.append({
            "rank": i,
            "scope": DAILY_SCOPE,
            "match_id": row["match_id"],
            "player_id": row["player_id"],
            "player_name": row["player_name"],
            "team_name": row["team_name"],
            "position": row["position"],
            "score": row["score"],
            "score_breakdown_json": row["score_breakdown_json"],
        })

    return _attach_match_context(db_path, results, model_version)


def get_match_leaderboard(
    db_path: str = "pitch_agent.db",
    match_id: str | None = None,
    position: str | None = None,
    limit: int = 10,
    model_version: str = "1.0.0-lite",
) -> list[dict[str, Any]]:
    """Return a leaderboard for a specific match.

    Parameters
    ----------
    match_id : str or None
        Filter by match.  None returns scores across all matches.
    position : str or None
        Filter by position (FWD, MID, DEF, GK).
    limit : int
        Maximum number of results.

    Returns
    -------
    list of dict
        Same format as ``get_leaderboard``.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            s.match_id,
            s.player_id,
            p.player_name,
            p.team_name,
            p.position,
            s.score,
            s.score_breakdown_json
        FROM form_index_scores s
        JOIN player_match_stats p
            ON s.match_id = p.match_id AND s.player_id = p.player_id
        WHERE s.model_version = ?
    """
    params: list[Any] = [model_version]

    if match_id:
        query += " AND s.match_id = ?"
        params.append(match_id)

    if position:
        query += " AND p.position = ?"
        params.append(position.upper())

    query += " ORDER BY s.score DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for i, row in enumerate(rows, 1):
        results.append({
            "rank": i,
            "scope": PLAYER_MATCH_SCOPE,
            "match_id": match_id if match_id else row["match_id"],
            "player_id": row["player_id"],
            "player_name": row["player_name"],
            "team_name": row["team_name"],
            "position": row["position"],
            "score": row["score"],
            "score_breakdown_json": row["score_breakdown_json"],
        })

    return _attach_match_context(db_path, results, model_version)


def get_tournament_leaderboard(
    db_path: str = "pitch_agent.db",
    position: str | None = None,
    limit: int = 10,
    model_version: str = "1.0.0-lite",
) -> list[dict[str, Any]]:
    """Return one row per player from cumulative tournament scores."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = """
        WITH latest_player_meta AS (
            SELECT
                player_id,
                player_name,
                team_name,
                position,
                row_number() OVER (
                    PARTITION BY player_id
                    ORDER BY matchday DESC, match_id DESC
                ) AS player_rank
            FROM player_match_stats
        ),
        ranked_tournament AS (
            SELECT
                t.tournament_id,
                t.player_id,
                t.cumulative_score,
                t.matches_played,
                row_number() OVER (
                    PARTITION BY t.player_id
                    ORDER BY t.cumulative_score DESC, t.tournament_id ASC
                ) AS tournament_rank
            FROM tournament_form_index t
            WHERE t.model_version = ?
        )
        SELECT
            t.tournament_id,
            t.player_id,
            p.player_name,
            p.team_name,
            p.position,
            t.cumulative_score AS score,
            t.matches_played
        FROM ranked_tournament t
        JOIN latest_player_meta p
            ON t.player_id = p.player_id AND p.player_rank = 1
        WHERE t.tournament_rank = 1
    """
    params: list[Any] = [model_version]

    if position:
        query += " AND p.position = ?"
        params.append(position.upper())

    query += " ORDER BY t.cumulative_score DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for i, row in enumerate(rows, 1):
        results.append({
            "rank": i,
            "scope": TOURNAMENT_SCOPE,
            "tournament_id": row["tournament_id"],
            "player_id": row["player_id"],
            "player_name": row["player_name"],
            "team_name": row["team_name"],
            "position": row["position"],
            "score": row["score"],
            "matches_played": row["matches_played"],
        })

    return results


# ── Match context enrichment ────────────────────────────────────────────────


def _attach_match_context(
    db_path: str,
    rows: list[dict[str, Any]],
    model_version: str,
) -> list[dict[str, Any]]:
    """Add match label, date, key reason, and score movement to each row.

    Every field is best-effort: when match metadata or prior matches are
    unavailable the field is an empty string or ``None`` rather than an error.
    """
    if not rows:
        return rows

    matches = _load_matches(db_path)
    stats = _load_stats(db_path)
    history = _load_score_history(db_path, model_version)

    for row in rows:
        match_id = row.get("match_id")
        player_id = row.get("player_id")
        match = matches.get(match_id, {})

        home = match.get("home_team_name", "")
        away = match.get("away_team_name", "")
        row["match_label"] = f"{home} vs {away}" if home and away else ""
        row["match_date"] = match.get("date", "")
        row["key_reason"] = _key_reason(stats.get((match_id, player_id), {}))

        previous = _previous_score(history, player_id, match_id)
        row["previous_score"] = previous
        if previous is not None:
            row["score_movement"] = round(row["score"] - previous, 1)
        else:
            row["score_movement"] = None

    return rows


def _load_matches(db_path: str) -> dict[str, dict[str, Any]]:
    """Return match metadata keyed by match_id; empty when unavailable."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT match_id, home_team_name, away_team_name, date, matchday FROM matches"
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return {}
    return {r["match_id"]: dict(r) for r in rows}


def _load_stats(db_path: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Return scoring inputs keyed by (match_id, player_id) for key reasons."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT match_id, player_id, goals, assists, clean_sheet, "
        "team_result, minutes FROM player_match_stats"
    ).fetchall()
    conn.close()
    return {(r["match_id"], r["player_id"]): dict(r) for r in rows}


def _load_score_history(
    db_path: str,
    model_version: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return each player's match scores ordered chronologically."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.player_id, s.match_id, s.score, p.matchday
        FROM form_index_scores s
        JOIN player_match_stats p
            ON s.match_id = p.match_id AND s.player_id = p.player_id
        WHERE s.model_version = ?
        ORDER BY p.matchday ASC, s.match_id ASC
        """,
        (model_version,),
    ).fetchall()
    conn.close()

    history: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        history.setdefault(r["player_id"], []).append(
            {"match_id": r["match_id"], "score": r["score"]}
        )
    return history


def _previous_score(
    history: dict[str, list[dict[str, Any]]],
    player_id: str | None,
    match_id: str | None,
) -> float | None:
    """Return the player's score in the match immediately before this one."""
    entries = history.get(player_id or "", [])
    for idx, entry in enumerate(entries):
        if entry["match_id"] == match_id:
            if idx == 0:
                return None
            return entries[idx - 1]["score"]
    return None


def _key_reason(stats: dict[str, Any]) -> str:
    """Build a short, human key reason like '2 goals, 1 assist, team win'."""
    if not stats:
        return ""
    parts: list[str] = []
    goals = int(stats.get("goals") or 0)
    assists = int(stats.get("assists") or 0)
    if goals:
        parts.append(f"{goals} goal" + ("s" if goals != 1 else ""))
    if assists:
        parts.append(f"{assists} assist" + ("s" if assists != 1 else ""))
    if int(stats.get("clean_sheet") or 0) == 1:
        parts.append("clean sheet")
    result = str(stats.get("team_result") or "").upper()
    if result == "WIN":
        parts.append("team win")
    if parts:
        return ", ".join(parts)

    # No standout events — fall back to a minutes-based description.
    minutes = int(stats.get("minutes") or 0)
    if minutes >= 90:
        return "full 90 minutes"
    if minutes > 0:
        return f"{minutes} minutes played"
    return ""
