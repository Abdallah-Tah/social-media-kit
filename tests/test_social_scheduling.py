"""Tests for social draft scheduling and publish-due."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from agent.social_drafts import (
    create_social_drafts_from_blog,
    load_social_draft,
    publish_due_social_drafts,
    save_social_draft,
    schedule_social_drafts,
)


def _iso(when):
    return when.isoformat()


def _make_draft(status, tmp_path):
    drafts = create_social_drafts_from_blog(
        "src", "https://example.com/blog", "Title", "Body", ["linkedin"],
    )
    sd = drafts[0]
    sd.status = status
    save_social_draft(sd)
    return sd


def test_cannot_schedule_unapproved_draft(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("draft", tmp_path)
        when = _iso(datetime.now(timezone.utc) + timedelta(hours=1))
        result = schedule_social_drafts([sd.draft_id], when)
        assert result["results"][sd.draft_id]["ok"] is False
        assert "approved" in result["results"][sd.draft_id]["error"]
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_approved_draft_schedules_correctly(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) + timedelta(hours=2))
        result = schedule_social_drafts([sd.draft_id], when)
        assert result["results"][sd.draft_id]["ok"] is True
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "scheduled"
        assert loaded.scheduled_at == when
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_publish_due_skips_future_drafts(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) + timedelta(hours=1))
        schedule_social_drafts([sd.draft_id], when)
        with patch("linkedin_org_poster.post_org") as mock_post:
            mock_post.return_value = {"id": "123"}
            result = publish_due_social_drafts()
        assert result["results"][sd.draft_id]["skipped"] is True
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "scheduled"
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_publish_due_publishes_due_drafts(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        schedule_social_drafts([sd.draft_id], when)
        with patch("linkedin_org_poster.post_org") as mock_post:
            mock_post.return_value = {"id": "123"}
            result = publish_due_social_drafts()
        assert result["results"][sd.draft_id]["ok"] is True
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "published"
        assert loaded.published_url
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_publish_due_failure_marks_failed(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        schedule_social_drafts([sd.draft_id], when)
        with patch("linkedin_org_poster.post_org") as mock_post:
            mock_post.return_value = None
            result = publish_due_social_drafts()
        assert result["results"][sd.draft_id]["ok"] is False
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "failed"
        assert loaded.error
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_publish_due_dry_run_does_not_publish_live(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        schedule_social_drafts([sd.draft_id], when)
        with patch("linkedin_org_poster.post_org") as mock_post:
            result = publish_due_social_drafts(dry_run=True)
        assert result["results"][sd.draft_id]["ok"] is True
        mock_post.assert_not_called()
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "published"
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
