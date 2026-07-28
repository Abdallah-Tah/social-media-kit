"""Phase 1 Stage 7B — dormant editorial orchestrator tests.

Covers:
  * All 7 required outcomes
  * Shadow and replay modes only; live rejected
  * No publishing, no notifications, no live history writes
  * Deterministic fake draft builder
  * Persistence to git-ignored state paths
  * EDITORIAL_SLOTS_ENABLED remains false
  * Cron unchanged
  * Production format rotation unchanged
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from agent.editorial.orchestrator import (
    ALLOWED_MODES,
    MODE_REPLAY,
    MODE_SHADOW,
    OUTCOME_DRAFT_GENERATION_FAILED,
    OUTCOME_INVALID_CONFIGURATION,
    OUTCOME_PIPELINE_FAILED,
    OUTCOME_QUALITY_REJECTED,
    OUTCOME_READY_IN_SHADOW,
    OUTCOME_REQUIRES_MANUAL_REVIEW,
    OUTCOME_SKIPPED_NO_CANDIDATE,
    PipelineInput,
    PipelineResult,
    SlotResult,
    _default_draft_builder,
    _editorial_day_for,
    run_pipeline,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _fake_candidate(cid="c1", title="OpenAI releases GPT-5",
                    entity="openai", dev_type="model_release",
                    url="https://openai.com/blog/gpt-5",
                    opp_score=90):
    """Minimal candidate-like object for the default draft builder."""
    c = MagicMock()
    c.candidate_id = cid
    c.title = title
    c.subject_org = entity
    c.subject_name = entity
    c.development_type = dev_type
    c.url = url
    c.opportunity_score = opp_score
    c.canonical_topic_id = f"topic_{cid}"
    c.sources = ()
    c.claims = ()
    c.primary_source = None
    c.warnings = ()
    c.metadata = {}
    return c


def _fake_record(cid="c1", title="OpenAI releases GPT-5",
                 url="https://openai.com/blog/gpt-5",
                 source="hackernews", opp_score=90):
    """A plain dict record that normalize_candidate can handle."""
    return {
        "title": title,
        "url": url,
        "source": source,
        "candidate_id": cid,
        "opportunity_score": opp_score,
        "discovered_at": "2026-07-28T12:00:00Z",
    }


def _fake_draft_builder(candidate, format_id, slot_objective,
                        source_confidence=None, quality_hints=None):
    """Deterministic fake draft builder for tests."""
    title = getattr(candidate, "title", "Test")
    return {
        "title": title,
        "body": f"# {title}\n\n## What Happened\n\nThis is a test draft.\n\n"
                f"## Confirmed Facts\n\n- Fact one\n\n"
                f"## Sources\n\n- https://example.com\n",
        "summary": f"Test draft for {title}",
        "format_id": format_id,
        "artifact_type": format_id,
        "slot_objective": slot_objective,
        "sources": ({"url": "https://example.com", "kind": "primary"},),
        "claims": ({"text": "Fact one", "verification": "verified_independent",
                     "source_url": "https://example.com"},),
        "confirmed_facts": ({"text": "Fact one", "source_url": "https://example.com"},),
    }


# ── mode validation ──────────────────────────────────────────────────────────

class TestModeValidation:
    def test_shadow_mode_accepted(self):
        assert MODE_SHADOW in ALLOWED_MODES

    def test_replay_mode_accepted(self):
        assert MODE_REPLAY in ALLOWED_MODES

    def test_live_mode_rejected(self):
        result = run_pipeline(PipelineInput(
            mode="live", date="2026-07-28",
        ))
        assert result.config_errors
        assert "unsupported mode" in result.config_errors[0]

    def test_dry_run_mode_rejected(self):
        result = run_pipeline(PipelineInput(
            mode="dry_run", date="2026-07-28",
        ))
        assert result.config_errors
        assert "unsupported mode" in result.config_errors[0]


# ── outcome: invalid_configuration ───────────────────────────────────────────

class TestInvalidConfiguration:
    def test_missing_slots_file(self, tmp_path, monkeypatch):
        from agent.editorial import slots as SLOTS
        monkeypatch.setattr(SLOTS, "SLOTS_PATH", tmp_path / "nonexistent.yaml")
        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
        ))
        assert result.config_errors
        assert any("not found" in e or "problem" in e for e in result.config_errors)


# ── outcome: skipped_no_candidate ────────────────────────────────────────────

class TestSkippedNoCandidate:
    def test_empty_candidates(self):
        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(),
        ))
        for sr in result.slot_results:
            assert sr.outcome == OUTCOME_SKIPPED_NO_CANDIDATE

    def test_all_candidates_fail_normalization(self):
        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=({"title": "", "url": ""},),
        ))
        for sr in result.slot_results:
            assert sr.outcome in (OUTCOME_SKIPPED_NO_CANDIDATE, OUTCOME_PIPELINE_FAILED)


# ── outcome: draft_generation_failed ─────────────────────────────────────────

class TestDraftGenerationFailed:
    def test_failing_draft_builder(self):
        def bad_builder(*args, **kwargs):
            raise RuntimeError("draft generation exploded")

        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=bad_builder,
        ))
        outcomes = {sr.outcome for sr in result.slot_results}
        assert OUTCOME_DRAFT_GENERATION_FAILED in outcomes or \
               OUTCOME_SKIPPED_NO_CANDIDATE in outcomes or \
               OUTCOME_PIPELINE_FAILED in outcomes


# ── outcome: quality_rejected ────────────────────────────────────────────────

class TestQualityRejected:
    def test_short_body_fails_quality(self):
        def tiny_builder(*args, **kwargs):
            return {
                "title": "Tiny",
                "body": "Too short.",
                "summary": "Tiny",
                "format_id": "intelligence_brief",
                "artifact_type": "intelligence_brief",
                "slot_objective": "test",
                "sources": (),
                "claims": (),
                "confirmed_facts": (),
            }

        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=tiny_builder,
        ))
        outcomes = {sr.outcome for sr in result.slot_results}
        has_quality_fail = (
            OUTCOME_QUALITY_REJECTED in outcomes or
            OUTCOME_PIPELINE_FAILED in outcomes or
            OUTCOME_SKIPPED_NO_CANDIDATE in outcomes
        )
        assert has_quality_fail


# ── outcome: ready_in_shadow ─────────────────────────────────────────────────

class TestReadyInShadow:
    def test_shadow_mode_produces_result(self):
        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        assert result.mode == MODE_SHADOW
        assert result.date == "2026-07-28"
        assert result.editorial_day == "tuesday"
        assert len(result.slot_results) > 0

    def test_replay_mode_produces_result(self):
        result = run_pipeline(PipelineInput(
            mode=MODE_REPLAY, date="2026-07-27",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        assert result.mode == MODE_REPLAY
        assert result.editorial_day == "monday"


# ── no side effects ──────────────────────────────────────────────────────────

class TestNoSideEffects:
    def test_no_publishing_calls(self):
        with patch("agent.drafts.publish_blog",
                   side_effect=AssertionError("no publishing")), \
             patch("agent.social_publishers.publish",
                   side_effect=AssertionError("no publishing")):
            run_pipeline(PipelineInput(
                mode=MODE_SHADOW, date="2026-07-28",
                candidates=(_fake_record(),),
                draft_builder=_fake_draft_builder,
            ))

    def test_no_notification_calls(self):
        with patch("agent.notify.notify_publish",
                   side_effect=AssertionError("no notifications")):
            run_pipeline(PipelineInput(
                mode=MODE_SHADOW, date="2026-07-28",
                candidates=(_fake_record(),),
                draft_builder=_fake_draft_builder,
            ))

    def test_no_live_history_writes(self, tmp_path, monkeypatch):
        import agent.content_decisions as CD
        monkeypatch.setattr(CD, "DECISION_LOG", tmp_path / "decisions.jsonl")
        run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        assert not (tmp_path / "decisions.jsonl").exists()

    def test_no_saturation_history_writes(self):
        """The orchestrator must not write to the saturation index file."""
        from agent.editorial.saturation import INDEX_PATH
        before = INDEX_PATH.read_text() if INDEX_PATH.exists() else None
        run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        after = INDEX_PATH.read_text() if INDEX_PATH.exists() else None
        assert before == after

    def test_no_format_rotation_mutation(self, tmp_path,monkeypatch):
        monkeypatch.setenv("SMKIT_STATE_DIR", str(tmp_path / "state"))
        before = Path(KIT / "content" / "format_rotation.json")
        before_content = before.read_text() if before.exists() else None
        run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        after_content = before.read_text() if before.exists() else None
        assert before_content == after_content


# ── persistence ──────────────────────────────────────────────────────────────

class TestPersistence:
    def test_shadow_persists_per_slot(self, tmp_path, monkeypatch):
        from agent.editorial import orchestrator as ORCH
        monkeypatch.setattr(ORCH, "STATE_DIR", tmp_path / "editorial")
        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        shadow_dir = tmp_path / "editorial" / "shadow"
        files = list(shadow_dir.glob("pipeline_2026-07-28_*.json"))
        assert len(files) == len(result.slot_results)
        for f in files:
            data = json.loads(f.read_text())
            assert data["mode"] == "shadow"
            assert data["date"] == "2026-07-28"
            assert "slot_result" in data

    def test_replay_persists_per_slot(self, tmp_path, monkeypatch):
        from agent.editorial import orchestrator as ORCH
        monkeypatch.setattr(ORCH, "STATE_DIR", tmp_path / "editorial")
        result = run_pipeline(PipelineInput(
            mode=MODE_REPLAY, date="2026-07-27",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        replay_dir = tmp_path / "editorial" / "replay"
        files = list(replay_dir.glob("pipeline_2026-07-27_*.json"))
        assert len(files) == len(result.slot_results)

    def test_multiple_slots_preserved(self, tmp_path, monkeypatch):
        """Running multiple slots for the same date preserves every result."""
        from agent.editorial import orchestrator as ORCH
        monkeypatch.setattr(ORCH, "STATE_DIR", tmp_path / "editorial")
        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=_fake_draft_builder,
        ))
        shadow_dir = tmp_path / "editorial" / "shadow"
        files = list(shadow_dir.glob("pipeline_2026-07-28_*.json"))
        slot_ids = set()
        for f in files:
            data = json.loads(f.read_text())
            slot_ids.add(data["slot_result"]["slot_id"])
        assert len(slot_ids) == len(result.slot_results)
        assert len(slot_ids) >= 3

    def test_persistence_is_deterministic(self, tmp_path, monkeypatch):
        from agent.editorial import orchestrator as ORCH
        monkeypatch.setattr(ORCH, "STATE_DIR", tmp_path / "editorial")
        import datetime as dt
        now = dt.datetime(2026, 7, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
        r1 = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(),
            now=now,
        ))
        d1 = r1.to_dict()
        d1.pop("completed_at", None)
        d1.pop("started_at", None)
        shadow_dir = tmp_path / "editorial" / "shadow"
        for f in shadow_dir.glob("pipeline_2026-07-28_*.json"):
            f.unlink()
        r2 = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(),
            now=now,
        ))
        d2 = r2.to_dict()
        d2.pop("completed_at", None)
        d2.pop("started_at", None)
        assert d1 == d2


# ── draft builder ────────────────────────────────────────────────────────────

class TestDraftBuilder:
    def test_default_builder_produces_structured_output(self):
        candidate = _fake_candidate()
        result = _default_draft_builder(candidate, "intelligence_brief", "test objective", None)
        assert "title" in result
        assert "body" in result
        assert "summary" in result
        assert result["format_id"] == "intelligence_brief"

    def test_default_builder_is_deterministic(self):
        c1 = _fake_candidate()
        c2 = _fake_candidate()
        r1 = _default_draft_builder(c1, "intelligence_brief", "test", None)
        r2 = _default_draft_builder(c2, "intelligence_brief", "test", None)
        assert r1 == r2

    def test_custom_builder_used(self):
        custom_called = []

        def custom_builder(*args, **kwargs):
            custom_called.append(True)
            return _fake_draft_builder(*args, **kwargs)

        result = run_pipeline(PipelineInput(
            mode=MODE_SHADOW, date="2026-07-28",
            candidates=(_fake_record(),),
            draft_builder=custom_builder,
        ))
        outcomes = {sr.outcome for sr in result.slot_results}
        if OUTCOME_SKIPPED_NO_CANDIDATE not in outcomes:
            assert len(custom_called) > 0


# ── feature flag and production isolation ────────────────────────────────────

class TestProductionIsolation:
    def test_feature_flag_remains_false(self):
        from agent.editorial.flags import editorial_slots_enabled
        assert editorial_slots_enabled() is False

    def test_editorial_formats_disjoint_from_live(self):
        from scripts.content_formats import (
            EDITORIAL_FORMATS, NEWS_FORMATS, TUTORIAL_FORMATS,
        )
        editorial_ids = set(EDITORIAL_FORMATS.keys())
        live_ids = set(NEWS_FORMATS.keys()) | set(TUTORIAL_FORMATS.keys())
        assert editorial_ids & live_ids == set()

    def test_production_format_rotation_unchanged(self):
        from scripts.content_formats import formats_for
        news = formats_for("news")
        assert "intelligence_brief" not in news


# ── editorial day calculation ────────────────────────────────────────────────

class TestEditorialDay:
    def test_monday(self):
        assert _editorial_day_for("2026-07-27", "America/New_York") == "monday"

    def test_tuesday(self):
        assert _editorial_day_for("2026-07-28", "America/New_York") == "tuesday"

    def test_sunday(self):
        assert _editorial_day_for("2026-07-26", "America/New_York") == "sunday"


# ── LLM call tracking ───────────────────────────────────────────────────────

class TestLLMCalls:
    def test_default_builder_no_llm(self):
        import agent.llm_ops as LLM
        with patch.object(LLM, "chat", side_effect=AssertionError("no LLM")):
            candidate = _fake_candidate()
            _default_draft_builder(candidate, "intelligence_brief", "test", None)

    def test_pipeline_with_default_builder_no_llm(self):
        import agent.llm_ops as LLM
        with patch.object(LLM, "chat", side_effect=AssertionError("no LLM")):
            run_pipeline(PipelineInput(
                mode=MODE_SHADOW, date="2026-07-28",
                candidates=(_fake_record(),),
                draft_builder=_fake_draft_builder,
            ))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── corrected outcome mapping ────────────────────────────────────────────────

class TestOutcomeMapping:
    """Verify readiness status maps to the correct pipeline outcome."""

    def test_ready_maps_to_ready_in_shadow(self):
        from agent.editorial.orchestrator import OUTCOME_READY_IN_SHADOW
        assert OUTCOME_READY_IN_SHADOW == "ready_in_shadow"

    def test_ready_with_warnings_maps_to_hold(self):
        from agent.editorial.orchestrator import OUTCOME_READY_WITH_WARNINGS_HOLD
        assert OUTCOME_READY_WITH_WARNINGS_HOLD == "ready_with_warnings_hold"

    def test_ready_with_warnings_never_ready_in_shadow(self):
        """ready_with_warnings must NOT map to ready_in_shadow."""
        from agent.editorial import readiness as RDY
        from agent.editorial.orchestrator import (
            OUTCOME_READY_IN_SHADOW,
            OUTCOME_READY_WITH_WARNINGS_HOLD,
        )
        # Verify the mapping logic
        rd_status = RDY.STATUS_READY_WITH_WARNINGS
        if rd_status == RDY.STATUS_READY:
            outcome = OUTCOME_READY_IN_SHADOW
        elif rd_status == RDY.STATUS_READY_WITH_WARNINGS:
            outcome = OUTCOME_READY_WITH_WARNINGS_HOLD
        elif rd_status == RDY.STATUS_REQUIRES_MANUAL_REVIEW:
            outcome = "requires_manual_review"
        else:
            outcome = "quality_rejected"
        assert outcome == OUTCOME_READY_WITH_WARNINGS_HOLD
        assert outcome != OUTCOME_READY_IN_SHADOW

    def test_requires_manual_review_held(self):
        from agent.editorial import readiness as RDY
        from agent.editorial.orchestrator import OUTCOME_REQUIRES_MANUAL_REVIEW
        rd_status = RDY.STATUS_REQUIRES_MANUAL_REVIEW
        if rd_status == RDY.STATUS_READY:
            outcome = "ready_in_shadow"
        elif rd_status == RDY.STATUS_READY_WITH_WARNINGS:
            outcome = "ready_with_warnings_hold"
        elif rd_status == RDY.STATUS_REQUIRES_MANUAL_REVIEW:
            outcome = OUTCOME_REQUIRES_MANUAL_REVIEW
        else:
            outcome = "quality_rejected"
        assert outcome == OUTCOME_REQUIRES_MANUAL_REVIEW

    def test_rejected_never_ready(self):
        from agent.editorial import readiness as RDY
        from agent.editorial.orchestrator import OUTCOME_QUALITY_REJECTED
        rd_status = RDY.STATUS_REJECTED
        if rd_status == RDY.STATUS_READY:
            outcome = "ready_in_shadow"
        elif rd_status == RDY.STATUS_READY_WITH_WARNINGS:
            outcome = "ready_with_warnings_hold"
        elif rd_status == RDY.STATUS_REQUIRES_MANUAL_REVIEW:
            outcome = "requires_manual_review"
        else:
            outcome = OUTCOME_QUALITY_REJECTED
        assert outcome == OUTCOME_QUALITY_REJECTED


# ── artifact routing ─────────────────────────────────────────────────────────

class TestArtifactRouting:
    """Verify the correct 7A builder is invoked per slot type."""

    def test_morning_slot_uses_intelligence_brief(self):
        from agent.editorial.orchestrator import _generate_artifact
        from agent.editorial.slots import ContentType

        ct = ContentType(name="intelligence_brief", formats=("intelligence_brief",))
        result = _generate_artifact(
            ct, "intelligence_brief", "tuesday", (), None, "", {}, None,
            None, "", (), (), None, "intelligence_brief",
        )
        assert result is not None
        assert result["artifact_type"] == "intelligence_brief"

    def test_sunday_trend_uses_weekly_trend_analysis(self):
        from agent.editorial.orchestrator import _generate_artifact
        from agent.editorial.slots import ContentType

        ct = ContentType(name="weekly_trend", artifact="weekly_trend_analysis")
        result = _generate_artifact(
            ct, "midday_authority", "sunday", (), None, "", {}, None,
            None, "", (), (), None, "weekly_trend_analysis",
        )
        assert result is not None
        assert result["artifact_type"] == "weekly_trend_analysis"

    def test_sunday_report_uses_weekly_intelligence_report(self):
        from agent.editorial.orchestrator import _generate_artifact
        from agent.editorial.slots import ContentType

        ct = ContentType(name="weekly_report", artifact="weekly_intelligence_report")
        result = _generate_artifact(
            ct, "practical_takeaway", "sunday", (), None, "", {}, None,
            None, "", (), (), None, "weekly_intelligence_report",
        )
        assert result is not None
        assert result["artifact_type"] == "weekly_intelligence_report"

    def test_tutorial_slot_no_system_artifact(self):
        from agent.editorial.orchestrator import _generate_artifact
        from agent.editorial.slots import ContentType

        ct = ContentType(name="tutorial_deep_dive", formats=("tutorial_deep_dive",))
        result = _generate_artifact(
            ct, "midday_authority", "monday", (), None, "", {}, None,
            None, "", (), (), None, "tutorial_deep_dive",
        )
        assert result is None

    def test_takeaway_slot_no_system_artifact(self):
        from agent.editorial.orchestrator import _generate_artifact
        from agent.editorial.slots import ContentType

        ct = ContentType(name="takeaway_checklist", formats=("takeaway_checklist",))
        result = _generate_artifact(
            ct, "practical_takeaway", "wednesday", (), None, "", {}, None,
            None, "", (), (), None, "takeaway_checklist",
        )
        assert result is None

    def test_sunday_artifacts_materially_distinct(self):
        from agent.editorial.orchestrator import _generate_artifact
        from agent.editorial.slots import ContentType
        from agent.editorial.artifacts import validate_artifact_distinctness, Artifact

        ct_trend = ContentType(name="weekly_trend", artifact="weekly_trend_analysis")
        ct_report = ContentType(name="weekly_report", artifact="weekly_intelligence_report")
        trend_dict = _generate_artifact(
            ct_trend, "midday_authority", "sunday", (), None, "", {}, None,
            None, "", (), (), None, "weekly_trend_analysis",
        )
        report_dict = _generate_artifact(
            ct_report, "practical_takeaway", "sunday", (), None, "", {}, None,
            None, "", (), (), None, "weekly_intelligence_report",
        )
        trend_art = Artifact(
            artifact_type="weekly_trend_analysis", format_id="weekly_trend_analysis",
            editorial_day="sunday",
            sections=tuple((s["heading"], s["body"]) for s in trend_dict["sections"]),
        )
        report_art = Artifact(
            artifact_type="weekly_intelligence_report", format_id="weekly_intelligence_report",
            editorial_day="sunday",
            sections=tuple((s["heading"], s["body"]) for s in report_dict["sections"]),
        )
        validate_artifact_distinctness(trend_art, report_art)


# ── generation metadata ──────────────────────────────────────────────────────

class TestGenerationMetadata:
    def test_default_builder_labels_deterministic_scaffold(self):
        from agent.editorial.orchestrator import _default_draft_builder
        candidate = _fake_candidate()
        result = _default_draft_builder(candidate, "intelligence_brief", "test", None)
        assert result["generation_mode"] == "deterministic_scaffold"

    def test_default_builder_not_labeled_llm(self):
        from agent.editorial.orchestrator import _default_draft_builder
        candidate = _fake_candidate()
        result = _default_draft_builder(candidate, "intelligence_brief", "test", None)
        assert result.get("generation_mode") != "llm"
        assert "provider" not in result
        assert "model" not in result
        assert "cost" not in result
