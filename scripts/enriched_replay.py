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
from agent.editorial.evidence_retrieval import (
    load_evidence_retrieval_config,
    retrieve_evidence_for_candidates,
)
from agent.editorial.evidence_extraction import (
    load_extraction_config,
    extract_structured_evidence,
)
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
    
    # Source-confidence observability
    sc_details = []  # List of (candidate_id, total_score, components, warnings, rejection_reasons)

    for day in result.days:
        for sr in day.slot_results:
            outcome_counts[sr.outcome] += 1
            if sr.source_confidence is not None:
                sc_scores.append(sr.source_confidence)
            if sr.editorial_quality is not None:
                eq_scores.append(sr.editorial_quality)
            if sr.format_id:
                formats[sr.format_id] += 1
            
            # Extract source-confidence component details
            candidate_sc_details = {}
            candidate_rejection_reasons = []
            for ev in sr.evaluations:
                if ev.get("stage") == "source_confidence" and ev.get("status") == "scored":
                    candidate_sc_details[ev["candidate_id"]] = {
                        "total_score": ev.get("total_score"),
                        "components": ev.get("components", {}),
                        "warnings": ev.get("warnings", []),
                    }
                if ev.get("stage") == "admission":
                    total_evaluated += 1
                    if ev.get("status") == "admitted":
                        admitted += 1
                    candidate_rejection_reasons = ev.get("rejection_reasons", [])
                    for r in candidate_rejection_reasons:
                        rejection_reasons[r] += 1
            
            # Store source-confidence details with rejection reasons
            for cand_id, details in candidate_sc_details.items():
                sc_details.append({
                    "candidate_id": cand_id,
                    "total_score": details["total_score"],
                    "components": details["components"],
                    "warnings": details["warnings"],
                    "rejection_reasons": candidate_rejection_reasons,
                })

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
        "sc_details": sc_details,  # Full source-confidence breakdowns
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


def print_top_candidates(replay_result: dict, candidates_by_day: dict, top_n: int = 10):
    """Print the top N strongest candidates with full component breakdowns."""
    sc_details = replay_result.get("sc_details", [])
    if not sc_details:
        print("\n  No source-confidence details available.")
        return
    
    # Sort by total score (descending)
    sorted_candidates = sorted(sc_details, key=lambda x: x.get("total_score", 0), reverse=True)
    top_candidates = sorted_candidates[:top_n]
    
    print(f"\n{'='*78}")
    print(f"  TOP {top_n} STRONGEST CANDIDATES (by source-confidence score)")
    print("=" * 78)
    
    # Build a lookup for candidate metadata
    candidate_lookup = {}
    for day, candidates in candidates_by_day.items():
        for cand in candidates:
            cand_id = cand.get("candidate_id", "")
            if cand_id:
                candidate_lookup[cand_id] = cand
    
    for i, details in enumerate(top_candidates, 1):
        cand_id = details.get("candidate_id", "")
        total_score = details.get("total_score", 0)
        components = details.get("components", {})
        warnings = details.get("warnings", [])
        rejection_reasons = details.get("rejection_reasons", [])
        
        # Get candidate metadata
        cand = candidate_lookup.get(cand_id, {})
        title = cand.get("title", "Unknown")[:60]
        dev_type = cand.get("development_type", "unknown")
        subject_org = cand.get("subject_org", "")
        
        print(f"\n  {i}. {title}")
        print(f"     Candidate ID: {cand_id}")
        print(f"     Development Type: {dev_type}")
        print(f"     Subject Org: {subject_org or '(unresolved)'}")
        print(f"     Total Score: {total_score}")
        
        # Component breakdown
        print(f"     Components:")
        for comp_name in ["primary_source", "corroboration", "domain_authority", "recency", "claim_traceability"]:
            comp = components.get(comp_name, {})
            score = comp.get("score", 0)
            max_score = comp.get("max", 0)
            reason = comp.get("reason", "")
            print(f"       - {comp_name:<25} {score:>3}/{max_score:<3} {reason}")
        
        # Warnings
        if warnings:
            print(f"     Warnings: {', '.join(warnings)}")
        
        # Rejection reasons
        if rejection_reasons:
            print(f"     Rejection Reasons: {', '.join(rejection_reasons)}")
        else:
            print(f"     Rejection Reasons: (none - admitted)")


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

    # ── Evidence retrieval (Stage 7C.7) ───────────────────────────────────
    evidence_config = load_evidence_retrieval_config()
    if evidence_config.enabled:
        print("\n  Retrieving evidence for top candidates (Stage 7C.7)...")
        evidence_by_day = {}
        total_evidence = 0
        for d in DATES:
            enriched_records = list(enriched_by_day[d])
            evidence_records = retrieve_evidence_for_candidates(enriched_records, evidence_config)
            evidence_by_day[d] = tuple(evidence_records)
            total_evidence += len(evidence_records)
        print(f"  Total candidates with evidence retrieval: {total_evidence}")
        print(f"  Config: max_candidates={evidence_config.max_candidates_per_run}, "
              f"max_urls={evidence_config.max_urls_per_candidate}, "
              f"timeout={evidence_config.timeout_seconds}s")

        print("  Running AFTER-EVIDENCE replay (enriched + evidence)...")
        after_evidence = run_replay(evidence_by_day, history)
        
        # ── Structured evidence extraction (Stage 7C.8) ─────────────────────
        extraction_config = load_extraction_config()
        if extraction_config.enabled:
            print("\n  Extracting structured evidence (Stage 7C.8)...")
            extraction_by_day = {}
            total_extraction = 0
            extraction_metrics = {
                "candidates_extracted": 0,
                "claims_accepted": 0,
                "claims_rejected": 0,
                "cache_hits": 0,
                "llm_calls": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "total_latency_ms": 0,
                "candidates_merged": 0,
            }
            for d in DATES:
                evidence_records = list(evidence_by_day[d])
                extraction_candidates, metrics = extract_structured_evidence(evidence_records, extraction_config)
                # Convert merged Candidate objects back to dicts for replay pipeline
                extraction_records = [c.to_dict() for c in extraction_candidates]
                extraction_by_day[d] = tuple(extraction_records)
                total_extraction += len(extraction_records)
                # Aggregate metrics
                for key in extraction_metrics:
                    if key in metrics:
                        extraction_metrics[key] += metrics[key]
            print(f"  Total candidates with extraction: {total_extraction}")
            print(f"  Extraction metrics:")
            print(f"    Candidates extracted: {extraction_metrics['candidates_extracted']}")
            print(f"    Candidates merged: {extraction_metrics['candidates_merged']}")
            print(f"    Claims accepted: {extraction_metrics['claims_accepted']}")
            print(f"    Claims rejected: {extraction_metrics['claims_rejected']}")
            print(f"    Cache hits: {extraction_metrics['cache_hits']}")
            print(f"    LLM calls: {extraction_metrics['llm_calls']}")
            print(f"    Total tokens: {extraction_metrics['total_tokens']}")
            print(f"    Total cost: ${extraction_metrics['total_cost_usd']:.4f}")
            print(f"    Total latency: {extraction_metrics['total_latency_ms']}ms")
            
            print("  Running AFTER-EXTRACTION replay (enriched + evidence + extraction)...")
            after_extraction = run_replay(extraction_by_day, history)
        else:
            print("\n  Structured extraction disabled (EDITORIAL_EVIDENCE_EXTRACTION_ENABLED=false)")
            after_extraction = after_evidence
    else:
        print("\n  Evidence retrieval disabled (EVIDENCE_RETRIEVAL_ENABLED=false)")
        after_evidence = after
        after_extraction = after

    # ── Comparison ─────────────────────────────────────────────────────────
    print_comparison(before, after)
    
    if evidence_config.enabled:
        print(f"\n{'='*78}")
        print("  EVIDENCE RETRIEVAL IMPACT (Stage 7C.7)")
        print("=" * 78)
        print_comparison(after, after_evidence)
        
        if extraction_config.enabled:
            print(f"\n{'='*78}")
            print("  STRUCTURED EXTRACTION IMPACT (Stage 7C.8)")
            print("=" * 78)
            print_comparison(after_evidence, after_extraction)
            
            # Report top 10 strongest candidates with full component breakdowns
            print_top_candidates(after_extraction, extraction_by_day, top_n=10)

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
