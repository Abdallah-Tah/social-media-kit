"""Tests for the read-only Intelligence dashboard."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from agent.dashboard_intelligence import (
    filter_cards,
    handle_brief,
    handle_briefs,
    handle_run,
    handle_snapshot,
    handle_snapshots,
    load_snapshot,
    list_snapshots,
)


def sample_cards() -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "opportunity": {"opportunity_score": 75, "signals": ["test"]},
            "trend": {"direction": "exploding"},
            "recommendation": {"recommendation": "youtube_short", "confidence_score": 80},
            "cluster": {"headline": "A", "urls": ["https://a.com"], "sources": ["hackernews"]},
        },
        {
            "rank": 2,
            "opportunity": {"opportunity_score": 45, "signals": ["test"]},
            "trend": {"direction": "stable"},
            "recommendation": {"recommendation": "blog", "confidence_score": 60},
            "cluster": {"headline": "B", "urls": ["https://b.com"], "sources": ["rss"]},
        },
        {
            "rank": 3,
            "opportunity": {"opportunity_score": 20, "signals": []},
            "trend": {"direction": "dead"},
            "recommendation": {"recommendation": "skip", "confidence_score": 20},
            "cluster": {"headline": "C", "urls": ["https://c.com"], "sources": ["rss"]},
        },
    ]


def test_list_snapshots_empty(tmp_path):
    from agent import dashboard_intelligence

    original = dashboard_intelligence.SNAPSHOTS_DIR
    dashboard_intelligence.SNAPSHOTS_DIR = tmp_path
    try:
        assert list_snapshots() == []
    finally:
        dashboard_intelligence.SNAPSHOTS_DIR = original


def test_list_snapshots_returns_sorted(tmp_path):
    from agent import dashboard_intelligence

    original = dashboard_intelligence.SNAPSHOTS_DIR
    dashboard_intelligence.SNAPSHOTS_DIR = tmp_path
    try:
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        snaps = list_snapshots()
        assert len(snaps) == 2
        assert all("name" in s and "when" in s for s in snaps)
    finally:
        dashboard_intelligence.SNAPSHOTS_DIR = original


def test_load_snapshot_bad_name():
    assert "error" in load_snapshot("../secrets.json")


def test_filter_cards_min_score():
    cards = sample_cards()
    assert len(filter_cards(cards, 50, "", "")) == 1
    assert filter_cards(cards, 50, "", "")[0]["rank"] == 1


def test_filter_cards_trend():
    cards = sample_cards()
    assert len(filter_cards(cards, 0, "exploding", "")) == 1


def test_filter_cards_content_type():
    cards = sample_cards()
    assert len(filter_cards(cards, 0, "", "blog")) == 1


def test_filter_cards_combined():
    cards = sample_cards()
    assert len(filter_cards(cards, 70, "exploding", "youtube_short")) == 1


def test_handle_brief_no_publish():
    body = {"card": sample_cards()[0]}
    result = handle_brief(body)
    assert result["ok"] is True
    brief = result["brief"]
    assert brief["publish_ready"] is False
    assert brief["content_type"] == "youtube_short"
    assert brief["title"]
    assert brief["hook"]


def test_handle_run_does_not_mutate_seen_store(tmp_path):
    from agent import dashboard_intelligence
    from agent import feed
    from agent import feed_intelligence

    original_feed_dir = feed.FEED_DIR
    original_seen_path = feed.SEEN_PATH
    original_snapshots_dir = dashboard_intelligence.SNAPSHOTS_DIR
    feed.FEED_DIR = tmp_path
    feed.SEEN_PATH = tmp_path / "seen.json"
    dashboard_intelligence.SNAPSHOTS_DIR = tmp_path / "intel"

    item = type(
        "Item",
        (),
        {
            "title": "Laravel AI",
            "url": "https://laravel.com/ai",
            "source": "rss",
            "published_at": "2026-07-09T11:00:00+00:00",
            "summary": "",
            "score": 50.0,
            "matched_interests": ["laravel"],
            "reason": "",
            "metadata": {},
            "to_dict": lambda self: {},
        },
    )()
    feed_intelligence.build_feed = lambda **kwargs: [item]
    try:
        result = handle_run({"topic": ["laravel"], "include_seen": ["0"]})
        assert result["ok"] is True
        # Dashboard run does not save snapshots automatically.
        assert not (tmp_path / "intel" / "run.json").exists()
    finally:
        feed_intelligence.build_feed = None
        feed.FEED_DIR = original_feed_dir
        feed.SEEN_PATH = original_seen_path
        dashboard_intelligence.SNAPSHOTS_DIR = original_snapshots_dir


def test_handle_briefs_no_publish():
    cards = sample_cards()[:2]
    cards[0]["recommendation"]["recommendation"] = "youtube_short"
    cards[1]["recommendation"]["recommendation"] = "blog"
    result = handle_briefs({"cards": cards})
    assert result["ok"] is True
    assert len(result["briefs"]) == 2
    assert result["briefs"][0]["publish_ready"] is False
    assert result["briefs"][0]["content_type"] == "youtube_short"
    assert result["briefs"][1]["content_type"] == "blog"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
