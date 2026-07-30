"""Editorial API route handlers — read-only Stage 7D live shadow status.

Surfaces the Stage 7D live shadow pipeline status from
``state/editorial/shadow/stage_7d/``. This module is STRICTLY read-only:

  * it reads shadow-state JSON files (per-slot results, timing, safety, report)
  * it queries systemd for the shadow service status (``systemctl --user show``)
  * it reads the current crontab to prove cron is unchanged (``crontab -l``)

It never publishes, notifies, or mutates any state file. By design it imports
no publisher and no notification module, and the response exposes no fetched
excerpts, credentials, headers, tokens, or secrets — only the bounded status
fields the dashboard card needs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SHADOW_STATE_DIR = ROOT / "state" / "editorial" / "shadow" / "stage_7d"

SERVICE_UNIT = "smkit-stage7d-shadow.service"
DEFAULT_TIMEZONE = "America/New_York"

# The three shadow slots, scheduled daily in the editorial timezone. The second
# element is the slot identifier used by the shadow runner and the dashboard.
SLOT_SCHEDULE: tuple[tuple[str, str], ...] = (
    ("08:00", "intelligence_brief"),
    ("12:00", "midday_authority"),
    ("17:00", "practical_takeaway"),
)
SLOTS_EXPECTED = len(SLOT_SCHEDULE)

# Outcomes that represent a terminal failure of the slot pipeline.
_FAILURE_OUTCOMES = frozenset({
    "draft_generation_failed",
    "pipeline_failed",
    "invalid_configuration",
    "slot_not_found",
})

# Outcomes counted in the aggregate breakdown.
_AGGREGATE_OUTCOMES = (
    "ready_in_shadow",
    "ready_with_warnings_hold",
    "requires_manual_review",
    "quality_rejected",
    "skipped_no_candidate",
    "draft_generation_failed",
)

# Files in the shadow dir that are NOT per-slot results.
_META_FILES = frozenset({
    "safety_before.json",
    "safety_after.json",
    "safety_diff.json",
    "safety_pre_service_baseline.json",
    "timing.json",
    "stage_7d_report.json",
})


# ── Safe readers ─────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from ``path``; return None on any error.

    Corrupt or partial files are ignored safely rather than raising — the
    dashboard must render even while a slot file is mid-write.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _to_int(value: Any, default: int | None = 0) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _editorial_tz_name() -> str:
    """Editorial timezone name, read from shadow state (never the host zone)."""
    for name in ("safety_before.json", "timing.json"):
        data = _read_json(SHADOW_STATE_DIR / name)
        if data and isinstance(data.get("editorial_timezone"), str):
            return data["editorial_timezone"]
    return DEFAULT_TIMEZONE


def _zoneinfo(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — degrade to the default zone then UTC
        try:
            return ZoneInfo(DEFAULT_TIMEZONE)
        except Exception:  # noqa: BLE001
            return dt.timezone.utc


def _parse_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


# ── Read-only external queries ───────────────────────────────────────────────

def _systemctl_show() -> dict[str, str]:
    """Query systemd for a few shadow-service properties (read-only).

    Best-effort: returns {} if systemctl is unavailable or the unit is unknown.
    Only specific properties are requested so no Environment/secrets are dumped.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", SERVICE_UNIT,
             "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
             "-p", "MainPID", "-p", "ExecMainStatus"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0 and not proc.stdout:
        return {}
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip()
    return out


def _current_cron_hash() -> str | None:
    """Hash of the current crontab (read-only), for the cron-unchanged proof."""
    try:
        proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout.encode()).hexdigest()[:16]


# ── Response blocks ──────────────────────────────────────────────────────────

def _service_status(timing: dict[str, Any] | None) -> dict[str, Any]:
    report_exists = (SHADOW_STATE_DIR / "stage_7d_report.json").exists()
    props = _systemctl_show()
    load_state = props.get("LoadState", "")
    active_state = props.get("ActiveState", "")
    main_pid = _to_int(props.get("MainPID"), 0) or 0
    exec_status = _to_int(props.get("ExecMainStatus"), None)

    if report_exists:
        status = "completed"
    elif load_state == "not-found" and timing is None:
        status = "not_started"
    elif active_state == "active":
        status = "running"
    elif active_state == "failed":
        status = "failed"
    elif active_state in ("inactive", "dead", ""):
        if timing is None:
            status = "not_started"
        elif exec_status == 0:
            status = "completed"
        else:
            status = "failed"
    else:
        status = "running" if main_pid else "not_started"

    started_at = timing.get("actual_start") if timing else None
    planned = timing.get("planned_completion") if timing else None

    time_remaining = None
    if status == "running" and planned:
        planned_dt = _parse_iso(planned)
        if planned_dt is not None:
            secs = int((planned_dt - dt.datetime.now(dt.timezone.utc)).total_seconds())
            time_remaining = max(0, secs)

    return {
        "status": status,
        "pid": main_pid if status == "running" else None,
        "started_at": started_at,
        "planned_completion_at": planned,
        "time_remaining_seconds": time_remaining,
    }


def _safety_state(safety_before: dict[str, Any] | None) -> dict[str, Any]:
    slots_enabled = bool((safety_before or {}).get("editorial_slots_enabled", False))
    cron_unchanged = True
    before_cron = (safety_before or {}).get("cron_hash")
    if before_cron:
        current = _current_cron_hash()
        cron_unchanged = (current == before_cron) if current is not None else True
    return {
        "shadow_mode": True,
        # Publishing is gated on the slots flag, which the shadow run forces off.
        "editorial_slots_enabled": slots_enabled,
        "publishing_enabled": slots_enabled,
        # The shadow pipeline never sends notifications, regardless of flags.
        "notifications_enabled": False,
        "cron_unchanged": cron_unchanged,
    }


def _scheduled_at(date_str: str, slot_time: str, tz: dt.tzinfo) -> str | None:
    """ISO timestamp for a scheduled slot in the editorial timezone."""
    try:
        hour, minute = map(int, slot_time.split(":"))
        day = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
        local = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        return local.isoformat()
    except (ValueError, TypeError):
        return None


def _slot_status(outcome: str | None) -> str:
    if not outcome:
        return "failed"
    if outcome in _FAILURE_OUTCOMES:
        return "failed"
    return "completed"


def _map_slot_result(data: dict[str, Any], tz: dt.tzinfo, fallback_path: str) -> dict[str, Any]:
    """Map a persisted per-slot result file onto the API slot schema.

    Only bounded status fields are exposed — no excerpts, claims text, or
    component detail beyond the top score numbers.
    """
    date_str = str(data.get("date", ""))
    slot_time = str(data.get("slot_time", ""))
    slot_id = str(data.get("content_type", ""))
    outcome = data.get("outcome")
    top_scores = data.get("top_5_scores")
    if not isinstance(top_scores, list):
        top_scores = []
    # Numbers only — never pass through component detail or excerpts.
    top_scores = [s for s in top_scores if isinstance(s, (int, float))]

    completed_at = None
    fp = _parse_iso(data.get("completed_at"))
    if fp is not None:
        completed_at = fp.isoformat()

    # Distinct admission/rejection reason codes, order-preserving. The shadow
    # runner accumulates reasons per evaluated candidate (so they repeat); the
    # panel wants the distinct set.
    raw_reasons = data.get("admission_reasons") or data.get("reason_codes") or []
    if not isinstance(raw_reasons, list):
        raw_reasons = []
    seen_reasons: set[str] = set()
    admission_reasons: list[str] = []
    for r in raw_reasons:
        if isinstance(r, str) and r and r not in seen_reasons:
            seen_reasons.add(r)
            admission_reasons.append(r)

    return {
        "slot_id": slot_id,
        "content_type": slot_id,
        "scheduled_at": _scheduled_at(date_str, slot_time, tz),
        "completed_at": completed_at,
        "status": _slot_status(str(outcome) if outcome else None),
        "candidates_received": _to_int(data.get("candidates_received"), 0),
        "candidates_enriched": _to_int(data.get("candidates_enriched"), 0),
        "candidates_merged": _to_int(data.get("candidates_merged"), 0),
        "evidence_urls_fetched": _to_int(data.get("urls_fetched"), 0),
        "evidence_fetch_failures": _to_int(data.get("evidence_fetch_failures"), 0),
        "extraction_successes": _to_int(data.get("extraction_claims_accepted"), 0),
        "extraction_failures": _to_int(data.get("extraction_claims_rejected"), 0),
        "extraction_llm_calls": _to_int(data.get("extraction_llm_calls"), 0),
        "top_source_confidence_scores": top_scores,
        "selected_candidate": data.get("selected_candidate_id") or None,
        "selected_format": data.get("selected_format") or None,
        "admission_result": data.get("admission_status") or (str(outcome) if outcome else None),
        "admission_reasons": admission_reasons,
        "quality_score": data.get("editorial_quality"),
        "readiness_status": data.get("readiness_status") or None,
        "shadow_outcome": str(outcome) if outcome else None,
        "latency_ms": _to_int(data.get("pipeline_latency_ms"), None),
        "api_cost_usd": data.get("extraction_cost_usd"),
        "result_path": data.get("result_path") or fallback_path,
    }


def _load_slot_results(tz: dt.tzinfo) -> list[dict[str, Any]]:
    """Load and map every per-slot result file (corrupt files skipped)."""
    if not SHADOW_STATE_DIR.exists():
        return []
    slots: list[dict[str, Any]] = []
    for path in sorted(SHADOW_STATE_DIR.glob("*.json")):
        if path.name in _META_FILES:
            continue
        data = _read_json(path)
        if data is None:
            continue  # corrupt/partial file — ignore safely
        # A slot result must carry a content_type; otherwise it is not a slot.
        if "content_type" not in data and "outcome" not in data:
            continue
        slots.append(_map_slot_result(data, tz, str(path)))
    slots.sort(key=lambda s: s.get("scheduled_at") or "")
    return slots


def _expected_slots(timing: dict[str, Any] | None, tz: dt.tzinfo) -> list[dict[str, Any]]:
    """Generate the scheduled slot occurrences between start and completion."""
    if not timing:
        return []
    start = _parse_iso(timing.get("actual_start"))
    # Use the planned completion; fall back to start + 24h.
    completion = _parse_iso(timing.get("planned_completion"))
    if start is None:
        return []
    if completion is None:
        completion = start + dt.timedelta(hours=24)
    expected: list[dict[str, Any]] = []
    day = start.astimezone(tz).date()
    last_day = completion.astimezone(tz).date()
    while day <= last_day:
        for slot_time, slot_id in SLOT_SCHEDULE:
            iso = _scheduled_at(day.strftime("%Y-%m-%d"), slot_time, tz)
            sched = _parse_iso(iso)
            if sched is not None and start <= sched <= completion:
                expected.append({
                    "slot_id": slot_id,
                    "content_type": slot_id,
                    "scheduled_at": iso,
                    "_dt": sched,
                })
        day += dt.timedelta(days=1)
    expected.sort(key=lambda s: s["_dt"])
    return expected


def _next_slot(now: dt.datetime, expected: list[dict[str, Any]],
               completed_ids: set[tuple[str, str]]) -> dict[str, Any] | None:
    """The earliest scheduled slot that is still in the future and not done."""
    for slot in expected:
        sched = slot["_dt"]
        key = (str(slot.get("scheduled_at", ""))[:10], slot["slot_id"])
        if sched > now and key not in completed_ids:
            return {"slot_id": slot["slot_id"], "scheduled_at": slot["scheduled_at"]}
    return None


def _aggregate(slots: list[dict[str, Any]], report: dict[str, Any] | None) -> dict[str, Any]:
    agg = {name: 0 for name in _AGGREGATE_OUTCOMES}
    total_cost = 0.0

    if report and isinstance(report.get("outcome_counts"), dict):
        for name in _AGGREGATE_OUTCOMES:
            agg[name] = _to_int(report["outcome_counts"].get(name), 0) or 0
        total_cost = report.get("total_api_cost_usd") or 0.0
    else:
        for slot in slots:
            outcome = slot.get("shadow_outcome")
            if outcome in agg:
                agg[outcome] += 1
            cost = slot.get("api_cost_usd")
            if isinstance(cost, (int, float)):
                total_cost += cost

    agg["total_api_cost_usd"] = round(float(total_cost), 4)
    return agg


# ── Assembly ─────────────────────────────────────────────────────────────────

def _pending_slot(exp: dict[str, Any], status: str) -> dict[str, Any]:
    """A scheduled slot with no result file yet (waiting or running)."""
    return {
        "slot_id": exp["slot_id"],
        "content_type": exp["content_type"],
        "scheduled_at": exp["scheduled_at"],
        "completed_at": None,
        "status": status,
        "candidates_received": 0,
        "candidates_enriched": 0,
        "candidates_merged": 0,
        "evidence_urls_fetched": 0,
        "evidence_fetch_failures": 0,
        "extraction_successes": 0,
        "extraction_failures": 0,
        "extraction_llm_calls": 0,
        "top_source_confidence_scores": [],
        "selected_candidate": None,
        "selected_format": None,
        "admission_result": None,
        "admission_reasons": [],
        "quality_score": None,
        "readiness_status": None,
        "shadow_outcome": None,
        "latency_ms": None,
        "api_cost_usd": None,
        "result_path": None,
    }


def _build_status() -> dict[str, Any]:
    tz = _zoneinfo(_editorial_tz_name())
    timing = _read_json(SHADOW_STATE_DIR / "timing.json")
    safety_before = _read_json(SHADOW_STATE_DIR / "safety_before.json")
    report = _read_json(SHADOW_STATE_DIR / "stage_7d_report.json")

    service = _service_status(timing)
    safety = _safety_state(safety_before)
    actual = _load_slot_results(tz)
    expected = _expected_slots(timing, tz)

    # Index actual results by (date, slot_id) so the schedule can absorb them.
    actual_by_key = {
        (str(s.get("scheduled_at", ""))[:10], s["slot_id"]): s
        for s in actual
    }

    now = dt.datetime.now(dt.timezone.utc)
    merged: list[dict[str, Any]] = []
    completed_count = 0
    for exp in expected:
        key = (str(exp["scheduled_at"])[:10], exp["slot_id"])
        if key in actual_by_key:
            slot = actual_by_key[key]
            merged.append(slot)
            if slot.get("status") in ("completed", "failed"):
                completed_count += 1
        else:
            sched = exp.get("_dt")
            status = "waiting" if (sched is None or sched > now) else "running"
            merged.append(_pending_slot(exp, status))
    merged.sort(key=lambda s: s.get("scheduled_at") or "")

    # Surface any actual results that did not match an expected slot (e.g. when
    # timing.json is absent so no schedule could be generated).
    merged_keys = {(str(s.get("scheduled_at", ""))[:10], s["slot_id"]) for s in merged}
    for s in actual:
        key = (str(s.get("scheduled_at", ""))[:10], s["slot_id"])
        if key not in merged_keys:
            merged.append(s)
            if s.get("status") in ("completed", "failed"):
                completed_count += 1

    completed_ids = {
        (str(s.get("scheduled_at", ""))[:10], s["slot_id"])
        for s in merged if s.get("status") in ("completed", "failed")
    }
    next_slot = _next_slot(now, expected, completed_ids)

    progress = {
        "slots_expected": SLOTS_EXPECTED,
        "slots_completed": completed_count,
        "next_slot": next_slot,
    }

    return {
        "service": service,
        "safety": safety,
        "progress": progress,
        "slots": merged,
        # Aggregate over REAL results only (not empty waiting placeholders).
        "aggregate": _aggregate(actual, report),
    }


def register_routes(path: str, query: dict[str, list[str]], body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read-only editorial API. Only GET /api/editorial/stage7d-status is served."""
    if path == "/api/editorial/stage7d-status":
        try:
            return {"ok": True, **_build_status()}
        except Exception as exc:  # noqa: BLE001 — never crash the dashboard
            return {"ok": False, "error": f"status unavailable: {exc}",
                    "service": {"status": "not_started", "pid": None,
                                "started_at": None, "planned_completion_at": None,
                                "time_remaining_seconds": None},
                    "safety": {"shadow_mode": True, "editorial_slots_enabled": False,
                               "publishing_enabled": False, "notifications_enabled": False,
                               "cron_unchanged": True},
                    "progress": {"slots_expected": SLOTS_EXPECTED, "slots_completed": 0,
                                 "next_slot": None},
                    "slots": [],
                    "aggregate": {name: 0 for name in _AGGREGATE_OUTCOMES} | {"total_api_cost_usd": 0.0}}
    return {"error": "not found"}
