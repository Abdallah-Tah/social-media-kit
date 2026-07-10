"""ML/Elo 'build-in-public' posts for the World Cup model — proving the skill
with a public, accountable prediction -> result loop. LinkedIn + X copy.

Framing: software/ML engineering (Elo ratings + form + Poisson, graded against
the real result). NO betting language (guarded). The model's record comes from
the IMMUTABLE accuracy ledger — never fabricated.

data dict (from the predictions table / football_prediction_shorts.predict):
  {home, away, leader, confidence(int %), key_factor, ledger("19-12 · 61.3%")}
result adds: {home_score, away_score, verdict, correct(bool)}
"""
from __future__ import annotations

from .shorts_meta import assert_no_betting

HASHTAGS_LI = "#MachineLearning #DataScience #WorldCup2026 #Python #Elo #BuildInPublic"
HASHTAGS_X = "#MachineLearning #WorldCup2026 #Elo"


def _underdog(d: dict) -> str:
    return d["away"] if d.get("leader") == d["home"] else d["home"]


def prediction_post(d: dict) -> dict:
    """Pre-match: the model's call + how it works. Logged before kickoff."""
    h, a = d["home"], d["away"]
    leader = d.get("leader") or h
    conf = d.get("confidence", "")
    kf = d.get("key_factor") or "team strength and recent form"
    ledger = d.get("ledger", "")
    rec = f" Running record: {ledger}." if ledger else ""

    linkedin = (
        f"My Elo-based ML model's read on {h} vs {a} (World Cup 2026).\n\n"
        f"The model favors {leader} — {conf}% win probability. Biggest factor it's "
        f"weighting: {kf}.\n\n"
        f"How it works: each team carries an Elo strength rating that updates after "
        f"every match, blended with recent form and a Poisson goal model, then graded "
        f"against the real result every single time.{rec}\n\n"
        f"This prediction is logged BEFORE kickoff — no hindsight. After full-time I'll "
        f"post the result and whether the model got it right. That's the honest way to "
        f"measure a model.\n\n"
        f"{HASHTAGS_LI}"
    )
    x = (
        f"My Elo-based ML model's World Cup call: {leader} over {_underdog(d)} "
        f"({conf}% win prob).\n\n"
        f"Logged before kickoff. Result + grade after FT.{(' Record ' + ledger + '.') if ledger else ''}\n\n"
        f"{HASHTAGS_X}"
    )
    assert_no_betting(linkedin, x)
    return {"linkedin": linkedin, "x": x, "post_kind": "worldcup"}


def result_post(d: dict) -> dict:
    """Post-match: the real result vs the model's call + updated record."""
    h, a = d["home"], d["away"]
    hs, as_ = d.get("home_score"), d.get("away_score")
    leader = d.get("leader") or h
    conf = d.get("confidence", "")
    verdict = d.get("verdict", f"{leader} to win")
    correct = bool(d.get("correct"))
    ledger = d.get("ledger", "")
    mark = "called it right" if correct else "got this one wrong"
    sign = "✓" if correct else "✗"
    rec = f" Updated record: {ledger}." if ledger else ""

    linkedin = (
        f"Result: {h} {hs}-{as_} {a}.\n\n"
        f"My Elo-based ML model predicted {verdict} ({conf}% win probability) — it "
        f"{mark}.{rec}\n\n"
        f"Every prediction is logged before kickoff and graded against the real score. "
        f"Wins and misses both go on the record — that's what makes the accuracy number "
        f"mean something.\n\n"
        f"{HASHTAGS_LI}"
    )
    x = (
        f"{sign} {h} {hs}-{as_} {a}\n\n"
        f"My ML model predicted {verdict} ({conf}%) — it {mark}.{(' Record now ' + ledger + '.') if ledger else ''}\n\n"
        f"Predict before kickoff, grade against reality.\n{HASHTAGS_X}"
    )
    assert_no_betting(linkedin, x)
    return {"linkedin": linkedin, "x": x, "post_kind": "worldcup"}
