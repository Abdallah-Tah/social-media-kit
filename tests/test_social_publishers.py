"""Tests for social publisher adapters and publish flow."""
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

from agent.social_drafts import (
    SocialDraft,
    create_social_drafts_from_blog,
    load_social_draft,
    publish_social_draft,
    save_social_draft,
)
from agent.social_publishers import SUPPORTED_PLATFORMS, publish


SAMPLE_PUBLISHED_DRAFT = {
    "title": "AI Guide",
    "body": "This is the body of the published blog post.",
    "blog_url": "https://buildwithabdallah.com/tutorials/ai-guide",
}


def _make_approved_social(platform: str, tmp_path):
    drafts = create_social_drafts_from_blog(
        "src", SAMPLE_PUBLISHED_DRAFT["blog_url"],
        SAMPLE_PUBLISHED_DRAFT["title"],
        SAMPLE_PUBLISHED_DRAFT["body"],
        [platform],
    )
    sd = drafts[0]
    sd.status = "approved"
    save_social_draft(sd)
    return sd


def test_draft_status_blocks_publish(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = create_social_drafts_from_blog(
            "src", "https://example.com/blog", "Title", "Body", ["linkedin"],
        )
        sd = drafts[0]
        sd.status = "draft"
        save_social_draft(sd)
        result = publish_social_draft(sd.draft_id)
        assert result["ok"] is False
        assert "approved" in result["error"]
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


@pytest.mark.parametrize("platform", ["linkedin", "facebook", "threads", "x", "reddit"])
def test_platform_adapter_publishes_with_mock(platform, tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_approved_social(platform, tmp_path)
        module_map = {
            "linkedin": "linkedin_org_poster.post_org",
            "facebook": "fb_poster.post_text",
            "threads": "threads_poster.post",
            "x": "x_poster.post_tweet",
            "reddit": "reddit_poster.post",
        }
        with patch(module_map[platform]) as mock_post:
            if platform == "reddit":
                mock_post.return_value = {"json": {"data": {"url": "https://reddit.com/r/test/comments/123/x"}}}
            else:
                mock_post.return_value = {"id": "12345"}
            result = publish_social_draft(sd.draft_id)
        assert result["ok"] is True
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "published"
        assert loaded.published_url
        assert loaded.published_at
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_dry_run_does_not_publish(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_approved_social("facebook", tmp_path)
        with patch("fb_poster.post_text") as mock_post:
            result = publish_social_draft(sd.draft_id, dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        mock_post.assert_not_called()
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "published"
        assert result["published_url"]
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_youtube_refuses_live_publish(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_approved_social("youtube", tmp_path)
        result = publish_social_draft(sd.draft_id)
        assert result["ok"] is False
        assert "disabled" in result["error"].lower()
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "failed"
        assert loaded.error
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_failure_keeps_approved_status(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_approved_social("x", tmp_path)
        with patch("x_poster.post_tweet") as mock_post:
            mock_post.return_value = None
            result = publish_social_draft(sd.draft_id)
        assert result["ok"] is False
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "failed"
        assert loaded.error
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_newsletter_writes_file(tmp_path):
    from agent import social_drafts
    from agent.drafts import ROOT
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_approved_social("newsletter", tmp_path)
        result = publish_social_draft(sd.draft_id)
        assert result["ok"] is True
        assert result["published_url"].startswith("file://")
        assert (ROOT / "content" / "newsletter_drafts" / f"{sd.draft_id}.md").exists()
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_publish_direct_adapter_unsupported_platform():
    result = publish("pinterest", {"text": "x"})
    assert result["ok"] is False
    assert "unsupported" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
