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
        "src",
        "https://example.com/blog",
        "Rate limiting Laravel queues without losing jobs",
        (
        "Laravel queue workers will happily run the same job twice when a worker is "
        "restarted mid-execution, because the reserved_at timestamp is cleared "
        "before the handler finishes. That double execution stays invisible until "
        "it charges a customer twice.\n\nWrap the handler in an atomic Redis lock "
        "keyed on the job payload hash and release it after the transaction commits."
        ),
        ["linkedin"],
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
        with patch("linkedin_poster.post_text") as mock_post:
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
        with patch("linkedin_poster.post_text") as mock_post:
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
        with patch("linkedin_poster.post_text") as mock_post:
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
        with patch("linkedin_poster.post_text") as mock_post:
            result = publish_due_social_drafts(dry_run=True)
        assert result["results"][sd.draft_id]["ok"] is True
        mock_post.assert_not_called()
        # A rehearsal leaves the queue intact: previously the draft was marked
        # published with a placeholder URL, retiring it without ever posting.
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "scheduled"
        assert not loaded.published_url
        assert not loaded.published_at
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_quota_failure_reschedules_instead_of_failing(tmp_path):
    """A daily-limit rejection is the platform being full, not a broken draft."""
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        schedule_social_drafts([sd.draft_id], when)
        with patch("linkedin_policy.allowed") as mock_allowed:
            mock_allowed.return_value = (False, "LinkedIn skipped: daily news limit reached (5/5).")
            result = publish_due_social_drafts()
        assert result["results"][sd.draft_id]["retryable"] is True
        loaded = load_social_draft(sd.draft_id)
        assert loaded.status == "scheduled"
        assert loaded.attempts == 1
        # Requeued past midnight local, so it is no longer due this run.
        assert social_drafts._parse_when(loaded.scheduled_at) > datetime.now(timezone.utc)
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_quota_failure_gives_up_after_max_attempts(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        schedule_social_drafts([sd.draft_id], when)
        loaded = load_social_draft(sd.draft_id)
        loaded.attempts = social_drafts.MAX_PUBLISH_ATTEMPTS - 1
        save_social_draft(loaded)
        with patch("linkedin_policy.allowed") as mock_allowed:
            mock_allowed.return_value = (False, "LinkedIn skipped: daily news limit reached (5/5).")
            publish_due_social_drafts()
        assert load_social_draft(sd.draft_id).status == "failed"
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_quality_gate_failure_leaves_the_scheduled_queue(tmp_path):
    """Otherwise the hourly publisher retries an unpublishable draft forever."""
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        when = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        schedule_social_drafts([sd.draft_id], when)
        loaded = load_social_draft(sd.draft_id)
        loaded.text = "too short"
        save_social_draft(loaded)
        with patch("linkedin_poster.post_text") as mock_post:
            result = publish_due_social_drafts()
        mock_post.assert_not_called()
        assert result["results"][sd.draft_id]["ok"] is False
        parked = load_social_draft(sd.draft_id)
        assert parked.status == "needs_review"
        # No longer in the scheduled queue, so the next run does not see it.
        assert publish_due_social_drafts()["results"] == {}
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_max_per_run_caps_a_backlog_burst(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        ids = []
        for _ in range(4):
            sd = _make_draft("approved", tmp_path)
            ids.append(sd.draft_id)
        when = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))
        schedule_social_drafts(ids, when)
        with patch("linkedin_poster.post_text") as mock_post:
            mock_post.return_value = {"id": "123"}
            result = publish_due_social_drafts(max_per_run=2)
        published = [r for r in result["results"].values() if r.get("ok")]
        deferred = [r for r in result["results"].values() if r.get("skipped")]
        assert len(published) == 2
        assert len(deferred) == 2
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_stagger_spaces_a_scheduled_batch(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        ids = [_make_draft("approved", tmp_path).draft_id for _ in range(3)]
        base = datetime.now(timezone.utc) + timedelta(hours=1)
        schedule_social_drafts(ids, _iso(base), stagger_minutes=90)
        times = [social_drafts._parse_when(load_social_draft(i).scheduled_at) for i in ids]
        gaps = [(times[n + 1] - times[n]).total_seconds() / 60 for n in range(len(times) - 1)]
        assert gaps == [90, 90]
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_naive_scheduled_at_is_local_not_utc(tmp_path):
    """A naive time read as UTC published every locally-typed post early."""
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        sd = _make_draft("approved", tmp_path)
        local_now = datetime.now(social_drafts.LOCAL_TZ)
        # Two hours ahead on the local wall clock: not due yet.
        naive = (local_now + timedelta(hours=2)).replace(tzinfo=None).isoformat()
        schedule_social_drafts([sd.draft_id], naive)
        with patch("linkedin_poster.post_text") as mock_post:
            publish_due_social_drafts()
        mock_post.assert_not_called()
        assert load_social_draft(sd.draft_id).status == "scheduled"
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
