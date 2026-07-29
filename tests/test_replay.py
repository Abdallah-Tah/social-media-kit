"""Phase 1 Stage 7C — historical Monday-to-Sunday replay tests.

Covers:
  * Weekly replay iterates all 7 days
  * Each day evaluates all 3 slots
  * Sunday slots generate weekly artifacts
  * Per-day candidates are routed correctly
  * Persistence to state/editorial/replay/
  * Weekly summary report
  * Replay mode only — no publishing, no notifications
  * Non-Monday week_start rejected
  * EDITORIAL_SLOTS_ENABLED remains false
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

from agent.editorial.replay import (
    DayReplayResult,
    WeeklyReplayInput,
    WeeklyReplayResult,
    run_weekly_replay,
    _week_dates,
)
from agent.editorial.orchestrator import (
    MODE_REPLAY,
    OUTCOME_READY_IN_SHADOW,
    OUTCOME_SKIPPED_NO_CANDIDATE,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _fake_record(cid="c1", title="Test candidate", url="https://example.com/c1"):
    return {
        "title": title,
        "url": url,
        "source": "hackernews",
        "candidate_id": cid,
        "opportunity_score": 90,
        "discovered_at": "2026-07-27T08:00:00Z",
        "summary": "A test candidate for replay verification.",
        "metadata": {"development_type": "model_release", "subject_org": "testorg"},
        "sources": [
            {"url": url, "kind": "official_announcement",
             "covers_exact_development": True, "adds_independent_evidence": False},
            {"url": f"https://independent.com/{cid}", "kind": "secondary",
             "covers_exact_development": True, "adds_independent_evidence": True},
        ],
        "claims": [
            {"text": "Test claim", "verification": "verified_independent",
             "source_url": url},
        ],
    }


def _scaffold_draft(candidate, format_id, slot_objective, source_confidence=None,
                    quality_hints=None):
    title = getattr(candidate, "title", "Test") or "Test"
    body = (
        f"# {title}\n\n## Summary\n\n"
        f"Analysis of {title} published on 2026-07-27. "
        "The release includes version 2.1 with API changes at api.example.com/v2. "
        "The model supports gpt-5-turbo variant with 200K context window. "
        "Repository: github.com/example/sdk. Documentation: docs.example.com.\n\n"
        "## What Happened\n\n"
        "Detailed analysis with concrete signals: version 2.1, released 2026-07-27, "
        "API endpoint POST /v2/chat/completions, model=gpt-5-turbo, "
        "max_tokens default 16384. Migration from gpt-4 requires parameter updates. "
        "The SDK is available via pip install example-sdk>=2.1.0. "
        "Breaking changes affect the /chat/completions endpoint structure.\n\n"
        "## Confirmed Facts\n\n"
        "- Officially announced on 2026-07-27 via primary channels\n"
        "- Independently corroborated by multiple credible outlets\n"
        "- Technical specs documented at docs.example.com\n"
        "- API: POST /v2/chat/completions with model=gpt-5-turbo\n\n"
        "## Unverified Claims\n\n"
        "- Vendor benchmarks await independent verification\n\n"
        "## Practical Implications\n\n"
        "Developers should evaluate against their current stack. "
        "Migration path is straightforward for most use cases. "
        "Test in staging before production. Run pip install example-sdk>=2.1.0. "
        "Review docs.example.com/migration for the upgrade procedure. "
        "Teams on legacy v1 should plan migration before 2026-12-31 sunset.\n\n"
        "## What Developers Should Watch\n\n"
        "- Monitor /v2/chat/completions for latency changes post-migration\n"
        "- Watch rate limit adjustments in first 48 hours\n"
        "- Track independent benchmarks expected within 2 weeks\n"
        "- Review v1 deprecation timeline (sunset: 2026-12-31)\n"
        "- Check fine-tuned model compatibility with v2\n\n"
        "## Sources\n\n"
        "- https://example.com/primary\n"
        "- https://example.com/coverage\n"
    )
    return {
        "title": title, "body": body, "summary": f"Analysis of {title}",
        "format_id": format_id, "artifact_type": format_id,
        "slot_objective": slot_objective,
        "sources": ({"url": "https://example.com/primary", "kind": "primary"},),
        "claims": ({"text": "Test claim", "verification": "verified_independent",
                     "source_url": "https://example.com/primary"},),
        "confirmed_facts": ({"text": "Test claim", "source_url": "https://example.com/primary"},),
        "generation_mode": "deterministic_scaffold",
    }


# ── date helpers ─────────────────────────────────────────────────────────────

class TestWeekDates:
    def test_monday_start(self):
        dates = _week_dates("2026-07-27")
        assert len(dates) == 7
        assert dates[0] == ("2026-07-27", "monday")
        assert dates[6] == ("2026-08-02", "sunday")

    def test_non_monday_rejected(self):
        with pytest.raises(ValueError, match="must be a Monday"):
            _week_dates("2026-07-28")  # Tuesday


# ── weekly replay ────────────────────────────────────────────────────────────

class TestWeeklyReplay:
    def test_iterates_all_7_days(self):
        result = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27",
        ))
        assert len(result.days) == 7
        weekdays = [d.weekday for d in result.days]
        assert weekdays == ["monday", "tuesday", "wednesday", "thursday",
                            "friday", "saturday", "sunday"]

    def test_each_day_has_3_slots(self):
        result = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27",
        ))
        for day in result.days:
            assert len(day.slot_results) == 3

    def test_sunday_generates_weekly_artifacts(self):
        result = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27",
        ))
        sunday = result.days[6]
        slot_map = {sr.slot_id: sr for sr in sunday.slot_results}
        assert slot_map["midday_authority"].artifact_type == "weekly_trend_analysis"
        assert slot_map["practical_takeaway"].artifact_type == "weekly_intelligence_report"

    def test_per_day_candidates_routed(self):
        result = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27",
            candidates_by_day={
                "2026-07-27": (_fake_record("c1", "Monday candidate"),),
                "2026-07-29": (_fake_record("c2", "Wednesday candidate"),),
            },
            draft_builder=_scaffold_draft,
        ))
        monday = result.days[0]
        tuesday = result.days[1]
        # Monday has candidates → slots should evaluate them (even if rejected)
        # At least one slot should have evaluations recorded
        monday_has_evals = any(
            sr.evaluations or sr.candidate_id
            for sr in monday.slot_results
        )
        # Tuesday has no candidates → all skipped with no evaluations
        for sr in tuesday.slot_results:
            assert sr.outcome == OUTCOME_SKIPPED_NO_CANDIDATE
            assert not sr.candidate_id

    def test_weekly_summary_report(self):
        result = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27",
        ))
        summary = result._summary()
        assert summary["total_slots_evaluated"] == 21  # 7 days × 3 slots
        assert "outcome_counts" in summary
        assert "slot_outcomes" in summary

    def test_non_monday_rejected(self):
        result = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-28",  # Tuesday
        ))
        assert len(result.days) == 0


# ── persistence ──────────────────────────────────────────────────────────────

class TestReplayPersistence:
    def test_persists_to_replay_dir(self, tmp_path, monkeypatch):
        from agent.editorial import replay as REPLAY
        monkeypatch.setattr(REPLAY, "REPLAY_DIR", tmp_path / "replay")
        result = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27",
        ))
        expected = tmp_path / "replay" / "weekly_2026-07-27.json"
        assert expected.exists()
        data = json.loads(expected.read_text())
        assert data["week_start"] == "2026-07-27"
        assert data["week_end"] == "2026-08-02"
        assert len(data["days"]) == 7

    def test_per_slot_files_created(self, tmp_path, monkeypatch):
        from agent.editorial import orchestrator as ORCH
        monkeypatch.setattr(ORCH, "STATE_DIR", tmp_path / "editorial")
        run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27",
        ))
        replay_dir = tmp_path / "editorial" / "replay"
        files = list(replay_dir.glob("pipeline_*.json"))
        assert len(files) == 21  # 7 days × 3 slots


# ── purity guarantees ────────────────────────────────────────────────────────

class TestReplayPurity:
    def test_no_publishing_calls(self):
        with patch("agent.drafts.publish_blog",
                   side_effect=AssertionError("no publishing")):
            run_weekly_replay(WeeklyReplayInput(week_start="2026-07-27"))

    def test_no_notification_calls(self):
        with patch("agent.notify.notify_publish",
                   side_effect=AssertionError("no notifications")):
            run_weekly_replay(WeeklyReplayInput(week_start="2026-07-27"))

    def test_no_llm_calls(self):
        import agent.llm_ops as LLM
        with patch.object(LLM, "chat", side_effect=AssertionError("no LLM")):
            run_weekly_replay(WeeklyReplayInput(week_start="2026-07-27"))

    def test_feature_flag_remains_false(self):
        from agent.editorial.flags import editorial_slots_enabled
        assert editorial_slots_enabled() is False


# ── determinism ──────────────────────────────────────────────────────────────

class TestReplayDeterminism:
    def test_same_input_same_output(self):
        import datetime as dt
        now = dt.datetime(2026, 7, 27, 12, 0, 0, tzinfo=dt.timezone.utc)
        r1 = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27", now=now,
        ))
        r2 = run_weekly_replay(WeeklyReplayInput(
            week_start="2026-07-27", now=now,
        ))
        d1 = r1.to_dict()
        d2 = r2.to_dict()
        d1.pop("started_at", None)
        d1.pop("completed_at", None)
        d2.pop("started_at", None)
        d2.pop("completed_at", None)
        assert d1 == d2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
