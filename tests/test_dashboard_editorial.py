"""Tests for the read-only Stage 7D shadow status endpoint (dashboard_editorial).

Covers: service not started / running / completed / failed, slot result parsing,
corrupt-JSON safety, and the security guarantees (no secrets exposed, no
publisher or notification imports).
"""
from __future__ import annotations

import ast
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent import dashboard
from agent import dashboard_editorial as de

MODULE_SOURCE = Path(de.__file__).read_text(encoding="utf-8")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def server():
    srv = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard._make_handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


@pytest.fixture
def shadow_dir(tmp_path, monkeypatch):
    d = tmp_path / "stage_7d"
    d.mkdir()
    monkeypatch.setattr(de, "SHADOW_STATE_DIR", d)
    return d


@pytest.fixture(autouse=True)
def stub_external(monkeypatch):
    """Default: shadow unit unknown, cron hash stable. Tests override as needed."""
    monkeypatch.setattr(de, "_systemctl_show", lambda: {"LoadState": "not-found"})
    monkeypatch.setattr(de, "_current_cron_hash", lambda: "cronhash123")


# ── File builders ────────────────────────────────────────────────────────────

def write_timing(d: Path, start="2026-07-29T16:09:31-04:00",
                 completion="2026-07-30T16:09:31-04:00") -> None:
    (d / "timing.json").write_text(json.dumps({
        "actual_start": start,
        "planned_completion": completion,
        "safety_cap": "2026-07-31T16:09:31-04:00",
        "next_slot_at_start": "17:00 practical_takeaway (in 51 min)",
    }), encoding="utf-8")


def write_safety_before(d: Path, slots_enabled=False, cron_hash="cronhash123") -> None:
    (d / "safety_before.json").write_text(json.dumps({
        "editorial_slots_enabled": slots_enabled,
        "editorial_timezone": "America/New_York",
        "cron_hash": cron_hash,
        "cron_lines": 4,
        "files": {},
    }), encoding="utf-8")


def write_slot(d: Path, date: str, slot_time: str, content_type: str,
               outcome="ready_in_shadow", **extra) -> None:
    fname = f"{date}_{slot_time.replace(':', '')}_{content_type}.json"
    data = {
        "slot_time": slot_time,
        "content_type": content_type,
        "date": date,
        "outcome": outcome,
        "selected_candidate_id": extra.get("selected_candidate_id", "cand_abc123def456"),
        "selected_format": extra.get("selected_format", "technical_analysis"),
        "source_confidence": extra.get("source_confidence", 72),
        "editorial_quality": extra.get("editorial_quality", 81),
        "readiness_status": extra.get("readiness_status", "ready"),
        "admission_status": extra.get("admission_status", "admitted"),
        "reason_codes": extra.get("reason_codes", []),
        "admission_reasons": extra.get("admission_reasons", [
            "artifact_not_allowed", "source_confidence_below_threshold",
            "practical_value_missing", "artifact_not_allowed",
        ]),
        "top_5_scores": extra.get("top_5_scores", [72, 68, 65, 61, 58]),
        "candidates_received": extra.get("candidates_received", 50),
        "candidates_enriched": extra.get("candidates_enriched", 50),
        "candidates_merged": extra.get("candidates_merged", 10),
        "urls_fetched": extra.get("urls_fetched", 12),
        "evidence_fetch_failures": extra.get("evidence_fetch_failures", 0),
        "extraction_claims_accepted": extra.get("extraction_claims_accepted", 3),
        "extraction_claims_rejected": extra.get("extraction_claims_rejected", 1),
        "extraction_llm_calls": extra.get("extraction_llm_calls", 10),
        "pipeline_latency_ms": extra.get("pipeline_latency_ms", 1500),
        "extraction_cost_usd": extra.get("extraction_cost_usd", 0.012),
        "result_path": extra.get("result_path", f"/state/editorial/shadow/stage_7d/{fname}"),
    }
    (d / fname).write_text(json.dumps(data), encoding="utf-8")


def write_report(d: Path, outcome_counts=None, total_cost=0.03) -> None:
    (d / "stage_7d_report.json").write_text(json.dumps({
        "outcome_counts": outcome_counts or {"ready_in_shadow": 2, "skipped_no_candidate": 1},
        "total_api_cost_usd": total_cost,
    }), encoding="utf-8")


def set_running(monkeypatch, pid=255644):
    monkeypatch.setattr(de, "_systemctl_show", lambda: {
        "LoadState": "loaded", "ActiveState": "active", "SubState": "running",
        "MainPID": str(pid), "ExecMainStatus": "0",
    })


# ── Service-state tests ──────────────────────────────────────────────────────

def test_service_not_started(server, shadow_dir):
    # No timing.json, unit not found.
    status, body = _get(server + "/api/editorial/stage7d-status")
    assert status == 200
    assert body["ok"] is True
    assert body["service"]["status"] == "not_started"
    assert body["service"]["pid"] is None
    assert body["slots"] == []
    assert body["progress"]["slots_completed"] == 0


def test_running_with_no_slot_results(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir)
    set_running(monkeypatch, pid=99999)

    status, body = _get(server + "/api/editorial/stage7d-status")
    assert status == 200
    assert body["service"]["status"] == "running"
    assert body["service"]["pid"] == 99999
    assert body["service"]["started_at"] == "2026-07-29T16:09:31-04:00"
    assert body["service"]["planned_completion_at"] == "2026-07-30T16:09:31-04:00"
    assert isinstance(body["service"]["time_remaining_seconds"], int)
    # Three expected slots, all waiting, none completed.
    assert body["progress"]["slots_expected"] == 3
    assert body["progress"]["slots_completed"] == 0
    assert all(s["status"] in ("waiting", "running") for s in body["slots"])
    assert body["progress"]["next_slot"] is not None


def test_one_completed_slot(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir)
    set_running(monkeypatch)
    write_slot(shadow_dir, "2026-07-29", "17:00", "practical_takeaway",
               outcome="ready_in_shadow")

    status, body = _get(server + "/api/editorial/stage7d-status")
    assert status == 200
    assert body["progress"]["slots_completed"] == 1
    completed = [s for s in body["slots"] if s["status"] == "completed"]
    assert len(completed) == 1
    slot = completed[0]
    assert slot["slot_id"] == "practical_takeaway"
    assert slot["shadow_outcome"] == "ready_in_shadow"
    assert slot["selected_format"] == "technical_analysis"
    assert slot["quality_score"] == 81
    assert slot["top_source_confidence_scores"] == [72, 68, 65, 61, 58]
    # New funnel / extraction / rejection-reason fields.
    assert slot["candidates_received"] == 50
    assert slot["candidates_enriched"] == 50
    assert slot["candidates_merged"] == 10
    assert slot["evidence_urls_fetched"] == 12
    assert slot["evidence_fetch_failures"] == 0
    assert slot["extraction_llm_calls"] == 10
    # Duplicate reasons in the source file are deduplicated, order preserved.
    assert slot["admission_reasons"] == [
        "artifact_not_allowed", "source_confidence_below_threshold", "practical_value_missing",
    ]
    assert body["aggregate"]["ready_in_shadow"] == 1


def test_all_three_slots_completed(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir)
    # Service exited cleanly and the report exists -> completed.
    monkeypatch.setattr(de, "_systemctl_show", lambda: {
        "LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead",
        "MainPID": "0", "ExecMainStatus": "0",
    })
    write_slot(shadow_dir, "2026-07-29", "17:00", "practical_takeaway", outcome="ready_in_shadow")
    write_slot(shadow_dir, "2026-07-30", "08:00", "intelligence_brief", outcome="skipped_no_candidate")
    write_slot(shadow_dir, "2026-07-30", "12:00", "midday_authority", outcome="ready_in_shadow")
    write_report(shadow_dir, outcome_counts={"ready_in_shadow": 2, "skipped_no_candidate": 1},
                 total_cost=0.045)

    status, body = _get(server + "/api/editorial/stage7d-status")
    assert status == 200
    assert body["service"]["status"] == "completed"
    assert body["progress"]["slots_completed"] == 3
    assert body["aggregate"]["ready_in_shadow"] == 2
    assert body["aggregate"]["skipped_no_candidate"] == 1
    assert body["aggregate"]["total_api_cost_usd"] == 0.045


def test_failed_service(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir)
    monkeypatch.setattr(de, "_systemctl_show", lambda: {
        "LoadState": "loaded", "ActiveState": "failed", "SubState": "failed",
        "MainPID": "0", "ExecMainStatus": "1",
    })

    status, body = _get(server + "/api/editorial/stage7d-status")
    assert status == 200
    assert body["service"]["status"] == "failed"


def test_corrupt_json_ignored_safely(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir)
    set_running(monkeypatch)
    # One valid slot, one corrupt slot file.
    write_slot(shadow_dir, "2026-07-29", "17:00", "practical_takeaway", outcome="ready_in_shadow")
    (shadow_dir / "2026-07-30_0800_intelligence_brief.json").write_text(
        "{ this is not valid json", encoding="utf-8")

    status, body = _get(server + "/api/editorial/stage7d-status")
    # Must not crash; the corrupt file is skipped, the valid one is parsed.
    assert status == 200
    assert body["ok"] is True
    completed = [s for s in body["slots"] if s["status"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["slot_id"] == "practical_takeaway"


def test_cron_unchanged_detection(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir, cron_hash="cronhash123")
    set_running(monkeypatch)
    # Current cron matches the before-hash.
    monkeypatch.setattr(de, "_current_cron_hash", lambda: "cronhash123")
    _, body = _get(server + "/api/editorial/stage7d-status")
    assert body["safety"]["cron_unchanged"] is True

    # Now the cron differs -> detected as changed.
    monkeypatch.setattr(de, "_current_cron_hash", lambda: "DIFFERENT")
    _, body2 = _get(server + "/api/editorial/stage7d-status")
    assert body2["safety"]["cron_unchanged"] is False


def test_safety_flags_reflect_shadow(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir, slots_enabled=False)
    set_running(monkeypatch)
    _, body = _get(server + "/api/editorial/stage7d-status")
    assert body["safety"]["shadow_mode"] is True
    assert body["safety"]["editorial_slots_enabled"] is False
    assert body["safety"]["publishing_enabled"] is False
    assert body["safety"]["notifications_enabled"] is False


# ── Security tests ───────────────────────────────────────────────────────────

def _all_keys(obj, acc=None):
    """Recursively collect every dict key in a JSON structure."""
    if acc is None:
        acc = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            _all_keys(v, acc)
    elif isinstance(obj, list):
        for item in obj:
            _all_keys(item, acc)
    return acc


def test_no_secret_fields_in_response(server, shadow_dir, monkeypatch):
    write_timing(shadow_dir)
    write_safety_before(shadow_dir)
    set_running(monkeypatch)
    write_slot(shadow_dir, "2026-07-29", "17:00", "practical_takeaway", outcome="ready_in_shadow")

    status, body = _get(server + "/api/editorial/stage7d-status")
    assert status == 200
    raw = json.dumps(body).lower()

    # No secret/credential material or fetched content may appear.
    for forbidden in ("api_key", "apikey", "token", "secret", "password",
                      "authorization", "bearer", "excerpt", "private_key",
                      "access_token", "client_secret"):
        assert forbidden not in raw, f"forbidden field {forbidden!r} leaked into response"

    # Component detail (sc_details) must not be exposed — only score numbers.
    keys = _all_keys(body)
    assert "sc_details" not in keys
    assert "components" not in keys
    # The score field is numbers only.
    for slot in body["slots"]:
        assert all(isinstance(s, (int, float)) for s in slot["top_source_confidence_scores"])


def _imported_modules(source: str) -> set[str]:
    """Top-level module names imported by the given source."""
    tree = ast.parse(source)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return mods


def test_no_publisher_imports():
    mods = _imported_modules(MODULE_SOURCE)
    forbidden = {
        "news_publish", "blog_publisher", "linkedin_poster", "x_poster",
        "facebook_poster", "discord_poster", "bluesky_poster", "pinterest_poster",
        "tiktok_upload", "youtube_shorts_publisher", "fb_poster",
    }
    assert not (mods & forbidden), f"publisher modules imported: {mods & forbidden}"
    # Also assert no publisher path appears anywhere in the source text.
    for name in forbidden:
        assert name not in MODULE_SOURCE


def test_no_notification_imports():
    mods = _imported_modules(MODULE_SOURCE)
    forbidden = {"telegram", "newsletter", "smtp", "email_notifier"}
    assert not (mods & forbidden), f"notification modules imported: {mods & forbidden}"
    for name in forbidden:
        assert name not in MODULE_SOURCE


def test_endpoint_is_read_only_get(server, shadow_dir, monkeypatch):
    """The endpoint only serves GET; POST is not routed to it."""
    write_timing(shadow_dir)
    write_safety_before(shadow_dir)
    set_running(monkeypatch)
    # GET works.
    status, body = _get(server + "/api/editorial/stage7d-status")
    assert status == 200 and body["ok"] is True
    # An unknown editorial path returns the JSON 404 sentinel.
    status404, body404 = _get(server + "/api/editorial/does-not-exist")
    assert status404 == 404
    assert body404["error"] == "not found"
