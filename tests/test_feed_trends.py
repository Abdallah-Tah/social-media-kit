"""Tests for Phase 3: trend detection."""
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

from agent.feed_trends import TrendBreakdown, detect_trend, trend_for_cluster


@dataclass
class FakeItem:
    title: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def now_iso(offset_hours: float = 0) -> str:
    base = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=offset_hours)
    return base.isoformat()


def test_trend_exploding_many_sources_recent():
    items = [
        FakeItem(title="A", source="hackernews", metadata={"upvotes": 2000}),
        FakeItem(title="B", source="reddit", metadata={"upvotes": 500}),
        FakeItem(title="C", source="google_news"),
        FakeItem(title="D", source="rss"),
    ]
    trend = detect_trend(items, latest=now_iso(1), earliest=now_iso(2))
    assert trend.direction == "exploding"
    assert trend.velocity > 0
    assert any("4 unique sources" in s for s in trend.signals)


def test_trend_growing_recent_moderate_coverage():
    items = [FakeItem(title="A", source="hackernews"), FakeItem(title="B", source="google_news")]
    trend = detect_trend(items, latest=now_iso(5), earliest=now_iso(6))
    assert trend.direction == "growing"
    assert trend.recommendation


def test_trend_stable_old_single_source():
    items = [FakeItem(title="A", source="rss")]
    trend = detect_trend(items, latest=now_iso(48), earliest=now_iso(50))
    assert trend.direction in ("stable", "declining")


def test_trend_declining_stale_moderate_coverage():
    items = [
        FakeItem(title="A", source="rss"),
        FakeItem(title="B", source="google_news"),
        FakeItem(title="C", source="hackernews"),
    ]
    trend = detect_trend(items, latest=now_iso(96), earliest=now_iso(120))
    assert trend.direction in ("declining", "dead", "stable")
    assert trend.freshness_score <= 0.30




def test_trend_dead_no_fresh_items():
    items = [FakeItem(title="A", source="rss")]
    trend = detect_trend(items, latest=now_iso(200), earliest=now_iso(220))
    assert trend.direction == "dead"


def test_trend_engagement_boost():
    items = [FakeItem(title="A", source="hackernews", metadata={"upvotes": 300, "comments": 80})]
    trend = detect_trend(items, latest=now_iso(1), earliest=now_iso(2))
    assert trend.engagement_score > 0
    assert any("300" in s or "80" in s for s in trend.signals)


def test_trend_breakdown_to_dict():
    b = TrendBreakdown(direction="growing", velocity=0.5, signals=["fresh"])
    d = b.to_dict()
    assert d["direction"] == "growing"
    assert d["velocity"] == 0.5
    assert "signals" in d
    assert "recommendation" in d


def test_trend_for_cluster():
    @dataclass
    class FakeCluster:
        items: list[Any]
        latest: str
        earliest: str

    cluster = FakeCluster(
        items=[FakeItem(title="A", source="hackernews", metadata={"upvotes": 1000})],
        latest=now_iso(0.5),
        earliest=now_iso(1),
    )
    trend = trend_for_cluster(cluster)
    assert trend.direction in ("exploding", "growing")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
