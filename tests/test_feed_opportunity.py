"""Tests for Phase 4: opportunity engine."""
from __future__ import annotations

import datetime as dt
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

from agent.feed_opportunity import (
    VALID_ACTIONS,
    OpportunityBreakdown,
    opportunity_for_cluster,
    score_competition,
    score_content_gap,
    score_opportunity,
    score_virality,
)


@dataclass
class FakeItem:
    title: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
        }


@dataclass
class FakeCluster:
    representative: Any
    items: list[Any] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    size: int = 1
    latest: str = ""
    earliest: str = ""


@dataclass
class FakeTrend:
    direction: str = "stable"
    velocity: float = 0.0


def now_iso(offset_hours: float = 0) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=offset_hours)).isoformat()


def test_high_opportunity_story():
    item = FakeItem(
        title="Laravel adds new AI integration for developers",
        url="https://blog.laravel.com/ai-integration",
        source="rss",
        published_at=now_iso(2),
    )
    cluster = FakeCluster(
        representative=item,
        items=[item, FakeItem(title="Laravel AI lands", url="https://a.com", source="google_news")],
        sources=["rss", "google_news", "hackernews"],
        size=3,
    )
    trend = FakeTrend(direction="growing", velocity=0.6)
    opp = score_opportunity(item, interests=["laravel", "ai"], cluster=cluster, trend=trend)
    assert opp.opportunity_score >= 60
    assert opp.suggested_next_action != "skip"
    assert opp.recommendation_reason


def test_low_opportunity_story():
    item = FakeItem(title="Generic marketing fluff about synergy", url="https://spam.com/x", source="rss", published_at=now_iso(200))
    opp = score_opportunity(item, interests=["laravel"])
    assert opp.opportunity_score < 40
    assert opp.suggested_next_action == "skip"


def test_fresh_but_low_authority():
    item = FakeItem(title="New Python async patterns", url="https://unknown-blog.dev/py", source="rss", published_at=now_iso(1))
    opp = score_opportunity(item, interests=["python"])
    assert opp.opportunity_score >= 20
    assert opp.freshness_score >= 0.8
    assert opp.authority_score < 0.6


def test_high_authority_but_stale():
    item = FakeItem(title="DeepMind paper on LLM reasoning", url="https://deepmind.google/reasoning", source="google_news", published_at=now_iso(200))
    opp = score_opportunity(item, interests=["ai"])
    assert opp.authority_score >= 0.5
    assert opp.freshness_score < 0.5


def test_high_trend_and_strong_interest():
    item = FakeItem(title="OpenAI GPT-5 leaked features", url="https://techcrunch.com/gpt5", source="techcrunch.com", published_at=now_iso(1))
    cluster = FakeCluster(
        representative=item,
        items=[item, FakeItem(title="GPT-5 details", url="https://b.com", source="hackernews", metadata={"upvotes": 1200})],
        sources=["techcrunch.com", "hackernews", "reddit", "google_news"],
        size=4,
    )
    trend = FakeTrend(direction="exploding", velocity=0.9)
    opp = score_opportunity(item, interests=["openai", "ai"], cluster=cluster, trend=trend)
    assert opp.trend_score >= 0.8
    assert opp.opportunity_score >= 70
    assert opp.suggested_next_action in {"create_short", "create_thread"}


def test_score_breakdown_totals_sanity():
    item = FakeItem(title="Laravel PHP 8.4 feature", url="https://laravel.com/news", source="rss", published_at=now_iso(5))
    opp = score_opportunity(item, interests=["laravel", "php"])
    breakdown = opp.score_breakdown
    assert 0 <= breakdown["authority"] <= 1
    assert 0 <= breakdown["freshness"] <= 1
    assert 0 <= breakdown["interest"] <= 1
    assert 0 <= breakdown["novelty"] <= 1


def test_suggested_action_selection_blog_for_authoritative_gap():
    item = FakeItem(title="Comprehensive Laravel testing guide", url="https://laravel.com/docs/testing", source="rss", published_at=now_iso(1))
    opp = score_opportunity(item, interests=["laravel"], existing_content=[])
    assert opp.suggested_next_action in {"create_blog", "create_linkedin_post", "create_newsletter"}


def test_opportunity_for_cluster():
    item = FakeItem(title="New AI agent framework", url="https://github.com/org/agent", source="hackernews", published_at=now_iso(1), metadata={"upvotes": 400})
    cluster = FakeCluster(
        representative=item,
        items=[item],
        sources=["hackernews"],
        size=1,
        latest=now_iso(1),
        earliest=now_iso(1),
    )
    opp = opportunity_for_cluster(cluster, interests=["ai"])
    assert opp.opportunity_score >= 0
    assert opp.suggested_next_action in VALID_ACTIONS


def test_content_gap_existing_match():
    existing = type("E", (), {"title": "Laravel testing guide", "url": "https://buildwithabdallah.com/laravel-testing", "summary": "", "topics": ["laravel"]})()
    item = FakeItem(title="Laravel testing guide", summary="the ultimate laravel testing guide")
    score, signals = score_content_gap(item, [existing])
    assert score < 0.5


def test_content_gap_true_gap():
    existing = type("E", (), {"title": "Old Python tricks", "url": "https://buildwithabdallah.com/python", "summary": "", "topics": ["python"]})()
    item = FakeItem(title="New AI agent framework for Laravel")
    score, signals = score_content_gap(item, [existing])
    assert score >= 0.8


def test_competition_estimate():
    cluster = FakeCluster(representative=None, size=10, sources=["google_news", "reuters.com", "bloomberg.com", "techcrunch.com"])
    score, _ = score_competition(cluster)
    assert score <= 0.3


def test_virality_estimate():
    trend = FakeTrend(direction="exploding")
    cluster = FakeCluster(representative=None, items=[FakeItem(metadata={"upvotes": 2000})])
    score, _ = score_virality(trend, cluster)
    assert score > 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
