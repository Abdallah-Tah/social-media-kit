#!/usr/bin/env python3
"""Stage 7D targeted shadow validation.

Runs each normal slot (intelligence_brief, midday_authority, practical_takeaway)
once in shadow mode against current candidates, after the Stage 7C.8 corrections
(clean article-text extraction + combined opportunity/confidence evaluation pool).

Shadow mode only: never publishes, never notifies, never writes live history.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))

# Bound the extraction for this validation run.
os.environ.setdefault("EDITORIAL_EVIDENCE_EXTRACTION_MAX_CANDIDATES_PER_RUN", "12")

import stage_7d_shadow as s7d  # noqa: E402
from agent.editorial.orchestrator import MODE_SHADOW, PipelineInput, run_pipeline  # noqa: E402

VALIDATION_DATE = "2026-07-30"  # a Thursday
NORMAL_SLOTS = ("intelligence_brief", "midday_authority", "practical_takeaway")
REPORT_PATH = KIT / "state" / "editorial" / "shadow" / "validation_report.json"


def _slot_summary(sr) -> dict:
    admission_evs = [e for e in sr.evaluations if e.get("stage") == "admission"]
    sc_evs = [e for e in sr.evaluations
              if e.get("stage") == "source_confidence" and e.get("status") == "scored"]
    evaluated = [{
        "candidate_id": e.get("candidate_id"),
        "status": e.get("status"),
        "opportunity_score": e.get("opportunity_score"),
        "source_confidence": e.get("source_confidence"),
        "rejection_reasons": e.get("rejection_reasons", []),
    } for e in admission_evs]
    top_opp = sorted(evaluated, key=lambda x: (-(x.get("opportunity_score") or 0)))[:5]
    top_conf = sorted(evaluated, key=lambda x: (-(x.get("source_confidence") or 0)))[:5]
    sc_scores = sorted([e.get("total_score") for e in sc_evs if e.get("total_score") is not None],
                       reverse=True)
    return {
        "slot_id": sr.slot_id,
        "content_type": sr.content_type,
        "outcome": sr.outcome,
        "selected_candidate_id": sr.candidate_id or None,
        "selected_source_confidence": sr.source_confidence,
        "editorial_quality": sr.editorial_quality,
        "readiness_status": sr.readiness_status or None,
        "slot_reason_codes": list(sr.reason_codes or ()),
        "draft_generated": bool(sr.artifact),
        "draft_title": sr.draft_title or None,
        "candidates_evaluated": len(evaluated),
        "source_confidence_scores": sc_scores,
        "top_by_opportunity": top_opp,
        "top_by_confidence": top_conf,
        "evaluated_candidates": evaluated,
    }


def main() -> None:
    print("=== Stage 7D targeted shadow validation ===", flush=True)
    print(f"Validation date: {VALIDATION_DATE} (Thursday)", flush=True)

    print("\n[1] Processing current candidates (fetch -> retrieve -> clean -> extract)...", flush=True)
    merged, batch = s7d.process_candidates(limit=20)
    print(f"  received={batch.get('candidates_received')} "
          f"enriched={batch.get('candidates_enriched')} merged={batch.get('candidates_merged')}", flush=True)
    print(f"  evidence: urls_fetched={batch.get('urls_fetched')} "
          f"failures={batch.get('evidence_fetch_failures')}", flush=True)
    print(f"  extraction: claims+={batch.get('extraction_claims_accepted')} "
          f"claims-={batch.get('extraction_claims_rejected')} "
          f"llm_calls={batch.get('extraction_llm_calls')} "
          f"cache_hits={batch.get('extraction_cache_hits')} "
          f"cost=${batch.get('extraction_cost_usd')}", flush=True)

    cleaning_path = KIT / "content" / "feed" / "evidence_cleaning.json"
    cleaning = json.loads(cleaning_path.read_text()) if cleaning_path.exists() else []
    cleaning_summary: dict = {}
    if cleaning:
        usable = sum(1 for d in cleaning if d.get("usable_text"))
        methods: dict = {}
        for d in cleaning:
            methods[d.get("extraction_method", "?")] = methods.get(d.get("extraction_method", "?"), 0) + 1
        cleaning_summary = {
            "sources": len(cleaning),
            "usable": usable,
            "success_rate": round(usable / len(cleaning), 3),
            "avg_raw_chars": int(sum(d.get("raw_content_chars", 0) for d in cleaning) / len(cleaning)),
            "avg_clean_chars": int(sum(d.get("clean_content_chars", 0) for d in cleaning) / len(cleaning)),
            "avg_boilerplate_ratio": round(sum(d.get("boilerplate_ratio", 0) for d in cleaning) / len(cleaning), 3),
            "methods": methods,
        }
        print(f"  cleaning: {usable}/{len(cleaning)} usable ({cleaning_summary['success_rate']}), "
              f"avg raw={cleaning_summary['avg_raw_chars']} clean={cleaning_summary['avg_clean_chars']} "
              f"boilerplate={cleaning_summary['avg_boilerplate_ratio']}", flush=True)
        print(f"  cleaning methods: {methods}", flush=True)

    print(f"\n[2] Running shadow pipeline for {VALIDATION_DATE}...", flush=True)
    inp = PipelineInput(mode=MODE_SHADOW, date=VALIDATION_DATE,
                        candidates=tuple(merged), history_rows=())
    result = run_pipeline(inp)
    if result.config_errors:
        print(f"  config_errors: {result.config_errors}", flush=True)

    slot_summaries = {}
    for sr in result.slot_results:
        if sr.slot_id in NORMAL_SLOTS:
            s = _slot_summary(sr)
            slot_summaries[sr.slot_id] = s
            print(f"\n  {sr.slot_id} ({sr.content_type}): outcome={s['outcome']} "
                  f"selected={s['selected_candidate_id']} quality={s['editorial_quality']} "
                  f"readiness={s['readiness_status']} evaluated={s['candidates_evaluated']} "
                  f"draft={s['draft_generated']}", flush=True)
            print(f"    SC scores: {s['source_confidence_scores'][:10]}", flush=True)
            print(f"    top by opportunity: "
                  f"{[(e['candidate_id'][:16], e['opportunity_score']) for e in s['top_by_opportunity']]}", flush=True)
            print(f"    top by confidence: "
                  f"{[(e['candidate_id'][:16], e['source_confidence']) for e in s['top_by_confidence']]}", flush=True)
            for e in s["evaluated_candidates"][:10]:
                print(f"      {e['candidate_id'][:16]} opp={e['opportunity_score']} "
                      f"sc={e['source_confidence']} status={e['status']} "
                      f"reasons={e['rejection_reasons']}", flush=True)

    report = {
        "validation_date": VALIDATION_DATE,
        "batch": batch,
        "cleaning": cleaning_summary,
        "slots": slot_summaries,
        "total_api_cost_usd": batch.get("extraction_cost_usd", 0.0),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {REPORT_PATH}", flush=True)
    print("=== validation complete ===", flush=True)


if __name__ == "__main__":
    main()
