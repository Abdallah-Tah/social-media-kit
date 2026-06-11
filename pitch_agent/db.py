"""SQLite database layer for The Pitch Agent.

All tables use UPSERT semantics — re-computing a match updates existing
rows rather than skipping them.  The ``runs`` table is for
publishing/content dedup only, not score calculations.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pitch_agent.config import ALL_FIELDS


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS player_match_stats (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id              TEXT    NOT NULL,
    player_id             TEXT    NOT NULL,
    player_name           TEXT    NOT NULL DEFAULT '',
    team_id               TEXT    NOT NULL DEFAULT '',
    team_name             TEXT    NOT NULL DEFAULT '',
    position              TEXT    NOT NULL DEFAULT '',
    competition_id        TEXT    NOT NULL DEFAULT '',
    season                TEXT    NOT NULL DEFAULT '',
    matchday              INTEGER NOT NULL DEFAULT 0,
    stage                 TEXT    NOT NULL DEFAULT '',
    -- Basic stats (always present)
    goals                 INTEGER NOT NULL DEFAULT 0,
    assists               INTEGER NOT NULL DEFAULT 0,
    minutes               INTEGER NOT NULL DEFAULT 0,
    yellow_cards          INTEGER NOT NULL DEFAULT 0,
    red_cards             INTEGER NOT NULL DEFAULT 0,
    own_goals             INTEGER NOT NULL DEFAULT 0,
    clean_sheet           INTEGER NOT NULL DEFAULT 0,
    team_result           TEXT    NOT NULL DEFAULT '',
    -- Richer stats (default to 0 when not available)
    pass_accuracy         REAL    NOT NULL DEFAULT 0.0,
    shots_on_target       INTEGER NOT NULL DEFAULT 0,
    key_passes            INTEGER NOT NULL DEFAULT 0,
    successful_dribbles   INTEGER NOT NULL DEFAULT 0,
    big_chances_created   INTEGER NOT NULL DEFAULT 0,
    big_chances_missed    INTEGER NOT NULL DEFAULT 0,
    tackles_won           INTEGER NOT NULL DEFAULT 0,
    interceptions         INTEGER NOT NULL DEFAULT 0,
    blocked_shots         INTEGER NOT NULL DEFAULT 0,
    aerial_duels_won      INTEGER NOT NULL DEFAULT 0,
    saves                 INTEGER NOT NULL DEFAULT 0,
    penalty_saves         INTEGER NOT NULL DEFAULT 0,
    shots_faced           INTEGER NOT NULL DEFAULT 0,
    possession_lost       INTEGER NOT NULL DEFAULT 0,
    xg                    REAL    NOT NULL DEFAULT 0.0,
    duels                 INTEGER NOT NULL DEFAULT 0,
    distance_covered_km   REAL    NOT NULL DEFAULT 0.0,
    pressures             INTEGER NOT NULL DEFAULT 0,
    -- Metadata
    data_quality          TEXT    NOT NULL DEFAULT 'basic',
    available_fields      TEXT    NOT NULL DEFAULT '',
    provider_name         TEXT    NOT NULL DEFAULT '',
    data_quality_level    TEXT    NOT NULL DEFAULT 'basic',
    raw_json              TEXT    NOT NULL DEFAULT '{}',
    created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id, player_id)
);

CREATE TABLE IF NOT EXISTS matches (
    match_id              TEXT    PRIMARY KEY,
    competition_id        TEXT    NOT NULL DEFAULT '',
    matchday              INTEGER NOT NULL DEFAULT 0,
    stage                 TEXT    NOT NULL DEFAULT '',
    home_team_id          TEXT    NOT NULL DEFAULT '',
    home_team_name        TEXT    NOT NULL DEFAULT '',
    away_team_id          TEXT    NOT NULL DEFAULT '',
    away_team_name        TEXT    NOT NULL DEFAULT '',
    home_score            INTEGER NOT NULL DEFAULT 0,
    away_score            INTEGER NOT NULL DEFAULT 0,
    date                  TEXT    NOT NULL DEFAULT '',
    group_name            TEXT    NOT NULL DEFAULT '',
    status                TEXT    NOT NULL DEFAULT '',
    provider_name         TEXT    NOT NULL DEFAULT '',
    created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS form_index_scores (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id                TEXT    NOT NULL,
    player_id               TEXT    NOT NULL,
    model_version           TEXT    NOT NULL DEFAULT '1.0.0-lite',
    score                   REAL    NOT NULL DEFAULT 0.0,
    score_breakdown_json    TEXT    NOT NULL DEFAULT '{}',
    created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id, player_id, model_version)
);

CREATE TABLE IF NOT EXISTS tournament_form_index (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id         TEXT    NOT NULL,
    player_id             TEXT    NOT NULL,
    model_version         TEXT    NOT NULL DEFAULT '1.0.0-lite',
    cumulative_score      REAL    NOT NULL DEFAULT 0.0,
    matches_played        INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tournament_id, player_id, model_version)
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type    TEXT NOT NULL,
    pillar      TEXT NOT NULL DEFAULT '',
    provider    TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL DEFAULT '',
    dry_run     INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_type, pillar, provider, mode, created_at)
);

CREATE TABLE IF NOT EXISTS predictions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id          TEXT    NOT NULL,
    model_version     TEXT    NOT NULL DEFAULT '1.0.0-lite',
    predicted_home    INTEGER NOT NULL,
    predicted_away    INTEGER NOT NULL,
    home_win_prob     REAL,
    draw_prob         REAL,
    away_win_prob     REAL,
    top_scorelines    TEXT    NOT NULL DEFAULT '[]',
    key_factor        TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id, model_version)
);

CREATE TABLE IF NOT EXISTS prediction_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id   INTEGER NOT NULL REFERENCES predictions(id),
    actual_home     INTEGER,
    actual_away     INTEGER,
    correct         INTEGER,
    graded_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(prediction_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_stats_match ON player_match_stats(match_id);
CREATE INDEX IF NOT EXISTS idx_stats_player ON player_match_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_stats_position ON player_match_stats(position);
CREATE INDEX IF NOT EXISTS idx_scores_match ON form_index_scores(match_id);
CREATE INDEX IF NOT EXISTS idx_scores_player ON form_index_scores(player_id);
CREATE INDEX IF NOT EXISTS idx_tournament_player ON tournament_form_index(player_id);
"""


# Columns added to ``matches`` after the table first shipped. Each entry is
# (column_name, column_definition) and is applied only when missing.
_MATCHES_MIGRATIONS = [
    ("status", "TEXT NOT NULL DEFAULT ''"),
    ("provider_name", "TEXT NOT NULL DEFAULT ''"),
]


def init_db(db_path: str = "pitch_agent.db") -> sqlite3.Connection:
    """Create tables, apply migrations, and return a connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Ensure the schema is current; return the list of columns added.

    Idempotent: creating tables uses ``IF NOT EXISTS`` and columns are only
    added when missing, so this is safe to run on every startup/sync.
    """
    conn.executescript(SCHEMA_SQL)
    added = _migrate_matches_columns(conn)
    conn.commit()
    return added


def migrate_db(db_path: str = "pitch_agent.db") -> list[str]:
    """Open ``db_path``, apply any pending migrations, and return added columns."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return run_migrations(conn)
    finally:
        conn.close()


def _migrate_matches_columns(conn: sqlite3.Connection) -> list[str]:
    """Add newer ``matches`` columns to databases created before they existed."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    added: list[str] = []
    for column, definition in _MATCHES_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {column} {definition}")
            added.append(column)
    return added


def get_connection(db_path: str = "pitch_agent.db") -> sqlite3.Connection:
    """Return a connection to an existing database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Column lists (for INSERT/UPSERT) ─────────────────────────────────────────

_STATS_COLUMNS = [
    "match_id", "player_id", "player_name", "team_id", "team_name",
    "position", "competition_id", "season", "matchday", "stage",
    "goals", "assists", "minutes", "yellow_cards", "red_cards",
    "own_goals", "clean_sheet", "team_result",
    "pass_accuracy", "shots_on_target", "key_passes",
    "successful_dribbles", "big_chances_created", "big_chances_missed",
    "tackles_won", "interceptions", "blocked_shots",
    "aerial_duels_won", "saves", "penalty_saves", "shots_faced",
    "possession_lost", "xg", "duels", "distance_covered_km", "pressures",
    "data_quality", "available_fields", "provider_name",
    "data_quality_level", "raw_json",
]

_STATS_UPDATE_COLUMNS = [c for c in _STATS_COLUMNS if c not in ("match_id", "player_id")]

_MATCHES_COLUMNS = [
    "match_id", "competition_id", "matchday", "stage",
    "home_team_id", "home_team_name", "away_team_id", "away_team_name",
    "home_score", "away_score", "date", "group_name", "status", "provider_name",
]
_MATCHES_UPDATE_COLUMNS = [c for c in _MATCHES_COLUMNS if c != "match_id"]

_SCORES_COLUMNS = ["match_id", "player_id", "model_version", "score", "score_breakdown_json"]
_SCORES_UPDATE_COLUMNS = ["score", "score_breakdown_json"]

_TOURNAMENT_COLUMNS = ["tournament_id", "player_id", "model_version", "cumulative_score", "matches_played"]
_TOURNAMENT_UPDATE_COLUMNS = ["cumulative_score", "matches_played"]


def upsert_player_match_stats(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a player-match stats row.

    Note: does NOT commit — the caller should batch inserts and commit once.
    """
    # Ensure all columns have a value (default to 0 or empty string)
    row = _normalise_stats_record(record)

    cols = []
    vals = []
    for col in _STATS_COLUMNS:
        cols.append(col)
        vals.append(row.get(col, 0 if col != "team_result" else ""))

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    update_sets = ", ".join(
        f"{c} = excluded.{c}" for c in _STATS_UPDATE_COLUMNS
    ) + ", updated_at = datetime('now')"

    sql = (
        f"INSERT INTO player_match_stats ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(match_id, player_id) DO UPDATE SET {update_sets}"
    )
    conn.execute(sql, vals)
    # Caller is responsible for committing the transaction.


def _normalise_stats_record(record: dict[str, Any]) -> dict[str, Any]:
    """Fill in missing columns with defaults and compute available_fields."""
    defaults: dict[str, Any] = {
        "player_name": "", "team_id": "", "team_name": "", "position": "",
        "competition_id": "", "season": "", "matchday": 0, "stage": "",
        "team_result": "",
        "data_quality": "basic", "available_fields": "",
        "provider_name": "", "data_quality_level": "basic", "raw_json": "{}",
    }
    # Numeric defaults
    for col in _STATS_COLUMNS:
        if col not in defaults and col not in ("match_id", "player_id"):
            defaults[col] = 0

    row: dict[str, Any] = {}
    present_fields: list[str] = []
    for col in _STATS_COLUMNS:
        if col in record and record[col] is not None:
            row[col] = record[col]
            if col in ALL_FIELDS:
                present_fields.append(col)
        elif col in defaults:
            row[col] = defaults[col]
        else:
            row[col] = 0

    # Compute available_fields from what the provider actually sent
    if "available_fields" not in record or not record.get("available_fields"):
        row["available_fields"] = json.dumps(sorted(present_fields))

    # Serialise raw_json if it's a dict
    if isinstance(row.get("raw_json"), dict):
        row["raw_json"] = json.dumps(row["raw_json"])

    return row


def upsert_match(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a match metadata row (label, date, score).

    Note: does NOT commit — the caller should batch inserts and commit once.
    """
    # The CSV column is "group"; map it to the reserved-word-safe "group_name".
    source = dict(record)
    if "group_name" not in source and "group" in source:
        source["group_name"] = source["group"]

    int_cols = {"matchday", "home_score", "away_score"}
    cols, vals = [], []
    for col in _MATCHES_COLUMNS:
        cols.append(col)
        default: Any = 0 if col in int_cols else ""
        val = source.get(col, default)
        if val is None:
            # JSON nulls (e.g. TBD knockout teams, unplayed scores) → safe default.
            val = default
        if col in int_cols:
            try:
                val = int(val) if str(val).strip() != "" else 0
            except (TypeError, ValueError):
                val = 0
        vals.append(val)

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    update_sets = ", ".join(
        f"{c} = excluded.{c}" for c in _MATCHES_UPDATE_COLUMNS
    ) + ", updated_at = datetime('now')"

    sql = (
        f"INSERT INTO matches ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(match_id) DO UPDATE SET {update_sets}"
    )
    conn.execute(sql, vals)
    # Caller is responsible for committing the transaction.


def upsert_form_index(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a form-index score row.

    Note: does NOT commit — the caller should batch inserts and commit once.
    """
    cols = []
    vals = []
    for col in _SCORES_COLUMNS:
        cols.append(col)
        val = record.get(col, "")
        if isinstance(val, dict):
            val = json.dumps(val)
        vals.append(val)

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    update_sets = ", ".join(
        f"{c} = excluded.{c}" for c in _SCORES_UPDATE_COLUMNS
    ) + ", updated_at = datetime('now')"

    sql = (
        f"INSERT INTO form_index_scores ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(match_id, player_id, model_version) DO UPDATE SET {update_sets}"
    )
    conn.execute(sql, vals)
    # Caller is responsible for committing the transaction.


def upsert_tournament_form_index(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a cumulative tournament form-index row.

    Note: does NOT commit — the caller should batch inserts and commit once.
    """
    cols = []
    vals = []
    for col in _TOURNAMENT_COLUMNS:
        cols.append(col)
        vals.append(record.get(col, 0))

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    update_sets = ", ".join(
        f"{c} = excluded.{c}" for c in _TOURNAMENT_UPDATE_COLUMNS
    ) + ", updated_at = datetime('now')"

    sql = (
        f"INSERT INTO tournament_form_index ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(tournament_id, player_id, model_version) DO UPDATE SET {update_sets}"
    )
    conn.execute(sql, vals)
    # Caller is responsible for committing the transaction.


def insert_run(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert a run record for deduping publishing/content runs only."""
    cols = ["run_type", "pillar", "provider", "mode", "dry_run", "status"]
    vals = [record.get(c, "") for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    sql = f"INSERT OR IGNORE INTO runs ({col_names}) VALUES ({placeholders})"
    conn.execute(sql, vals)
    conn.commit()


# ── Predictions ─────────────────────────────────────────────────────────────

_PREDICTIONS_COLUMNS = [
    "match_id", "model_version", "predicted_home", "predicted_away",
    "home_win_prob", "draw_prob", "away_win_prob", "top_scorelines", "key_factor",
]
_PREDICTIONS_UPDATE_COLUMNS = [
    "predicted_home", "predicted_away",
    "home_win_prob", "draw_prob", "away_win_prob", "top_scorelines", "key_factor",
]


def upsert_prediction(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a prediction for a match.

    Note: does NOT commit — the caller should batch inserts and commit once.
    """
    cols, vals = [], []
    for col in _PREDICTIONS_COLUMNS:
        cols.append(col)
        val = record.get(col, "" if col == "key_factor" or col == "top_scorelines" else 0)
        if col == "top_scorelines" and isinstance(val, list):
            val = json.dumps(val)
        vals.append(val)

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    update_sets = ", ".join(
        f"{c} = excluded.{c}" for c in _PREDICTIONS_UPDATE_COLUMNS
    )

    sql = (
        f"INSERT INTO predictions ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(match_id, model_version) DO UPDATE SET {update_sets}"
    )
    conn.execute(sql, vals)


def upsert_prediction_result(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a prediction result (auto-graded after match).

    Note: does NOT commit — the caller should batch inserts and commit once.
    """
    cols = ["prediction_id", "actual_home", "actual_away", "correct"]
    vals = [record.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    sql = (
        f"INSERT OR REPLACE INTO prediction_results ({col_names}) VALUES ({placeholders})"
    )
    conn.execute(sql, vals)


def grade_predictions(conn: sqlite3.Connection) -> int:
    """Grade all ungraded predictions where the match result is known.

    Returns the number of predictions graded.
    """
    # Find predictions with finished matches that haven't been graded yet
    rows = conn.execute(
        """
        SELECT p.id, p.match_id, p.predicted_home, p.predicted_away,
               m.home_score, m.away_score
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        LEFT JOIN prediction_results r ON p.id = r.prediction_id
        WHERE m.home_score IS NOT NULL
          AND m.home_score != 0 OR m.away_score != 0
          AND r.id IS NULL
        """
    ).fetchall()

    graded = 0
    for row in rows:
        pred_id, match_id, pred_home, pred_away, actual_home, actual_away = row
        pred_winner = "home" if pred_home > pred_away else ("away" if pred_away > pred_home else "draw")
        actual_winner = "home" if (actual_home or 0) > (actual_away or 0) else (
            "away" if (actual_away or 0) > (actual_home or 0) else "draw"
        )
        correct = 1 if pred_winner == actual_winner else 0

        upsert_prediction_result(conn, {
            "prediction_id": pred_id,
            "actual_home": actual_home,
            "actual_away": actual_away,
            "correct": correct,
        })
        graded += 1

    if graded:
        conn.commit()
    return graded


def get_prediction_accuracy(
    conn: sqlite3.Connection,
    model_version: str = "1.0.0-lite",
) -> dict[str, Any]:
    """Return prediction accuracy stats: total, correct, percentage."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(r.correct) AS correct,
            ROUND(AVG(r.correct) * 100, 1) AS pct
        FROM prediction_results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE p.model_version = ?
        """
        ,
        (model_version,),
    ).fetchone()

    if not row or row["total"] == 0:
        return {"total": 0, "correct": 0, "pct": 0.0}

    return {
        "total": row["total"],
        "correct": row["correct"],
        "pct": row["pct"],
    }