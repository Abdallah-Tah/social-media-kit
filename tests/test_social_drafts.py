"""Tests for social draft generation from published blog posts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.social_drafts import (
    SUPPORTED_PLATFORMS,
    SocialDraft,
    create_social_drafts_from_blog,
    delete_social_draft,
    generate_social_drafts,
    list_social_drafts,
    load_social_draft,
    update_social_draft,
)


def test_cannot_generate_without_blog_url(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = generate_social_drafts("abc", "", "Title", "Body", ["linkedin"])
        assert drafts == []
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_generates_selected_platforms_only(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = create_social_drafts_from_blog(
            "abc", "https://buildwithabdallah.com/tutorials/test", "Title", "Body text here",
            ["linkedin", "x"],
        )
        assert len(drafts) == 2
        platforms = {d.platform for d in drafts}
        assert platforms == {"linkedin", "x"}
        assert all(d.blog_url == "https://buildwithabdallah.com/tutorials/test" for d in drafts)
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_blog_url_included_in_text(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        url = "https://buildwithabdallah.com/tutorials/ai-guide"
        drafts = create_social_drafts_from_blog("abc", url, "AI Guide", "Body", ["facebook"])
        assert drafts[0].blog_url == url
        assert url in drafts[0].text
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_social_drafts_are_editable(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = create_social_drafts_from_blog(
            "abc", "https://example.com/blog", "Title", "Body", ["linkedin"],
        )
        sd = drafts[0]
        updated = update_social_draft(sd.draft_id, {"text": "Updated text", "status": "approved"})
        assert updated is not None
        assert updated.text == "Updated text"
        assert updated.status == "approved"
        assert updated.updated_at != updated.created_at
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_no_live_publishing_happens(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = create_social_drafts_from_blog(
            "abc", "https://example.com/blog", "Title", "Body", list(SUPPORTED_PLATFORMS),
        )
        assert len(drafts) == len(SUPPORTED_PLATFORMS)
        assert all(d.status == "draft" for d in drafts)
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_list_social_drafts_by_source_and_status(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        create_social_drafts_from_blog(
            "s1", "https://example.com/1", "A", "Body", ["linkedin"],
        )
        s2 = create_social_drafts_from_blog(
            "s2", "https://example.com/2", "B", "Body", ["linkedin"],
        )[0]
        update_social_draft(s2.draft_id, {"status": "approved"})
        assert len(list_social_drafts(source_draft_id="s1")) == 1
        assert len(list_social_drafts(source_draft_id="s2")) == 1
        assert len(list_social_drafts(status="approved")) == 1
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
