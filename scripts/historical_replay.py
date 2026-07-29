#!/usr/bin/env python3
"""Historical Monday-to-Sunday replay using real archived SMKit data.

Loads feed snapshots from content/feed/YYYY-MM-DD.json, ContentDecision
records from content/content_decisions.jsonl, and runs the full 21-slot
editorial pipeline for the week of 2026-07-21 to 2026-07-27.

Replay-only: never publishes, notifies, or modifies live histories.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))

from agent.editorial.replay import WeeklyReplayInput, run_weekly_replay
from agent.editorial.orchestrator import (
    OUTCOME_READY_IN_SHADOW,
    OUTCOME_READY_WITH_WARNINGS_HOLD,
    OUTCOME_REQUIRES_MANUAL_REVIEW,
    OUTCOME_QUALITY_REJECTED,
    OUTCOME_SKIPPED_NO_CANDIDATE,
    OUTCOME_DRAFT_GENERATION_FAILED,
    OUTCOME_INVALID_CONFIGURATION,
    OUTCOME_PIPELINE_FAILED,
)

WEEK_START = "2026-07-20"  # Monday
WEEK_END = "2026-07-26"    # Sunday
FEED_DIR = KIT / "content" / "feed"
DECISIONS_FILE = KIT / "content" / "content_decisions.jsonl"


def load_feed_candidates(date_str: str) -> list[dict]:
    """Load feed snapshot for a date, returning candidate dicts."""
    path = FEED_DIR / f"{date_str}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("items", [])
    except (json.JSONDecodeError, OSError):
        return []


def load_decision_history() -> list[dict]:
    """Load all ContentDecision records."""
    if not DECISIONS_FILE.exists():
        return []
    try:
        rows = []
        for line in DECISIONS_FILE.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
    except (json.JSONDecodeError, OSError):
        return []


def main():
    print("=" * 78)
    print("  HISTORICAL REPLAY: 2026-07-21 (Mon) to 2026-07-27 (Sun)")
    print("=" * 78)

    # ── Load real data ─────────────────────────────────────────────────────
    dates = [
        "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
        "2026-07-24", "2026-07-25", "2026-07-26",
    ]
    weekdays = ["monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday"]

    candidates_by_day = {}
    total_candidates = 0
    for date_str in dates:
        items = load_feed_candidates(date_str)
        candidates_by_day[date_str] = tuple(items)
        total_candidates += len(items)
        print(f"  {date_str}: {len(items)} candidates loaded")

    history_rows = tuple(load_decision_history())
    print(f"  Decision history: {len(history_rows)} records")
    print(f"  Total candidates: {total_candidates}")
    print()

    # ── Run replay ─────────────────────────────────────────────────────────
    print("  Running 21-slot replay...")
    result = run_weekly_replay(WeeklyReplayInput(
        week_start=WEEK_START,
        candidates_by_day=candidates_by_day,
        history_rows=history_rows,
    ))
    print(f"  Replay complete: {len(result.days)} days")
    print()

    # ── Per-slot detail ────────────────────────────────────────────────────
    print("=" * 78)
    print("  PER-SLOT DETAIL")
    print("=" * 78)

    all_slot_results = []
    for day in result.days:
        print(f"\n  ── {day.date} ({day.weekday}) ──")
        for sr in day.slot_results:
            all_slot_results.append((day.date, day.weekday, sr))
            print(f"    {sr.slot_id} | {sr.content_type}")
            print(f"      outcome={sr.outcome}")
            if sr.candidate_id:
                print(f"      candidate={sr.candidate_id}")
            if sr.format_id:
                print(f"      format={sr.format_id}")
            if sr.source_confidence is not None:
                print(f"      source_confidence={sr.source_confidence}")
            if sr.editorial_quality is not None:
                print(f"      quality={sr.editorial_quality}")
            if sr.readiness_status:
                print(f"      readiness={sr.readiness_status}")
            if sr.reason_codes:
                print(f"      reason_codes={list(sr.reason_codes)}")
            if sr.warnings:
                print(f"      warnings={list(sr.warnings)}")
            if sr.error:
                print(f"      error={sr.error}")
            if sr.artifact:
                print(f"      artifact={sr.artifact.get('artifact_type', '?')}")

    # ── Aggregate report ───────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("  WEEKLY AGGREGATE REPORT")
    print("=" * 78)

    # 1. Slot fill rate
    outcome_counts = Counter()
    for _, _, sr in all_slot_results:
        outcome_counts[sr.outcome] += 1

    print(f"\n  1. SLOT FILL RATE")
    print(f"     Total slots:              {len(all_slot_results)}")
    print(f"     ready_in_shadow:          {outcome_counts.get(OUTCOME_READY_IN_SHADOW, 0)}")
    print(f"     ready_with_warnings_hold: {outcome_counts.get(OUTCOME_READY_WITH_WARNINGS_HOLD, 0)}")
    print(f"     requires_manual_review:   {outcome_counts.get(OUTCOME_REQUIRES_MANUAL_REVIEW, 0)}")
    print(f"     quality_rejected:         {outcome_counts.get(OUTCOME_QUALITY_REJECTED, 0)}")
    print(f"     skipped_no_candidate:     {outcome_counts.get(OUTCOME_SKIPPED_NO_CANDIDATE, 0)}")
    print(f"     draft_generation_failed:  {outcome_counts.get(OUTCOME_DRAFT_GENERATION_FAILED, 0)}")
    print(f"     invalid_configuration:    {outcome_counts.get(OUTCOME_INVALID_CONFIGURATION, 0)}")
    print(f"     pipeline_failed:          {outcome_counts.get(OUTCOME_PIPELINE_FAILED, 0)}")

    fill_rate = (outcome_counts.get(OUTCOME_READY_IN_SHADOW, 0) / len(all_slot_results) * 100
                 if all_slot_results else 0)
    print(f"     Fill rate (ready/total):  {fill_rate:.1f}%")

    # 2. Candidate funnel
    print(f"\n  2. CANDIDATE FUNNEL")
    print(f"     Candidates received:      {total_candidates}")
    # Count evaluations from slot results
    normalized_count = 0
    rejected_normalization = 0
    rejected_source_conf = 0
    rejected_saturation = 0
    rejected_policy = 0
    admitted_count = 0
    for _, _, sr in all_slot_results:
        for ev in sr.evaluations:
            stage = ev.get("stage", "")
            status = ev.get("status", "")
            reasons = ev.get("rejection_reasons", [])
            if stage == "normalization":
                if status == "failed":
                    rejected_normalization += 1
            elif stage == "admission":
                if status == "admitted":
                    admitted_count += 1
                elif status == "rejected":
                    for r in reasons:
                        if "source_confidence" in r:
                            rejected_source_conf += 1
                        elif "saturat" in r or r.startswith("R"):
                            rejected_saturation += 1
                        else:
                            rejected_policy += 1

    print(f"     Rejected (normalization): {rejected_normalization}")
    print(f"     Rejected (source conf):   {rejected_source_conf}")
    print(f"     Rejected (saturation):    {rejected_saturation}")
    print(f"     Rejected (slot policy):   {rejected_policy}")
    print(f"     Admitted:                 {admitted_count}")

    # 3. Quality metrics
    sc_scores = [sr.source_confidence for _, _, sr in all_slot_results
                 if sr.source_confidence is not None]
    eq_scores = [sr.editorial_quality for _, _, sr in all_slot_results
                 if sr.editorial_quality is not None]

    print(f"\n  3. QUALITY METRICS")
    if sc_scores:
        print(f"     Source confidence: avg={sum(sc_scores)/len(sc_scores):.1f}, "
              f"min={min(sc_scores)}, max={max(sc_scores)}, n={len(sc_scores)}")
    else:
        print(f"     Source confidence: (no data)")
    if eq_scores:
        print(f"     Editorial quality: avg={sum(eq_scores)/len(eq_scores):.1f}, "
              f"min={min(eq_scores)}, max={max(eq_scores)}, n={len(eq_scores)}")
    else:
        print(f"     Editorial quality: (no data)")

    # Hard failures and warnings
    all_reason_codes = Counter()
    all_warnings = Counter()
    for _, _, sr in all_slot_results:
        for rc in sr.reason_codes:
            all_reason_codes[rc] += 1
        for w in sr.warnings:
            all_warnings[w] += 1

    if all_reason_codes:
        print(f"     Reason codes:")
        for code, count in all_reason_codes.most_common():
            print(f"       {code}: {count}")
    if all_warnings:
        print(f"     Warnings:")
        for code, count in all_warnings.most_common():
            print(f"       {code}: {count}")

    # 4. Saturation metrics
    print(f"\n  4. SATURATION METRICS")
    saturation_rejections = sum(1 for _, _, sr in all_slot_results
                                for ev in sr.evaluations
                                if ev.get("stage") == "admission"
                                and any("saturat" in r or r.startswith("R")
                                        for r in ev.get("rejection_reasons", [])))
    print(f"     Saturation rejections:    {saturation_rejections}")

    # 5. Editorial diversity
    print(f"\n  5. EDITORIAL DIVERSITY")
    format_counts = Counter()
    entity_counts = Counter()
    for _, _, sr in all_slot_results:
        if sr.format_id:
            format_counts[sr.format_id] += 1
    if format_counts:
        print(f"     Formats selected:")
        for fmt, count in format_counts.most_common():
            print(f"       {fmt}: {count}")

    # 6. Source relationship metrics
    print(f"\n  6. SOURCE RELATIONSHIP METRICS")
    print(f"     (Derived from admission evaluations)")
    relationship_unknown = 0
    for _, _, sr in all_slot_results:
        for ev in sr.evaluations:
            if "relationship_unknown" in str(ev.get("rejection_reasons", [])):
                relationship_unknown += 1
    print(f"     relationship_unknown:     {relationship_unknown}")

    # 7. Content-volume assessment
    print(f"\n  7. CONTENT-VOLUME ASSESSMENT")
    ready = outcome_counts.get(OUTCOME_READY_IN_SHADOW, 0)
    held = outcome_counts.get(OUTCOME_READY_WITH_WARNINGS_HOLD, 0)
    review = outcome_counts.get(OUTCOME_REQUIRES_MANUAL_REVIEW, 0)
    skipped = outcome_counts.get(OUTCOME_SKIPPED_NO_CANDIDATE, 0)
    print(f"     Ready to publish:         {ready}/21 slots")
    print(f"     Held (warnings):          {held}/21 slots")
    print(f"     Manual review:            {review}/21 slots")
    print(f"     Skipped (no candidate):   {skipped}/21 slots")
    if ready <= 3:
        print(f"     Assessment: TOO LITTLE — most slots lack admissible candidates")
    elif ready <= 10:
        print(f"     Assessment: APPROPRIATE — selective but consistent output")
    else:
        print(f"     Assessment: HIGH VOLUME — review quality thresholds")

    # ── Representative examples ────────────────────────────────────────────
    print()
    print("=" * 78)
    print("  FIVE REPRESENTATIVE SLOT EXAMPLES")
    print("=" * 78)

    examples = []
    for date, weekday, sr in all_slot_results:
        if sr.candidate_id and sr.outcome not in (OUTCOME_SKIPPED_NO_CANDIDATE,):
            examples.append((date, weekday, sr))
    for date, weekday, sr in examples[:5]:
        print(f"\n  {date} ({weekday}) | {sr.slot_id} | {sr.content_type}")
        print(f"    outcome:          {sr.outcome}")
        print(f"    candidate:        {sr.candidate_id}")
        print(f"    format:           {sr.format_id}")
        print(f"    source_conf:      {sr.source_confidence}")
        print(f"    quality:          {sr.editorial_quality}")
        print(f"    readiness:        {sr.readiness_status}")
        print(f"    reason_codes:     {list(sr.reason_codes)}")
        print(f"    warnings:         {list(sr.warnings)}")
        print(f"    draft_title:      {sr.draft_title[:60] if sr.draft_title else '(none)'}")

    # ── Skipped slot reasons ───────────────────────────────────────────────
    print()
    print("=" * 78)
    print("  ALL SKIPPED-SLOT REASONS")
    print("=" * 78)
    for date, weekday, sr in all_slot_results:
        if sr.outcome == OUTCOME_SKIPPED_NO_CANDIDATE:
            reasons = []
            for ev in sr.evaluations:
                if ev.get("status") == "rejected":
                    reasons.extend(ev.get("rejection_reasons", []))
            reason_str = ", ".join(reasons) if reasons else "no candidates received"
            print(f"  {date} {sr.slot_id}: {reason_str}")

    # ── Persisted files ────────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("  PERSISTED FILES")
    print("=" * 78)
    replay_dir = KIT / "state" / "editorial" / "replay"
    if replay_dir.exists():
        for f in sorted(replay_dir.glob("*.json")):
            print(f"  {f.relative_to(KIT)}")

    print()
    print("=" * 78)
    print("  REPLAY COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
