"""Unit tests for the opportunity calendar module."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.intelligence.models import AudiencePain, ContentGapResult, ContentOpportunity
from agent.intelligence.newsletter_mining import NewsletterItem
from agent.intelligence.opportunity_calendar import (
    CalendarSlot,
    DayPlan,
    WeeklyCalendar,
    _guard_ok,
    _is_duplicate_or_similar,
    _score_calendar_fitness,
    build_weekly_calendar,
    generate_calendar_report,
)


class DuplicateTests(unittest.TestCase):
    def test_detects_similar_titles(self):
        self.assertTrue(
            _is_duplicate_or_similar(
                "Laravel Filament Dashboard Tutorial",
                ["Laravel Filament Dashboard Step by Step"],
                [],
            )
        )
        # Exact title match should always be duplicate.
        self.assertTrue(
            _is_duplicate_or_similar(
                "filamentphp/filament",
                ["filamentphp/filament"],
                [],
            )
        )

    def test_distinct_titles_not_duplicate(self):
        self.assertFalse(
            _is_duplicate_or_similar(
                "Python asyncio deep dive",
                ["Laravel Filament Dashboards"],
                [],
            )
        )


class FitnessScoringTests(unittest.TestCase):
    def test_tutorial_slot_prefers_high_tutorial_potential(self):
        opp = ContentOpportunity(
            title="Laravel tutorial",
            opportunity_score=80,
            gap_score=100,
            tutorial_potential=95,
            knowledge_score=80,
        )
        score = _score_calendar_fitness(opp, prefer_tutorial=True)
        self.assertGreater(score, _score_calendar_fitness(opp, prefer_tutorial=False))

    def test_newsletter_item_fitness(self):
        item = NewsletterItem(
            title="Laravel 12 released",
            url="https://example.com",
            source="Laravel News",
            urgency_score=70,
            tutorial_potential=80,
            knowledge_score=90,
        )
        self.assertGreater(_score_calendar_fitness(item, prefer_newsletter=True), 0)


class GuardTests(unittest.TestCase):
    def test_gambling_topic_blocked(self):
        opp = ContentOpportunity(
            title="Best betting strategy for World Cup",
            why_it_matters="Sports betting picks",
        )
        self.assertFalse(_guard_ok(opp))

    def test_clean_topic_allowed(self):
        opp = ContentOpportunity(
            title="Laravel Filament Tutorial",
            why_it_matters="Build dashboards",
        )
        self.assertTrue(_guard_ok(opp))

    def test_guard_note_blocks(self):
        opp = ContentOpportunity(
            title="Something",
            why_it_matters="x",
            risk_notes=["Guard: trading"],
        )
        self.assertFalse(_guard_ok(opp))


class CalendarBuildTests(unittest.TestCase):
    def test_generates_seven_days(self):
        opps = [
            ContentOpportunity(
                title=f"Tutorial {i}",
                opportunity_score=80 - i,
                gap_score=100,
                tutorial_potential=90,
                knowledge_score=80,
                why_it_matters="Good topic",
                evidence=["source: test"],
                source_urls=["https://example.com"],
                gap_result=ContentGapResult(action="create", gap_score=100, duplicate_risk="none"),
            )
            for i in range(10)
        ]
        calendar = build_weekly_calendar(opps, [], [])
        self.assertEqual(len(calendar.days), 7)
        # At least Monday should have a primary slot.
        self.assertIsNotNone(calendar.days[0].primary)

    def test_high_gap_tutorial_prioritized_monday(self):
        opp = ContentOpportunity(
            title="Self-host n8n on Raspberry Pi",
            opportunity_score=95,
            gap_score=100,
            tutorial_potential=95,
            knowledge_score=90,
            why_it_matters="Strong BWA fit",
            evidence=["source: github"],
            source_urls=["https://github.com/n8n-io/n8n"],
            suggested_format="long-form tutorial + LinkedIn/FB post + YouTube Short",
            gap_result=ContentGapResult(action="create", gap_score=100, duplicate_risk="none"),
        )
        calendar = build_weekly_calendar([opp], [], [])
        self.assertIsNotNone(calendar.days[0].primary)
        self.assertIn("n8n", calendar.days[0].primary.title.lower())

    def test_audience_pain_placed_thursday(self):
        opp = ContentOpportunity(
            title="Placeholder tutorial",
            opportunity_score=50,
            gap_score=80,
            tutorial_potential=80,
            knowledge_score=70,
            why_it_matters="placeholder",
            evidence=["source: test"],
            gap_result=ContentGapResult(action="create", gap_score=80, duplicate_risk="low"),
        )
        pain = AudiencePain(
            label="How do I deploy Laravel on a Raspberry Pi?",
            evidence=["telegram] How do I deploy Laravel on a Raspberry Pi?"],
            frequency=5,
            cross_platform=True,
        )
        calendar = build_weekly_calendar([opp], [], [pain])
        thursday = next(d for d in calendar.days if d.day == "Thursday")
        self.assertIsNotNone(thursday.primary)
        self.assertIn("Raspberry Pi", thursday.primary.title)

    def test_newsletter_item_placed_wednesday(self):
        opp = ContentOpportunity(
            title="Placeholder",
            opportunity_score=40,
            gap_score=50,
            tutorial_potential=50,
            knowledge_score=40,
            why_it_matters="placeholder",
            evidence=["source: test"],
            gap_result=ContentGapResult(action="create", gap_score=50, duplicate_risk="low"),
        )
        news = NewsletterItem(
            title="Laravel 12 Released",
            url="https://example.com",
            source="Laravel News",
            urgency_score=80,
            tutorial_potential=70,
            knowledge_score=90,
        )
        calendar = build_weekly_calendar([opp], [news], [])
        wednesday = next(d for d in calendar.days if d.day == "Wednesday")
        self.assertIsNotNone(wednesday.primary)
        self.assertIn("Laravel 12", wednesday.primary.title)

    def test_report_output(self):
        slot = CalendarSlot(
            title="Laravel tutorial",
            format="long-form tutorial",
            reason="High gap score",
            evidence="source: test",
            source_signal="github-trending",
            action="create tutorial",
        )
        day = DayPlan(day="Monday", theme="main_tutorial_or_build_log", primary=slot)
        calendar = WeeklyCalendar(days=[day])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "calendar.md"
            generate_calendar_report(calendar, out)
            self.assertTrue(out.exists())
            content = out.read_text()
            self.assertIn("Laravel tutorial", content)
            self.assertIn("Monday", content)


if __name__ == "__main__":
    unittest.main()
