"""Tests for the smkit feed engine."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from agent.feed import (
    FeedItem,
    canonical_url,
    doctor_feed,
    is_seen,
    mark_seen,
    save_feed,
)
from scripts.feed_ranker import (
    _matches as matches,
    _title_similarity as title_similarity,
    dedupe_items,
    rank_items,
    score_item,
)


def test_canonical_url_strips_utm():
    raw = "https://example.com/post?utm_source=twitter&utm_campaign=ai&utm_medium=social"
    assert canonical_url(raw) == "https://example.com/post"


def test_canonical_url_perserves_useful_params():
    raw = "https://example.com/post?id=42&page=2&utm_source=x"
    assert canonical_url(raw) == "https://example.com/post?id=42&page=2"


def test_matches_phrase_and_words():
    text = "the new laravel release ships with great php features"
    assert matches(text, "Laravel") is True
    assert matches(text, "artificial intelligence") is False
    assert matches(text, "php features") is True


def test_title_similarity():
    assert title_similarity("Laravel 11 Released", "Laravel 11 is Released") > 0.6
    assert title_similarity("Laravel 11 Released", "Python 3.13 Released") < 0.5


def test_dedupe_items_removes_similar_titles():
    items = [
        FeedItem(title="Laravel 11 Released", url="https://a.com/laravel", source="rss"),
        FeedItem(title="Laravel 11 Is Released", url="https://b.com/laravel", source="rss"),
        FeedItem(title="Python 3.13 Released", url="https://c.com/python", source="rss"),
    ]
    unique = dedupe_items(items)
    assert len(unique) == 2
    urls = {item.url for item in unique}
    assert "https://a.com/laravel" in urls
    assert "https://b.com/laravel" not in urls
    assert "https://c.com/python" in urls


def test_score_item_populates_matched_interests():
    item = FeedItem(
        title="Laravel 11 adds new PHP features",
        url="https://example.com",
        source="rss",
        published_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    scored = score_item(item, ["laravel", "php", "artificial intelligence"])
    assert "laravel" in scored.matched_interests
    assert "php" in scored.matched_interests
    assert scored.score > 0
    assert scored.reason


def test_score_item_topic_bonus():
    item = FeedItem(
        title="OpenAI ships new model for developers",
        url="https://example.com",
        source="google_news",
        published_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    scored = score_item(item, ["startups", "laravel"], topic="AI startups")
    assert scored.score > 0


def test_rank_items_orders_by_score():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    items = [
        FeedItem(title="Old generic post", url="https://example.com/old", source="rss", published_at=old),
        FeedItem(title="Laravel AI integration lands today", url="https://example.com/new", source="hackernews", published_at=now),
        FeedItem(title="Laravel AI integration released today", url="https://example.com/dupe", source="reddit", published_at=now),
    ]
    ranked = rank_items(items, ["laravel", "artificial intelligence"])
    assert len(ranked) == 2
    assert "Laravel AI" in ranked[0].title
    assert ranked[0].score > ranked[1].score


def test_seen_store_dedupes(tmp_path):
    from agent import feed

    original_dir = feed.FEED_DIR
    original_seen = feed.SEEN_PATH
    feed.FEED_DIR = tmp_path
    feed.SEEN_PATH = tmp_path / "seen.json"
    try:
        url = "https://example.com/post?utm_source=x"
        assert is_seen(url) is False
        mark_seen([url])
        assert is_seen("https://example.com/post") is True
        assert is_seen("https://example.com/post?utm_source=other") is True
    finally:
        feed.FEED_DIR = original_dir
        feed.SEEN_PATH = original_seen


def test_save_feed_writes_json(tmp_path):
    from agent import feed

    original_dir = feed.FEED_DIR
    feed.FEED_DIR = tmp_path
    try:
        items = [
            FeedItem(
                title="Test item",
                url="https://example.com",
                source="hackernews",
                published_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                score=75.0,
                matched_interests=["python"],
                reason="test",
            )
        ]
        path = save_feed(items, tmp_path / "snapshot.json")
        data = json.loads(path.read_text())
        assert data["count"] == 1
        assert data["items"][0]["title"] == "Test item"
    finally:
        feed.FEED_DIR = original_dir


def test_doctor_feed_reports_sources():
    result = doctor_feed()
    assert "sources" in result
    for name, status in result["sources"].items():
        assert "ok" in status


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
