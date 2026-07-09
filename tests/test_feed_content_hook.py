"""Tests for Phase 6: content generator hook."""
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

from agent.feed_content_hook import (
    ContentBrief,
    build_brief,
    generate_briefs_for_clusters,
    to_smkit_args,
)


@dataclass
class FakeRec:
    recommendation: str
    confidence_score: int = 75
    suggested_angle: str = "test angle"
    suggested_hook: str = "test hook"


@dataclass
class FakeItem:
    title: str = ""
    url: str = ""
    source: str = ""
    summary: str = ""


@dataclass
class FakeCluster:
    headline: str = ""
    representative: Any | None = None
    items: list[Any] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    size: int = 1


@dataclass
class FakeClusterWithRep:
    representative: Any
    items: list[Any] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    size: int = 1

    @property
    def headline(self) -> str:
        return getattr(self.representative, "title", "")


def make_cluster(title: str, content_type: str | None = None) -> tuple[Any, Any]:
    item = FakeItem(title=title, url="https://example.com/a", source="hackernews", summary="A big change. It ships today.")
    cluster = FakeClusterWithRep(
        representative=item,
        items=[item],
        sources=["hackernews", "google_news"],
        urls=["https://example.com/a", "https://example.com/b"],
        size=2,
    )
    rec = FakeRec(recommendation=content_type or "blog")
    return cluster, rec


def test_blog_brief():
    cluster, rec = make_cluster("Laravel adds AI tooling", "blog")
    brief = build_brief(cluster, rec, interests=["laravel"])
    assert brief.content_type == "blog"
    assert brief.title
    assert brief.hook
    assert brief.angle
    assert brief.key_points
    assert brief.source_urls
    assert brief.call_to_action
    assert brief.suggested_assets
    assert brief.publish_ready is False


def test_youtube_short_brief():
    cluster, rec = make_cluster("OpenAI GPT-5 ships", "youtube_short")
    brief = build_brief(cluster, rec, interests=["ai"])
    assert brief.content_type == "youtube_short"
    assert any("60" in h or "Seconds" in brief.title for h in [brief.title])
    assert brief.suggested_assets


def test_linkedin_post_brief():
    cluster, rec = make_cluster("Why API observability matters", "linkedin_post")
    brief = build_brief(cluster, rec, interests=["startups"])
    assert brief.content_type == "linkedin_post"
    assert "engineering" in brief.hook.lower() or "teams" in brief.hook.lower()


def test_twitter_thread_brief():
    cluster, rec = make_cluster("React 20 released", "twitter_thread")
    brief = build_brief(cluster, rec, interests=["react"])
    assert brief.content_type == "twitter_thread"
    assert "🧵" in brief.hook or "thread" in brief.hook.lower()


def test_newsletter_brief():
    cluster, rec = make_cluster("Python 3.14 ships", "newsletter")
    brief = build_brief(cluster, rec, interests=["python"])
    assert brief.content_type == "newsletter"
    assert "This Week:" in brief.title


def test_tutorial_brief():
    cluster, rec = make_cluster("Deploy Laravel on Kubernetes", "tutorial")
    brief = build_brief(cluster, rec, interests=["laravel"])
    assert brief.content_type == "tutorial"
    assert "How to" in brief.title or "step" in brief.hook.lower()
    assert any("code" in kp.lower() for kp in brief.key_points)


def test_skip_brief():
    cluster, rec = make_cluster("Boring fluff", "skip")
    brief = build_brief(cluster, rec)
    assert brief.content_type == "skip"
    assert not brief.publish_ready


def test_to_smkit_args_dry_run():
    cluster, rec = make_cluster("Laravel AI", "blog")
    brief = build_brief(cluster, rec)
    args = to_smkit_args(brief, profile="live-blog-fb-linkedin", dry_run=True)
    assert args["command"][0] == "smkit"
    assert "--dry-run" in args["command"]
    assert args["dry_run"] is True
    assert "brief" in args


def test_generate_briefs_for_clusters_filters_skip():
    clusters_recs = [
        make_cluster("A", "blog"),
        make_cluster("B", "skip"),
        make_cluster("C", "linkedin_post"),
    ]
    briefs = generate_briefs_for_clusters(clusters_recs)
    assert len(briefs) == 2
    assert all(b.content_type != "skip" for b in briefs)


def test_brief_to_dict():
    cluster, rec = make_cluster("Rust 1.90 ships", "blog")
    brief = build_brief(cluster, rec)
    d = brief.to_dict()
    assert d["publish_ready"] is False
    assert d["content_type"] == "blog"
    assert "source_urls" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
