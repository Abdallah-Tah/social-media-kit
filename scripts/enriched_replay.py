#!/usr/bin/env python3
"""Enriched historical replay — before/after comparison.

Enriches the 140 archived candidates from 2026-07-20 to 2026-07-26,
then re-runs the 21-slot replay and compares results.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))

from agent.editorial.enrichment import enrich_many
from agent.editorial.replay import WeeklyReplayInput, run_weekly_replay
from agent.editorial.orchestrator import (
    OUTCOME_READY_IN_SHADOW,
    OUTCOME_READY_WITH_WARNINGS_HOLD,
    OUTCOME_REQUIRES_MANUAL_REVIEW,
    OUTCOME_QUALITY_REJECTED,
    OUTCOME_SKIPPED_NO_CANDIDATE,
)

WEEK_START = "2026-07-20"
FEED_DIR = KIT / "content" / "feed"
DECISIONS_FILE = KIT / "content" / "content_decisions.jsonl"

DATES = [
    "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
    "2026-07-24", "2026-07-25", "2026-07-26",
]


def load_raw_candidates(date_str: str) -> list[dict]:
    path = FEED_DIR / f"{date_str}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("items", [])
    except (json.JSONDecodeError, OSError):
        return []


def load_history() -> list[dict]:
    if not DECISIONS_FILE.exists():
        return []
    try:
        return [json.loads(l) for l in DECISIONS_FILE.read_text().splitlines() if l.strip()]
    except (json.JSONDecodeError, OSError):
        return []


def enrich_day(items: list[dict]) -> list[dict]:
    """Enrich a day's feed items and convert to pipeline-consumable records."""
    enriched = enrich_many(items)
    records = []
    for original, result in enriched:
        record = dict(original)  # Don't mutate original
        # Add enrichment data as metadata
        record["metadata"] = dict(record.get("metadata", {}) or {})
        record["metadata"]["enrichment"] = result.to_dict()
        # Add structured sources from enrichment
        if result.sources:
            record["sources"] = list(result.sources)
        # Add structured claims from enrichment
        if result.claims:
            record["claims"] = list(result.claims)
        # Add development type
        if result.development_type != "unknown":
            record["metadata"]["development_type"] = result.development_type
        # Add subject org
        if result.subject_org:
            record["metadata"]["subject_org"] = result.subject_org
        records.append(record)
    return records


def run_replay(candidates_by_day: dict, history: list[dict]) -> dict:
    """Run replay and return aggregate stats."""
    result = run_weekly_replay(WeeklyReplayInput(
        week_start=WEEK_START,
        candidates_by_day=candidates_by_day,
        history_rows=tuple(history),
    ))

    outcome_counts = Counter()
    sc_scores = []
    eq_scores = []
    rejection_reasons = Counter()
    total_evaluated = 0
    admitted = 0
    formats = Counter()

    for day in result.days:
        for sr in day.slot_results:
            outcome_counts[sr.outcome] += 1
            if sr.source_confidence is not None:
                sc_scores.append(sr.source_confidence)
            if sr.editorial_quality is not None:
                eq_scores.append(sr.editorial_quality)
            if sr.format_id:
                formats[sr.format_id] += 1
            for ev in sr.evaluations:
                if ev.get("stage") == "admission":
                    total_evaluated += 1
                    if ev.get("status") == "admitted":
                        admitted += 1
                    for r in ev.get("rejection_reasons", []):
                        rejection_reasons[r] += 1

    return {
        "outcome_counts": dict(outcome_counts),
        "sc_scores": sc_scores,
        "eq_scores": eq_scores,
        "rejection_reasons": dict(rejection_reasons),
        "total_evaluated": total_evaluated,
        "admitted": admitted,
        "formats": dict(formats),
        "days": len(result.days),
        "slot_results": [
            (d.date, d.weekday, sr.slot_id, sr.content_type, sr.outcome,
             sr.candidate_id, sr.source_confidence, sr.editorial_quality,
             sr.readiness_status, sr.format_id)
            for d in result.days for sr in d.slot_results
        ],
    }


def print_comparison(before: dict, after: dict):
    print("=" * 78)
    print("  BEFORE / AFTER COMPARISON")
    print("=" * 78)

    print(f"\n  {'Metric':<40} {'Before':>12} {'After':>12}")
    print(f"  {'-'*40} {'-'*12} {'-'*12}")

    # Slot fill rate
    for outcome in [OUTCOME_READY_IN_SHADOW, OUTCOME_READY_WITH_WARNINGS_HOLD,
                    OUTCOME_REQUIRES_MANUAL_REVIEW, OUTCOME_QUALITY_REJECTED,
                    OUTCOME_SKIPPED_NO_CANDIDATE]:
        b = before["outcome_counts"].get(outcome, 0)
        a = after["outcome_counts"].get(outcome, 0)
        label = outcome.replace("_", " ").title()[:38]
        print(f"  {label:<40} {b:>12} {a:>12}")

    # Candidate funnel
    print(f"  {'Candidates evaluated':<40} {before['total_evaluated']:>12} {after['total_evaluated']:>12}")
    print(f"  {'Candidates admitted':<40} {before['admitted']:>12} {after['admitted']:>12}")

    # Source confidence
    b_sc = before["sc_scores"]
    a_sc = after["sc_scores"]
    if b_sc:
        print(f"  {'SC avg':<40} {sum(b_sc)/len(b_sc):>12.1f} ", end="")
    else:
        print(f"  {'SC avg':<40} {'(none)':>12} ", end="")
    if a_sc:
        print(f"{sum(a_sc)/len(a_sc):>12.1f}")
    else:
        print(f"{'(none)':>12}")

    if b_sc:
        print(f"  {'SC min-max':<40} {min(b_sc):>5}-{max(b_sc):<5} ", end="")
    else:
        print(f"  {'SC min-max':<40} {'(none)':>12} ", end="")
    if a_sc:
        print(f"{min(a_sc):>5}-{max(a_sc):<5}")
    else:
        print(f"{'(none)':>12}")

    # Editorial quality
    b_eq = before["eq_scores"]
    a_eq = after["eq_scores"]
    if b_eq:
        print(f"  {'EQ avg':<40} {sum(b_eq)/len(b_eq):>12.1f} ", end="")
    else:
        print(f"  {'EQ avg':<40} {'(none)':>12} ", end="")
    if a_eq:
        print(f"{sum(a_eq)/len(a_eq):>12.1f}")
    else:
        print(f"{'(none)':>12}")

    # Rejection reasons
    print(f"\n  Rejection reasons:")
    all_reasons = set(before["rejection_reasons"].keys()) | set(after["rejection_reasons"].keys())
    for reason in sorted(all_reasons):
        b = before["rejection_reasons"].get(reason, 0)
        a = after["rejection_reasons"].get(reason, 0)
        print(f"    {reason:<38} {b:>10} {a:>10}")

    # Formats
    print(f"\n  Formats selected:")
    all_formats = set(before["formats"].keys()) | set(after["formats"].keys())
    for fmt in sorted(all_formats):
        b = before["formats"].get(fmt, 0)
        a = after["formats"].get(fmt, 0)
        print(f"    {fmt:<38} {b:>10} {a:>10}")


def main():
    print("=" * 78)
    print("  ENRICHED HISTORICAL REPLAY: 2026-07-20 (Mon) to 2026-07-26 (Sun)")
    print("=" * 78)

    history = load_history()

    # ── BEFORE: raw candidates ─────────────────────────────────────────────
    print("\n  Loading raw candidates...")
    raw_by_day = {}
    total_raw = 0
    for d in DATES:
        items = load_raw_candidates(d)
        raw_by_day[d] = tuple(items)
        total_raw += len(items)
    print(f"  Total raw candidates: {total_raw}")

    print("  Running BEFORE replay (raw)...")
    before = run_replay(raw_by_day, history)

    # ── Enrichment ─────────────────────────────────────────────────────────
    print("\n  Enriching candidates...")
    enriched_by_day = {}
    total_enriched = 0
    enrichment_stats = Counter()
    for d in DATES:
        items = load_raw_candidates(d)
        enriched_records = enrich_day(items)
        enriched_by_day[d] = tuple(enriched_records)
        total_enriched += len(enriched_records)
        # Count enrichment statuses
        for _, result in enrich_many(items):
            enrichment_stats[result.status] += 1
    print(f"  Total enriched candidates: {total_enriched}")
    print(f"  Enrichment statuses: {dict(enrichment_stats)}")

    # ── AFTER: enriched candidates ─────────────────────────────────────────
    print("  Running AFTER replay (enriched)...")
    after = run_replay(enriched_by_day, history)

    # ── Comparison ─────────────────────────────────────────────────────────
    print_comparison(before, after)

    # ── Per-slot detail (after) ────────────────────────────────────────────
    print(f"\n{'='*78}")
    print("  PER-SLOT DETAIL (ENRICHED)")
    print("=" * 78)
    for date, weekday, slot_id, ct, outcome, cid, sc, eq, rd, fmt in after["slot_results"]:
        print(f"  {date} ({weekday}) {slot_id} | {ct}")
        print(f"    outcome={outcome}", end="")
        if cid:
            print(f" candidate={cid[:20]}...", end="")
        if sc is not None:
            print(f" sc={sc}", end="")
        if eq is not None:
            print(f" eq={eq}", end="")
        if rd:
            print(f" readiness={rd}", end="")
        if fmt:
            print(f" format={fmt}", end="")
        print()

    # ── Enrichment detail ──────────────────────────────────────────────────
    print(f"\n{'='*78}")
    print("  ENRICHMENT DETAIL (first 5 candidates)")
    print("=" * 78)
    first_day_items = load_raw_candidates(DATES[0])
    enriched_first = enrich_many(first_day_items[:5])
    for original, result in enriched_first:
        print(f"\n  {original.get('title', '?')[:60]}")
        print(f"    status={result.status} confidence={result.confidence}")
        print(f"    primary_source={'yes' if result.primary_source else 'no'}")
        print(f"    development_type={result.development_type}")
        print(f"    subject_org={result.subject_org or '(unresolved)'}")
        print(f"    sources={len(result.sources)} claims={len(result.claims)}")
        print(f"    artifacts={list(result.recommended_artifact_types)}")
        print(f"    warnings={list(result.warnings)}")
        signals = {k: v for k, v in result.practical_signals.items() if v}
        if signals:
            print(f"    practical_signals={list(signals.keys())}")

    print(f"\n{'='*78}")
    print("  REPLAY COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
