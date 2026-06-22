"""Unit tests for content gap detection."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.intelligence.content_gap import (
    _normalize,
    _token_set,
    detect_content_gap,
    load_local_content_index,
    load_sitemap_content,
)
from agent.intelligence.models import ExistingContentItem


class NormalizationTests(unittest.TestCase):
    def test_normalize_lowercases_and_strips_punctuation(self):
        self.assertEqual(_normalize("Hello, World!"), "hello world")

    def test_token_set_drops_stopwords(self):
        tokens = _token_set("How to deploy a Laravel app")
        self.assertIn("laravel", tokens)
        self.assertIn("deploy", tokens)
        self.assertNotIn("how", tokens)
        self.assertNotIn("a", tokens)


class GapDetectionTests(unittest.TestCase):
    def test_true_gap_when_no_existing_content(self):
        result = detect_content_gap("Deploy Laravel on Raspberry Pi", "", [])
        self.assertEqual(result.gap_score, 100)
        self.assertEqual(result.duplicate_risk, "none")
        self.assertEqual(result.action, "create")

    def test_exact_duplicate_detected(self):
        existing = [
            ExistingContentItem(
                title="Deploy Laravel on Raspberry Pi",
                url="https://example.com/deploy-laravel-raspberry-pi",
                slug="deploy-laravel-raspberry-pi",
                published_at="2026-06-17T00:00:00Z",
            )
        ]
        result = detect_content_gap("Deploy Laravel on Raspberry Pi", "", existing)
        self.assertLess(result.gap_score, 25)
        self.assertEqual(result.duplicate_risk, "high")
        self.assertEqual(result.action, "skip")

    def test_near_duplicate_update_suggestion(self):
        existing = [
            ExistingContentItem(
                title="Laravel on Raspberry Pi tutorial",
                url="https://example.com/laravel-raspberry-pi",
                slug="laravel-raspberry-pi",
                published_at="2026-01-01T00:00:00Z",
            )
        ]
        result = detect_content_gap("How to deploy Laravel on a Raspberry Pi", "", existing)
        self.assertGreaterEqual(result.gap_score, 20)
        self.assertLess(result.gap_score, 60)
        self.assertEqual(result.action, "update")

    def test_related_but_distinct_angle(self):
        existing = [
            ExistingContentItem(
                title="Building AI Agents with Python",
                url="https://example.com/ai-agents-python",
                slug="ai-agents-python",
            )
        ]
        result = detect_content_gap("Deploying AI agents on a Raspberry Pi", "", existing)
        self.assertGreaterEqual(result.gap_score, 50)
        self.assertLess(result.gap_score, 100)


class LocalIndexTests(unittest.TestCase):
    def test_loads_existing_content_json(self):
        items = [
            {
                "title": "Laravel Queues Explained",
                "url": "https://example.com/laravel-queues",
                "slug": "laravel-queues",
                "category": "tutorial",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing_content.json"
            path.write_text(json.dumps(items))
            loaded = load_local_content_index(path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].title, "Laravel Queues Explained")


class SitemapFailureTests(unittest.TestCase):
    def test_bad_sitemap_url_returns_empty(self):
        result = load_sitemap_content("https://invalid.example.com/sitemap.xml")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
