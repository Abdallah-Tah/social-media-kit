"""SQLite layer for the Taco run journal.

Mirrors ``pitch_agent/db.py``: ``IF NOT EXISTS`` schema, idempotent
column migrations via ``PRAGMA table_info``, WAL mode, ``Row`` factory.
Writers do not commit inside helpers unless documented.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def default_db_path() -> str:
    """Journal DB path: ``TACO_JOURNAL_DB`` env var, else repo-root file.

    Anchored to the repo root (not the CWD like pitch_agent.db) so cron
    jobs and interactive runs always hit the same database.
    """
    return os.environ.get("TACO_JOURNAL_DB", str(REPO_ROOT / "agent_journal.db"))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    task_type       TEXT    NOT NULL,
    pillar          TEXT    NOT NULL DEFAULT '',
    model_used      TEXT    NOT NULL DEFAULT '',
    prompt_version  TEXT    NOT NULL DEFAULT '',
    input_summary   TEXT    NOT NULL DEFAULT '',
    output_ref      TEXT    NOT NULL DEFAULT '',
    tool_calls_json TEXT    NOT NULL DEFAULT '[]',
    error           TEXT    DEFAULT NULL,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    outcome         TEXT    DEFAULT NULL,
    outcome_detail  TEXT    DEFAULT NULL,
    outcome_at      TEXT    DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    source_run_ids  TEXT    NOT NULL DEFAULT '[]',
    type            TEXT    NOT NULL,
    target          TEXT    NOT NULL DEFAULT '',
    change          TEXT    NOT NULL DEFAULT '',
    evidence        TEXT    NOT NULL DEFAULT '',
    expected_effect TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'pending',
    decided_at      TEXT    DEFAULT NULL,
    decision_note   TEXT    DEFAULT NULL,
    applied_rule_id INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS reflections (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    requested_model   TEXT    NOT NULL DEFAULT '',
    responded_model   TEXT    NOT NULL DEFAULT '',
    runs_count        INTEGER NOT NULL DEFAULT 0,
    run_id_min        INTEGER DEFAULT NULL,
    run_id_max        INTEGER DEFAULT NULL,
    proposals_created INTEGER NOT NULL DEFAULT 0,
    error             TEXT    DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_outcome ON agent_runs(task_type, outcome);
CREATE INDEX IF NOT EXISTS idx_runs_version ON agent_runs(prompt_version);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
"""


# Columns added after a table first shipped: (table, column, definition).
# Applied only when missing — same pattern as pitch_agent's migrations.
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = []


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Create tables, apply migrations, and return a connection."""
    conn = sqlite3.connect(db_path or default_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Return a connection, ensuring the schema exists (idempotent)."""
    return init_db(db_path)


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Ensure the schema is current; return the list of columns added."""
    conn.executescript(SCHEMA_SQL)
    added: list[str] = []
    for table, column, definition in _COLUMN_MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            added.append(f"{table}.{column}")
    conn.commit()
    return added


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
