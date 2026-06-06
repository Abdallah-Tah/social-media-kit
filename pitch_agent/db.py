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
    run_type    TEXT    NOT NULL,
    pillar      TEXT    NOT NULL DEFAULT '',
    provider    TEXT    NOT NULL DEFAULT '',
    mode        TEXT    NOT NULL DEFAULT '',
    dry_run     INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_type, pillar, provider, mode, created_at)
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
    """Insert or update a player-match stats row."""
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
    conn.commit()


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
    """Insert or update a match metadata row (label, date, score)."""
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
    conn.commit()


def upsert_form_index(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a form-index score row."""
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
    conn.commit()


def upsert_tournament_form_index(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert or update a cumulative tournament form-index row."""
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
    conn.commit()


def insert_run(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert a run record for deduping publishing/content runs only."""
    cols = ["run_type", "pillar", "provider", "mode", "dry_run", "status"]
    vals = [record.get(c, "") for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    sql = f"INSERT OR IGNORE INTO runs ({col_names}) VALUES ({placeholders})"
    conn.execute(sql, vals)
    conn.commit()