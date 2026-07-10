"""Tests for pitch_agent.skill_post — ML/Elo prediction & result copy."""
import pytest

from pitch_agent import skill_post as sp
from pitch_agent import shorts_meta as sm

PRED = {"home": "England", "away": "Croatia", "leader": "England",
        "confidence": 58, "key_factor": "England's attack rates higher",
        "ledger": "19-12 · 61.3%"}
RES = dict(PRED, home_score=2, away_score=1, verdict="England to win", correct=True)

BETTING = ("odds", "lock", "tip", "best bet", "stake", "guaranteed", "parlay", "wager", "bet")


@pytest.mark.parametrize("gen,data", [(sp.prediction_post, PRED), (sp.result_post, RES)])
def test_has_both_channels_and_kind(gen, data):
    out = gen(data)
    assert out["linkedin"] and out["x"]
    assert out["post_kind"] == "worldcup"


@pytest.mark.parametrize("gen,data", [(sp.prediction_post, PRED), (sp.result_post, RES)])
def test_no_betting_language(gen, data):
    blob = (gen(data)["linkedin"] + " " + gen(data)["x"]).lower()
    for w in BETTING:
        assert w not in blob, f"banned word {w!r} leaked"


def test_prediction_mentions_elo_and_logged_before_kickoff():
    li = sp.prediction_post(PRED)["linkedin"].lower()
    assert "elo" in li and "before kickoff" in li
    assert "58%" in sp.prediction_post(PRED)["linkedin"]


def test_result_reflects_correct_and_record():
    right = sp.result_post(dict(RES, correct=True))["linkedin"].lower()
    wrong = sp.result_post(dict(RES, correct=False))["linkedin"].lower()
    assert "right" in right and "wrong" in wrong
    assert "19-12" in sp.result_post(RES)["linkedin"]


def test_x_is_short_enough():
    # X limit is 280 for standard accounts; keep a safe margin.
    assert len(sp.prediction_post(PRED)["x"]) <= 280
    assert len(sp.result_post(RES)["x"]) <= 280


def test_worldcup_kind_now_allowed_by_policy():
    import importlib, sys
    sys.path.insert(0, "scripts")
    lp = importlib.import_module("linkedin_policy")
    assert "worldcup" in lp.DAILY_LIMITS
