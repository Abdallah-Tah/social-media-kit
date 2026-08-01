"""Background automation scheduler for smkit.

Manages a registry of periodic jobs with persistent config and an
append-only run log. All jobs default to disabled and dry_run=True.

The scheduler runs as a daemon thread started by the dashboard server.
It is resilient to individual job failures (exceptions are logged, not
re-raised) and idempotent across restarts (next_run derived from
last_run + interval_hours).

State layout
------------
Definitions (version-controlled)::

    content/automations.json          # enabled, interval_hours, dry_run defaults

Runtime state (git-ignored)::

    state/automations_runtime.json    # last_run, last_result, last_error

Logs (git-ignored)::

    logs/automation_log.jsonl         # append-only execution log

Override with ``SMKIT_STATE_DIR`` / ``SMKIT_LOG_DIR`` to place runtime
files outside the repository in production.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"

# ── path resolution ──────────────────────────────────────────────────────────

# Version-controlled definitions — static job config only.
AUTOMATIONS_FILE = CONTENT_DIR / "automations.json"

# Runtime state and logs — resolved from env or repo-local defaults.
# Tests and production override via SMKIT_STATE_DIR / SMKIT_LOG_DIR.

_RUNTIME_FIELDS = {"last_run", "last_result", "last_error"}


def _state_dir() -> Path:
    override = os.environ.get("SMKIT_STATE_DIR")
    if override:
        return Path(override)
    return ROOT / "state"


def _log_dir() -> Path:
    override = os.environ.get("SMKIT_LOG_DIR")
    if override:
        return Path(override)
    return ROOT / "logs"


def _runtime_file() -> Path:
    return _state_dir() / "automations_runtime.json"


def _log_file() -> Path:
    return _log_dir() / "automation_log.jsonl"


# Legacy paths — used by migration only.
LOG_FILE = CONTENT_DIR / "automation_log.jsonl"

JOB_DEFAULTS: dict[str, dict[str, Any]] = {
    "feed_run": {
        "label": "News Feed Refresh",
        "description": "Fetch fresh Google News, Hacker News, and Reddit stories into the feed.",
        "interval_hours": 3,
        "enabled": False,
        "dry_run": True,
    },
    "intelligence_run": {
        "label": "Intelligence Run",
        "description": "Fetch and score fresh stories from all configured sources.",
        "interval_hours": 6,
        "enabled": False,
        "dry_run": True,
    },
    "publish_due": {
        "label": "Publish Scheduled Posts",
        "description": "Publish social drafts whose scheduled_at time has passed.",
        "interval_hours": 1,
        "enabled": False,
        "dry_run": True,
    },
    "analytics_sync": {
        "label": "Analytics Sync",
        "description": "Pull latest performance data from connected platforms.",
        "interval_hours": 24,
        "enabled": False,
        "dry_run": True,
    },
    "auto_draft": {
        "label": "Auto-Generate Drafts",
        "description": "Create content drafts from top intelligence opportunities.",
        "interval_hours": 12,
        "enabled": False,
        "dry_run": True,
    },
}

_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None
_migrated = False


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _migrate_once() -> None:
    """Seed the runtime state file from legacy definitions and relocate the
    old log file.  Idempotent — runs at most once per process.

    The migration is *read-only* for the tracked definitions file: it copies
    runtime fields into the state directory without rewriting the definitions.
    The next ``_save_config()`` call writes clean definitions naturally.
    """
    global _migrated
    if _migrated:
        return
    _migrated = True

    # 1. Seed runtime state from content/automations.json if the runtime
    #    file does not yet exist.  Never rewrite the definitions file.
    rt = _runtime_file()
    if AUTOMATIONS_FILE.exists() and not rt.exists():
        try:
            saved = json.loads(AUTOMATIONS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}
        runtime: dict[str, dict[str, Any]] = {}
        for job_id, cfg in saved.items():
            extracted = {k: cfg[k] for k in cfg if k in _RUNTIME_FIELDS}
            if extracted:
                runtime[job_id] = extracted
        if runtime:
            rt.parent.mkdir(parents=True, exist_ok=True)
            rt.write_text(json.dumps(runtime, indent=2), encoding="utf-8")

    # 2. Move legacy log file into logs/.
    legacy_log = CONTENT_DIR / "automation_log.jsonl"
    new_log = _log_file()
    if legacy_log.exists() and not new_log.exists():
        new_log.parent.mkdir(parents=True, exist_ok=True)
        legacy_log.rename(new_log)


def _load_runtime() -> dict[str, dict[str, Any]]:
    """Load runtime state (last_run, last_result, last_error)."""
    rt = _runtime_file()
    if rt.exists():
        try:
            return json.loads(rt.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_runtime(runtime: dict[str, dict[str, Any]]) -> None:
    """Persist runtime state to the state directory."""
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    _runtime_file().write_text(json.dumps(runtime, indent=2), encoding="utf-8")


def _load_config() -> dict[str, dict[str, Any]]:
    """Load automation config: definitions from tracked file, runtime from state dir."""
    _migrate_once()
    if AUTOMATIONS_FILE.exists():
        try:
            saved = json.loads(AUTOMATIONS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}
    else:
        saved = {}

    runtime = _load_runtime()

    config: dict[str, dict[str, Any]] = {}
    for job_id, defaults in JOB_DEFAULTS.items():
        config[job_id] = dict(defaults)
        if job_id in saved:
            for k in ("enabled", "interval_hours", "dry_run"):
                if k in saved[job_id]:
                    config[job_id][k] = saved[job_id][k]
        if job_id in runtime:
            for k in _RUNTIME_FIELDS:
                if k in runtime[job_id]:
                    config[job_id][k] = runtime[job_id][k]
    return config


def _save_config(config: dict[str, dict[str, Any]]) -> None:
    """Split config into definitions (tracked) and runtime state (ignored)."""
    definitions: dict[str, dict[str, Any]] = {}
    runtime: dict[str, dict[str, Any]] = {}
    for job_id, cfg in config.items():
        defs = {k: v for k, v in cfg.items() if k not in _RUNTIME_FIELDS}
        definitions[job_id] = defs
        rt = {k: v for k, v in cfg.items() if k in _RUNTIME_FIELDS}
        if rt:
            runtime[job_id] = rt

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    AUTOMATIONS_FILE.write_text(json.dumps(definitions, indent=2), encoding="utf-8")
    _save_runtime(runtime)


def _append_log(job_id: str, ok: bool, message: str, dry_run: bool) -> None:
    entry = {
        "ts": _now_iso(),
        "job_id": job_id,
        "ok": ok,
        "message": message,
        "dry_run": dry_run,
    }
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    with _log_file().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _compute_next_run(cfg: dict[str, Any]) -> str | None:
    last_run = cfg.get("last_run")
    if not cfg.get("enabled") or not last_run:
        return None
    try:
        last_dt = dt.datetime.fromisoformat(last_run)
        return (last_dt + dt.timedelta(hours=cfg.get("interval_hours", 1))).isoformat()
    except ValueError:
        return None


def list_automations() -> list[dict[str, Any]]:
    with _lock:
        config = _load_config()
    out = []
    for job_id, cfg in config.items():
        out.append({"job_id": job_id, **cfg, "next_run": _compute_next_run(cfg)})
    return out


def update_automation(job_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"enabled", "interval_hours", "dry_run"}
    with _lock:
        config = _load_config()
        if job_id not in config:
            return None
        for k, v in fields.items():
            if k in allowed:
                config[job_id][k] = v
        _save_config(config)
        cfg = config[job_id]
    return {"job_id": job_id, **cfg, "next_run": _compute_next_run(cfg)}


def run_job(job_id: str) -> dict[str, Any]:
    """Run a job immediately (synchronous). Updates last_run + log."""
    with _lock:
        config = _load_config()
    if job_id not in config:
        return {"ok": False, "error": f"unknown job: {job_id}"}
    dry_run = config[job_id].get("dry_run", True)
    result = _execute_job(job_id, dry_run)
    ok = result.get("ok", False)
    message = result.get("message", result.get("error", ""))
    _append_log(job_id, ok, message, dry_run)
    with _lock:
        config2 = _load_config()
        config2[job_id]["last_run"] = _now_iso()
        config2[job_id]["last_result"] = "ok" if ok else "error"
        config2[job_id]["last_error"] = "" if ok else message
        _save_config(config2)
    return result


def _execute_job(job_id: str, dry_run: bool) -> dict[str, Any]:
    try:
        if job_id == "feed_run":
            return _job_feed_run(dry_run)
        if job_id == "intelligence_run":
            return _job_intelligence_run(dry_run)
        if job_id == "publish_due":
            return _job_publish_due(dry_run)
        if job_id == "analytics_sync":
            return _job_analytics_sync(dry_run)
        if job_id == "auto_draft":
            return _job_auto_draft(dry_run)
        return {"ok": False, "error": f"unknown job: {job_id}"}
    except Exception as exc:
        tb = traceback.format_exc()
        return {"ok": False, "error": f"{job_id} raised: {exc}", "traceback": tb}


def _job_feed_run(dry_run: bool) -> dict[str, Any]:
    """Fetch Google News + HN + Reddit and save to content/feed/."""
    import sys
    from pathlib import Path
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from .feed import build_feed, last_enrichment_stats, save_feed
    # include_seen: the browse feed should always show current top stories.
    # It also means the same stories recur run after run, which is why the
    # enrichment cache (not the seen store) is what stops re-summarizing them.
    items = build_feed(limit=20, use_llm=not dry_run, include_seen=True)
    if not dry_run and items:  # never overwrite a good snapshot with 0 items
        save_feed(items)
    enrichment = last_enrichment_stats().to_dict()
    suffix = (
        f" | llm: {enrichment['llm_calls']} calls, {enrichment['enriched']} enriched, "
        f"{enrichment['cache_hits']} cached, {enrichment['failed']} failed"
    ) if enrichment["enabled"] else " | llm: disabled"
    return {
        "ok": True,
        "message": (
            f"Feed refresh: {len(items)} items "
            f"{'(dry run — not saved)' if dry_run else 'saved'}{suffix}"
        ),
        "count": len(items),
        "dry_run": dry_run,
        "enrichment": enrichment,
    }


def _job_intelligence_run(dry_run: bool) -> dict[str, Any]:
    from .feed_intelligence import run_intelligent_feed
    cards = run_intelligent_feed(profile_name="default", limit=20)
    return {
        "ok": True,
        "message": f"Intelligence run: {len(cards)} cards",
        "count": len(cards),
        "dry_run": dry_run,
    }


def _job_publish_due(dry_run: bool) -> dict[str, Any]:
    from .social_drafts import publish_due_social_drafts
    try:
        max_per_run = int(os.environ.get("SMKIT_PUBLISH_MAX_PER_RUN", "3"))
    except ValueError:
        max_per_run = 3
    result = publish_due_social_drafts(dry_run=dry_run, max_per_run=max_per_run)
    results = result.get("results", {})
    published = sum(1 for v in results.values() if v.get("ok"))
    retried = sum(1 for v in results.values() if v.get("retryable"))
    failed = sum(
        1 for v in results.values()
        if not v.get("ok") and not v.get("skipped") and not v.get("retryable")
    )
    message = f"Publish due: {published} published, {retried} rescheduled, {failed} failed"
    if failed:
        first = next(
            (v.get("error", "") for v in results.values()
             if not v.get("ok") and not v.get("skipped") and not v.get("retryable")),
            "",
        )
        message = f"{message} — {first}"
    return {
        # A run where every post was rejected is not a success. Reporting ok
        # unconditionally left the dashboard green while nothing shipped.
        "ok": failed == 0,
        "message": message,
        "dry_run": dry_run,
        "results": results,
    }


def _job_analytics_sync(dry_run: bool) -> dict[str, Any]:
    from .analytics import compute_analytics
    snapshot = compute_analytics()
    return {
        "ok": True,
        "message": "Analytics synced",
        "dry_run": dry_run,
        "generated_at": snapshot.generated_at,
    }


def _job_auto_draft(dry_run: bool) -> dict[str, Any]:
    """Generate drafts from top unseen intelligence opportunities."""
    from .feed_intelligence import run_intelligent_feed
    from .drafts import create_draft
    cards_objs = run_intelligent_feed(profile_name="default", limit=20)
    top = [c for c in cards_objs if not c.previously_seen][:3]
    if dry_run:
        return {
            "ok": True,
            "message": f"Auto-draft dry run: would create {len(top)} drafts",
            "dry_run": True,
            "count": len(top),
        }
    created = 0
    for card in top:
        card_dict = card.to_dict()
        brief = card_dict.get("brief") or {}
        if brief:
            create_draft(card_dict, brief)
            created += 1
    return {
        "ok": True,
        "message": f"Auto-draft: created {created} drafts",
        "dry_run": False,
        "count": created,
    }


def _scheduler_loop() -> None:
    import time
    while True:
        time.sleep(60)
        # The loop body is guarded as a whole: this thread is the only thing
        # driving every automation, and an unhandled error anywhere in it
        # (a corrupt state file, a full disk) would kill the thread silently
        # and stop all scheduled publishing with no signal anywhere.
        try:
            with _lock:
                config = _load_config()
            now = dt.datetime.now(dt.timezone.utc)
            for job_id, cfg in config.items():
                if not cfg.get("enabled"):
                    continue
                interval_hours = cfg.get("interval_hours", 1)
                last_run = cfg.get("last_run")
                if last_run:
                    try:
                        last_dt = dt.datetime.fromisoformat(last_run)
                        if (now - last_dt).total_seconds() < interval_hours * 3600:
                            continue
                    except ValueError:
                        pass
                dry_run = cfg.get("dry_run", True)
                result = _execute_job(job_id, dry_run)
                ok = result.get("ok", False)
                message = result.get("message", result.get("error", ""))
                _append_log(job_id, ok, message, dry_run)
                with _lock:
                    config2 = _load_config()
                    config2[job_id]["last_run"] = now.isoformat()
                    config2[job_id]["last_result"] = "ok" if ok else "error"
                    config2[job_id]["last_error"] = "" if ok else message
                    _save_config(config2)
        except Exception as exc:  # noqa: BLE001 — the thread must never die
            try:
                _append_log("scheduler", False, f"scheduler loop error: {exc}", False)
            except Exception:
                pass


def start_scheduler() -> None:
    """Start the background scheduler daemon. Safe to call multiple times."""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    t = threading.Thread(target=_scheduler_loop, name="smkit-automation", daemon=True)
    t.start()
    _scheduler_thread = t


def list_logs(limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent log entries, newest first."""
    log_path = _log_file()
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))
