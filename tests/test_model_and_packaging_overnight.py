"""Tests for the overnight model + packaging work (Dixon-Coles, packaging)."""
from pitch_agent.poisson import match_outcome_probs, scoreline_distribution
from pitch_agent import promo as packaging


def test_dixon_coles_default_is_plain_poisson():
    # rho=0.0 must reproduce independent Poisson exactly (zero live impact).
    assert match_outcome_probs(1.3, 1.1) == match_outcome_probs(1.3, 1.1, rho=0.0)
    o = match_outcome_probs(1.2, 1.2, rho=0.0)
    assert abs(o["draw"] - 0.276) < 0.002


def test_dixon_coles_lifts_draws():
    base = match_outcome_probs(1.2, 1.2, rho=0.0)["draw"]
    lifted = match_outcome_probs(1.2, 1.2, rho=-0.10)["draw"]
    assert lifted > base  # negative rho must increase draw probability


def test_distribution_renormalises():
    dist = scoreline_distribution(1.4, 1.0, rho=-0.12)
    assert abs(sum(r["probability"] for r in dist) - 1.0) < 0.01


def test_pre_titles_nonempty_and_bounded():
    titles = packaging.pre_match_titles("Morocco", "Spain", "home", 0.44, 0.33,
                                        favorite_is_lower_elo=True)
    assert titles and all(len(t) <= 90 for t in titles)
    assert any("UPSET" in t for t in titles)


def test_post_titles_reflect_correctness():
    right = packaging.post_match_titles("Mexico", "South Africa", 2, 0, correct=True)
    wrong = packaging.post_match_titles("Canada", "Bosnia-H.", 1, 1, correct=False)
    assert any("Called it" in t for t in right)
    assert any("cooked" in t.lower() or "WRONG" in t for t in wrong)


def test_thumbnail_text_short():
    assert len(packaging.thumbnail_text("home", "Morocco", "Spain").split()) <= 4


def test_report_card_line_is_string():
    assert isinstance(packaging.report_card_line(), str)


def test_draw_decision_backs_even_matches():
    from pitch_agent.poisson import (
        match_outcome_probs, top_scorelines, resolve_predicted_outcome)
    from pitch_agent.content import DRAW_RHO, DRAW_PREF_EPS
    # Dead-even xG → must now predict a draw (v1.2 draw-aware decision).
    o = match_outcome_probs(1.2, 1.2, rho=DRAW_RHO)
    t = top_scorelines(1.2, 1.2, 1, rho=DRAW_RHO)[0]
    assert resolve_predicted_outcome(o, t, draw_pref_eps=DRAW_PREF_EPS) == "draw"


def test_clear_favorite_still_wins():
    from pitch_agent.poisson import (
        match_outcome_probs, top_scorelines, resolve_predicted_outcome)
    from pitch_agent.content import DRAW_RHO, DRAW_PREF_EPS
    # Big favourite must NOT be downgraded to a draw.
    o = match_outcome_probs(1.85, 0.55, rho=DRAW_RHO)
    t = top_scorelines(1.85, 0.55, 1, rho=DRAW_RHO)[0]
    assert resolve_predicted_outcome(o, t, draw_pref_eps=DRAW_PREF_EPS) == "home"


def test_default_decision_unchanged():
    from pitch_agent.poisson import resolve_predicted_outcome
    # eps=0 (default) must keep the original argmax behaviour.
    o = {"home_win": 0.34, "draw": 0.32, "away_win": 0.34}
    assert resolve_predicted_outcome(o, {"home_goals": 1, "away_goals": 1}) in ("home", "away", "draw")
    o2 = {"home_win": 0.50, "draw": 0.30, "away_win": 0.20}
    assert resolve_predicted_outcome(o2) == "home"
