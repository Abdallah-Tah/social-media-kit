"""Tests for Phase 2: story clustering."""
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

from agent.feed_clustering import (
    StoryCluster,
    canonical_host,
    cluster_items,
    cluster_url_key,
    should_cluster,
    summarize_clusters,
    title_similarity,
    top_clusters,
)


@dataclass
class FakeItem:
    title: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "score": self.score,
        }


def test_cluster_url_key_strips_tracking_and_collapse_variants():
    a = "https://www.example.com/2026/07/ai-model-release?utm_source=x"
    b = "https://example.com/2026/07/ai-model-release?ref=homepage"
    assert cluster_url_key(a) == cluster_url_key(b)


def test_cluster_url_key_keeps_different_stories_apart():
    a = "https://example.com/2026/07/ai-model-release"
    b = "https://example.com/2026/06/old-framework"
    assert cluster_url_key(a) != cluster_url_key(b)


def test_canonical_host():
    assert canonical_host("https://www.github.com/torvalds/linux") == "github.com"


def test_title_similarity_same_story():
    assert title_similarity(
        "OpenAI releases GPT-5 developers",
        "OpenAI launches GPT-5 developer preview",
    ) > 0.30


def test_title_similarity_different_stories():
    assert title_similarity(
        "Laravel 11 adds new PHP features",
        "Python 3.13 ships free-threaded builds",
    ) < 0.5


def test_should_cluster_by_url():
    a = FakeItem(title="X", url="https://example.com/a?utm=1", source="rss")
    b = FakeItem(title="Y", url="https://example.com/a?ref=2", source="rss")
    assert should_cluster(a, b) is True


def test_should_cluster_by_title():
    a = FakeItem(
        title="Anthropic unveils Claude 4 developer tools",
        url="https://a.com/anthropic-claude-4",
        source="rss",
    )
    b = FakeItem(
        title="Claude 4 developer tools announced by Anthropic",
        url="https://b.com/claude-4",
        source="rss",
    )
    assert should_cluster(a, b) is True


def test_should_not_cluster_unrelated():
    a = FakeItem(title="Laravel 11 released", url="https://a.com/laravel", source="rss")
    b = FakeItem(title="Best pizza in NYC", url="https://b.com/pizza", source="rss")
    assert should_cluster(a, b) is False


def test_cluster_items_groups_duplicates():
    items = [
        FakeItem(title="OpenAI GPT-5 for developers", url="https://a.com/gpt5", source="rss", published_at="2026-07-09T08:00:00+00:00"),
        FakeItem(title="OpenAI launches GPT-5 preview", url="https://b.com/gpt-5", source="google_news", published_at="2026-07-09T09:00:00+00:00"),
        FakeItem(title="Laravel 11 released", url="https://c.com/laravel", source="hackernews", published_at="2026-07-09T07:00:00+00:00"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 2
    gpt_cluster = next(c for c in clusters if "gpt" in c.headline.lower())
    assert gpt_cluster.size == 2
    assert len(gpt_cluster.urls) == 2
    assert len(gpt_cluster.sources) == 2


def test_cluster_summary_structure():
    items = [
        FakeItem(title="Alpha", url="https://example.com/alpha", source="rss", published_at="2026-07-09T08:00:00+00:00"),
        FakeItem(title="Beta", url="https://example.com/beta", source="hackernews", published_at="2026-07-09T09:00:00+00:00"),
    ]
    clusters = cluster_items(items)
    summary = summarize_clusters(clusters)
    assert all("cluster_id" in s for s in summary)
    assert all("headline" in s for s in summary)
    assert all("urls" in s for s in summary)
    assert all("sources" in s for s in summary)
    assert all("representative" in s for s in summary)


def test_top_clusters_returns_sorted():
    items = [
        FakeItem(title="A", url="https://example.com/a", source="reuters.com", published_at="2026-07-09T08:00:00+00:00"),
        FakeItem(title="B", url="https://example.com/b", source="example.com", published_at="2026-07-09T07:00:00+00:00"),
    ]
    clusters = cluster_items(items)
    top = top_clusters(clusters, n=1)
    assert len(top) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
