"""Read-only forecast evaluation for the Pitch Agent.

Honest scoreboard for the prediction model. Computes calibration metrics
(Brier, log-loss), outcome accuracy, draw calibration, and comparison
against naive baselines, over the predictions that are already journaled
and graded.

This NEVER writes to the predictions ledger — it only reads
`predictions` + `prediction_results` + `matches`. Run it any time:

    python3 -m pitch_agent.backtest

See MODEL_DIAGNOSIS.md for why calibration (not raw 2/4 hit-rate) is the
metric we should be judging the model on.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "pitch_agent.db"


def _actual_outcome(hs: int, as_: int) -> str:
    return "home" if hs > as_ else ("away" if as_ > hs else "draw")


def load_graded(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """All graded predictions joined to their actual results (read-only)."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT p.predicted_outcome, p.home_win_prob, p.draw_prob, p.away_win_prob,
               m.home_score, m.away_score,
               m.home_team_name AS home, m.away_team_name AS away, m.date
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        JOIN prediction_results r ON r.prediction_id = p.id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY m.date
        """
    ).fetchall()
    return [dict(r) for r in rows]


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute accuracy + calibration metrics + baseline comparisons."""
    n = len(rows)
    if n == 0:
        return {"n": 0}

    hits = brier = logloss = 0.0
    draw_pred_mass = draw_actual = 0
    base_home_hits = base_fav_hits = 0
    uniform_brier = uniform_logloss = 0.0

    for r in rows:
        actual = _actual_outcome(r["home_score"], r["away_score"])
        p = {"home": r["home_win_prob"] or 0.0,
             "draw": r["draw_prob"] or 0.0,
             "away": r["away_win_prob"] or 0.0}
        # Outcome accuracy (model's own argmax label, as journaled)
        hits += 1 if r["predicted_outcome"] == actual else 0
        # 3-class Brier + log-loss (the metrics that matter for a forecaster)
        for k, v in p.items():
            brier += (v - (1.0 if k == actual else 0.0)) ** 2
        logloss += -math.log(max(p[actual], 1e-9))
        # Draw calibration
        draw_pred_mass += p["draw"]
        draw_actual += 1 if actual == "draw" else 0
        # Baselines
        base_home_hits += 1 if actual == "home" else 0
        fav = max(p, key=p.get)
        base_fav_hits += 1 if fav == actual else 0
        for k in ("home", "draw", "away"):
            uniform_brier += (1 / 3 - (1.0 if k == actual else 0.0)) ** 2
        uniform_logloss += -math.log(1 / 3)

    return {
        "n": n,
        "accuracy": round(hits / n, 3),
        "brier": round(brier / n, 3),
        "logloss": round(logloss / n, 3),
        "draw_pred_rate": round(draw_pred_mass / n, 3),
        "draw_actual_rate": round(draw_actual / n, 3),
        "baseline_always_home": round(base_home_hits / n, 3),
        "baseline_always_favorite": round(base_fav_hits / n, 3),
        "baseline_uniform_brier": round(uniform_brier / n, 3),
        "baseline_uniform_logloss": round(uniform_logloss / n, 3),
    }


def main() -> int:
    if not DB_PATH.exists():
        print(f"No DB at {DB_PATH}")
        return 1
    conn = sqlite3.connect(DB_PATH)
    rows = load_graded(conn)
    m = evaluate(rows)
    print("=== Pitch Agent forecast scoreboard (read-only) ===")
    if m["n"] == 0:
        print("No graded predictions yet.")
        return 0
    print(f"graded predictions      : {m['n']}")
    print(f"outcome accuracy        : {m['accuracy']*100:.0f}%")
    print(f"3-class Brier (lower=better)  : {m['brier']:.3f}   (uniform baseline {m['baseline_uniform_brier']:.3f})")
    print(f"log-loss     (lower=better)  : {m['logloss']:.3f}   (uniform baseline {m['baseline_uniform_logloss']:.3f})")
    print(f"draw calibration        : predicted {m['draw_pred_rate']*100:.0f}% vs actual {m['draw_actual_rate']*100:.0f}%")
    print(f"baseline always-home    : {m['baseline_always_home']*100:.0f}%")
    print(f"baseline always-favorite: {m['baseline_always_favorite']*100:.0f}%")
    edge_b = m["baseline_uniform_brier"] - m["brier"]
    print(f"\nmodel vs coin-flip (Brier edge): {edge_b:+.3f}  "
          f"({'model better' if edge_b > 0 else 'no edge yet'})")
    print("\nNote: at small n these numbers are noisy. Judge the model on Brier/"
          "log-loss trend as the group stage fills in, not single results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
