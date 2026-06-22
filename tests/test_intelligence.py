"""Unit tests for the Content Intelligence Engine."""
from __future__ import annotations

import unittest

from agent.intelligence.knowledge import load_knowledge_base, match_text_against_knowledge
from agent.intelligence.models import TrendSignal
from agent.intelligence.scoring import (
    compute_authority_with_knowledge,
    content_guard_adjustment,
    score_authority,
    score_social_potential,
    score_tutorial_potential,
)


def make_signal(title: str, summary: str = "", topics: list[str] | None = None) -> TrendSignal:
    return TrendSignal(
        title=title,
        source="test",
        url="https://example.com/test",
        summary=summary,
        topics=topics or [],
    )


class IntelligenceScoringTests(unittest.TestCase):
    def test_laravel_signal_scores_high(self):
        sig = make_signal("filamentphp/filament", "A Laravel UI framework", ["laravel"])
        authority = score_authority(sig)
        self.assertGreaterEqual(authority.total, 60)
        self.assertGreaterEqual(authority.laravel, 60)

    def test_python_signal_scores_high(self):
        sig = make_signal("awesome-python", "Python resources", ["python"])
        authority = score_authority(sig)
        self.assertGreaterEqual(authority.total, 41)
        self.assertGreaterEqual(authority.python, 55)

    def test_tool_tutorial_potential_is_high(self):
        sig = make_signal("n8n-io/n8n", "Workflow automation platform", ["automation"])
        self.assertGreaterEqual(score_tutorial_potential(sig), 65)

    def test_launch_social_potential_is_high(self):
        sig = make_signal("Launch HN: Adam (YC W25) – Open-Source AI CAD", "", ["ai agent"])
        self.assertGreaterEqual(score_social_potential(sig), 60)

    def test_trading_content_gets_guard_penalty(self):
        sig = make_signal("TradingAgents", "Multi-Agents LLM Financial Trading Framework")
        penalty, note = content_guard_adjustment(sig)
        self.assertLess(penalty, 0)
        self.assertIn("trading", note.lower())

    def test_clean_content_gets_no_guard_penalty(self):
        sig = make_signal("filamentphp/filament", "A Laravel UI framework")
        penalty, note = content_guard_adjustment(sig)
        self.assertEqual(penalty, 0)
        self.assertEqual(note, "")

    def test_knowledge_base_loads_all_files(self):
        kb = load_knowledge_base()
        self.assertGreater(len(kb.expertise), 0)
        self.assertGreater(len(kb.projects), 0)
        self.assertGreater(len(kb.stack), 0)
        self.assertGreater(len(kb.rules), 0)

    def test_laravel_topic_matches_bwa_knowledge(self):
        kb = load_knowledge_base()
        result = match_text_against_knowledge("filament laravel tutorial", kb)
        self.assertGreater(result["total_knowledge_score"], 0)
        self.assertIn("Laravel", result["expertise_matches"][0])

    def test_authority_includes_knowledge_for_laravel(self):
        kb = load_knowledge_base()
        sig = make_signal("filamentphp/filament", "A Laravel UI framework", ["laravel"])
        authority, knowledge = compute_authority_with_knowledge(sig, kb)
        self.assertGreaterEqual(authority.total, score_authority(sig).total)
        self.assertGreater(knowledge["total_knowledge_score"], 0)


if __name__ == "__main__":
    unittest.main()
