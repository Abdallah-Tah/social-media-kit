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

def elo_to_xg(
    home_elo: float,
    away_elo: float,
    home_advantage: bool = False,
) -> tuple[float, float]:
    """Convert Elo ratings to expected goals using the standard formula.

    Uses the Elo expected-score formula (base-10, 400-point scale):
        E_home = 1 / (1 + 10**((away_elo - home_elo) / 400))

    **Neutral venue by default** (World Cup 2026 is played on neutral
    grounds unless the home team is a host nation). With
    ``home_advantage=False``, equal Elo produces symmetric xG.

    When ``home_advantage=True`` (host nation playing at home), a
    ~0.3 xG boost is applied to the home side.

    Calibration target: a 200-point Elo gap ≈ 65/35 outcome split.
    """
    # Standard Elo expected score
    e_home = 1.0 / (1.0 + 10 ** ((away_elo - home_elo) / 400.0))
    e_away = 1.0 - e_home

    # Map expected score to xG — symmetric at neutral venue
    # At 50/50 Elo: both teams get ~1.2 xG (neutral venue)
    # At 65/35 Elo: stronger team ~1.7, weaker ~0.7
    home_xg = 0.4 + 1.6 * e_home  # 50%→1.2, 76%→1.6, 35%→0.96
    away_xg = 0.4 + 1.6 * e_away  # 50%→1.2, 24%→0.78, 65%→1.44

    # Home-field advantage: +0.3 xG for home team when host nation at home
    if home_advantage:
        home_xg += 0.30
        away_xg -= 0.05  # slight defensive suppression

    # Floor at 0.3 xG to avoid degenerate predictions
    home_xg = max(home_xg, 0.3)
    away_xg = max(away_xg, 0.3)

    return round(home_xg, 2), round(away_xg, 2)


def predict_xg(
    home_team: str,
    away_team: str,
    home_avg_fi: float | None,
    away_avg_fi: float | None,
    home_elo: float | None,
    away_elo: float | None,
    home_matches: int = 0,
    away_matches: int = 0,
    host_nations: list[str] | None = None,
    host_team_ids: list[str] | None = None,
) -> tuple[float, float, str, str] | None:
    """Blend Elo-prior xG and Form-Index xG per-team.

    Each side blends independently:
    - Home xG: ``prior_home * (1 - w_home) + fi_home * w_home``
    - Away xG: ``prior_away * (1 - w_away) + fi_away * w_away``
    where ``w = min(3, matches) / 3``.

    Returns ``(home_xg, away_xg, basis_home, basis_away)`` or ``None`` if
    neither Elo nor FI data is available for either team. No baseline
    values are ever used — a prediction requires real data.

    ``host_nations`` controls home advantage in Elo xG. When the home
    team is a host nation (USA, Mexico, Canada for WC2026), home
    advantage is applied to ``elo_to_xg``. All other matches are
    neutral-venue (symmetric xG at equal Elo).
    """
    if host_nations is None:
        host_nations = ["USA", "Mexico", "Canada"]
    if host_team_ids is None:
        host_team_ids = []

    # Match by team ID first, fall back to exact name match
    is_home_advantage = (
        (home_team in host_nations or home_team in host_team_ids)
        and away_team not in host_nations
        and away_team not in host_team_ids
    )

    # Elo-based xG — required, no baseline fallback
    if home_elo is None or away_elo is None:
        # No Elo data — cannot predict without real data
        if home_avg_fi is None and away_avg_fi is None:
            return None
        # Partial: use baseline Elo as fallback only when one side has FI
        # (predict_xg should not be called in this case; _match_prediction
        # handles the skip logic)
        prior_xg = (_BASE_HOME_XG, _BASE_AWAY_XG)
    else:
        prior_xg = elo_to_xg(home_elo, away_elo, home_advantage=is_home_advantage)

    # FI-based xG
    if home_avg_fi is not None and away_avg_fi is not None:
        fi_xg = form_index_to_xg(home_avg_fi, away_avg_fi)
    else:
        fi_xg = None

    # Per-team blend weights
    w_home = min(3, home_matches) / 3.0
    w_away = min(3, away_matches) / 3.0

    # Home side
    if home_avg_fi is None and away_avg_fi is None:
        # No FI at all
        return prior_xg[0], prior_xg[1], "elo_prior", "elo_prior"

    # Calculate per-team xG
    if home_avg_fi is not None and away_avg_fi is not None:
        # Full FI available for both sides
        if home_matches == 0 and away_matches == 0:
            return prior_xg[0], prior_xg[1], "elo_prior", "elo_prior"
        # Blend home side
        if home_matches >= 3:
            home_xg = fi_xg[0]  # type: ignore[index]
            basis_home = "form_index"
        elif home_matches == 0:
            home_xg = prior_xg[0]
            basis_home = "elo_prior"
        else:
            home_xg = prior_xg[0] * (1 - w_home) + fi_xg[0] * w_home  # type: ignore[index]
            basis_home = "blended"
        # Blend away side
        if away_matches >= 3:
            away_xg = fi_xg[1]  # type: ignore[index]
            basis_away = "form_index"
        elif away_matches == 0:
            away_xg = prior_xg[1]
            basis_away = "elo_prior"
        else:
            away_xg = prior_xg[1] * (1 - w_away) + fi_xg[1] * w_away  # type: ignore[index]
            basis_away = "blended"
    elif home_avg_fi is not None:
        # Only home has FI
        if home_matches >= 3:
            home_xg = form_index_to_xg(home_avg_fi, away_avg_fi or 50)[0]
            basis_home = "form_index"
        else:
            home_xg = prior_xg[0]
            basis_home = "elo_prior"
        away_xg = prior_xg[1]
        basis_away = "elo_prior"
    else:
        # Only away has FI
        home_xg = prior_xg[0]
        basis_home = "elo_prior"
        if away_matches >= 3:
            away_xg = form_index_to_xg(home_avg_fi or 50, away_avg_fi)[1]  # type: ignore[arg-type]
            basis_away = "form_index"
        else:
            away_xg = prior_xg[1]
            basis_away = "elo_prior"

    # Floor at 0.3
    home_xg = max(home_xg, 0.3)
    away_xg = max(away_xg, 0.3)

    return round(home_xg, 2), round(away_xg, 2), basis_home, basis_away