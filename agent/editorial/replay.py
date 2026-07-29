"""Phase 1 Stage 7C — historical Monday-to-Sunday replay.

Runs the full editorial pipeline for every slot across a complete week,
using historical or fixture-based candidates. Replay-only: never publishes,
never notifies, never modifies live histories.

Persistence: state/editorial/replay/pipeline_YYYY-MM-DD_<slot_id>.json
Summary:     state/editorial/replay/weekly_YYYY-MM-DD.json

Usage:
    from agent.editorial.replay import run_weekly_replay, WeeklyReplayInput
    result = run_weekly_replay(WeeklyReplayInput(
        week_start="2026-07-27",  # Monday
        candidates_by_day={...},  # optional per-day candidates
    ))
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .orchestrator import (
    MODE_REPLAY,
    OUTCOME_READY_IN_SHADOW,
    OUTCOME_READY_WITH_WARNINGS_HOLD,
    OUTCOME_REQUIRES_MANUAL_REVIEW,
    OUTCOME_QUALITY_REJECTED,
    OUTCOME_SKIPPED_NO_CANDIDATE,
    OUTCOME_DRAFT_GENERATION_FAILED,
    OUTCOME_INVALID_CONFIGURATION,
    OUTCOME_PIPELINE_FAILED,
    PipelineInput,
    PipelineResult,
    SlotResult,
    run_pipeline,
    _default_draft_builder,
)

KIT = Path(__file__).resolve().parents[2]
REPLAY_DIR = KIT / "state" / "editorial" / "replay"

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday")


# ── Input / output ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WeeklyReplayInput:
    """Complete input for a weekly replay run."""
    week_start: str  # YYYY-MM-DD (must be a Monday)
    candidates_by_day: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    history_rows: tuple[dict[str, Any], ...] = ()
    draft_builder: Callable[..., dict[str, Any]] | None = None
    now: dt.datetime | None = None


@dataclass(frozen=True)
class DayReplayResult:
    """Replay results for one day."""
    date: str
    weekday: str
    slot_results: tuple[SlotResult, ...]
    config_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "weekday": self.weekday,
            "config_errors": list(self.config_errors),
            "slot_results": [
                {
                    "slot_id": sr.slot_id,
                    "content_type": sr.content_type,
                    "outcome": sr.outcome,
                    "candidate_id": sr.candidate_id,
                    "format_id": sr.format_id,
                    "artifact_type": sr.artifact_type,
                    "source_confidence": sr.source_confidence,
                    "editorial_quality": sr.editorial_quality,
                    "readiness_status": sr.readiness_status,
                    "reason_codes": list(sr.reason_codes),
                    "warnings": list(sr.warnings),
                    "draft_title": sr.draft_title,
                    "error": sr.error,
                }
                for sr in self.slot_results
            ],
        }


@dataclass(frozen=True)
class WeeklyReplayResult:
    """Complete results for a weekly replay."""
    week_start: str
    week_end: str
    days: tuple[DayReplayResult, ...]
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "days": [d.to_dict() for d in self.days],
            "summary": self._summary(),
        }

    def _summary(self) -> dict[str, Any]:
        outcome_counts: dict[str, int] = {}
        slot_outcomes: dict[str, dict[str, int]] = {}
        total_slots = 0
        for day in self.days:
            for sr in day.slot_results:
                total_slots += 1
                outcome_counts[sr.outcome] = outcome_counts.get(sr.outcome, 0) + 1
                if sr.slot_id not in slot_outcomes:
                    slot_outcomes[sr.slot_id] = {}
                slot_outcomes[sr.slot_id][sr.outcome] = \
                    slot_outcomes[sr.slot_id].get(sr.outcome, 0) + 1
        return {
            "total_slots_evaluated": total_slots,
            "outcome_counts": outcome_counts,
            "slot_outcomes": slot_outcomes,
        }


# ── Date helpers ─────────────────────────────────────────────────────────────

def _week_dates(week_start: str) -> list[tuple[str, str]]:
    """Return 7 (date_str, weekday_name) tuples starting from week_start."""
    start = dt.date.fromisoformat(week_start)
    if start.weekday() != 0:
        raise ValueError(f"week_start must be a Monday, got {week_start} "
                         f"({WEEKDAYS[start.weekday()]})")
    return [
        ((start + dt.timedelta(days=i)).isoformat(), WEEKDAYS[i])
        for i in range(7)
    ]


# ── Public entry point ───────────────────────────────────────────────────────

def run_weekly_replay(inp: WeeklyReplayInput) -> WeeklyReplayResult:
    """Run the full editorial pipeline for every slot across a complete week.

    Replay-only: never publishes, never notifies, never modifies live histories.
    """
    now = inp.now or dt.datetime.now(dt.timezone.utc)
    started_at = now.isoformat()
    draft_builder = inp.draft_builder or _default_draft_builder

    try:
        week_dates = _week_dates(inp.week_start)
    except ValueError as exc:
        return WeeklyReplayResult(
            week_start=inp.week_start,
            week_end="",
            days=(),
            started_at=started_at,
            completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )

    week_end = week_dates[-1][0]
    days: list[DayReplayResult] = []

    for date_str, weekday in week_dates:
        candidates = inp.candidates_by_day.get(date_str, ())
        day_result = run_pipeline(PipelineInput(
            mode=MODE_REPLAY,
            date=date_str,
            candidates=candidates,
            history_rows=inp.history_rows,
            draft_builder=draft_builder,
            now=now,
        ))
        days.append(DayReplayResult(
            date=date_str,
            weekday=weekday,
            slot_results=day_result.slot_results,
            config_errors=day_result.config_errors,
        ))

    completed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    result = WeeklyReplayResult(
        week_start=inp.week_start,
        week_end=week_end,
        days=tuple(days),
        started_at=started_at,
        completed_at=completed_at,
    )

    _persist_weekly(result)
    return result


# ── Persistence ──────────────────────────────────────────────────────────────

def _persist_weekly(result: WeeklyReplayResult) -> Path:
    """Write the weekly summary to the git-ignored replay directory."""
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"weekly_{result.week_start}.json"
    path = REPLAY_DIR / filename
    path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
