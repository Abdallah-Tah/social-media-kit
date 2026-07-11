"""Tests for the draft workspace."""
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

from agent.drafts import (
    ContentDraft,
    create_draft,
    delete_draft,
    list_drafts,
    load_draft,
    publish_blog,
    transition_status,
    update_draft,
)


SAMPLE_CARD = {
    "cluster": {
        "headline": "GPT-5.6 approved for public release",
        "urls": ["https://example.com/gpt56"],
        "sources": ["hackernews"],
        "representative": {"title": "GPT-5.6 approved", "url": "https://example.com/gpt56"},
    },
    "recommendation": {"recommendation": "youtube_short", "confidence_score": 0.85},
    "opportunity": {"opportunity_score": 91},
}

SAMPLE_BRIEF = {
    "content_type": "youtube_short",
    "title": "GPT-5.6 Public Release Changes Everything",
    "hook": "OpenAI quietly got approval for GPT-5.6...",
    "markdown": "# GPT-5.6\n\nBody here.",
}


def test_create_draft(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        assert draft.title == "GPT-5.6 Public Release Changes Everything"
        assert draft.content_type == "youtube_short"
        assert draft.status == "draft"
        assert draft.source_urls == ["https://example.com/gpt56"]
        assert len(draft.draft_id) == 8
        path = drafts._draft_path(draft.draft_id)
        assert path.exists()
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_load_and_update_draft(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        loaded = load_draft(draft.draft_id)
        assert loaded is not None
        assert loaded.title == draft.title

        updated = update_draft(draft.draft_id, {"title": "Updated Title", "body": "New body"})
        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.body == "New body"
        assert updated.updated_at != updated.created_at
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_status_transitions(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        assert transition_status(draft.draft_id, "reviewed") is not None
        assert transition_status(draft.draft_id, "approved") is not None
        assert transition_status(draft.draft_id, "published") is None
        assert transition_status(draft.draft_id, "invalid") is None

        loaded = load_draft(draft.draft_id)
        assert loaded.status == "approved"
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_list_drafts_by_status(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        d1 = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        d2 = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        transition_status(d2.draft_id, "approved")
        assert len(list_drafts()) == 2
        assert len(list_drafts("approved")) == 1
        assert list_drafts("approved")[0]["draft_id"] == d2.draft_id
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_delete_draft(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        assert delete_draft(draft.draft_id) is True
        assert load_draft(draft.draft_id) is None
        assert delete_draft(draft.draft_id) is False
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_draft_to_dict_roundtrip(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = ContentDraft(title="Hello World", content_type="blog", body="x")
        save_path = drafts.save_draft(draft)
        data = save_path.read_text()
        assert "draft_id" in data
        loaded = load_draft(draft.draft_id)
        assert loaded.title == "Hello World"
        assert loaded.slug == "hello-world"
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_publish_requires_approved_status(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        result = publish_blog(draft.draft_id)
        assert result["ok"] is False
        assert "approved" in result["error"]
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_approved_draft_publishes_blog_and_saves_url(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        transition_status(draft.draft_id, "approved")
        with patch("blog_publisher.publish_article") as mock_pub:
            mock_pub.return_value = {"id": 999, "slug": draft.slug}
            result = publish_blog(draft.draft_id)
        assert result["ok"] is True
        assert result["blog_url"].endswith(f"/tutorials/{draft.slug}")

        loaded = load_draft(draft.draft_id)
        assert loaded.status == "published"
        assert loaded.blog_url == result["blog_url"]
        assert loaded.published_at
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_publish_failure_keeps_draft_approved(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        transition_status(draft.draft_id, "approved")
        with patch("blog_publisher.publish_article") as mock_pub:
            mock_pub.return_value = None
            result = publish_blog(draft.draft_id)
        assert result["ok"] is False
        loaded = load_draft(draft.draft_id)
        assert loaded.status == "approved"
        assert not loaded.blog_url
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_publish_blog_no_social_side_effects(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        transition_status(draft.draft_id, "approved")
        with patch("blog_publisher.publish_article") as mock_pub:
            mock_pub.return_value = {"id": 42, "slug": "test-slug"}
            publish_blog(draft.draft_id)
            mock_pub.assert_called_once()
    finally:
        drafts.DRAFTS_DIR = original_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_create_draft_builds_body_from_structured_brief(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    structured_brief = {
        "content_type": "youtube_short",
        "title": "AI Agent Memory in 60 Seconds",
        "hook": "Choosing memory strategy changes how reliable your agent feels.",
        "angle": "Decision tree for builders",
        "key_points": ["Use short-term memory for the current task.", "Use long-term memory for preferences."],
        "call_to_action": "Follow for more builder news.",
        "suggested_assets": ["Vertical brand card"],
    }
    try:
        draft = create_draft(SAMPLE_CARD, structured_brief)
        assert draft.body
        assert "## 60-second script" in draft.body
        assert "Use short-term memory" in draft.body
        assert "https://example.com/gpt56" in draft.body
    finally:
        drafts.DRAFTS_DIR = original_dir


def test_cannot_mark_unpublished_draft_as_published(tmp_path):
    from agent import drafts
    original_dir = drafts.DRAFTS_DIR
    drafts.DRAFTS_DIR = tmp_path
    try:
        draft = create_draft(SAMPLE_CARD, SAMPLE_BRIEF)
        assert update_draft(draft.draft_id, {"status": "published"}) is None
        loaded = load_draft(draft.draft_id)
        assert loaded.status == "draft"
        assert not loaded.blog_url
    finally:
        drafts.DRAFTS_DIR = original_dir
