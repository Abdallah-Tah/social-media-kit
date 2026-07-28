"""Phase 1 Stage 7A — deterministic artifact builder tests.

Covers:
  * Deterministic daily brief
  * Confirmed and vendor claims remain separate
  * Rejection reasons represented accurately
  * Missing selected candidate → valid skipped-slot brief
  * Weekly trend uses forward-looking inputs
  * Weekly report uses retrospective inputs
  * Two Sunday artifacts are materially distinct
  * No LLM, network, publishing, or notification calls
  * No live state mutation
  * Production format rotation unchanged
  * Feature flag remains false
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.editorial.artifacts import (
    Artifact,
    ArtifactOverlapError,
    BriefCandidate,
    BriefClaim,
    BriefSource,
    DailyBriefInput,
    QualityBreakdown,
    SourceConfidenceBreakdown,
    WeeklyReportInput,
    WeeklyTrendInput,
    build_intelligence_brief,
    build_weekly_intelligence_report,
    build_weekly_trend_analysis,
    save_artifact,
    validate_artifact_distinctness,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _candidate(cid="c1", title="OpenAI releases GPT-5", entity="openai",
               dev_type="model_release", sc=82, opp=90,
               status="admitted", reasons=(),
               primary_url="https://openai.com/blog/gpt-5",
               domains=("arxiv.org",)):
    return BriefCandidate(
        candidate_id=cid, title=title, entity=entity,
        development_type=dev_type, source_confidence=sc,
        opportunity_score=opp, admission_status=status,
        rejection_reasons=reasons, primary_source_url=primary_url,
        corroborating_domains=domains,
    )


def _brief_input(**overrides):
    defaults = dict(
        editorial_day="2026-07-28",
        sources_scanned=(BriefSource("hackernews", 12), BriefSource("reddit", 8)),
        candidates=(
            _candidate("c1", "OpenAI releases GPT-5", status="admitted"),
            _candidate("c2", "Google updates Bard", entity="google", status="rejected",
                       reasons=("entity_saturated",)),
        ),
        selected_candidate=_candidate("c1", "OpenAI releases GPT-5"),
        confirmed_claims=(
            BriefClaim("GPT-5 scores 92% on MMLU", "verified_independent",
                       "https://openai.com/blog/gpt-5"),
        ),
        unverified_claims=(
            BriefClaim("GPT-5 is 3x faster", "vendor_provided",
                       "https://openai.com/blog/gpt-5"),
        ),
        source_confidence=SourceConfidenceBreakdown(24, 15, 16, 12, 10, 77),
        quality=QualityBreakdown(22, 17, 18, 13, 16, 86),
        readiness_status="ready",
        slot_id="intelligence_brief",
        format_id="intelligence_brief",
    )
    defaults.update(overrides)
    return DailyBriefInput(**defaults)


def _trend_input(**overrides):
    defaults = dict(
        week_start="2026-07-21", week_end="2026-07-27",
        entity_counts=(("openai", 5), ("google", 3), ("microsoft", 2)),
        theme_counts=(("ai_models", 6), ("devtools", 3)),
        source_activity=(("hackernews", 40), ("reddit", 25)),
        development_type_counts=(("model_release", 4), ("api_release", 3)),
        emerging_entities=("anthropic",),
        emerging_themes=("ai_safety",),
        total_candidates_evaluated=30,
        total_admitted=10,
        total_rejected=20,
        coverage_gaps=("rust_ecosystem",),
    )
    defaults.update(overrides)
    return WeeklyTrendInput(**defaults)


def _report_input(**overrides):
    defaults = dict(
        week_start="2026-07-21", week_end="2026-07-27",
        total_decisions=30, accepted=10, rejected=20,
        rejected_by_reason=(("entity_saturated", 8), ("source_confidence_below_threshold", 5)),
        readiness_decisions=(("ready", 8), ("rejected", 15), ("requires_manual_review", 7)),
        avg_source_confidence=72.5,
        avg_editorial_quality=78.3,
        source_confidence_range=(45, 92),
        quality_range=(55, 95),
        duplicates_prevented=4,
        saturation_rejections=6,
        material_exceptions=2,
        slots_filled=12,
        slots_skipped=3,
        quality_hard_failures=(("prompt_leakage", 1),),
        top_sources=(("hackernews", 40),),
    )
    defaults.update(overrides)
    return WeeklyReportInput(**defaults)


# ── intelligence_brief tests ─────────────────────────────────────────────────

class TestIntelligenceBrief:
    def test_deterministic_same_input_same_output(self):
        a = build_intelligence_brief(_brief_input())
        b = build_intelligence_brief(_brief_input())
        assert a.to_dict() == b.to_dict()
        assert a.to_markdown() == b.to_markdown()

    def test_all_ten_sections_present(self):
        artifact = build_intelligence_brief(_brief_input())
        headings = [h for h, _ in artifact.sections]
        assert len(headings) == 10
        assert "## What I Scanned" in headings
        assert "## Confirmed Facts" in headings
        assert "## Unverified Or Vendor Claims" in headings
        assert "## Source Confidence" in headings
        assert "## Primary Sources" in headings

    def test_confirmed_and_vendor_claims_separate(self):
        artifact = build_intelligence_brief(_brief_input())
        sections = {h: b for h, b in artifact.sections}
        confirmed = sections["## Confirmed Facts"]
        unverified = sections["## Unverified Or Vendor Claims"]
        assert "GPT-5 scores 92% on MMLU" in confirmed
        assert "GPT-5 is 3x faster" in unverified
        assert "GPT-5 is 3x faster" not in confirmed
        assert "GPT-5 scores 92% on MMLU" not in unverified

    def test_rejection_reasons_accurate(self):
        artifact = build_intelligence_brief(_brief_input())
        sections = {h: b for h, b in artifact.sections}
        rejected = sections["## What I Rejected"]
        assert "entity_saturated" in rejected
        assert "Google updates Bard" in rejected

    def test_missing_selected_candidate_skipped_slot(self):
        artifact = build_intelligence_brief(_brief_input(
            selected_candidate=None,
            candidates=(_candidate(status="rejected", reasons=("source_confidence_below_threshold",)),),
        ))
        sections = {h: b for h, b in artifact.sections}
        assert "slot skipped" in sections["## The Lead Story"].lower()
        assert "no candidate selected" in sections["## Why This One"].lower()
        assert artifact.metadata["candidates_admitted"] == 0

    def test_source_confidence_table(self):
        artifact = build_intelligence_brief(_brief_input())
        sections = {h: b for h, b in artifact.sections}
        sc = sections["## Source Confidence"]
        assert "Primary source" in sc
        assert "Corroboration" in sc
        assert "77" in sc

    def test_no_claims_when_empty(self):
        artifact = build_intelligence_brief(_brief_input(
            confirmed_claims=(), unverified_claims=(),
        ))
        sections = {h: b for h, b in artifact.sections}
        assert "no confirmed claims" in sections["## Confirmed Facts"].lower()
        assert "no unverified" in sections["## Unverified Or Vendor Claims"].lower()

    def test_missing_source_confidence_shown(self):
        artifact = build_intelligence_brief(_brief_input(source_confidence=None))
        sections = {h: b for h, b in artifact.sections}
        assert "not computed" in sections["## Source Confidence"].lower()

    def test_artifact_type_and_format(self):
        artifact = build_intelligence_brief(_brief_input())
        assert artifact.artifact_type == "intelligence_brief"
        assert artifact.format_id == "intelligence_brief"
        assert artifact.editorial_day == "2026-07-28"


# ── weekly_trend_analysis tests ──────────────────────────────────────────────

class TestWeeklyTrendAnalysis:
    def test_deterministic(self):
        a = build_weekly_trend_analysis(_trend_input())
        b = build_weekly_trend_analysis(_trend_input())
        assert a.to_dict() == b.to_dict()

    def test_forward_looking_sections(self):
        artifact = build_weekly_trend_analysis(_trend_input())
        headings = [h for h, _ in artifact.sections]
        assert "## Emerging Themes" in headings
        assert "## What May Matter Next Week" in headings
        assert "## Coverage Gaps" in headings

    def test_entity_activity_sorted_by_frequency(self):
        artifact = build_weekly_trend_analysis(_trend_input())
        sections = {h: b for h, b in artifact.sections}
        entity = sections["## Entity Activity"]
        openai_pos = entity.index("openai")
        google_pos = entity.index("google")
        assert openai_pos < google_pos

    def test_emerging_entities_shown(self):
        artifact = build_weekly_trend_analysis(_trend_input())
        sections = {h: b for h, b in artifact.sections}
        assert "anthropic" in sections["## What May Matter Next Week"]
        assert "ai_safety" in sections["## Emerging Themes"]

    def test_empty_inputs_show_placeholder(self):
        artifact = build_weekly_trend_analysis(_trend_input(
            entity_counts=(), theme_counts=(), emerging_entities=(),
            emerging_themes=(),
        ))
        sections = {h: b for h, b in artifact.sections}
        assert "no entity data" in sections["## Entity Activity"].lower()
        assert "no emerging themes" in sections["## Emerging Themes"].lower()

    def test_artifact_type(self):
        artifact = build_weekly_trend_analysis(_trend_input())
        assert artifact.artifact_type == "weekly_trend_analysis"


# ── weekly_intelligence_report tests ─────────────────────────────────────────

class TestWeeklyIntelligenceReport:
    def test_deterministic(self):
        a = build_weekly_intelligence_report(_report_input())
        b = build_weekly_intelligence_report(_report_input())
        assert a.to_dict() == b.to_dict()

    def test_retrospective_sections(self):
        artifact = build_weekly_intelligence_report(_report_input())
        headings = [h for h, _ in artifact.sections]
        assert "## Rejection Breakdown" in headings
        assert "## Readiness Outcomes" in headings
        assert "## Lessons For Next Week" in headings

    def test_rejection_breakdown_accurate(self):
        artifact = build_weekly_intelligence_report(_report_input())
        sections = {h: b for h, b in artifact.sections}
        rej = sections["## Rejection Breakdown"]
        assert "entity_saturated" in rej
        assert "8" in rej

    def test_readiness_outcomes_accurate(self):
        artifact = build_weekly_intelligence_report(_report_input())
        sections = {h: b for h, b in artifact.sections}
        rd = sections["## Readiness Outcomes"]
        assert "ready" in rd
        assert "rejected" in rd

    def test_lessons_reflect_data(self):
        artifact = build_weekly_intelligence_report(_report_input())
        sections = {h: b for h, b in artifact.sections}
        lessons = sections["## Lessons For Next Week"]
        assert "duplicate" in lessons.lower()
        assert "saturation" in lessons.lower()
        assert "slot" in lessons.lower()

    def test_empty_inputs_show_placeholder(self):
        artifact = build_weekly_intelligence_report(_report_input(
            total_decisions=0, accepted=0, rejected=0,
            rejected_by_reason=(), readiness_decisions=(),
            avg_source_confidence=None, avg_editorial_quality=None,
        ))
        sections = {h: b for h, b in artifact.sections}
        assert "no rejections" in sections["## Rejection Breakdown"].lower()
        assert "no source confidence" in sections["## Source Confidence Distribution"].lower()

    def test_artifact_type(self):
        artifact = build_weekly_intelligence_report(_report_input())
        assert artifact.artifact_type == "weekly_intelligence_report"


# ── distinctness guard ───────────────────────────────────────────────────────

class TestArtifactDistinctness:
    def test_distinct_artifacts_pass(self):
        trend = build_weekly_trend_analysis(_trend_input())
        report = build_weekly_intelligence_report(_report_input())
        validate_artifact_distinctness(trend, report)

    def test_identical_section_headings_fail(self):
        fake = Artifact(
            artifact_type="fake", format_id="fake", editorial_day="2026-07-27",
            sections=(("## A", "x"), ("## B", "y"), ("## C", "z")),
        )
        fake2 = Artifact(
            artifact_type="fake2", format_id="fake2", editorial_day="2026-07-27",
            sections=(("## A", "p"), ("## B", "q"), ("## C", "r")),
        )
        with pytest.raises(ArtifactOverlapError):
            validate_artifact_distinctness(fake, fake2, threshold=0.5)

    def test_real_artifacts_have_distinct_headings(self):
        trend = build_weekly_trend_analysis(_trend_input())
        report = build_weekly_intelligence_report(_report_input())
        trend_headings = {h for h, _ in trend.sections}
        report_headings = {h for h, _ in report.sections}
        shared = trend_headings & report_headings
        assert len(shared) <= 2


# ── purity guarantees ────────────────────────────────────────────────────────

class TestPurityGuarantees:
    def test_no_llm_calls(self):
        import agent.llm_ops as LLM
        with patch.object(LLM, "chat", side_effect=AssertionError("no LLM")):
            build_intelligence_brief(_brief_input())
            build_weekly_trend_analysis(_trend_input())
            build_weekly_intelligence_report(_report_input())

    def test_no_network_calls(self):
        import urllib.request
        with patch.object(urllib.request, "urlopen",
                          side_effect=AssertionError("no network")):
            build_intelligence_brief(_brief_input())
            build_weekly_trend_analysis(_trend_input())
            build_weekly_intelligence_report(_report_input())

    def test_no_publishing_calls(self, tmp_path):
        with patch("agent.drafts.publish_blog",
                   side_effect=AssertionError("no publishing")):
            build_intelligence_brief(_brief_input())
            build_weekly_trend_analysis(_trend_input())
            build_weekly_intelligence_report(_report_input())

    def test_no_notification_calls(self):
        with patch("agent.notify.notify_publish",
                   side_effect=AssertionError("no notifications")):
            build_intelligence_brief(_brief_input())
            build_weekly_trend_analysis(_trend_input())
            build_weekly_intelligence_report(_report_input())

    def test_no_live_state_mutation(self, tmp_path, monkeypatch):
        import agent.content_decisions as CD
        monkeypatch.setattr(CD, "DECISION_LOG", tmp_path / "decisions.jsonl")
        build_intelligence_brief(_brief_input())
        build_weekly_trend_analysis(_trend_input())
        build_weekly_intelligence_report(_report_input())
        assert not (tmp_path / "decisions.jsonl").exists()

    def test_feature_flag_remains_false(self):
        from agent.editorial.flags import editorial_slots_enabled
        assert editorial_slots_enabled() is False


# ── production format isolation ──────────────────────────────────────────────

class TestFormatIsolation:
    def test_editorial_formats_disjoint_from_live(self):
        from scripts.content_formats import (
            EDITORIAL_FORMATS, NEWS_FORMATS, TUTORIAL_FORMATS,
        )
        editorial_ids = set(EDITORIAL_FORMATS.keys())
        live_ids = set(NEWS_FORMATS.keys()) | set(TUTORIAL_FORMATS.keys())
        assert editorial_ids & live_ids == set()

    def test_retired_names_not_in_editorial_formats(self):
        from scripts.content_formats import EDITORIAL_FORMATS
        assert "build_along" not in EDITORIAL_FORMATS
        assert "from_scratch" not in EDITORIAL_FORMATS

    def test_approved_replacements_present(self):
        from scripts.content_formats import EDITORIAL_FORMATS
        assert "guided_build" in EDITORIAL_FORMATS
        assert "ground_up_build" in EDITORIAL_FORMATS

    def test_production_format_rotation_unchanged(self):
        from scripts.content_formats import formats_for, pick_format
        news = formats_for("news")
        assert "intelligence_brief" not in news
        assert "weekly_trend_analysis" not in news


# ── persistence ──────────────────────────────────────────────────────────────

class TestPersistence:
    def test_save_artifact_writes_to_ignored_dir(self, tmp_path, monkeypatch):
        import agent.editorial.artifacts as ART
        monkeypatch.setattr(ART, "ARTIFACT_DIR", tmp_path)
        artifact = build_intelligence_brief(_brief_input())
        path = save_artifact(artifact)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["artifact_type"] == "intelligence_brief"
        assert data["editorial_day"] == "2026-07-28"

    def test_save_artifact_deterministic(self, tmp_path, monkeypatch):
        import agent.editorial.artifacts as ART
        monkeypatch.setattr(ART, "ARTIFACT_DIR", tmp_path)
        a = build_intelligence_brief(_brief_input())
        b = build_intelligence_brief(_brief_input())
        path_a = save_artifact(a)
        path_b = save_artifact(b)
        assert path_a.read_text() == path_b.read_text()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
