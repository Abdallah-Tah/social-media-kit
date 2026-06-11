"""Poisson scoreline probability distribution for match predictions.

Uses independent Poisson distributions for each team's goal count,
parameterised by expected goals (xG). Provides top-N most likely scorelines,
win/draw/away probabilities, and a Form-Index-to-xG mapping for when
no external xG source is available.
"""
from __future__ import annotations

import math
from typing import Any


def poisson_prob(lam: float, k: int) -> float:
    """P(k goals | lambda expected goals)."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def scoreline_distribution(
    home_xg: float,
    away_xg: float,
    max_goals: int = 7,
) -> list[dict[str, Any]]:
    """Return all scorelines with probabilities, sorted by likelihood.

    Each entry: ``{"home_goals": h, "away_goals": a,
    "probability": p, "label": "h-a"}``.
    """
    results: list[dict[str, Any]] = []
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            prob = poisson_prob(home_xg, h) * poisson_prob(away_xg, a)
            results.append({
                "home_goals": h,
                "away_goals": a,
                "probability": round(prob, 4),
                "label": f"{h}-{a}",
            })
    results.sort(key=lambda r: r["probability"], reverse=True)
    return results


def top_scorelines(
    home_xg: float,
    away_xg: float,
    n: int = 3,
) -> list[dict[str, Any]]:
    """Top N most likely scorelines with probabilities."""
    dist = scoreline_distribution(home_xg, away_xg)
    return dist[:n]


def match_outcome_probs(
    home_xg: float,
    away_xg: float,
) -> dict[str, float]:
    """Home win / draw / away win probabilities from Poisson xG."""
    dist = scoreline_distribution(home_xg, away_xg)
    home_win = sum(r["probability"] for r in dist if r["home_goals"] > r["away_goals"])
    draw = sum(r["probability"] for r in dist if r["home_goals"] == r["away_goals"])
    away_win = sum(r["probability"] for r in dist if r["home_goals"] < r["away_goals"])
    return {
        "home_win": round(home_win, 3),
        "draw": round(draw, 3),
        "away_win": round(away_win, 3),
    }


# ── Form Index → xG mapping ──────────────────────────────────────────────
# Empirical calibration: a team averaging 70+ Form Index against one averaging
# 50 should produce ~2.0 xG vs ~0.8.  Linear interpolation between bands.
# This is the minimum viable model; replace with Elo-xG when rich data arrives.

_FI_XG_TABLE: list[tuple[float, float]] = [
    # (Form Index differential, home_xG_boost, away_xG_boost)
    # Higher diff → more home xG, less away xG
    (-30, 0.7, 1.8),
    (-20, 0.9, 1.6),
    (-10, 1.1, 1.3),
    (0, 1.3, 1.1),
    (10, 1.6, 0.9),
    (20, 1.8, 0.7),
    (30, 2.0, 0.6),
    (40, 2.2, 0.5),
]

_BASE_HOME_XG = 1.3
_BASE_AWAY_XG = 1.1


def form_index_to_xg(
    home_avg: float,
    away_avg: float,
) -> tuple[float, float]:
    """Convert average Form Index scores to expected goals.

    Uses a calibration table that maps the Form Index differential to
    home/away xG.  The baseline (diff=0) yields 1.3–1.1 xG, roughly
    matching typical World Cup group-stage averages.
    """
    diff = home_avg - away_avg

    # Clamp to table bounds
    if diff <= _FI_XG_TABLE[0][0]:
        return _FI_XG_TABLE[0][1], _FI_XG_TABLE[0][2]
    if diff >= _FI_XG_TABLE[-1][0]:
        return _FI_XG_TABLE[-1][1], _FI_XG_TABLE[-1][2]

    # Linear interpolation between the two nearest table entries
    for i in range(len(_FI_XG_TABLE) - 1):
        d_lo, hx_lo, ax_lo = _FI_XG_TABLE[i]
        d_hi, hx_hi, ax_hi = _FI_XG_TABLE[i + 1]
        if d_lo <= diff <= d_hi:
            t = (diff - d_lo) / (d_hi - d_lo)
            home_xg = hx_lo + t * (hx_hi - hx_lo)
            away_xg = ax_lo + t * (ax_hi - ax_lo)
            return round(home_xg, 2), round(away_xg, 2)

    # Fallback (should not reach here)
    return _BASE_HOME_XG, _BASE_AWAY_XG


def prediction_key_factor(
    home_scores: list[dict[str, Any]],
    away_scores: list[dict[str, Any]],
) -> str:
    """Return the single biggest factor driving the prediction.

    Compares average Form Index, goals, and team result between the two
    sides and returns a one-line explanation.
    """
    if not home_scores and not away_scores:
        return "Evenly matched — insufficient data"

    home_avg = (
        sum(s.get("score", 0) for s in home_scores) / len(home_scores)
        if home_scores else 50
    )
    away_avg = (
        sum(s.get("score", 0) for s in away_scores) / len(away_scores)
        if away_scores else 50
    )
    diff = home_avg - away_avg

    if abs(diff) < 3:
        return "Evenly matched — Form Index within 3 points"

    leader = "Home" if diff > 0 else "Away"
    abs_diff = abs(diff)

    home_goals = sum(s.get("goals", 0) for s in home_scores) / max(len(home_scores), 1)
    away_goals = sum(s.get("goals", 0) for s in away_scores) / max(len(away_scores), 1)

    if abs(home_goals - away_goals) >= 0.5:
        return (
            f"{leader} +{abs_diff:.0f} Form Index "
            f"(goals avg {home_goals:.1f} vs {away_goals:.1f})"
        )
    return f"{leader} +{abs_diff:.0f} Form Index differential"