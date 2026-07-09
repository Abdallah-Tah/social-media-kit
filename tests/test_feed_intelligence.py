"""Tests for smkit feed --intelligence orchestration."""
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

from agent.feed_intelligence import (
    IntelligenceCard,
    generate_brief_for_top,
    run_intelligent_feed,
    save_intelligence,
)


@dataclass
class FakeItem:
    title: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""
    summary: str = ""
    score: float = 0.0
    matched_interests: list[str] = field(default_factory=list)
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "score": self.score,
        }


def test_intelligence_card_to_dict():
    card = IntelligenceCard(rank=1)
    d = card.to_dict()
    assert d["rank"] == 1
    assert "opportunity" in d
    assert "recommendation" in d


def test_generate_brief_for_top_skips_skip():
    @dataclass
    class FakeCluster:
        headline: str = "A"
        representative: Any = None
        items: list[Any] = field(default_factory=list)
        sources: list[str] = field(default_factory=lambda: ["rss"])
        urls: list[str] = field(default_factory=lambda: ["https://example.com"])
        size: int = 1

    skip_card = IntelligenceCard(
        cluster=FakeCluster(headline="Skip me"),
        recommendation={"recommendation": "skip"},
        opportunity={"opportunity_score": 10},
    )
    good_card = IntelligenceCard(
        cluster=FakeCluster(headline="Good story", representative=FakeItem(title="Good story", url="https://example.com/good", source="hackernews")),
        recommendation={"recommendation": "blog", "suggested_angle": "angle", "suggested_hook": "hook", "confidence_score": 80},
        opportunity={"opportunity_score": 80},
    )
    brief = generate_brief_for_top([skip_card, good_card])
    assert brief is not None
    assert brief.content_type == "blog"


def test_save_intelligence_writes_json(tmp_path):
    card = IntelligenceCard(rank=1)
    path = save_intelligence([card], path=tmp_path / "intel.json")
    import json

    data = json.loads(path.read_text())
    assert data["count"] == 1
    assert "cards" in data


def test_run_intelligent_feed_empty():
    # Patching the imported build_feed to avoid network calls.
    from agent import feed_intelligence

    original_build_feed = feed_intelligence.build_feed
    feed_intelligence.build_feed = lambda **kwargs: []
    try:
        cards = run_intelligent_feed(topic="nonsense-for-empty", profile_name="default", limit=5)
        assert cards == []
    finally:
        feed_intelligence.build_feed = original_build_feed


def test_run_intelligent_feed_with_items():
    from agent import feed_intelligence

    now = "2026-07-09T11:00:00+00:00"
    item = FakeItem(
        title="Laravel adds AI tooling for developers",
        url="https://laravel.com/news/ai-tooling",
        source="rss",
        published_at=now,
        summary="A new AI integration ships in Laravel.",
    )
    original_build_feed = feed_intelligence.build_feed
    feed_intelligence.build_feed = lambda **kwargs: [item]
    try:
        cards = run_intelligent_feed(topic="laravel ai", profile_name="default", limit=3)
        assert len(cards) >= 1
        top = cards[0]
        assert top.opportunity.get("opportunity_score", 0) >= 0
        assert top.trend.get("direction") in {"exploding", "growing", "stable", "declining", "dead"}
        assert top.recommendation.get("recommendation") in {"blog", "tutorial", "linkedin_post", "youtube_short", "twitter_thread", "newsletter", "skip"}
        assert top.previously_seen is False
    finally:
        feed_intelligence.build_feed = original_build_feed


def test_include_seen_flags_previously_seen():
    from agent import feed
    from agent import feed_intelligence

    now = "2026-07-09T11:00:00+00:00"
    item = FakeItem(
        title="Laravel adds AI tooling for developers",
        url="https://laravel.com/news/ai-tooling",
        source="rss",
        published_at=now,
    )
    # Mark the URL as seen first.
    feed.mark_seen([item.url])
    original_build_feed = feed_intelligence.build_feed

    def fake_build_feed(*, include_seen=False, **kwargs):
        if include_seen:
            return [item]
        return []

    feed_intelligence.build_feed = fake_build_feed
    try:
        # Without include_seen: no cards.
        cards_default = run_intelligent_feed(topic="laravel ai", profile_name="default", limit=3)
        assert cards_default == []
        # With include_seen: card marked as previously_seen.
        cards_seen = run_intelligent_feed(topic="laravel ai", profile_name="default", limit=3, include_seen=True)
        assert len(cards_seen) >= 1
        assert cards_seen[0].previously_seen is True
    finally:
        feed_intelligence.build_feed = original_build_feed


def test_include_seen_does_not_update_seen_store(tmp_path):
    from agent import feed
    from agent import feed_intelligence

    original_feed_dir = feed.FEED_DIR
    original_seen_path = feed.SEEN_PATH
    feed.FEED_DIR = tmp_path
    feed.SEEN_PATH = tmp_path / "seen.json"

    now = "2026-07-09T11:00:00+00:00"
    item = FakeItem(
        title="Laravel AI tooling",
        url="https://laravel.com/news/ai-tooling",
        source="rss",
        published_at=now,
    )
    original_build_feed = feed_intelligence.build_feed
    feed_intelligence.build_feed = lambda **kwargs: [item]
    try:
        run_intelligent_feed(topic="laravel", profile_name="default", limit=3, include_seen=True)
        # seen.json should not have been created/updated.
        assert not feed.SEEN_PATH.exists()
    finally:
        feed_intelligence.build_feed = original_build_feed
        feed.FEED_DIR = original_feed_dir
        feed.SEEN_PATH = original_seen_path


def test_intelligence_brief_option():
    from agent import feed_intelligence

    now = "2026-07-09T11:00:00+00:00"
    item = FakeItem(
        title="React 20 ships concurrent features",
        url="https://react.dev/blog/react-20",
        source="rss",
        published_at=now,
        summary="React 20 is out with concurrency improvements.",
    )
    original_build_feed = feed_intelligence.build_feed
    feed_intelligence.build_feed = lambda **kwargs: [item]
    try:
        cards = run_intelligent_feed(topic="react", profile_name="default", limit=3)
        brief = generate_brief_for_top(cards)
        assert brief is not None
        assert brief.publish_ready is False
        assert brief.content_type in {"blog", "tutorial", "linkedin_post", "youtube_short", "twitter_thread", "newsletter"}
    finally:
        feed_intelligence.build_feed = original_build_feed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
