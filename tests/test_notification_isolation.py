"""Notification isolation — tests must never send real Telegram messages.

Verifies that the environment guard in agent.notify blocks all outbound
notifications unless the process is explicitly configured for production.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from agent.notify import notifications_enabled, notify_publish


# ── helpers ──────────────────────────────────────────────────────────────────

def _clear_notification_env():
    """Remove every env var the guard inspects."""
    for key in ("SMKIT_ENV", "SMKIT_NOTIFICATIONS_ENABLED",
                "SMKIT_MODE", "SMKIT_TESTING"):
        os.environ.pop(key, None)


def _production_env():
    """Set the minimum env for notifications to be permitted."""
    os.environ["SMKIT_ENV"] = "production"
    os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "1"
    os.environ.pop("SMKIT_MODE", None)
    os.environ.pop("SMKIT_TESTING", None)


# ── guard unit tests ─────────────────────────────────────────────────────────

class TestNotificationsEnabledGuard:
    def setup_method(self):
        _clear_notification_env()

    def teardown_method(self):
        _clear_notification_env()

    def test_default_disabled(self):
        """No env vars → notifications disabled."""
        assert notifications_enabled() is False

    def test_production_env_alone_not_enough(self):
        os.environ["SMKIT_ENV"] = "production"
        assert notifications_enabled() is False

    def test_production_with_opt_in(self):
        _production_env()
        assert notifications_enabled() is True

    def test_prod_alias_accepted(self):
        os.environ["SMKIT_ENV"] = "prod"
        os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "1"
        assert notifications_enabled() is True

    def test_testing_blocks_even_in_production(self):
        _production_env()
        os.environ["SMKIT_TESTING"] = "1"
        assert notifications_enabled() is False

    def test_dry_run_mode_blocks(self):
        _production_env()
        os.environ["SMKIT_MODE"] = "dry_run"
        assert notifications_enabled() is False

    def test_test_mode_blocks(self):
        _production_env()
        os.environ["SMKIT_MODE"] = "test"
        assert notifications_enabled() is False

    def test_shadow_mode_blocks(self):
        _production_env()
        os.environ["SMKIT_MODE"] = "shadow"
        assert notifications_enabled() is False

    def test_replay_mode_blocks(self):
        _production_env()
        os.environ["SMKIT_MODE"] = "replay"
        assert notifications_enabled() is False

    def test_simulated_mode_blocks(self):
        _production_env()
        os.environ["SMKIT_MODE"] = "simulated"
        assert notifications_enabled() is False

    def test_staging_env_blocked(self):
        os.environ["SMKIT_ENV"] = "staging"
        os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "1"
        assert notifications_enabled() is False

    def test_opt_in_required(self):
        os.environ["SMKIT_ENV"] = "production"
        os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "0"
        assert notifications_enabled() is False


# ── notify_publish integration tests ─────────────────────────────────────────

class TestNotifyPublishIsolation:
    """Prove that notify_publish never reaches telegram_poster unless
    the full production guard is satisfied."""

    def setup_method(self):
        _clear_notification_env()

    def teardown_method(self):
        _clear_notification_env()

    def test_test_mode_sends_zero_telegram_messages(self):
        os.environ["SMKIT_ENV"] = "production"
        os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "1"
        os.environ["SMKIT_TESTING"] = "1"
        with patch("scripts.telegram_poster.post_message") as mock_tg:
            result = notify_publish("test message")
        assert result is False
        mock_tg.assert_not_called()

    def test_shadow_mode_sends_zero_telegram_messages(self):
        os.environ["SMKIT_ENV"] = "production"
        os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "1"
        os.environ["SMKIT_MODE"] = "shadow"
        with patch("scripts.telegram_poster.post_message") as mock_tg:
            result = notify_publish("shadow message")
        assert result is False
        mock_tg.assert_not_called()

    def test_replay_mode_sends_zero_telegram_messages(self):
        os.environ["SMKIT_ENV"] = "production"
        os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "1"
        os.environ["SMKIT_MODE"] = "replay"
        with patch("scripts.telegram_poster.post_message") as mock_tg:
            result = notify_publish("replay message")
        assert result is False
        mock_tg.assert_not_called()

    def test_dry_run_mode_sends_zero_telegram_messages(self):
        os.environ["SMKIT_ENV"] = "production"
        os.environ["SMKIT_NOTIFICATIONS_ENABLED"] = "1"
        os.environ["SMKIT_MODE"] = "dry_run"
        with patch("scripts.telegram_poster.post_message") as mock_tg:
            result = notify_publish("dry-run message")
        assert result is False
        mock_tg.assert_not_called()

    def test_default_env_sends_zero_telegram_messages(self):
        """No SMKIT_ENV set → blocked."""
        with patch("scripts.telegram_poster.post_message") as mock_tg:
            result = notify_publish("should not send")
        assert result is False
        mock_tg.assert_not_called()

    def test_fake_publisher_responses_do_not_reach_production_notifier(self):
        """Simulate the exact test scenario that leaked: a mocked platform
        publisher returns {"id": "12345"}, the social publisher calls
        notify_publish — the Telegram call must be blocked."""
        from agent.social_publishers import publish

        fake_draft = {
            "title": "Rate limiting Laravel queues",
            "text": "Laravel queue workers will happily run the same job twice.",
        }
        with patch("linkedin_poster.post_text", return_value={"id": "12345"}), \
             patch("scripts.telegram_poster.post_message") as mock_tg:
            result = publish("linkedin", fake_draft, dry_run=False)
        assert result["ok"] is True
        mock_tg.assert_not_called()

    def test_live_production_mode_sends_through_mocked_notifier(self):
        """When the full production guard is satisfied, notify_publish
        reaches telegram_poster (verified via mock)."""
        _production_env()
        with patch("telegram_poster.post_message", return_value={"ok": True}) as mock_tg:
            result = notify_publish("✅ Posted to linkedin: test\nhttps://linkedin.com/12345")
        assert result is True
        mock_tg.assert_called_once()

    def test_blog_publish_test_slug_does_not_notify(self):
        """Reproduce the exact /test-slug leak: mocked blog_publisher returns
        slug='test-slug', publish_blog calls notify_publish — must be blocked."""
        from agent import drafts
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            original_dir = drafts.DRAFTS_DIR
            drafts.DRAFTS_DIR = Path(tmp)
            try:
                draft = drafts.create_draft(
                    {"title": "Test", "url": "https://example.com", "score": 90},
                    {"excerpt": "Test", "content_type": "article", "title": "Test",
                     "angle": "Test angle", "key_points": ["point one for the article"],
                     "call_to_action": "Read more", "hook": "A hook for testing purposes that is long enough."},
                )
                drafts.transition_status(draft.draft_id, "approved")
                with patch("agent.drafts._generate_cover_for_draft", return_value={}), \
                     patch("blog_publisher.publish_article", return_value={"id": 42, "slug": "test-slug"}), \
                     patch("scripts.telegram_poster.post_message") as mock_tg:
                    drafts.publish_blog(draft.draft_id)
                mock_tg.assert_not_called()
            finally:
                drafts.DRAFTS_DIR = original_dir


# ── notify_feed isolation ────────────────────────────────────────────────────

class TestNotifyFeedIsolation:
    def setup_method(self):
        _clear_notification_env()

    def teardown_method(self):
        _clear_notification_env()

    def test_notify_feed_suppressed_outside_production(self):
        from agent.feed import FeedItem, notify_feed

        items = [FeedItem(
            title="Test story", url="https://example.com/1",
            score=90.0, source="hackernews", published_at="2026-07-28T12:00:00Z",
            summary="A test summary for isolation testing.",
        )]
        with patch("scripts.telegram_poster.post_message") as mock_tg:
            result = notify_feed(items, dry_run=False)
        mock_tg.assert_not_called()
        assert result.get("suppressed") is True

    def test_notify_feed_dry_run_never_sends(self):
        from agent.feed import FeedItem, notify_feed

        items = [FeedItem(
            title="Test story", url="https://example.com/1",
            score=90.0, source="hackernews", published_at="2026-07-28T12:00:00Z",
        )]
        with patch("scripts.telegram_poster.post_message") as mock_tg:
            result = notify_feed(items, dry_run=True)
        mock_tg.assert_not_called()
        assert result.get("dry_run") is True


# ── blog API test-slug guard ─────────────────────────────────────────────────

class TestBlogApiTestSlugGuard:
    """Test slugs must never reach the live blog API."""

    def test_test_slug_does_not_reach_blog_api(self, tmp_path):
        """Even if the guard were bypassed, verify that a test using a mocked
        blog_publisher with slug='test-slug' does not call the real API."""
        from agent import drafts

        original_dir = drafts.DRAFTS_DIR
        drafts.DRAFTS_DIR = tmp_path
        try:
            draft = drafts.create_draft(
                {"title": "Test", "url": "https://example.com", "score": 90},
                {"excerpt": "Test", "content_type": "article", "title": "Test",
                 "angle": "Test angle", "key_points": ["point one for the article"],
                 "call_to_action": "Read more", "hook": "A hook for testing purposes that is long enough."},
            )
            drafts.transition_status(draft.draft_id, "approved")
            with patch("agent.drafts._generate_cover_for_draft", return_value={}), \
                 patch("blog_publisher.publish_article", return_value={"id": 42, "slug": "test-slug"}) as mock_pub, \
                 patch("scripts.telegram_poster.post_message") as mock_tg:
                result = drafts.publish_blog(draft.draft_id)
            assert result["ok"] is True
            mock_pub.assert_called_once()
            mock_tg.assert_not_called()
        finally:
            drafts.DRAFTS_DIR = original_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
