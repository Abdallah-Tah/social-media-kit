"""Tests for Phase 1: explainable authority scoring."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from agent.feed_authority import (
    AuthorityBreakdown,
    history_score_for,
    item_authority,
    load_domain_authority,
    record_domain_success,
    save_domain_authority,
    social_score_for,
)


def test_load_domain_authority_has_defaults():
    auth = load_domain_authority()
    assert "github.com" in auth
    assert "reuters.com" in auth
    assert 0.0 <= auth["github.com"] <= 1.0


def test_user_overrides_persist(tmp_path):
    from agent import feed_authority

    original = feed_authority.DOMAIN_AUTHORITY_PATH
    feed_authority.DOMAIN_AUTHORITY_PATH = tmp_path / "domain_authority.json"
    try:
        save_domain_authority({"example.com": 0.95})
        merged = load_domain_authority()
        assert merged["example.com"] == 0.95
    finally:
        feed_authority.DOMAIN_AUTHORITY_PATH = original



def test_item_authority_known_domain():
    breakdown = item_authority("https://github.com/torvalds/linux", "rss")
    assert breakdown.domain_score == 0.85
    assert breakdown.final_score >= 0.5
    assert any("github.com" in s for s in breakdown.signals)


def test_item_authority_subdomain_match():
    breakdown = item_authority("https://blog.github.com/features", "rss")
    assert breakdown.domain_score == 0.85


def test_item_authority_unknown_domain():
    breakdown = item_authority("https://some-random-blog.example.com/post", "rss")
    assert breakdown.domain_score == 0.45
    assert "unknown domain" in breakdown.signals


def test_social_score_for_hn_upvotes():
    score, signals = social_score_for({"upvotes": 600, "comments": 120})
    assert score >= 0.15
    assert any("600" in s for s in signals)


def test_social_score_no_metadata():
    score, signals = social_score_for(None)
    assert score == 0.0
    assert signals == []


def test_history_score_capped():
    from agent import feed_authority

    original = feed_authority.DOMAIN_HISTORY_PATH
    feed_authority.DOMAIN_HISTORY_PATH = Path("/dev/null")
    history = {"clicks": {"example.com": 100}, "shares": {"example.com": 50}}
    try:
        score = history_score_for("example.com", history)
        assert 0 < score <= 0.25
    finally:
        feed_authority.DOMAIN_HISTORY_PATH = original


def test_record_domain_success(tmp_path):
    from agent import feed_authority

    original = feed_authority.DOMAIN_HISTORY_PATH
    feed_authority.DOMAIN_HISTORY_PATH = tmp_path / "history.json"
    try:
        record_domain_success("buildwithabdallah.com", kind="click", value=2)
        history = json.loads(feed_authority.DOMAIN_HISTORY_PATH.read_text())
        assert history["clicks"]["buildwithabdallah.com"] == 2
    finally:
        feed_authority.DOMAIN_HISTORY_PATH = original


def test_authority_breakdown_to_dict():
    b = AuthorityBreakdown(final_score=0.75, signals=["domain: github.com"])
    d = b.to_dict()
    assert d["final_score"] == 0.75
    assert "signals" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
