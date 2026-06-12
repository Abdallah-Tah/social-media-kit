"""Measurement: outcome rates per prompt_version (or other grouping).

This is the regression detector — if a new prompt version's corrected%
or rejected% climbs, roll back with ``proposals revert ID``.
"""
from __future__ import annotations

import sqlite3
from typing import Any

_GROUP_COLUMNS = ("prompt_version", "task_type", "pillar", "model_used")


def journal_stats(conn: sqlite3.Connection, by: str = "prompt_version") -> list[dict[str, Any]]:
    """Per-group outcome rates. Percentages are over *graded* runs;
    error rate is over all runs."""
    if by not in _GROUP_COLUMNS:
        raise ValueError(f"--by must be one of: {', '.join(_GROUP_COLUMNS)}")
    rows = conn.execute(
        f"""
        SELECT
            {by} AS grp,
            COUNT(*) AS runs,
            SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
            SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS graded,
            SUM(CASE WHEN outcome = 'approved'  THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN outcome = 'corrected' THEN 1 ELSE 0 END) AS corrected,
            SUM(CASE WHEN outcome = 'rejected'  THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN outcome = 'published' THEN 1 ELSE 0 END) AS published
        FROM agent_runs
        GROUP BY {by}
        ORDER BY grp
        """
    ).fetchall()

    out = []
    for r in rows:
        graded = r["graded"] or 0
        out.append({
            "group": r["grp"] or "(none)",
            "runs": r["runs"],
            "graded": graded,
            "approved_pct": round(100.0 * r["approved"] / graded, 1) if graded else 0.0,
            "corrected_pct": round(100.0 * r["corrected"] / graded, 1) if graded else 0.0,
            "rejected_pct": round(100.0 * r["rejected"] / graded, 1) if graded else 0.0,
            "published": r["published"],
            "error_pct": round(100.0 * r["errors"] / r["runs"], 1) if r["runs"] else 0.0,
        })
    return out


def format_stats(stats: list[dict[str, Any]], by: str) -> str:
    if not stats:
        return "No runs in the journal yet."
    header = (f"{by:<18} {'runs':>5} {'graded':>6} {'appr%':>6} {'corr%':>6} "
              f"{'rej%':>6} {'publ':>5} {'err%':>6}")
    lines = [header, "-" * len(header)]
    for s in stats:
        lines.append(
            f"{s['group']:<18} {s['runs']:>5} {s['graded']:>6} "
            f"{s['approved_pct']:>6} {s['corrected_pct']:>6} "
            f"{s['rejected_pct']:>6} {s['published']:>5} {s['error_pct']:>6}"
        )
    return "\n".join(lines)
