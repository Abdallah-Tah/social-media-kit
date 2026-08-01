#!/usr/bin/env python3
"""Stage 7D: 24-hour live shadow pipeline.

Runs the complete editorial pipeline in shadow mode for at least 24 hours with
three daily slots (08:00 intelligence_brief, 12:00 midday_authority,
17:00 practical_takeaway), using current live candidates. The run extends until
all three slot types have executed at least once (capped at 48h for safety).

Shadow mode guarantees (architectural, from orchestrator MODE_SHADOW):
- No blog publishing
- No social publishing
- No newsletter delivery
- No Telegram notifications
- No live format-history mutation
- No live publication-history mutation
- EDITORIAL_SLOTS_ENABLED forced false

The shadow process writes ONLY to:
- state/editorial/shadow/stage_7d/   (its own results)
- content/feed/*_cache.json          (enrichment/evidence caches)
- content/llm_usage.jsonl            (LLM cost ledger — extraction calls)

It never opens a live publication/notification record for writing.

Pipeline chain:
feed enrichment -> bounded evidence retrieval -> structured extraction ->
Candidate merge -> relationships -> source confidence -> saturation ->
admission -> draft -> quality -> readiness
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))

# Load the protected SMKit environment (config/secrets.env) the canonical way.
# Real env vars take precedence; secrets are never placed in the service file.
from agent.config import load_env  # noqa: E402

load_env()

# This is the explicit manual shadow run, so evidence retrieval/extraction are
# enabled here unless explicitly overridden (they default to off everywhere else
# to avoid paid calls outside intentional shadow runs).
os.environ.setdefault("EDITORIAL_EVIDENCE_RETRIEVAL_ENABLED", "true")
os.environ.setdefault("EDITORIAL_EVIDENCE_EXTRACTION_ENABLED", "true")

from agent.editorial.flags import (  # noqa: E402
    editorial_slots_enabled,
    editorial_zoneinfo,
    editorial_timezone,
)
from agent.editorial.orchestrator import (  # noqa: E402
    MODE_SHADOW,
    OUTCOME_READY_IN_SHADOW,
    OUTCOME_READY_WITH_WARNINGS_HOLD,
    OUTCOME_REQUIRES_MANUAL_REVIEW,
    OUTCOME_QUALITY_REJECTED,
    OUTCOME_SKIPPED_NO_CANDIDATE,
    PipelineInput,
    run_pipeline,
)
from agent.editorial.enrichment import enrich_many  # noqa: E402
from agent.editorial.evidence_retrieval import (  # noqa: E402
    load_evidence_retrieval_config,
    retrieve_evidence_for_candidates,
)
from agent.editorial.evidence_extraction import (  # noqa: E402
    load_extraction_config,
    extract_structured_evidence,
)
from scripts.feed_sources import fetch_all, _FETCHERS  # noqa: E402

# Shadow slots (three per day), scheduled in the editorial timezone.
SHADOW_SLOTS = [
    ("08:00", "intelligence_brief"),
    ("12:00", "midday_authority"),
    ("17:00", "practical_takeaway"),
]

# Shadow state (the ONLY directory this process writes results to).
SHADOW_STATE_DIR = KIT / "state" / "editorial" / "shadow" / "stage_7d"

# Live records that the shadow pipeline must NEVER mutate. Fingerprinted
# before/after to prove the shadow process left them untouched. (The concurrent
# production cron may legitimately change some of these; the report attributes
# any such change to the cron, not the shadow — see safety proof.)
SAFETY_FILES = {
    "blog_publication": KIT / "content" / "published.json",
    "social_linkedin": KIT / "content" / "linkedin_daily_posts.json",
    "social_daily_slate": KIT / "content" / "daily_slate_posted.json",
    "social_match_shorts": KIT / "content" / "match_shorts_posted.json",
    "social_prediction_shorts": KIT / "content" / "prediction_shorts_posted.json",
    "social_video_posts": KIT / "content" / "video_posts.json",
    "social_recap_posts": KIT / "content" / "recap_posts.json",
    "live_format_history": KIT / "content" / "format_history.json",
    "content_decisions": KIT / "content" / "content_decisions.jsonl",
    "newsletter_pitch_drafts": KIT / "content" / "pitch_post_drafts.json",
    "news_cron_log": Path.home() / "logs" / "smkit-news.log",
    "publish_cron_log": Path.home() / "logs" / "smkit-cron.log",
}


# ── Safety fingerprinting ────────────────────────────────────────────────────

def _file_fingerprint(path: Path) -> dict:
    """Size + mtime + sha256 (first 1MB) for a file, or 'absent'."""
    if not path.exists():
        return {"exists": False}
    try:
        stat = path.stat()
        h = hashlib.sha256()
        with path.open("rb") as fh:
            h.update(fh.read(1_000_000))
        return {
            "exists": True,
            "size": stat.st_size,
            "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
            "sha256_1mb": h.hexdigest()[:16],
        }
    except OSError as e:
        return {"exists": True, "error": str(e)}


def capture_safety_state() -> dict:
    """Fingerprint live records, cron, and the feature flag."""
    files = {label: _file_fingerprint(p) for label, p in SAFETY_FILES.items()}
    try:
        crontab = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=10,
        ).stdout
        cron_hash = hashlib.sha256(crontab.encode()).hexdigest()[:16]
        cron_lines = len([l for l in crontab.splitlines() if l.strip() and not l.strip().startswith("#")])
    except Exception as e:  # noqa: BLE001
        cron_hash, cron_lines = f"error:{e}", -1
    return {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": files,
        "cron_hash": cron_hash,
        "cron_lines": cron_lines,
        "editorial_slots_enabled": editorial_slots_enabled(),
        "editorial_timezone": editorial_timezone(),
    }


def diff_safety_state(before: dict, after: dict) -> dict:
    """Compare before/after fingerprints; classify each change."""
    changes = {}
    for label in SAFETY_FILES:
        b = before["files"].get(label, {})
        a = after["files"].get(label, {})
        if b != a:
            changes[label] = {"before": b, "after": a}
    return {
        "file_changes": changes,
        "cron_changed": before["cron_hash"] != after["cron_hash"],
        "flag_changed": before["editorial_slots_enabled"] != after["editorial_slots_enabled"],
        "flag_before": before["editorial_slots_enabled"],
        "flag_after": after["editorial_slots_enabled"],
    }


# ── Candidate processing (with metrics) ──────────────────────────────────────

def fetch_live_candidates(limit: int = 50) -> list[dict]:
    """Fetch current live candidates from all configured feed sources."""
    sources = list(_FETCHERS.keys())
    items = fetch_all(sources, topic=None)
    items = items[:limit]
    return [item.to_dict() for item in items]


def enrich_candidates(candidates: list[dict]) -> list[dict]:
    """Run deterministic feed enrichment."""
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
    return records


def retrieve_evidence(candidates: list[dict]) -> tuple[list[dict], dict]:
    """Run bounded evidence retrieval; return records + fetch metrics."""
    config = load_evidence_retrieval_config()
    if not config.enabled:
        return candidates, {"enabled": False, "urls_fetched": 0, "fetch_failures": 0}
    records = retrieve_evidence_for_candidates(candidates, config)
    urls_fetched = 0
    fetch_failures = 0
    for r in records:
        for ev in r.get("metadata", {}).get("fetched_evidence", []):
            urls_fetched += 1
            if ev.get("error") or ev.get("status", 0) != 200:
                fetch_failures += 1
    return records, {
        "enabled": True,
        "urls_fetched": urls_fetched,
        "fetch_failures": fetch_failures,
    }


def extract_and_merge(candidates: list[dict]) -> tuple[list, dict]:
    """Run structured extraction + Candidate merge; return candidates + metrics."""
    config = load_extraction_config()
    if not config.enabled:
        from agent.editorial.candidate_adapter import normalize_candidate
        merged = []
        for c in candidates:
            try:
                merged.append(normalize_candidate(c))
            except Exception:  # noqa: BLE001
                pass
        return merged, {"enabled": False}
    return extract_structured_evidence(candidates, config)


def process_candidates(limit: int = 50) -> tuple[list, dict]:
    """Full candidate-processing chain; returns (merged_candidates, batch_metrics)."""
    batch: dict = {}
    t0 = time.monotonic()

    raw = fetch_live_candidates(limit=limit)
    batch["candidates_received"] = len(raw)
    if not raw:
        return [], batch

    enriched = enrich_candidates(raw)
    batch["candidates_enriched"] = len(enriched)

    with_evidence, ev_metrics = retrieve_evidence(enriched)
    batch["urls_fetched"] = ev_metrics.get("urls_fetched", 0)
    batch["evidence_fetch_failures"] = ev_metrics.get("fetch_failures", 0)

    merged, ex_metrics = extract_and_merge(with_evidence)
    batch["candidates_merged"] = ex_metrics.get("candidates_merged", 0)
    batch["extraction_claims_accepted"] = ex_metrics.get("claims_accepted", 0)
    batch["extraction_claims_rejected"] = ex_metrics.get("claims_rejected", 0)
    batch["extraction_llm_calls"] = ex_metrics.get("llm_calls", 0)
    batch["extraction_cost_usd"] = ex_metrics.get("total_cost_usd", 0.0)
    batch["extraction_cache_hits"] = ex_metrics.get("cache_hits", 0)
    batch["processing_latency_ms"] = int((time.monotonic() - t0) * 1000)
    return merged, batch


# ── Shadow slot execution ────────────────────────────────────────────────────

# Slot-level watchdog: a single slot must not block the whole run indefinitely.
# The pipeline is deterministic, but a hung draft/LLM call must not stall the
# 24h run. SIGALRM interrupts the single-threaded slot execution cleanly.
SLOT_TIMEOUT_SECONDS = int(os.environ.get("STAGE7D_SLOT_TIMEOUT_SECONDS", "900"))


class SlotTimeout(Exception):
    pass


def _on_slot_timeout(signum, frame):
    raise SlotTimeout()


def _persist_slot_result(report: dict, date: str, slot_time: str, slot_id: str) -> None:
    """Write the per-slot result file — always, even for not-found/timed-out, so
    the dashboard never shows a slot as perpetually 'running' for lack of a file."""
    SHADOW_STATE_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{date}_{slot_time.replace(':', '')}_{slot_id}.json"
    result_path = SHADOW_STATE_DIR / fname
    try:
        result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["result_path"] = str(result_path)
    except OSError as e:
        report["result_path"] = f"write_error:{e}"


def run_shadow_slot(slot_time: str, slot_id: str, candidates: list,
                    date: str, batch: dict) -> dict:
    """Run the shadow pipeline for one slot and capture full metrics.

    ``slot_id`` is the slot identifier from SHADOW_SLOTS (e.g. midday_authority).
    The pipeline resolves each slot to a concrete content type per weekday, so the
    result is matched by ``slot_id`` (not by content type).
    """
    print(f"\n  ── Shadow slot {slot_time} {slot_id} ({date}) ──")
    t0 = time.monotonic()

    inp = PipelineInput(
        mode=MODE_SHADOW,
        date=date,
        candidates=tuple(candidates),
        history_rows=(),  # Shadow: no live history read or written
    )
    result = run_pipeline(inp)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Match by slot_id: the pipeline's content_type varies per weekday, so matching
    # by content_type fails for slots like midday_authority (root-cause fix).
    slot_result = next(
        (sr for sr in result.slot_results if sr.slot_id == slot_id),
        None,
    )
    if slot_result is None:
        report = {
            "slot_time": slot_time, "content_type": slot_id, "date": date,
            "outcome": "slot_not_found", "latency_ms": latency_ms, **batch,
            "error": f"Slot {slot_id} not found in pipeline results",
            "result_path": "",
        }
        _persist_slot_result(report, date, slot_time, slot_id)
        print(f"     outcome=slot_not_found (no pipeline result for slot_id={slot_id})")
        print(f"     persisted={report['result_path']}")
        return report

    # Source-confidence details for every scored candidate in this slot.
    sc_details = []
    for ev in slot_result.evaluations:
        if ev.get("stage") == "source_confidence" and ev.get("status") == "scored":
            sc_details.append({
                "candidate_id": ev["candidate_id"],
                "total_score": ev.get("total_score"),
                "components": ev.get("components", {}),
                "warnings": ev.get("warnings", []),
            })
    sc_details.sort(key=lambda x: x.get("total_score") or 0, reverse=True)
    top_5 = [d["total_score"] for d in sc_details[:5]]

    # Admission reason codes (from admission evaluations).
    admission_reasons: list[str] = []
    admission_status = ""
    for ev in slot_result.evaluations:
        if ev.get("stage") == "admission":
            admission_status = ev.get("status", "")
            admission_reasons.extend(ev.get("rejection_reasons", []))

    report = {
        "slot_time": slot_time,
        "content_type": slot_id,
        "resolved_content_type": slot_result.content_type,
        "date": date,
        "outcome": slot_result.outcome,
        "selected_candidate_id": slot_result.candidate_id,
        "selected_format": slot_result.format_id,
        "source_confidence": slot_result.source_confidence,
        "editorial_quality": slot_result.editorial_quality,
        "readiness_status": slot_result.readiness_status,
        "reason_codes": list(slot_result.reason_codes),
        "admission_status": admission_status,
        "admission_reasons": admission_reasons,
        "warnings": list(slot_result.warnings),
        "candidates_scored": len(sc_details),
        "top_5_scores": top_5,
        "sc_details": sc_details[:10],
        "pipeline_latency_ms": latency_ms,
        "result_path": "",
        **batch,
    }

    # Persist per-slot result.
    _persist_slot_result(report, date, slot_time, slot_id)

    # Console summary.
    print(f"     outcome={slot_result.outcome} sc={slot_result.source_confidence} "
          f"eq={slot_result.editorial_quality} readiness={slot_result.readiness_status or '-'}")
    print(f"     scored={len(sc_details)} top5={top_5} format={slot_result.format_id or '-'}")
    print(f"     received={batch.get('candidates_received')} "
          f"enriched={batch.get('candidates_enriched')} "
          f"urls={batch.get('urls_fetched')} "
          f"fetch_fail={batch.get('evidence_fetch_failures')}")
    print(f"     claims+={batch.get('extraction_claims_accepted')} "
          f"claims-={batch.get('extraction_claims_rejected')} "
          f"cost=${batch.get('extraction_cost_usd', 0.0):.4f} "
          f"latency={latency_ms}ms")
    if admission_reasons:
        print(f"     admission_reasons={admission_reasons}")
    print(f"     persisted={report['result_path']}")
    return report


def _run_slot_with_timeout(slot_time: str, slot_id: str, candidates: list,
                           date: str, batch: dict, timeout: int) -> dict:
    """Run one slot under a SIGALRM watchdog so a single slot cannot stall the run.

    On timeout (or error) write a result file recording the stage and partial
    batch metrics, then return so the run continues safely toward final
    reporting. Never publishes or notifies; never corrupts existing results.
    """
    signal.signal(signal.SIGALRM, _on_slot_timeout)
    signal.alarm(timeout)
    try:
        return run_shadow_slot(slot_time, slot_id, candidates, date, batch)
    except SlotTimeout:
        print(f"  ⚠️  Slot {slot_id} exceeded {timeout}s watchdog; marking timed_out.")
        report = {
            "slot_time": slot_time, "content_type": slot_id, "date": date,
            "outcome": "timed_out",
            "error": f"slot exceeded {timeout}s watchdog (STAGE7D_SLOT_TIMEOUT_SECONDS)",
            "pipeline_latency_ms": timeout * 1000,
            "result_path": "",
            **batch,
        }
        _persist_slot_result(report, date, slot_time, slot_id)
        return report
    except Exception as e:  # noqa: BLE001 — keep the run alive
        import traceback
        print(f"  ERROR in slot {slot_id}: {e}")
        traceback.print_exc()
        report = {
            "slot_time": slot_time, "content_type": slot_id, "date": date,
            "outcome": "slot_error", "error": str(e), "result_path": "", **batch,
        }
        _persist_slot_result(report, date, slot_time, slot_id)
        return report
    finally:
        signal.alarm(0)  # always cancel the alarm


def _write_progress(phase: str, active_slot: str | None = None,
                    iteration: int = 0, extra: dict | None = None) -> None:
    """Write a progress heartbeat the dashboard reads to detect stalls.

    Updated each iteration and around slot execution so the dashboard can show
    the current phase, the last-progress timestamp, and a stalled warning when
    nothing has progressed for a while. Best-effort; never raises.
    """
    progress = {
        "phase": phase,
        "active_slot": active_slot,
        "iteration": iteration,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "slot_timeout_seconds": SLOT_TIMEOUT_SECONDS,
    }
    if extra:
        progress.update(extra)
    try:
        SHADOW_STATE_DIR.mkdir(parents=True, exist_ok=True)
        (SHADOW_STATE_DIR / "progress.json").write_text(
            json.dumps(progress, indent=2), encoding="utf-8")
    except OSError:
        pass


# ── Scheduling helpers ───────────────────────────────────────────────────────

def _slot_minutes(slot_time: str) -> int:
    h, m = map(int, slot_time.split(":"))
    return h * 60 + m


def _next_slot_info(now_local: dt.datetime) -> str:
    """Human-readable next scheduled slot from now (editorial local time)."""
    now_min = now_local.hour * 60 + now_local.minute
    best = None
    for slot_time, content_type in SHADOW_SLOTS:
        sm = _slot_minutes(slot_time)
        delta = sm - now_min
        if delta < 0:
            delta += 24 * 60  # next day
        if best is None or delta < best[0]:
            best = (delta, slot_time, content_type)
    if best is None:
        return "none"
    delta, slot_time, content_type = best
    return f"{slot_time} {content_type} (in {delta} min)"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 78)
    print("  STAGE 7D: 24-HOUR LIVE SHADOW PIPELINE")
    print("=" * 78)

    # ── Safety interlock: force slots off, assert shadow ───────────────────
    os.environ["EDITORIAL_SLOTS_ENABLED"] = "false"
    os.environ.setdefault("EDITORIAL_SHADOW_MODE", "true")
    if editorial_slots_enabled():
        print("  FATAL: EDITORIAL_SLOTS_ENABLED resolved true; refusing to run.")
        return 2
    print(f"  EDITORIAL_SLOTS_ENABLED = {editorial_slots_enabled()} (forced false)")
    print(f"  EDITORIAL_SHADOW_MODE   = {os.environ.get('EDITORIAL_SHADOW_MODE')}")
    print(f"  Editorial timezone      = {editorial_timezone()}")
    tz = editorial_zoneinfo()

    SHADOW_STATE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Safety before-state ────────────────────────────────────────────────
    print("\n  Capturing safety before-state...")
    before_state = capture_safety_state()
    (SHADOW_STATE_DIR / "safety_before.json").write_text(
        json.dumps(before_state, indent=2), encoding="utf-8")
    print(f"    cron_hash={before_state['cron_hash']} cron_lines={before_state['cron_lines']}")
    print(f"    slots_enabled={before_state['editorial_slots_enabled']}")

    # ── Timing ─────────────────────────────────────────────────────────────
    start_utc = dt.datetime.now(dt.timezone.utc)
    min_end_utc = start_utc + dt.timedelta(hours=24)
    max_end_utc = start_utc + dt.timedelta(hours=48)  # safety cap
    start_local = start_utc.astimezone(tz)

    print(f"\n  Actual start time      : {start_local.isoformat()}")
    print(f"  Planned completion     : {min_end_utc.astimezone(tz).isoformat()} (>=24h)")
    print(f"  Safety cap             : {max_end_utc.astimezone(tz).isoformat()} (48h)")
    print(f"  Next scheduled slot    : {_next_slot_info(start_local)}")
    print(f"  Slots                  : {', '.join(f'{t} {ct}' for t, ct in SHADOW_SLOTS)}")

    timing = {
        "actual_start": start_local.isoformat(),
        "planned_completion": min_end_utc.astimezone(tz).isoformat(),
        "safety_cap": max_end_utc.astimezone(tz).isoformat(),
        "next_slot_at_start": _next_slot_info(start_local),
    }
    (SHADOW_STATE_DIR / "timing.json").write_text(json.dumps(timing, indent=2), encoding="utf-8")

    executed_slots: set[tuple[str, str]] = set()   # (local_date, slot_time)
    executed_types: set[str] = set()               # content_type
    all_slot_results: list[dict] = []
    iteration = 0
    total_api_cost = 0.0

    while True:
        now_utc = dt.datetime.now(dt.timezone.utc)
        now_local = now_utc.astimezone(tz)
        local_date = now_local.strftime("%Y-%m-%d")
        local_min = now_local.hour * 60 + now_local.minute
        iteration += 1
        _write_progress("checking_schedule", iteration=iteration)

        # ── Completion check ───────────────────────────────────────────────
        elapsed = now_utc - start_utc
        all_types_done = len(executed_types) >= len(SHADOW_SLOTS)
        if elapsed >= dt.timedelta(hours=24) and all_types_done:
            print(f"\n  Completion reached: elapsed={elapsed} and all "
                  f"{len(SHADOW_SLOTS)} slot types executed.")
            break
        if now_utc >= max_end_utc:
            print(f"\n  Safety cap reached ({elapsed}); stopping. "
                  f"types_executed={sorted(executed_types)}")
            break

        # ── Which slots are in window and not yet run today? ───────────────
        slots_to_run = []
        for slot_time, slot_id in SHADOW_SLOTS:
            if abs(local_min - _slot_minutes(slot_time)) <= 30:
                if (local_date, slot_time) not in executed_slots:
                    slots_to_run.append((slot_time, slot_id))

        if not slots_to_run:
            # Sleep, but not past the next window or completion point.
            _write_progress("idle", iteration=iteration)
            time.sleep(300)
            continue

        print(f"\n{'='*78}")
        print(f"  ITERATION {iteration}: {now_local.isoformat()} | "
              f"slots={[(t, ct) for t, ct in slots_to_run]}")
        print("=" * 78)

        # Process the live candidate batch once for this iteration.
        _write_progress("fetching_candidates", iteration=iteration)
        try:
            merged, batch = process_candidates(limit=50)
        except Exception as e:  # noqa: BLE001 — keep the run alive
            import traceback
            print(f"  ERROR processing candidates: {e}")
            traceback.print_exc()
            batch = {"error": str(e)}
            merged = []

        total_api_cost += batch.get("extraction_cost_usd", 0.0)

        for slot_time, slot_id in slots_to_run:
            _write_progress("running_slot", active_slot=slot_id, iteration=iteration)
            report = _run_slot_with_timeout(slot_time, slot_id, merged, local_date, batch,
                                            SLOT_TIMEOUT_SECONDS)
            executed_slots.add((local_date, slot_time))
            executed_types.add(slot_id)
            all_slot_results.append(report)

        print(f"\n  Executed types so far: {sorted(executed_types)} "
              f"({len(executed_types)}/{len(SHADOW_SLOTS)})")
        time.sleep(300)

    # ── Safety after-state ─────────────────────────────────────────────────
    end_utc = dt.datetime.now(dt.timezone.utc)
    print("\n  Capturing safety after-state...")
    after_state = capture_safety_state()
    (SHADOW_STATE_DIR / "safety_after.json").write_text(
        json.dumps(after_state, indent=2), encoding="utf-8")
    safety_diff = diff_safety_state(before_state, after_state)
    (SHADOW_STATE_DIR / "safety_diff.json").write_text(
        json.dumps(safety_diff, indent=2), encoding="utf-8")

    # ── Aggregate report ───────────────────────────────────────────────────
    outcome_counts = Counter(r["outcome"] for r in all_slot_results)
    rejection_counts = Counter()
    sc_all = []
    for r in all_slot_results:
        for reason in r.get("admission_reasons", []) + r.get("reason_codes", []):
            rejection_counts[reason] += 1
        for d in r.get("sc_details", []):
            if d.get("total_score") is not None:
                sc_all.append(d["total_score"])

    aggregate = {
        "timing": timing,
        "actual_end": end_utc.astimezone(tz).isoformat(),
        "elapsed_hours": round((end_utc - start_utc).total_seconds() / 3600, 2),
        "iterations": iteration,
        "slots_executed": len(all_slot_results),
        "slot_types_executed": sorted(executed_types),
        "outcome_counts": dict(outcome_counts),
        "ready_in_shadow": outcome_counts.get(OUTCOME_READY_IN_SHADOW, 0),
        "ready_with_warnings_hold": outcome_counts.get(OUTCOME_READY_WITH_WARNINGS_HOLD, 0),
        "requires_manual_review": outcome_counts.get(OUTCOME_REQUIRES_MANUAL_REVIEW, 0),
        "quality_rejected": outcome_counts.get(OUTCOME_QUALITY_REJECTED, 0),
        "skipped_no_candidate": outcome_counts.get(OUTCOME_SKIPPED_NO_CANDIDATE, 0),
        "rejection_reasons": dict(rejection_counts),
        "sc_distribution": {
            "count": len(sc_all),
            "min": min(sc_all) if sc_all else None,
            "max": max(sc_all) if sc_all else None,
            "avg": round(sum(sc_all) / len(sc_all), 1) if sc_all else None,
        },
        "total_api_cost_usd": round(total_api_cost, 4),
        "slot_results": all_slot_results,
        "safety": {
            "before": before_state,
            "after": after_state,
            "diff": safety_diff,
        },
    }
    report_path = SHADOW_STATE_DIR / "stage_7d_report.json"
    report_path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")

    # ── Console summary ────────────────────────────────────────────────────
    print(f"\n{'='*78}")
    print("  STAGE 7D SHADOW COMPLETE")
    print("=" * 78)
    print(f"  Elapsed: {aggregate['elapsed_hours']}h | Iterations: {iteration}")
    print(f"  Slots executed: {aggregate['slots_executed']} "
          f"(types: {aggregate['slot_types_executed']})")
    print(f"  ready_in_shadow={aggregate['ready_in_shadow']} "
          f"warnings_hold={aggregate['ready_with_warnings_hold']} "
          f"manual_review={aggregate['requires_manual_review']} "
          f"quality_rejected={aggregate['quality_rejected']} "
          f"skipped={aggregate['skipped_no_candidate']}")
    print(f"  SC distribution: {aggregate['sc_distribution']}")
    print(f"  Total API cost: ${aggregate['total_api_cost_usd']}")
    print(f"  Safety diff file changes: {list(safety_diff['file_changes'].keys())}")
    print(f"  Safety cron_changed={safety_diff['cron_changed']} "
          f"flag_changed={safety_diff['flag_changed']} "
          f"(flag {safety_diff['flag_before']}->{safety_diff['flag_after']})")
    print(f"  Report: {report_path}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
