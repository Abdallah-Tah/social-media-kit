"""X is a billed channel: it carries the weekly GitHub roundup and nothing else.

Every X post costs money, so the 5x/day news lane must never reach it. These
tests exist because X was briefly wired into that lane and spent on three posts
in a single day before the policy was set.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))


def test_news_lane_has_no_x_publishing_path():
    import news_publish
    assert not hasattr(news_publish, "queue_x_post")
    source = Path(KIT / "scripts" / "news_publish.py").read_text()
    assert "x_poster" not in source
    assert "make_x_social_copy" not in source


def test_news_lane_social_touches_only_facebook_and_linkedin(tmp_path):
    """The lane's own social step must not reach X, directly or via the queue."""
    import news_publish
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        with patch("fb_poster.post_text"), patch("fb_poster.post_photo"), \
             patch("linkedin_org_poster.fetch_org_token", return_value=(None, None)), \
             patch("social_copy.make_news_social_copy", return_value="post body"), \
             patch("x_poster.post_tweet") as mock_tweet:
            news_publish.publish_social("A title", "body", "https://example.com/a", None)
        mock_tweet.assert_not_called()
        # Nothing queued for a later run to pick up and bill for, either.
        assert social_drafts.list_social_drafts(status="scheduled") == []
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


ITEMS = [
    {"name": "acme/rocket", "full_name": "acme/rocket", "weekly_stars": 4210,
     "description": "A fast thing.", "url": "https://github.com/acme/rocket"},
    {"name": "beta/parser", "full_name": "beta/parser", "weekly_stars": 3100,
     "description": "Parses things.", "url": "https://github.com/beta/parser"},
    {"name": "gamma/agentkit", "full_name": "gamma/agentkit", "weekly_stars": 2050,
     "description": "Agents.", "url": "https://github.com/gamma/agentkit"},
    {"name": "delta/tui", "full_name": "delta/tui", "weekly_stars": 1900,
     "description": "Terminal UI.", "url": "https://github.com/delta/tui"},
    {"name": "eps/db", "full_name": "eps/db", "weekly_stars": 1500,
     "description": "A database.", "url": "https://github.com/eps/db"},
]
URL = "https://buildwithabdallah.com/tutorials/github-roundup-week"


def test_roundup_x_post_fits_the_limit_with_the_link_intact():
    import github_roundup as GR
    text = GR.build_x_social(ITEMS, URL, "ai")
    assert len(text) <= 280
    assert text.endswith(URL)


def test_roundup_x_post_leads_with_the_star_total():
    import github_roundup as GR
    text = GR.build_x_social(ITEMS, URL, "ai")
    assert "12,760" in text  # 4210+3100+2050+1900+1500
    assert "acme/rocket" in text


def test_roundup_posts_to_x_once_then_never_again(tmp_path, monkeypatch):
    """One roundup, one publish. A thread is several posts but still one run."""
    import github_roundup as GR
    monkeypatch.setattr(GR, "LEDGER", str(tmp_path / "roundups.json"))
    GR.record_roundup("github-roundup-week", ITEMS)

    with patch("x_poster.post_tweet", return_value={"id": "42"}) as mock_tweet:
        GR.publish_to_x(ITEMS, URL, "ai", "github-roundup-week")
    assert mock_tweet.call_count >= 1
    assert GR.x_already_posted("github-roundup-week")

    # A re-run of the same roundup must not pay twice.
    with patch("x_poster.post_tweet") as mock_again:
        GR.publish_to_x(ITEMS, URL, "ai", "github-roundup-week")
    mock_again.assert_not_called()


def test_no_thread_flag_costs_exactly_one_post(tmp_path, monkeypatch):
    """Each thread post is billed, so the single-post form must stay reachable."""
    import github_roundup as GR
    monkeypatch.setattr(GR, "LEDGER", str(tmp_path / "roundups.json"))
    GR.record_roundup("github-roundup-week", ITEMS)
    with patch("x_poster.post_tweet", return_value={"id": "42"}) as mock_tweet:
        GR.publish_to_x(ITEMS, URL, "ai", "github-roundup-week", thread=False)
    assert mock_tweet.call_count == 1


def test_thread_over_the_cap_falls_back_to_one_post(tmp_path, monkeypatch):
    """A freak 30-repo week must not silently become a 30-post charge."""
    import github_roundup as GR
    monkeypatch.setattr(GR, "LEDGER", str(tmp_path / "roundups.json"))
    monkeypatch.setattr(GR, "MAX_THREAD_POSTS", 2)
    GR.record_roundup("github-roundup-week", ITEMS)
    with patch("x_poster.post_tweet", return_value={"id": "42"}) as mock_tweet:
        GR.publish_to_x(ITEMS, URL, "ai", "github-roundup-week")
    assert mock_tweet.call_count == 1


def test_partial_thread_is_recorded_so_a_rerun_does_not_repost(tmp_path, monkeypatch):
    """The first post is already public; a retry must not pay for it again."""
    import github_roundup as GR
    monkeypatch.setattr(GR, "LEDGER", str(tmp_path / "roundups.json"))
    GR.record_roundup("github-roundup-week", ITEMS)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        return {"id": "42"} if calls["n"] == 1 else {"error": "rate limited"}

    with patch("x_poster.post_tweet", side_effect=flaky):
        GR.publish_to_x(ITEMS, URL, "ai", "github-roundup-week")
    assert GR.x_already_posted("github-roundup-week")


def test_failed_x_post_is_not_recorded_as_posted(tmp_path, monkeypatch):
    """A failure must stay retryable rather than burn the one allowed post."""
    import github_roundup as GR
    monkeypatch.setattr(GR, "LEDGER", str(tmp_path / "roundups.json"))
    GR.record_roundup("github-roundup-week", ITEMS)
    with patch("x_poster.post_tweet", return_value=None):
        GR.publish_to_x(ITEMS, URL, "ai", "github-roundup-week")
    assert not GR.x_already_posted("github-roundup-week")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
