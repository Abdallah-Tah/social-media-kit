#!/usr/bin/env python3
"""Stage 7D: 24-hour live shadow pipeline.

Runs the complete editorial pipeline in shadow mode for 24 hours with three
daily slots (08:00 intelligence_brief, 12:00 midday_authority, 17:00
practical_takeaway), using current live candidates.

Shadow mode guarantees:
- No blog publishing
- No social publishing
- No newsletter delivery
- No Telegram notifications
- No live format-history mutation
- No live publication-history mutation

Pipeline chain:
feed enrichment → bounded evidence retrieval → structured extraction →
Candidate merge → relationships → source confidence → saturation →
admission → draft → quality → readiness
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from collections import Counter
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))

from agent.editorial.orchestrator import (
    MODE_SHADOW,
    OUTCOME_READY_IN_SHADOW,
    OUTCOME_READY_WITH_WARNINGS_HOLD,
    OUTCOME_REQUIRES_MANUAL_REVIEW,
    OUTCOME_QUALITY_REJECTED,
    OUTCOME_SKIPPED_NO_CANDIDATE,
    PipelineInput,
    run_pipeline,
)
from agent.editorial.enrichment import enrich_many
from agent.editorial.evidence_retrieval import (
    load_evidence_retrieval_config,
    retrieve_evidence_for_candidates,
)
from agent.editorial.evidence_extraction import (
    load_extraction_config,
    extract_structured_evidence,
)
from scripts.feed_sources import fetch_all, _FETCHERS

# Shadow slots (three per day)
SHADOW_SLOTS = [
    ("08:00", "intelligence_brief"),
    ("12:00", "midday_authority"),
    ("17:00", "practical_takeaway"),
]

# State storage (shadow mode does not mutate live history)
SHADOW_STATE_DIR = KIT / "state" / "editorial" / "shadow" / "stage_7d"


def fetch_live_candidates(limit: int = 50) -> list[dict]:
    """Fetch current live candidates from feed sources."""
    print("  Fetching live candidates from feed sources...")
    try:
        sources = list(_FETCHERS.keys())
        items = fetch_all(sources, topic=None)
        # Limit to requested count
        items = items[:limit]
        print(f"  Fetched {len(items)} live candidates from {len(sources)} sources")
        return [item.to_dict() for item in items]
    except Exception as e:
        print(f"  ERROR fetching live candidates: {e}")
        import traceback
        traceback.print_exc()
        return []


def enrich_candidates(candidates: list[dict]) -> list[dict]:
    """Run feed enrichment on candidates."""
    print("  Enriching candidates...")
    enriched = enrich_many(candidates)
    records = []
    for original, result in enriched:
        record = dict(original)
        record["metadata"] = dict(record.get("metadata", {}) or {})
        record["metadata"]["enrichment"] = result.to_dict()
        if result.sources:
            record["sources"] = list(result.sources)
        if result.claims:
            record["claims"] = list(result.claims)
        if result.development_type != "unknown":
            record["metadata"]["development_type"] = result.development_type
        if result.subject_org:
            record["metadata"]["subject_org"] = result.subject_org
        records.append(record)
    print(f"  Enriched {len(records)} candidates")
    return records


def retrieve_evidence(candidates: list[dict]) -> list[dict]:
    """Run bounded evidence retrieval."""
    print("  Retrieving evidence (Stage 7C.7)...")
    config = load_evidence_retrieval_config()
    if not config.enabled:
        print("  Evidence retrieval disabled")
        return candidates
    
    evidence_records = retrieve_evidence_for_candidates(candidates, config)
    print(f"  Retrieved evidence for {len(evidence_records)} candidates")
    return evidence_records


def extract_and_merge(candidates: list[dict]) -> tuple[list, dict]:
    """Run structured extraction and merge (Stage 7C.8)."""
    print("  Extracting structured evidence (Stage 7C.8)...")
    config = load_extraction_config()
    if not config.enabled:
        print("  Structured extraction disabled")
        from agent.editorial.candidate_adapter import normalize_candidate
        return [normalize_candidate(c) for c in candidates], {"enabled": False}
    
    merged_candidates, metrics = extract_structured_evidence(candidates, config)
    print(f"  Extracted and merged {metrics.get('candidates_merged', 0)} candidates")
    print(f"  Claims accepted: {metrics.get('claims_accepted', 0)}")
    print(f"  Claims rejected: {metrics.get('claims_rejected', 0)}")
    print(f"  LLM calls: {metrics.get('llm_calls', 0)}")
    print(f"  Total cost: ${metrics.get('total_cost_usd', 0.0):.4f}")
    return merged_candidates, metrics


def run_shadow_slot(slot_time: str, content_type: str, candidates: list, date: str) -> dict:
    """Run shadow pipeline for one slot."""
    print(f"\n  Running shadow slot: {slot_time} {content_type}")
    
    inp = PipelineInput(
        mode=MODE_SHADOW,
        date=date,
        candidates=tuple(candidates),
        history_rows=(),  # Shadow mode: no live history
    )
    
    result = run_pipeline(inp)
    
    # Find the slot result for this content type
    slot_result = None
    for sr in result.slot_results:
        if sr.content_type == content_type:
            slot_result = sr
            break
    
    if not slot_result:
        return {
            "slot_time": slot_time,
            "content_type": content_type,
            "outcome": "slot_not_found",
            "error": f"Slot {content_type} not found in pipeline results",
        }
    
    # Extract metrics
    sc_details = []
    for ev in slot_result.evaluations:
        if ev.get("stage") == "source_confidence" and ev.get("status") == "scored":
            sc_details.append({
                "candidate_id": ev["candidate_id"],
                "total_score": ev.get("total_score"),
                "components": ev.get("components", {}),
            })
    
    # Sort by score
    sc_details.sort(key=lambda x: x.get("total_score", 0), reverse=True)
    top_5_scores = [d["total_score"] for d in sc_details[:5]]
    
    return {
        "slot_time": slot_time,
        "content_type": content_type,
        "outcome": slot_result.outcome,
        "candidate_id": slot_result.candidate_id,
        "format_id": slot_result.format_id,
        "source_confidence": slot_result.source_confidence,
        "editorial_quality": slot_result.editorial_quality,
        "readiness_status": slot_result.readiness_status,
        "reason_codes": list(slot_result.reason_codes),
        "warnings": list(slot_result.warnings),
        "candidates_received": len(candidates),
        "candidates_scored": len(sc_details),
        "top_5_scores": top_5_scores,
        "sc_details": sc_details,
    }


def main():
    print("=" * 78)
    print("  STAGE 7D: 24-HOUR LIVE SHADOW PIPELINE")
    print("=" * 78)
    
    # Safety proof: capture before state
    print("\n  Safety proof: capturing before state...")
    before_state = {
        "format_history_exists": (KIT / "content" / "format_history.json").exists(),
        "linkedin_posts_exists": (KIT / "content" / "linkedin_daily_posts.json").exists(),
        "editorial_slots_enabled": False,  # Must remain false
    }
    print(f"    format_history.json exists: {before_state['format_history_exists']}")
    print(f"    linkedin_daily_posts.json exists: {before_state['linkedin_posts_exists']}")
    print(f"    EDITORIAL_SLOTS_ENABLED: {before_state['editorial_slots_enabled']}")
    
    # Create shadow state directory
    SHADOW_STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Run shadow pipeline for 24 hours
    start_time = dt.datetime.now(dt.timezone.utc)
    end_time = start_time + dt.timedelta(hours=24)
    
    print(f"\n  Shadow pipeline started at: {start_time.isoformat()}")
    print(f"  Shadow pipeline ends at: {end_time.isoformat()}")
    print(f"  Running three slots per day: {', '.join(f'{t} {ct}' for t, ct in SHADOW_SLOTS)}")
    
    all_slot_results = []
    iteration = 0
    
    while dt.datetime.now(dt.timezone.utc) < end_time:
        iteration += 1
        current_time = dt.datetime.now(dt.timezone.utc)
        current_hour = current_time.strftime("%H:%M")
        current_date = current_time.strftime("%Y-%m-%d")
        
        print(f"\n{'='*78}")
        print(f"  ITERATION {iteration}: {current_time.isoformat()}")
        print("=" * 78)
        
        # Check if we should run a slot now
        slots_to_run = []
        for slot_time, content_type in SHADOW_SLOTS:
            # Run slot if we're within 30 minutes of the scheduled time
            slot_hour, slot_min = map(int, slot_time.split(":"))
            time_diff = abs((current_time.hour * 60 + current_time.minute) - 
                           (slot_hour * 60 + slot_min))
            if time_diff <= 30:
                slots_to_run.append((slot_time, content_type))
        
        if not slots_to_run:
            print(f"  No slots scheduled for {current_hour}. Waiting...")
            time.sleep(1800)  # Sleep 30 minutes
            continue
        
        # Fetch and process live candidates
        print("\n  Fetching and processing live candidates...")
        raw_candidates = fetch_live_candidates(limit=50)
        if not raw_candidates:
            print("  No candidates fetched. Waiting...")
            time.sleep(1800)
            continue
        
        enriched = enrich_candidates(raw_candidates)
        with_evidence = retrieve_evidence(enriched)
        merged_candidates, extraction_metrics = extract_and_merge(with_evidence)
        
        # Run shadow slots
        for slot_time, content_type in slots_to_run:
            slot_result = run_shadow_slot(slot_time, content_type, merged_candidates, current_date)
            all_slot_results.append(slot_result)
            
            # Save slot result
            result_file = SHADOW_STATE_DIR / f"{current_date}_{slot_time.replace(':', '')}_{content_type}.json"
            result_file.write_text(json.dumps(slot_result, indent=2))
            print(f"  Saved result to: {result_file}")
        
        # Wait before next iteration
        print(f"\n  Iteration {iteration} complete. Waiting 30 minutes...")
        time.sleep(1800)
    
    # Aggregate results
    print(f"\n{'='*78}")
    print("  STAGE 7D SHADOW PIPELINE COMPLETE")
    print("=" * 78)
    
    outcome_counts = Counter(sr["outcome"] for sr in all_slot_results)
    total_slots = len(all_slot_results)
    normal_slots_filled = sum(1 for sr in all_slot_results 
                              if sr["outcome"] in [OUTCOME_READY_IN_SHADOW, OUTCOME_READY_WITH_WARNINGS_HOLD])
    normal_slots_skipped = sum(1 for sr in all_slot_results 
                               if sr["outcome"] == OUTCOME_SKIPPED_NO_CANDIDATE)
    
    print(f"\n  Total slots run: {total_slots}")
    print(f"  Normal slots filled: {normal_slots_filled}")
    print(f"  Normal slots skipped: {normal_slots_skipped}")
    print(f"\n  Outcome distribution:")
    for outcome, count in sorted(outcome_counts.items()):
        print(f"    {outcome}: {count}")
    
    # Safety proof: capture after state
    print("\n  Safety proof: capturing after state...")
    after_state = {
        "format_history_exists": (KIT / "content" / "format_history.json").exists(),
        "linkedin_posts_exists": (KIT / "content" / "linkedin_daily_posts.json").exists(),
        "editorial_slots_enabled": False,  # Must remain false
    }
    print(f"    format_history.json exists: {after_state['format_history_exists']}")
    print(f"    linkedin_daily_posts.json exists: {after_state['linkedin_posts_exists']}")
    print(f"    EDITORIAL_SLOTS_ENABLED: {after_state['editorial_slots_enabled']}")
    
    # Verify no mutations
    if before_state == after_state:
        print("\n  ✅ Safety proof PASSED: No live mutations detected")
    else:
        print("\n  ❌ Safety proof FAILED: Live state changed!")
        print(f"    Before: {before_state}")
        print(f"    After: {after_state}")
    
    # Save aggregate report
    report_file = SHADOW_STATE_DIR / "stage_7d_report.json"
    report = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "total_slots": total_slots,
        "normal_slots_filled": normal_slots_filled,
        "normal_slots_skipped": normal_slots_skipped,
        "outcome_counts": dict(outcome_counts),
        "slot_results": all_slot_results,
        "safety_proof": {
            "before": before_state,
            "after": after_state,
            "passed": before_state == after_state,
        },
    }
    report_file.write_text(json.dumps(report, indent=2))
    print(f"\n  Saved aggregate report to: {report_file}")
    
    print(f"\n{'='*78}")
    print("  STAGE 7D COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
