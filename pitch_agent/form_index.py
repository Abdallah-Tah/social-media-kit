"""Form Index v1.1 scoring formula.

Computes a per-player per-match Form Index score from basic stats.
Missing fields default to 0 and never crash the calculation.

Scoring rules:
    base 50, goals × 18, assists × 10, team win +3, clean sheet +5
    yellow cards × -2, red cards × -10, own goals × -5

Minutes adjustment:
    unknown (-1) → multiplier from config (default 0.90)
    < 15 min  → multiplier 0.50
    15–44 min → multiplier 0.90
    ≥ 45 min  → multiplier 1.00
    Exception: if goals > 0 or assists > 0, the adjusted score is
    never reduced below 70 % of the raw (pre-multiplier) score.

Position bonuses (applied AFTER minutes adjustment):
    MID: +3 if pass_accuracy ≥ 88 and minutes ≥ 45
    GK:  +5 if shots_faced > 0 and saves / shots_faced ≥ 0.80
"""
from __future__ import annotations

import json
from typing import Any

from pitch_agent import MODEL_VERSION_LABEL
from pitch_agent.config import ALL_FIELDS, BASIC_FIELDS, RICH_FIELDS

# Scoring weights
BASE_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0
GOAL_WEIGHT = 18.0
ASSIST_WEIGHT = 10.0
TEAM_WIN_BONUS = 3.0
CLEAN_SHEET_BONUS = 5.0
YELLOW_CARD_PENALTY = -2.0
RED_CARD_PENALTY = -10.0
OWN_GOAL_PENALTY = -5.0

# Minutes thresholds
MINUTES_SHORT = 15
MINUTES_MEDIUM = 45
MINUTES_UNKNOWN = -1  # Sentinel: free-tier providers don't have per-player minutes
MULTIPLIER_SHORT = 0.50
MULTIPLIER_MEDIUM = 0.90
MULTIPLIER_FULL = 1.00
MULTIPLIER_UNKNOWN = None  # Loaded from config; falls back to 0.90
GOAL_ASSIST_FLOOR = 0.70

# Position bonus thresholds
MID_PASS_ACCURACY_THRESHOLD = 88.0


def _load_unknown_minutes_multiplier() -> float:
    """Load the unknown-minutes multiplier from config, falling back to 0.90."""
    try:
        from pitch_agent.config import PitchAgentConfig
        cfg = PitchAgentConfig.load()
        return cfg.unknown_minutes_multiplier
    except Exception:
        return 0.90
MID_MINUTES_THRESHOLD = 45
GK_SAVE_RATIO_THRESHOLD = 0.80

MODEL_VERSION = "1.1.0"


def compute_form_index(stats: dict[str, Any]) -> dict[str, Any]:
    """Compute the Form Index v1.1 for a single player-match.

    Parameters
    ----------
    stats : dict
        Player-match statistics.  Missing fields default to 0.

    Returns
    -------
    dict
        ``{"score": float, "breakdown": dict}`` with full breakdown
        including ``fields_present``, ``fields_absent``, ``provider_name``,
        ``data_quality_level``, ``model_version``, etc.
    """
    # ── Default missing fields ────────────────────────────────────────
    original_keys = set(stats.keys())
    safe: dict[str, Any] = {}

    for f in ALL_FIELDS:
        if f in stats and stats[f] is not None:
            safe[f] = stats[f]
        elif f == "team_result":
            safe[f] = stats.get(f, "")
        else:
            safe[f] = 0

    # Also carry identity fields through
    for f in ("player_name", "team_id", "team_name", "position",
              "match_id", "player_id", "competition_id", "season",
              "matchday", "stage", "provider_name", "data_quality_level"):
        safe[f] = stats.get(f, "")

    # ── Track present / absent ────────────────────────────────────────
    available_fields = _parse_available_fields(stats.get("available_fields"))
    if available_fields is not None:
        fields_present = sorted(f for f in available_fields if f in ALL_FIELDS)
        fields_absent = sorted(f for f in ALL_FIELDS if f not in fields_present)
    else:
        fields_present = []
        fields_absent = []
        for f in ALL_FIELDS:
            if f in original_keys and stats.get(f) is not None:
                fields_present.append(f)
            else:
                fields_absent.append(f)

    # ── Scoring components ────────────────────────────────────────────
    goal_score = safe["goals"] * GOAL_WEIGHT
    assist_score = safe["assists"] * ASSIST_WEIGHT
    team_win_bonus = TEAM_WIN_BONUS if safe["team_result"] == "WIN" else 0.0
    clean_sheet_bonus = CLEAN_SHEET_BONUS if safe.get("clean_sheet", 0) == 1 else 0.0
    yellow_penalty = safe["yellow_cards"] * YELLOW_CARD_PENALTY
    red_penalty = safe["red_cards"] * RED_CARD_PENALTY
    own_goal_penalty = safe.get("own_goals", 0) * OWN_GOAL_PENALTY

    action_total = (
        goal_score + assist_score + team_win_bonus + clean_sheet_bonus
        + yellow_penalty + red_penalty + own_goal_penalty
    )
    raw_score = BASE_SCORE + action_total

    # ── Minutes adjustment ────────────────────────────────────────────
    minutes = safe["minutes"]

    if minutes == MINUTES_UNKNOWN:
        # Free-tier providers don't provide per-player minutes.
        # Use configurable multiplier (default 0.90) to acknowledge uncertainty.
        multiplier = MULTIPLIER_UNKNOWN or _load_unknown_minutes_multiplier()
    elif minutes < MINUTES_SHORT:
        multiplier = MULTIPLIER_SHORT
    elif minutes < MINUTES_MEDIUM:
        multiplier = MULTIPLIER_MEDIUM
    else:
        multiplier = MULTIPLIER_FULL

    adjusted_score = raw_score * multiplier

    # ── Goal/assist floor exception ───────────────────────────────────
    if safe["goals"] > 0 or safe["assists"] > 0:
        floor = raw_score * GOAL_ASSIST_FLOOR
        adjusted_score = max(adjusted_score, floor)

    # ── Position bonuses ──────────────────────────────────────────────
    position = str(safe.get("position", "")).upper()
    position_bonus = 0.0

    # Midfielder bonus: +3 if pass_accuracy ≥ 88 and (minutes ≥ 45 or unknown)
    if position == "MID":
        if safe["pass_accuracy"] >= MID_PASS_ACCURACY_THRESHOLD and minutes >= MID_MINUTES_THRESHOLD:
            position_bonus += 3.0

    # Goalkeeper bonus: +5 if shots_faced > 0 and saves/shots_faced ≥ 0.80
    if position == "GK" and safe["shots_faced"] > 0:
        if safe["saves"] / safe["shots_faced"] >= GK_SAVE_RATIO_THRESHOLD:
            position_bonus += 5.0

    # ── Final score ────────────────────────────────────────────────────
    final_score = _clamp_score(adjusted_score + position_bonus)

    # ── Breakdown ──────────────────────────────────────────────────────
    breakdown = {
        "model_version": stats.get("model_version", MODEL_VERSION),
        "model_version_label": MODEL_VERSION_LABEL,
        "provider_name": safe.get("provider_name", ""),
        "data_quality_level": safe.get("data_quality_level", "basic"),
        "fields_present": sorted(fields_present),
        "fields_absent": sorted(fields_absent),
        "base": int(BASE_SCORE),
        "goal": goal_score,
        "assist": assist_score,
        "team_win": team_win_bonus,
        "clean_sheet": clean_sheet_bonus,
        "yellow_cards": yellow_penalty,
        "red_cards": red_penalty,
        "own_goals": own_goal_penalty,
        "raw_score_before_minutes": raw_score,
        "minutes_adjustment": multiplier,
        "position_bonus": position_bonus,
        "final_score": final_score,
    }

    return {"score": final_score, "breakdown": breakdown}


def _clamp_score(score: float) -> float:
    """Clamp the public Form Index score to the 0-100 range."""
    return min(MAX_SCORE, max(MIN_SCORE, score))


def _parse_available_fields(value: Any) -> set[str] | None:
    """Return provider-declared available fields when present."""
    if not value:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [v.strip() for v in value.split(",")]
    else:
        parsed = value
    if not isinstance(parsed, (list, tuple, set)):
        return None
    return {str(v) for v in parsed}


def compute_all(db_path: str = "pitch_agent.db", model_version: str = MODEL_VERSION) -> int:
    """Compute Form Index for all player_match_stats rows and upsert scores.

    Returns the number of scores computed.
    """
    from pitch_agent.db import (
        get_connection,
        upsert_form_index,
        upsert_tournament_form_index,
    )

    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM player_match_stats"
    ).fetchall()

    count = 0
    for row in rows:
        row_dict = dict(row)
        result = compute_form_index(row_dict)
        upsert_form_index(conn, {
            "match_id": row_dict["match_id"],
            "player_id": row_dict["player_id"],
            "model_version": model_version,
            "score": result["score"],
            "score_breakdown_json": json.dumps(result["breakdown"]),
        })
        count += 1

    # Commit all form index scores in one batch
    conn.commit()

    tournament_rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(p.competition_id, ''), 'default') AS tournament_id,
            s.player_id,
            SUM(s.score) AS cumulative_score,
            COUNT(*) AS matches_played
        FROM form_index_scores s
        JOIN player_match_stats p
            ON s.match_id = p.match_id AND s.player_id = p.player_id
        WHERE s.model_version = ?
        GROUP BY tournament_id, s.player_id
        """,
        (model_version,),
    ).fetchall()
    for row in tournament_rows:
        upsert_tournament_form_index(conn, {
            "tournament_id": row["tournament_id"],
            "player_id": row["player_id"],
            "model_version": model_version,
            "cumulative_score": row["cumulative_score"],
            "matches_played": row["matches_played"],
        })

    # Commit tournament scores in one batch
    conn.commit()
    conn.close()
    return count
