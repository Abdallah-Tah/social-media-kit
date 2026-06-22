"""Unit tests for Pitch Agent / World Cup performance collector."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.intelligence.performance_sources.pitch_agent import (
    PitchAgentPost,
    classify_pitch_post,
    collect_pitch_agent_metrics,
    contains_gambling_language,
    generate_pitch_report,
    summarize_pitch_agent_metrics,
)


class ClassificationTests(unittest.TestCase):
    def test_software_build_log_classification(self):
        ctype = classify_pitch_post(
            "How I built the prediction card pipeline with Python and ffmpeg"
        )
        self.assertEqual(ctype, "software_build_log")

    def test_automation_pipeline_classification(self):
        ctype = classify_pitch_post(
            "Using a Raspberry Pi to automate Telegram approval workflows"
        )
        self.assertEqual(ctype, "automation_pipeline")

    def test_analytics_explainer_classification(self):
        ctype = classify_pitch_post(
            "World Cup prediction model: data, metrics, and accuracy"
        )
        self.assertEqual(ctype, "analytics_explainer")

    def test_generic_sports_content_classification(self):
        ctype = classify_pitch_post("Match preview: Argentina vs Brazil")
        self.assertEqual(ctype, "generic_sports_content")

    def test_gambling_language_detection(self):
        self.assertTrue(contains_gambling_language("Best bet for France vs Germany"))
        self.assertFalse(contains_gambling_language("How I built the prediction pipeline"))


class FitScoreTests(unittest.TestCase):
    def test_technical_post_with_conversion_scores_high(self):
        post = PitchAgentPost(
            title="How I built the prediction pipeline",
            platform="youtube",
            content_type="software_build_log",
            views=1000,
            click_throughs_to_website=30,
            tutorial_clicks=10,
            subscribers_gained=5,
        )
        summary = summarize_pitch_agent_metrics([post])
        fit = summary.posts[0].metadata["fit_score"]
        self.assertGreaterEqual(fit, 80)

    def test_generic_sports_post_scores_low(self):
        post = PitchAgentPost(
            title="Match preview: Argentina vs Brazil",
            platform="youtube",
            content_type="generic_sports_content",
            views=3000,
            subscribers_gained=1,
        )
        summary = summarize_pitch_agent_metrics([post])
        fit = summary.posts[0].metadata["fit_score"]
        self.assertLess(fit, 50)


class DecisionTests(unittest.TestCase):
    def test_continue_when_technical_converts(self):
        posts = [
            PitchAgentPost(
                title="How I built the pipeline",
                content_type="software_build_log",
                views=1000,
                click_throughs_to_website=50,
                tutorial_clicks=15,
            )
        ]
        summary = summarize_pitch_agent_metrics(posts)
        self.assertEqual(summary.recommendation, "YES")

    def test_stop_when_only_generic_sports(self):
        posts = [
            PitchAgentPost(
                title="Match preview",
                content_type="generic_sports_content",
                views=2000,
                click_throughs_to_website=0,
                tutorial_clicks=0,
            )
        ]
        summary = summarize_pitch_agent_metrics(posts)
        self.assertEqual(summary.recommendation, "STOP OR REDUCE")

    def test_no_data_recommendation(self):
        summary = summarize_pitch_agent_metrics([])
        self.assertEqual(summary.recommendation, "NO DATA")


class JsonParsingTests(unittest.TestCase):
    def test_loads_pitch_agent_posts_json(self):
        items = [
            {
                "title": "How I built the prediction pipeline",
                "platform": "youtube",
                "views": 1000,
                "click_throughs_to_website": 20,
                "tutorial_clicks": 5,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pitch_agent_posts.json"
            path.write_text(json.dumps(items))
            posts = collect_pitch_agent_metrics(path.parent)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].content_type, "software_build_log")


class ReportTests(unittest.TestCase):
    def test_report_generated_with_metrics(self):
        posts = [
            PitchAgentPost(
                title="How I built the pipeline",
                content_type="software_build_log",
                views=1000,
                click_throughs_to_website=30,
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            generate_pitch_report(posts, out)
            self.assertTrue(out.exists())
            content = out.read_text()
            self.assertIn("YES", content)


if __name__ == "__main__":
    unittest.main()
