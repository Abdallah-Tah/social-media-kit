"""Run journal: write a row per pipeline step, grade outcomes later.

Design rule: **journaling can never break a content run.** ``record_run``
does no I/O until the step finishes, and the final write is wrapped so
any journal failure becomes a stderr warning, not an exception.
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from agent_journal.db import get_connection

# Outcomes a human (or the publish step) may assign.
VALID_OUTCOMES = ("approved", "corrected", "rejected", "published")


def current_prompt_version() -> str:
    """Read PROMPT_VERSION from the single source of truth (agent.prompts)."""
    try:
        from agent.prompts import PROMPT_VERSION
        return PROMPT_VERSION
    except Exception:
        return ""


@dataclass
class RunRecord:
    """Mutable record handed to the instrumented step; written on exit."""
    task_type: str
    pillar: str = ""
    model_used: str = ""
    prompt_version: str = ""
    input_summary: str = ""
    output_ref: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    outcome: str | None = None
    outcome_detail: str | None = None
    run_id: int | None = None  # set after the row is written


@contextmanager
def record_run(
    task_type: str,
    *,
    pillar: str = "",
    model_used: str = "",
    input_summary: str = "",
    db_path: str | None = None,
) -> Iterator[RunRecord]:
    """Journal one pipeline step.

    Usage::

        with record_run("generate", pillar="match_recap") as rec:
            result = do_work()
            rec.model_used = "claude-..."

    An exception inside the block fills ``rec.error`` and re-raises (the
    caller's own error handling is untouched). Journal write failures are
    swallowed with a stderr warning.
    """
    rec = RunRecord(
        task_type=task_type,
        pillar=pillar,
        model_used=model_used,
        prompt_version=current_prompt_version(),
        input_summary=input_summary,
    )
    start = time.monotonic()
    try:
        yield rec
    except Exception as exc:
        if rec.error is None:
            rec.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            _write_run(rec, duration_ms, db_path)
        except Exception as exc:  # noqa: BLE001 — journaling must never crash the run
            print(f"[agent_journal] WARNING: failed to write journal row: {exc}",
                  file=sys.stderr)


def _write_run(rec: RunRecord, duration_ms: int, db_path: str | None) -> None:
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO agent_runs
               (task_type, pillar, model_used, prompt_version, input_summary,
                output_ref, tool_calls_json, error, duration_ms,
                outcome, outcome_detail, outcome_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       CASE WHEN ? IS NULL THEN NULL ELSE datetime('now') END)""",
            (
                rec.task_type, rec.pillar, rec.model_used, rec.prompt_version,
                rec.input_summary[:500], rec.output_ref[:500],
                json.dumps(rec.tool_calls)[:10000], rec.error, duration_ms,
                rec.outcome, rec.outcome_detail, rec.outcome,
            ),
        )
        conn.commit()
        rec.run_id = cur.lastrowid
    finally:
        conn.close()


def grade_run(conn, run_id: int, outcome: str, note: str | None = None) -> dict[str, Any]:
    """Manually grade a run. Raises ``ValueError`` on bad outcome/run id."""
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"Invalid outcome '{outcome}'. Valid: {', '.join(VALID_OUTCOMES)}"
        )
    row = conn.execute("SELECT id, outcome FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"Run {run_id} not found")
    conn.execute(
        "UPDATE agent_runs SET outcome = ?, outcome_detail = ?, "
        "outcome_at = datetime('now') WHERE id = ?",
        (outcome, note, run_id),
    )
    conn.commit()
    return {"run_id": run_id, "outcome": outcome, "previous_outcome": row["outcome"]}


def list_runs(conn, last: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, started_at, task_type, pillar, model_used, prompt_version, "
        "outcome, error, duration_ms FROM agent_runs ORDER BY id DESC LIMIT ?",
        (last,),
    ).fetchall()
    return [dict(r) for r in rows]
