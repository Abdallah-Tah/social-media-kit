"""Fixture queries — upcoming/known matches from the ``matches`` table.

Fixtures are useful before any player grades exist: they power the
``fixtures`` CLI command, the fixtures chart, and the ``matchday_preview``
content pillar.

A single render must come from **one** data source: when football-data rows
exist they are preferred and CSV/demo/legacy rows are excluded, so a real
fixture preview never mixes synced data with sample rows. See
:func:`get_fixtures` (``provider_name`` filtering + deduplication) and
:func:`normalize_stage_label` (group/stage label normalization).
"""
from __future__ import annotations

import sqlite3
from typing import Any

# Provider whose rows are preferred for "real" fixture previews.
PRIMARY_PROVIDER = "football-data"

# Knockout / phase codes mapped to human labels. Group letters are handled
# separately in :func:`normalize_stage_label`.
_STAGE_LABELS = {
    "GROUP_STAGE": "Group stage",
    "LAST_32": "Round of 32",
    "ROUND_OF_32": "Round of 32",
    "LAST_16": "Round of 16",
    "ROUND_OF_16": "Round of 16",
    "QUARTER_FINALS": "Quarter-final",
    "QUARTER_FINAL": "Quarter-final",
    "SEMI_FINALS": "Semi-final",
    "SEMI_FINAL": "Semi-final",
    "THIRD_PLACE": "Third-place play-off",
    "THIRD_PLACE_PLAYOFF": "Third-place play-off",
    "FINAL": "Final",
    "PLAYOFFS": "Play-offs",
    "PRELIMINARY_ROUND": "Preliminary round",
}


def normalize_stage_label(value: str | None) -> str:
    """Normalize a group/stage code to a human-facing label.

    Idempotent. Examples::

        "A"        -> "Group A"
        "GROUP A"  -> "Group A"
        "GROUP_A"  -> "Group A"
        "Group A"  -> "Group A"
        "B"        -> "Group B"
        "LAST_16"  -> "Round of 16"
        ""/None    -> ""

    Unknown codes are humanized safely (underscores → spaces, title case).
    """
    text = str(value or "").strip()
    if not text:
        return ""

    canonical = text.replace("-", "_").replace(" ", "_").upper().strip("_")
    while "__" in canonical:
        canonical = canonical.replace("__", "_")

    if canonical in _STAGE_LABELS:
        return _STAGE_LABELS[canonical]

    # Group forms: "A", "GROUP_A", "GROUP A" all collapse to a single letter.
    token = canonical
    if token.startswith("GROUP_"):
        token = token[len("GROUP_"):]
    if len(token) == 1 and token.isalpha():
        return f"Group {token}"

    # Safe humanized fallback for anything else.
    return text.replace("_", " ").title()


def _provider_of(row: Any) -> str:
    """Lower-cased provider name for a match row (sqlite Row or dict)."""
    try:
        value = row["provider_name"]
    except (KeyError, IndexError, TypeError):
        value = ""
    return str(value or "").strip().lower()


def _select_by_provider(
    rows: list[Any], provider_name: str | None
) -> list[Any]:
    """Pick rows from a single provider.

    * Explicit ``provider_name`` → only that provider's rows. For
      ``football-data`` this excludes CSV and legacy/null-provider rows.
    * No ``provider_name`` (auto) → prefer football-data rows when any exist;
      otherwise fall back to whatever is stored (CSV/legacy/demo).
    """
    requested = (provider_name or "").strip().lower()
    if requested:
        return [r for r in rows if _provider_of(r) == requested]

    primary = [r for r in rows if _provider_of(r) == PRIMARY_PROVIDER]
    return primary if primary else rows


def _dedupe(rows: list[Any]) -> list[Any]:
    """Drop duplicate fixtures, preserving order.

    Dedupe by ``external_id`` first; when it is missing, dedupe by
    ``date`` + ``home_team_name`` + ``away_team_name`` + ``competition_id`` so
    the same fixture from a re-sync or a second provider is shown only once.
    """
    seen_ext: set[str] = set()
    seen_key: set[tuple[str, str, str, str]] = set()
    out: list[Any] = []
    for r in rows:
        ext = str(r["external_id"] or "").strip()
        if ext:
            if ext in seen_ext:
                continue
            seen_ext.add(ext)
        else:
            key = (
                str(r["date"] or "")[:10],
                str(r["home_team_name"] or "").strip().lower(),
                str(r["away_team_name"] or "").strip().lower(),
                str(r["competition_id"] or "").strip().lower(),
            )
            if key in seen_key:
                continue
            seen_key.add(key)
        out.append(r)
    return out


def get_fixtures(
    db_path: str = "pitch_agent.db",
    competition_id: str | None = None,
    limit: int = 10,
    provider_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return stored fixtures ordered by date (earliest first).

    Parameters
    ----------
    competition_id:
        Restrict to one competition (e.g. ``"WC"``) when provided.
    provider_name:
        Restrict to a single data source. When omitted, football-data rows are
        preferred and CSV/legacy rows are used only if no football-data rows
        exist — so a real preview never mixes sources.

    Each fixture dict has: ``match_id``, ``external_id``, ``competition_id``,
    ``date``, ``stage``, ``group_name``, ``home_team_name``, ``away_team_name``,
    ``home_score``, ``away_score``, ``status``, ``provider_name``, and a derived
    ``match_label`` (``Home vs Away`` or ``TBD`` when teams are unknown).
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        query = (
            "SELECT match_id, external_id, competition_id, date, stage, "
            "group_name, home_team_name, away_team_name, home_score, "
            "away_score, status, provider_name "
            "FROM matches"
        )
        params: list[Any] = []
        if competition_id:
            query += " WHERE competition_id = ?"
            params.append(competition_id)
        # Order before limiting; provider selection/dedup happen on the full set
        # so filtering can never let a stale row leak past the LIMIT window.
        query += " ORDER BY date ASC, match_id ASC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return []

    rows = _select_by_provider(rows, provider_name)
    rows = _dedupe(rows)
    rows = rows[: max(int(limit), 0)] if limit else rows

    fixtures = []
    for row in rows:
        home = row["home_team_name"]
        away = row["away_team_name"]
        fixtures.append({
            "match_id": row["match_id"],
            "external_id": row["external_id"],
            "competition_id": row["competition_id"],
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
