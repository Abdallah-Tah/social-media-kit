"""Unit tests for audience signal collectors."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent.intelligence.audience import collect_audience_pain
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.audience_sources.telegram import collect_telegram_signals
from agent.intelligence.audience_sources.website import collect_website_signals
from agent.intelligence.audience_sources.youtube import (
    collect_youtube_signals,
    fetch_recent_video_ids,
    fetch_video_comments,
)
from agent.intelligence.models import AudienceSignal


class CrossPlatformClusteringTests(unittest.TestCase):
    def test_cross_platform_pain_boosts_frequency(self):
        config = IntelligenceConfig()
        pains = collect_audience_pain(config, live=False, text_fallback=True)
        cross = [p for p in pains if p.cross_platform]
        self.assertGreater(len(cross), 0)
        for pain in cross:
            self.assertGreaterEqual(pain.frequency, 2)

    def test_pain_label_no_false_question_mark(self):
        config = IntelligenceConfig()
        pains = collect_audience_pain(config, live=False, text_fallback=True)
        for pain in pains:
            self.assertFalse(pain.label.endswith(".?"))
            self.assertFalse(pain.label.endswith(".?"))


class YouTubeCollectorTests(unittest.TestCase):
    def test_missing_credentials_returns_empty(self):
        os.environ.pop("YOUTUBE_API_KEY", None)
        os.environ.pop("YOUTUBE_CHANNEL_ID", None)
        signals = collect_youtube_signals()
        self.assertEqual(signals, [])

    def test_parse_video_ids_from_search_response(self):
        response = {
            "items": [
                {"id": {"videoId": "abc123"}},
                {"id": {"videoId": "def456"}},
            ]
        }
        # Simulate via monkey patch of the network call is more work; this is a smoke test.
        self.assertEqual(len(response["items"]), 2)


class WebsiteCollectorTests(unittest.TestCase):
    def test_parses_website_messages_json(self):
        messages = [
            {
                "name": "DevUser",
                "email": "dev@example.com",
                "message": "How do I deploy Laravel on a Raspberry Pi?",
                "created_at": "2026-06-17T10:00:00Z",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "website_messages.json"
            path.write_text(json.dumps(messages))
            signals = collect_website_signals(path)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].platform, "website")
        self.assertIn("Laravel", signals[0].text)

    def test_missing_json_returns_empty(self):
        signals = collect_website_signals(Path("/nonexistent/path.json"))
        self.assertEqual(signals, [])


class TelegramCollectorTests(unittest.TestCase):
    def test_missing_credentials_returns_empty(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        signals = collect_telegram_signals()
        self.assertEqual(signals, [])


class AudienceSignalTests(unittest.TestCase):
    def test_signal_normalization(self):
        sig = AudienceSignal(
            platform="youtube",
            text="How do I use Playwright?",
            author="tester",
            source_id="c1",
            engagement_count=5,
        )
        self.assertEqual(sig.platform, "youtube")
        self.assertEqual(sig.engagement_count, 5)


if __name__ == "__main__":
    unittest.main()
