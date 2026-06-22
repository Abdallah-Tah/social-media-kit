"""Unit tests for newsletter / release mining module."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent.intelligence.newsletter_mining import (
    NewsletterItem,
    NewsletterSource,
    _classify_action,
    _hype_guard_adjustment,
    _recency_score,
    collect_newsletter_items,
    fetch_source,
    generate_newsletter_report,
    load_newsletter_sources,
    parse_html_items,
    parse_json_items,
    parse_rss_items,
    score_newsletter_items,
)


class RssParsingTests(unittest.TestCase):
    def test_parse_rss_extracts_items(self):
        xml = """<?xml version="1.0"?>
        <rss><channel>
            <item>
                <title>Laravel 12 Released</title>
                <link>https://laravel.com/blog/laravel-12</link>
                <description>What's new in Laravel.</description>
                <pubDate>Wed, 18 Jun 2026 10:00:00 GMT</pubDate>
            </item>
        </channel></rss>"""
        source = NewsletterSource(name="Laravel News", url="https://example.com/feed", type="rss")
        items = parse_rss_items(source, xml, "https://example.com/feed")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Laravel 12 Released")
        self.assertEqual(items[0].source, "Laravel News")
        self.assertIn("laravel.com/blog/laravel-12", items[0].url)

    def test_parse_atom_extracts_items(self):
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <title>Python 3.14 Features</title>
                <link href="https://python.org/news/3.14"/>
                <summary>PEP highlights.</summary>
                <published>2026-06-18T10:00:00Z</published>
            </entry>
        </feed>"""
        source = NewsletterSource(name="Python Blog", url="https://example.com/feed", type="rss")
        items = parse_rss_items(source, xml, "https://example.com/feed")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Python 3.14 Features")

    def test_rss_no_items_returns_empty(self):
        xml = "<?xml version=\"1.0\"?><rss><channel></channel></rss>"
        source = NewsletterSource(name="Empty", url="https://example.com", type="rss")
        self.assertEqual(parse_rss_items(source, xml, "https://example.com"), [])


class HtmlParsingTests(unittest.TestCase):
    def test_extracts_article_links(self):
        html = """
        <html><body>
            <article><h2><a href="/post-1">How to self-host n8n</a></h2></article>
            <article><h2><a href="/post-2">OpenAI releases new model</a></h2></article>
        </body></html>"""
        source = NewsletterSource(name="OpenAI Blog", url="https://example.com", type="html")
        items = parse_html_items(source, html, "https://example.com")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "How to self-host n8n")
        self.assertTrue(items[0].url.startswith("https://example.com/post-1"))

    def test_ignores_short_titles(self):
        html = "<html><body><a href=\"/x\">Hi</a></body></html>"
        source = NewsletterSource(name="Blog", url="https://example.com", type="html")
        self.assertEqual(parse_html_items(source, html, "https://example.com"), [])


class JsonParsingTests(unittest.TestCase):
    def test_parse_json_items(self):
        payload = [
            {
                "title": "Anthropic releases new API",
                "url": "/api-news",
                "summary": "Tool use improvements.",
                "date": "2026-06-18T10:00:00Z",
            }
        ]
        source = NewsletterSource(
            name="Anthropic API",
            url="https://example.com/api",
            type="json",
            selectors={"title": "title", "url": "url", "summary": "summary", "date": "date"},
        )
        items = parse_json_items(source, json.dumps(payload), "https://example.com")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].url.endswith("/api-news"))


class SourceConfigTests(unittest.TestCase):
    def test_disabled_source_ignored(self):
        sources = [NewsletterSource(name="Off", url="https://example.com", type="html", enabled=False)]
        items = collect_newsletter_items(sources)
        self.assertEqual(items, [])

    def test_load_newsletter_sources_from_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "newsletter_sources.yaml"
            path.write_text("sources:\n  - name: Test\n    url: https://example.com\n    type: html\n")
            loaded = load_newsletter_sources(path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "Test")


class ScoringTests(unittest.TestCase):
    def test_laravel_item_scores_high(self):
        items = [
            NewsletterItem(
                title="Laravel 12: what's new and how to upgrade",
                url="https://example.com",
                source="Laravel News",
                summary="Step-by-step upgrade guide.",
            )
        ]
        scored = score_newsletter_items(items)
        self.assertGreater(scored[0].tutorial_potential, 0)
        self.assertGreater(scored[0].knowledge_score, 0)
        self.assertGreaterEqual(scored[0].urgency_score, 0)

    def test_recency_scoring(self):
        today = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.assertEqual(_recency_score(today), 100)
        old = "2026-05-01T00:00:00Z"
        self.assertEqual(_recency_score(old), 20)

    def test_classify_action(self):
        item = NewsletterItem(
            title="Build a tool",
            url="https://example.com",
            source="Dev",
            tutorial_potential=80,
            knowledge_score=60,
        )
        self.assertEqual(_classify_action(item), "create_tutorial")


class GuardTests(unittest.TestCase):
    def test_hype_guard_downranks_business_news(self):
        item = NewsletterItem(
            title="OpenAI raises funding and hires executives",
            url="https://example.com",
            source="TechCrunch",
            summary="Corporate updates.",
        )
        penalty, note = _hype_guard_adjustment(item)
        self.assertLess(penalty, 0)
        self.assertIn("business news", note)

    def test_guardrail_hits_gambling(self):
        item = NewsletterItem(
            title="Best crypto trading strategy",
            url="https://example.com",
            source="Bad",
            summary="Leverage and margin trading tips.",
        )
        penalty, note = _hype_guard_adjustment(item)
        self.assertLess(penalty, -20)
        self.assertIn("Guardrail", note)


class ReportTests(unittest.TestCase):
    def test_newsletter_report_generated(self):
        items = [
            NewsletterItem(
                title="Laravel tutorial",
                url="https://example.com",
                source="Laravel News",
                why_developers_care="Useful for Laravel devs",
                possible_bwa_angle="Build a tutorial",
                tutorial_potential=80,
                urgency_score=70,
                action="create_tutorial",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            generate_newsletter_report(items, out)
            self.assertTrue(out.exists())
            content = out.read_text()
            self.assertIn("Laravel tutorial", content)
            self.assertIn("create tutorial", content)


if __name__ == "__main__":
    unittest.main()
