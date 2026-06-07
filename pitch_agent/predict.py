"""Match outcome predictions — a transparent, data-based Poisson model.

The Pitch Agent estimates win/draw/loss probabilities for upcoming fixtures from
the goals teams have actually scored and conceded so far. The model is a simple,
explainable Poisson goals model — no betting odds, no black box:

    1. From finished matches, compute each team's attack and defense strength
       relative to the tournament's average goals (with shrinkage toward the
       mean so teams with few games stay near neutral).
    2. Turn those strengths into expected goals for each side of a fixture.
    3. Build the full scoreline probability matrix and sum it into
       P(home win) / P(draw) / P(away win), plus the most likely scoreline.

Everything here is a *data-based estimate*, not betting advice. See
:data:`PREDICTION_DISCLAIMER`.

Predictions are stored in the ``predictions`` table so their accuracy can be
scored against real results later (:func:`score_predictions`,
:func:`accuracy_summary`) — the honesty layer that makes the estimates worth
trusting.
"""
from __future__ import annotations

import math
import random
import sqlite3
from typing import Any

MODEL_VERSION = "poisson-1.0"

# Per-team baseline goals per match when no finished games exist yet.
DEFAULT_AVG_GOALS = 1.35
# Mild home/host multiplier; pass ``neutral=True`` for neutral venues.
HOME_ADVANTAGE = 1.10
# Pseudo-matches of league-average form blended into every team (shrinkage),
# so a team with one fluke result is not treated as world-beating.
PRIOR_MATCHES = 2.0
# Truncate the scoreline matrix here; tail mass beyond this is negligible.
MAX_GOALS = 10
# Match statuses that count as a completed, countable result.
FINISHED_STATUSES = {"FINISHED", "AWARDED"}

PREDICTION_DISCLAIMER = (
    "Data-based estimate, not betting advice. Independent analytics, "
    "not affiliated with FIFA."
)


# ── Poisson model (pure, deterministic) ─────────────────────────────────────

def _poisson_pmf(k: int, lam: float) -> float:
    """Probability of exactly *k* goals given expected goals *lam*."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)


def _is_finished(match: dict[str, Any]) -> bool:
    """True when a match row represents a completed result.

    Status is the only reliable signal: the ``matches`` table defaults scores to
    0, so a scheduled fixture and a real 0-0 are indistinguishable by score.
    """
    return str(match.get("status", "") or "").strip().upper() in FINISHED_STATUSES


def compute_team_ratings(
    matches: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], float]:
    """Return ``(ratings, league_avg)`` from finished matches.

    ``ratings[team] = {"attack", "defense", "games", "gf", "ga"}`` where attack
    and defense are multipliers around ``1.0`` (1.0 = exactly average). Teams are
    shrunk toward 1.0 by :data:`PRIOR_MATCHES` so early, noisy form is tempered.
    """
    gf: dict[str, float] = {}
    ga: dict[str, float] = {}
    games: dict[str, int] = {}
    total_goals = 0.0
    total_games = 0

    for m in matches:
        if not _is_finished(m):
            continue
        home = str(m.get("home_team_name", "") or "").strip()
        away = str(m.get("away_team_name", "") or "").strip()
        if not home or not away:
            continue
        hs = int(m.get("home_score", 0) or 0)
        as_ = int(m.get("away_score", 0) or 0)
        gf[home] = gf.get(home, 0.0) + hs
        ga[home] = ga.get(home, 0.0) + as_
        gf[away] = gf.get(away, 0.0) + as_
        ga[away] = ga.get(away, 0.0) + hs
        games[home] = games.get(home, 0) + 1
        games[away] = games.get(away, 0) + 1
        total_goals += hs + as_
        total_games += 1

    league_avg = (total_goals / (2 * total_games)) if total_games else DEFAULT_AVG_GOALS
    if league_avg <= 0:
        league_avg = DEFAULT_AVG_GOALS

    ratings: dict[str, dict[str, float]] = {}
    for team, n in games.items():
        # Shrink toward the league average with PRIOR_MATCHES pseudo-games.
        attack_rate = (gf[team] + PRIOR_MATCHES * league_avg) / (n + PRIOR_MATCHES)
        defense_rate = (ga[team] + PRIOR_MATCHES * league_avg) / (n + PRIOR_MATCHES)
        ratings[team] = {
            "attack": attack_rate / league_avg,
            "defense": defense_rate / league_avg,
            "games": float(n),
            "gf": gf[team],
            "ga": ga[team],
        }
    return ratings, league_avg


def _expected_goals(
    home: str,
    away: str,
    ratings: dict[str, dict[str, float]],
    league_avg: float,
    *,
    neutral: bool = False,
    home_advantage: float = HOME_ADVANTAGE,
) -> tuple[float, float]:
    """Expected goals for each side, clamped to a sane range. Unknown teams
    default to neutral (1.0) strength so the model degrades gracefully."""
    ha = 1.0 if neutral else home_advantage
    h = ratings.get(home, {})
    a = ratings.get(away, {})
    exp_home = league_avg * h.get("attack", 1.0) * a.get("defense", 1.0) * ha
    exp_away = league_avg * a.get("attack", 1.0) * h.get("defense", 1.0)
    return max(0.2, min(6.0, exp_home)), max(0.2, min(6.0, exp_away))


def predict_match(
    home: str,
    away: str,
    ratings: dict[str, dict[str, float]],
    league_avg: float,
    *,
    neutral: bool = False,
    home_advantage: float = HOME_ADVANTAGE,
) -> dict[str, Any]:
    """Predict a single fixture. Returns probabilities, expected goals, the most
    likely scoreline, the predicted outcome (``HOME``/``DRAW``/``AWAY``), and a
    ``confidence`` (the winning probability). Unknown teams default to neutral
    (1.0) strength, so the model degrades gracefully before any games are played.
    """
    exp_home, exp_away = _expected_goals(
        home, away, ratings, league_avg, neutral=neutral, home_advantage=home_advantage,
    )

    p_home = p_draw = p_away = 0.0
    best_p = -1.0
    best_score = (0, 0)
    for i in range(MAX_GOALS + 1):
        pi = _poisson_pmf(i, exp_home)
        for j in range(MAX_GOALS + 1):
            p = pi * _poisson_pmf(j, exp_away)
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
            if p > best_p:
                best_p = p
                best_score = (i, j)

    total = p_home + p_draw + p_away
    if total > 0:
        p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    outcome = max((("HOME", p_home), ("DRAW", p_draw), ("AWAY", p_away)), key=lambda x: x[1])
    return {
        "home_team_name": home,
        "away_team_name": away,
        "p_home": round(p_home, 4),
        "p_draw": round(p_draw, 4),
        "p_away": round(p_away, 4),
        "exp_home": round(exp_home, 2),
        "exp_away": round(exp_away, 2),
        "most_likely_score": f"{best_score[0]}-{best_score[1]}",
        "predicted_outcome": outcome[0],
        "confidence": round(outcome[1], 4),
    }


def predict_fixtures(
    fixtures: list[dict[str, Any]],
    ratings: dict[str, dict[str, float]],
    league_avg: float,
    *,
    neutral: bool = False,
) -> list[dict[str, Any]]:
    """Predict every upcoming (not finished) fixture with both teams known."""
    out: list[dict[str, Any]] = []
    for fx in fixtures:
        if _is_finished(fx):
            continue
        home = str(fx.get("home_team_name", "") or "").strip()
        away = str(fx.get("away_team_name", "") or "").strip()
        if not home or not away:
            continue
        pred = predict_match(home, away, ratings, league_avg, neutral=neutral)
        pred["match_id"] = str(fx.get("match_id", "") or "")
        pred["date"] = fx.get("date", "")
        pred["group_name"] = fx.get("group_name", "")
        out.append(pred)
    return out


# ── Group standings projection (Monte-Carlo) ────────────────────────────────

def _sample_poisson(lam: float, rng: random.Random) -> int:
    """Draw a single Poisson sample (Knuth's algorithm). Fine for small lambda."""
    target = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= target:
            return k - 1


def simulate_group(
    group_matches: list[dict[str, Any]],
    ratings: dict[str, dict[str, float]],
    league_avg: float,
    *,
    advance_count: int = 2,
    n_sims: int = 10000,
    neutral: bool = True,
    seed: int = 12345,
) -> list[dict[str, Any]]:
    """Project final group standings by simulating the remaining matches.

    Finished matches contribute fixed points; upcoming matches are simulated
    ``n_sims`` times with the Poisson model. Returns one row per team with its
    probability to **win the group** and to **advance** (finish in the top
    ``advance_count``), plus current and expected final points. Deterministic for
    a given ``seed`` so tests and re-runs are stable. Ranking tiebreak: points →
    goal difference → goals for → random.
    """
    teams: set[str] = set()
    base_pts: dict[str, int] = {}
    base_gd: dict[str, int] = {}
    base_gf: dict[str, int] = {}
    upcoming: list[tuple[str, str]] = []

    for m in group_matches:
        home = str(m.get("home_team_name", "") or "").strip()
        away = str(m.get("away_team_name", "") or "").strip()
        if not home or not away:
            continue
        teams.update([home, away])
        base_pts.setdefault(home, 0); base_pts.setdefault(away, 0)
        base_gd.setdefault(home, 0); base_gd.setdefault(away, 0)
        base_gf.setdefault(home, 0); base_gf.setdefault(away, 0)
        if _is_finished(m):
            hs = int(m.get("home_score", 0) or 0)
            as_ = int(m.get("away_score", 0) or 0)
            base_gd[home] += hs - as_; base_gd[away] += as_ - hs
            base_gf[home] += hs; base_gf[away] += as_
            if hs > as_:
                base_pts[home] += 3
            elif hs < as_:
                base_pts[away] += 3
            else:
                base_pts[home] += 1; base_pts[away] += 1
        else:
            upcoming.append((home, away))

    if not teams:
        return []

    # Pre-compute expected goals for each upcoming match once.
    exp = {
        (h, a): _expected_goals(h, a, ratings, league_avg, neutral=neutral)
        for (h, a) in upcoming
    }

    rng = random.Random(seed)
    win_group = {t: 0 for t in teams}
    advance = {t: 0 for t in teams}
    points_total = {t: 0 for t in teams}

    for _ in range(n_sims):
        pts = dict(base_pts)
        gd = dict(base_gd)
        gf = dict(base_gf)
        for (h, a) in upcoming:
            eh, ea = exp[(h, a)]
            hg = _sample_poisson(eh, rng)
            ag = _sample_poisson(ea, rng)
            gd[h] += hg - ag; gd[a] += ag - hg
            gf[h] += hg; gf[a] += ag
            if hg > ag:
                pts[h] += 3
            elif hg < ag:
                pts[a] += 3
            else:
                pts[h] += 1; pts[a] += 1
        ranked = sorted(teams, key=lambda t: (pts[t], gd[t], gf[t], rng.random()), reverse=True)
        win_group[ranked[0]] += 1
        for t in ranked[:advance_count]:
            advance[t] += 1
        for t in teams:
            points_total[t] += pts[t]

    out = [{
        "team": t,
        "current_points": base_pts[t],
        "exp_points": round(points_total[t] / n_sims, 2),
        "p_win_group": round(win_group[t] / n_sims, 4),
        "p_advance": round(advance[t] / n_sims, 4),
    } for t in teams]
    out.sort(key=lambda r: (r["p_advance"], r["p_win_group"], r["exp_points"]), reverse=True)
    return out


def project_group(
    group_name: str,
    db_path: str = "pitch_agent.db",
    *,
    advance_count: int = 2,
    n_sims: int = 10000,
    neutral: bool = True,
    seed: int = 12345,
) -> list[dict[str, Any]]:
    """Load matches, build ratings, and project one group's standings by label."""
    from pitch_agent.fixtures import normalize_stage_label

    matches = _load_matches(db_path)
    ratings, league_avg = compute_team_ratings(matches)
    target = normalize_stage_label(group_name)
    group_matches = [
        m for m in matches
        if normalize_stage_label(m.get("group_name", "")) == target
    ]
    return simulate_group(
        group_matches, ratings, league_avg,
        advance_count=advance_count, n_sims=n_sims, neutral=neutral, seed=seed,
    )


# ── Storage + accuracy scoring ──────────────────────────────────────────────

def _load_matches(db_path: str) -> list[dict[str, Any]]:
    """Load all match rows, preferring football-data over CSV/legacy rows."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT match_id, home_team_name, away_team_name, home_score, "
            "away_score, date, group_name, status, provider_name FROM matches"
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return []
    matches = [dict(r) for r in rows]
    primary = [m for m in matches if str(m.get("provider_name", "")).lower() == "football-data"]
    return primary if primary else matches


def predict_upcoming(
    db_path: str = "pitch_agent.db",
    *,
    competition_id: str | None = None,
    limit: int = 10,
    neutral: bool = False,
) -> list[dict[str, Any]]:
    """Convenience: read matches, compute ratings, predict upcoming fixtures."""
    from pitch_agent.fixtures import get_fixtures

    ratings, league_avg = compute_team_ratings(_load_matches(db_path))
    fixtures = get_fixtures(db_path, competition_id=competition_id, limit=limit)
    return predict_fixtures(fixtures, ratings, league_avg, neutral=neutral)


def save_predictions(
    predictions: list[dict[str, Any]],
    db_path: str = "pitch_agent.db",
    model_version: str = MODEL_VERSION,
) -> int:
    """UPSERT predictions into the ``predictions`` table. Returns rows written."""
    if not predictions:
        return 0
    conn = sqlite3.connect(db_path)
    written = 0
    for p in predictions:
        if not p.get("match_id"):
            continue
        conn.execute(
            """
            INSERT INTO predictions (
                match_id, model_version, home_team_name, away_team_name, date,
                p_home, p_draw, p_away, exp_home, exp_away, predicted_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id, model_version) DO UPDATE SET
                home_team_name=excluded.home_team_name,
                away_team_name=excluded.away_team_name,
                date=excluded.date,
                p_home=excluded.p_home, p_draw=excluded.p_draw, p_away=excluded.p_away,
                exp_home=excluded.exp_home, exp_away=excluded.exp_away,
                predicted_outcome=excluded.predicted_outcome,
                updated_at=datetime('now')
            """,
            (
                str(p["match_id"]), model_version,
                p.get("home_team_name", ""), p.get("away_team_name", ""), p.get("date", ""),
                p.get("p_home", 0.0), p.get("p_draw", 0.0), p.get("p_away", 0.0),
                p.get("exp_home", 0.0), p.get("exp_away", 0.0),
                p.get("predicted_outcome", ""),
            ),
        )
        written += 1
    conn.commit()
    conn.close()
    return written


def _actual_outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "HOME"
    if home_score < away_score:
        return "AWAY"
    return "DRAW"


def score_predictions(
    db_path: str = "pitch_agent.db",
    model_version: str = MODEL_VERSION,
) -> list[dict[str, Any]]:
    """Join stored predictions with finished results and grade each one.

    Returns one row per scored prediction with the predicted vs. actual outcome,
    whether it was ``correct``, and that match's Brier score (lower is better).
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT p.match_id, p.home_team_name, p.away_team_name, p.date,
                   p.p_home, p.p_draw, p.p_away, p.predicted_outcome,
                   m.home_score, m.away_score, m.status
            FROM predictions p
            JOIN matches m ON m.match_id = p.match_id
            WHERE p.model_version = ?
            """,
            (model_version,),
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return []

    scored: list[dict[str, Any]] = []
    for r in rows:
        if str(r["status"] or "").strip().upper() not in FINISHED_STATUSES:
            continue
        actual = _actual_outcome(int(r["home_score"] or 0), int(r["away_score"] or 0))
        ind = {"HOME": (1, 0, 0), "DRAW": (0, 1, 0), "AWAY": (0, 0, 1)}[actual]
        brier = (
            (r["p_home"] - ind[0]) ** 2
            + (r["p_draw"] - ind[1]) ** 2
            + (r["p_away"] - ind[2]) ** 2
        )
        scored.append({
            "match_id": r["match_id"],
            "home_team_name": r["home_team_name"],
            "away_team_name": r["away_team_name"],
            "date": r["date"],
            "predicted_outcome": r["predicted_outcome"],
            "actual_outcome": actual,
            "correct": r["predicted_outcome"] == actual,
            "brier": round(brier, 4),
        })
    return scored


def accuracy_summary(
    db_path: str = "pitch_agent.db",
    model_version: str = MODEL_VERSION,
) -> dict[str, Any]:
    """Aggregate scored predictions into a credibility scorecard."""
    scored = score_predictions(db_path, model_version)
    n = len(scored)
    if n == 0:
        return {"n": 0, "correct": 0, "accuracy": 0.0, "brier": 0.0}
    correct = sum(1 for s in scored if s["correct"])
    brier = sum(s["brier"] for s in scored) / n
    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4),
        "brier": round(brier, 4),
    }


__all__ = [
    "MODEL_VERSION",
    "PREDICTION_DISCLAIMER",
    "compute_team_ratings",
    "predict_match",
    "predict_fixtures",
    "predict_upcoming",
    "simulate_group",
    "project_group",
    "save_predictions",
    "score_predictions",
    "accuracy_summary",
]
