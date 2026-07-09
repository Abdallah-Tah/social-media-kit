"""Tests for Phase 5: recommendation engine."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from agent.feed_recommendations import (
    SUPPORTED_FORMATS,
    FormatRecommendation,
    compute_platform_fit,
    recommend_for_opportunities,
    recommend_format,
)


@dataclass
class FakeOpp:
    opportunity_score: int = 0
    authority_score: float = 0.0
    novelty_score: float = 0.0
    trend_score: float = 0.0
    gap_score: float = 0.0
    interest_score: float = 0.0


def test_exploding_trend_recommends_short_or_thread():
    opp = FakeOpp(opportunity_score=85, authority_score=0.6, novelty_score=0.8, trend_score=0.9, gap_score=0.5, interest_score=0.8)
    rec = recommend_format(opp, trend_direction="exploding", title="OpenAI ships GPT-5", interests=["ai"])
    assert rec.recommendation in {"youtube_short", "twitter_thread"}
    assert rec.confidence_score > 50
    assert rec.suggested_hook
    assert rec.suggested_angle


def test_high_authority_technical_depth_recommends_blog_or_tutorial():
    opp = FakeOpp(opportunity_score=80, authority_score=0.85, novelty_score=0.6, trend_score=0.3, gap_score=0.8, interest_score=0.7)
    rec = recommend_format(opp, trend_direction="stable", title="How to deploy Laravel on Kubernetes", interests=["laravel"])
    assert rec.recommendation in {"blog", "tutorial"}


def test_strong_professional_angle_recommends_linkedin():
    opp = FakeOpp(opportunity_score=65, authority_score=0.7, novelty_score=0.5, trend_score=0.4, gap_score=0.6, interest_score=0.7)
    rec = recommend_format(opp, trend_direction="stable", title="Why engineering teams need API observability", interests=["startups"])
    assert rec.recommendation == "linkedin_post"


def test_low_score_recommends_skip():
    opp = FakeOpp(opportunity_score=20, authority_score=0.3, novelty_score=0.2, trend_score=0.1, gap_score=0.2)
    rec = recommend_format(opp, trend_direction="dead", title="Generic fluff", interests=["laravel"])
    assert rec.recommendation == "skip"
    assert rec.confidence_score == 20


def test_explanation_output():
    opp = FakeOpp(opportunity_score=70, authority_score=0.6, novelty_score=0.7, trend_score=0.6, gap_score=0.6, interest_score=0.7)
    rec = recommend_format(opp, trend_direction="growing", title="Python 3.14 adds async improvements", interests=["python"])
    d = rec.to_dict()
    assert "recommendation" in d
    assert "confidence_score" in d
    assert "reason" in d
    assert "platform_fit_scores" in d
    assert "suggested_angle" in d
    assert "suggested_hook" in d
    assert "signals" in d


def test_confidence_scoring_in_range():
    opp = FakeOpp(opportunity_score=90, authority_score=0.8, novelty_score=0.8, trend_score=0.8, gap_score=0.8, interest_score=0.9)
    rec = recommend_format(opp, trend_direction="exploding", title="React 20 released", interests=["react"])
    assert 0 <= rec.confidence_score <= 100


def test_platform_fit_scores_sum_not_required():
    opp = FakeOpp(opportunity_score=60, authority_score=0.6, novelty_score=0.5, trend_score=0.4, gap_score=0.6, interest_score=0.6)
    fit = compute_platform_fit(opp, "growing", "Laravel 12 ships", interests=["laravel"])
    for fmt in ("blog", "youtube_short", "linkedin_post", "twitter_thread", "newsletter"):
        assert 0 <= fit[fmt] <= 1


def test_recommend_for_opportunities_batch():
    @dataclass
    class FakeItem:
        title: str

    opps = [
        (FakeItem("Hot AI release"), FakeOpp(opportunity_score=90, trend_score=0.9, novelty_score=0.8, authority_score=0.6, gap_score=0.5, interest_score=0.8)),
        (FakeItem("Boring update"), FakeOpp(opportunity_score=15, trend_score=0.1, novelty_score=0.2, authority_score=0.3, gap_score=0.2, interest_score=0.1)),
    ]
    results = recommend_for_opportunities(opps, interests=["ai"])
    assert len(results) == 2
    assert results[0][1].recommendation in SUPPORTED_FORMATS
    assert results[1][1].recommendation == "skip"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
