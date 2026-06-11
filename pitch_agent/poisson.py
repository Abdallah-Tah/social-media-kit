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


def resolve_predicted_outcome(
    outcomes: dict[str, float],
    top_scoreline: dict[str, Any] | None = None,
) -> str:
    """Resolve the predicted outcome from outcome probabilities.

    Uses argmax of (home_win, draw, away_win). When two outcomes
    have equal probability, the tie is broken by preferring the
    outcome that contains the most likely scoreline.

    For example, if home_win=0.35 and draw=0.35, but the most
    likely scoreline is 1-1 (a draw), the predicted outcome is
    'draw'. If the most likely scoreline is 1-0 (a home win),
    the predicted outcome is 'home'.
    """
    probs = {"home": outcomes["home_win"], "draw": outcomes["draw"], "away": outcomes["away_win"]}
    max_prob = max(probs.values())
    # Find all outcomes tied for max
    tied = [k for k, v in probs.items() if v == max_prob]
    if len(tied) == 1:
        return tied[0]

    # Tie-break: prefer the outcome containing the most likely scoreline
    if top_scoreline is not None:
        h = top_scoreline.get("home_goals", 0)
        a = top_scoreline.get("away_goals", 0)
        if h > a:
            scoreline_outcome = "home"
        elif h < a:
            scoreline_outcome = "away"
        else:
            scoreline_outcome = "draw"
        if scoreline_outcome in tied:
            return scoreline_outcome

    # Final fallback: prefer home > draw > away (home-field advantage)
    for pref in ("home", "draw", "away"):
        if pref in tied:
            return pref
    return "home"


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


# ── Elo prior → xG ────────────────────────────────────────────────────────

def elo_to_xg(home_elo: float, away_elo: float) -> tuple[float, float]:
    """Convert Elo ratings to expected goals using the standard formula.

    Uses the Elo expected-score formula (base-10, 400-point scale):
        E_home = 1 / (1 + 10**((away_elo - home_elo) / 400))

    Then maps expected-score differential to xG:
    - A 200-point Elo gap ≈ 76% expected score ≈ 65/35 outcome split
    - A 0-point gap → 50/50 → 1.3/1.1 baseline xG
    - Calibration: home_xG = base * (0.5 + 0.5 * E_home) * home_bonus
                    away_xG = base * (0.5 + 0.5 * E_away) * away_penalty
    """
    # Standard Elo expected score
    e_home = 1.0 / (1.0 + 10 ** ((away_elo - home_elo) / 400.0))
    e_away = 1.0 - e_home

    # Map expected score to xG
    # At 50/50: home=1.3, away=1.1 (baseline)
    # At 65/35: home=1.9, away=0.7 (strong home favorite)
    # At 35/65: home=0.7, away=1.9 (strong away favorite)
    # Home advantage baked in: even at 50/50 Elo, home gets 1.3 vs 1.1
    home_xg = 0.6 + 2.0 * e_home  # 50%→1.6, 76%→2.1, 35%→1.3
    away_xg = 0.6 + 2.0 * e_away  # 50%→1.6, 24%→1.1, 65%→1.9

    # Apply home-field advantage: scale home up, away down slightly
    home_xg *= 0.95  # adjusts so 50/50 yields ~1.3/1.1
    away_xg *= 0.85

    return round(home_xg, 2), round(away_xg, 2)


def predict_xg(
    home_team: str,
    away_team: str,
    home_avg_fi: float | None,
    away_avg_fi: float | None,
    home_elo: float | None,
    away_elo: float | None,
    home_matches: int = 0,
) -> tuple[float, float, str]:
    """Blend Elo-prior xG and Form-Index xG based on matches played.

    Returns (home_xg, away_xg, basis) where basis is one of:
    - ``'elo_prior'``: no FI data, pure Elo
    - ``'blended'``: partial FI data (1-2 matches)
    - ``'form_index'``: full FI data (3+ matches)

    Blend weight: n = min(3, home_matches)
    xG = prior_xg * (1 - n/3) + fi_xg * (n/3)
    """
    # Elo-based xG (fallback if no Elo data, use mid-range prior)
    if home_elo is not None and away_elo is not None:
        prior_xg = elo_to_xg(home_elo, away_elo)
    else:
        # No Elo either — use baseline
        prior_xg = (_BASE_HOME_XG, _BASE_AWAY_XG)

    # FI-based xG
    if home_avg_fi is not None and away_avg_fi is not None:
        fi_xg = form_index_to_xg(home_avg_fi, away_avg_fi)
    else:
        fi_xg = None

    # Decide basis
    if fi_xg is None:
        # No FI data at all
        return prior_xg[0], prior_xg[1], "elo_prior"

    n = min(3, home_matches)
    if n == 0:
        return prior_xg[0], prior_xg[1], "elo_prior"
    elif n < 3:
        # Blend
        weight = n / 3.0
        home_xg = prior_xg[0] * (1 - weight) + fi_xg[0] * weight
        away_xg = prior_xg[1] * (1 - weight) + fi_xg[1] * weight
        return round(home_xg, 2), round(away_xg, 2), "blended"
    else:
        # Full FI
        return fi_xg[0], fi_xg[1], "form_index"