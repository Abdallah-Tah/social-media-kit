"""Tests for agent.automation — job registry, scheduler, log."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))


def _patch_paths(tmp_path, monkeypatch):
    """Redirect automation storage to tmp_path."""
    import agent.automation as auto
    monkeypatch.setattr(auto, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(auto, "AUTOMATIONS_FILE", tmp_path / "automations.json")
    monkeypatch.setattr(auto, "LOG_FILE", tmp_path / "automation_log.jsonl")
    monkeypatch.setenv("SMKIT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SMKIT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(auto, "_migrated", False)
    return auto


def test_list_automations_returns_all_defaults(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    jobs = auto.list_automations()
    job_ids = {j["job_id"] for j in jobs}
    assert job_ids == {"feed_run", "intelligence_run", "publish_due", "analytics_sync", "auto_draft"}


def test_all_jobs_default_disabled_and_dry_run(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    for job in auto.list_automations():
        assert job["enabled"] is False
        assert job["dry_run"] is True


def test_update_automation_enables_job(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    updated = auto.update_automation("intelligence_run", {"enabled": True, "interval_hours": 3})
    assert updated["enabled"] is True
    assert updated["interval_hours"] == 3
    # Persisted across a reload
    jobs = {j["job_id"]: j for j in auto.list_automations()}
    assert jobs["intelligence_run"]["enabled"] is True
    assert jobs["intelligence_run"]["interval_hours"] == 3


def test_update_automation_unknown_job_returns_none(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    result = auto.update_automation("nonexistent_job", {"enabled": True})
    assert result is None


def test_update_automation_ignores_disallowed_fields(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    auto.update_automation("publish_due", {"label": "HACKED", "enabled": False})
    jobs = {j["job_id"]: j for j in auto.list_automations()}
    assert jobs["publish_due"]["label"] == "Publish Scheduled Posts"


def test_next_run_computed_from_last_run(tmp_path, monkeypatch):
    import datetime as dt
    auto = _patch_paths(tmp_path, monkeypatch)
    auto.update_automation("publish_due", {"enabled": True, "interval_hours": 2})
    # Manually set last_run via config
    config = auto._load_config()
    last = dt.datetime(2026, 1, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    config["publish_due"]["last_run"] = last.isoformat()
    auto._save_config(config)
    jobs = {j["job_id"]: j for j in auto.list_automations()}
    expected_next = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc).isoformat()
    assert jobs["publish_due"]["next_run"] == expected_next


def test_run_job_unknown_returns_error(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    result = auto.run_job("does_not_exist")
    assert result["ok"] is False
    assert "unknown" in result["error"]


def test_run_job_writes_log(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    with patch.object(auto, "_execute_job", return_value={"ok": True, "message": "test ok"}):
        auto.run_job("publish_due")
    logs = auto.list_logs()
    assert len(logs) == 1
    assert logs[0]["job_id"] == "publish_due"
    assert logs[0]["ok"] is True
    assert logs[0]["message"] == "test ok"


def test_run_job_updates_last_run(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    with patch.object(auto, "_execute_job", return_value={"ok": True, "message": "done"}):
        auto.run_job("analytics_sync")
    config = auto._load_config()
    assert config["analytics_sync"]["last_run"] is not None
    assert config["analytics_sync"]["last_result"] == "ok"


def test_run_job_failure_marks_error(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    with patch.object(auto, "_execute_job", return_value={"ok": False, "error": "boom"}):
        auto.run_job("intelligence_run")
    config = auto._load_config()
    assert config["intelligence_run"]["last_result"] == "error"
    assert config["intelligence_run"]["last_error"] == "boom"


def test_list_logs_empty_when_no_file(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    assert auto.list_logs() == []


def test_list_logs_respects_limit(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    for i in range(10):
        auto._append_log("publish_due", True, f"run {i}", True)
    logs = auto.list_logs(limit=3)
    assert len(logs) == 3
    # Newest first
    assert logs[0]["message"] == "run 9"


def test_execute_job_catches_exceptions(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)

    def boom(dry_run):
        raise RuntimeError("simulated crash")

    with patch.object(auto, "_job_intelligence_run", boom):
        result = auto._execute_job("intelligence_run", dry_run=True)
    assert result["ok"] is False
    assert "simulated crash" in result["error"]


def test_publish_due_job_dry_run(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    fake_result = {"results": {"abc": {"ok": True}}}
    with patch("agent.social_drafts.publish_due_social_drafts", return_value=fake_result):
        result = auto._job_publish_due(dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True


def test_start_scheduler_starts_daemon_thread(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    # Reset global thread so we can test start fresh
    monkeypatch.setattr(auto, "_scheduler_thread", None)
    auto.start_scheduler()
    assert auto._scheduler_thread is not None
    assert auto._scheduler_thread.is_alive()
    assert auto._scheduler_thread.daemon is True


def test_start_scheduler_idempotent(tmp_path, monkeypatch):
    auto = _patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(auto, "_scheduler_thread", None)
    auto.start_scheduler()
    thread_one = auto._scheduler_thread
    auto.start_scheduler()
    assert auto._scheduler_thread is thread_one


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── state-separation tests ───────────────────────────────────────────────────

class TestStateSeparation:
    """Runtime state must never dirty the version-controlled definitions file."""

    def test_save_config_splits_definitions_and_runtime(self, tmp_path, monkeypatch):
        auto = _patch_paths(tmp_path, monkeypatch)
        config = auto._load_config()
        config["feed_run"]["last_run"] = "2026-07-28T12:00:00+00:00"
        config["feed_run"]["last_result"] = "ok"
        config["feed_run"]["enabled"] = True
        auto._save_config(config)

        definitions = json.loads((tmp_path / "automations.json").read_text())
        assert "last_run" not in definitions.get("feed_run", {})
        assert "last_result" not in definitions.get("feed_run", {})
        assert definitions["feed_run"]["enabled"] is True

        runtime = json.loads((tmp_path / "state" / "automations_runtime.json").read_text())
        assert runtime["feed_run"]["last_run"] == "2026-07-28T12:00:00+00:00"
        assert runtime["feed_run"]["last_result"] == "ok"

    def test_load_config_merges_runtime_into_definitions(self, tmp_path, monkeypatch):
        auto = _patch_paths(tmp_path, monkeypatch)
        config = auto._load_config()
        config["feed_run"]["last_run"] = "2026-07-28T12:00:00+00:00"
        config["feed_run"]["last_result"] = "ok"
        auto._save_config(config)

        reloaded = auto._load_config()
        assert reloaded["feed_run"]["last_run"] == "2026-07-28T12:00:00+00:00"
        assert reloaded["feed_run"]["last_result"] == "ok"
        assert reloaded["feed_run"]["enabled"] is False  # default

    def test_migrate_extracts_runtime_from_legacy_file(self, tmp_path, monkeypatch):
        auto = _patch_paths(tmp_path, monkeypatch)
        legacy = {
            "feed_run": {
                "label": "News Feed Refresh",
                "enabled": True,
                "interval_hours": 3,
                "dry_run": False,
                "last_run": "2026-07-27T10:00:00+00:00",
                "last_result": "ok",
                "last_error": "",
            }
        }
        (tmp_path / "automations.json").write_text(json.dumps(legacy))
        monkeypatch.setattr(auto, "_migrated", False)

        config = auto._load_config()
        assert config["feed_run"]["last_run"] == "2026-07-27T10:00:00+00:00"
        assert config["feed_run"]["enabled"] is True

        definitions = json.loads((tmp_path / "automations.json").read_text())
        assert "last_run" not in definitions["feed_run"]

    def test_runtime_updates_do_not_dirty_definitions(self, tmp_path, monkeypatch):
        auto = _patch_paths(tmp_path, monkeypatch)
        with patch.object(auto, "_execute_job", return_value={"ok": True, "message": "done"}):
            auto.run_job("feed_run")

        definitions = json.loads((tmp_path / "automations.json").read_text())
        for job_id, cfg in definitions.items():
            assert "last_run" not in cfg
            assert "last_result" not in cfg

    def test_log_written_to_log_dir(self, tmp_path, monkeypatch):
        auto = _patch_paths(tmp_path, monkeypatch)
        auto._append_log("feed_run", True, "test entry", False)
        log_path = tmp_path / "logs" / "automation_log.jsonl"
        assert log_path.exists()
        content = log_path.read_text()
        assert "feed_run" in content

    def test_state_dir_env_override(self, tmp_path, monkeypatch):
        import agent.automation as auto
        custom_state = tmp_path / "custom_state"
        custom_state.mkdir()
        monkeypatch.setenv("SMKIT_STATE_DIR", str(custom_state))
        monkeypatch.setattr(auto, "_migrated", False)

        auto._save_runtime({"feed_run": {"last_run": "2026-01-01T00:00:00Z"}})
        assert (custom_state / "automations_runtime.json").exists()

    def test_log_dir_env_override(self, tmp_path, monkeypatch):
        import agent.automation as auto
        custom_logs = tmp_path / "custom_logs"
        custom_logs.mkdir()
        monkeypatch.setenv("SMKIT_LOG_DIR", str(custom_logs))

        auto._append_log("feed_run", True, "custom location", False)
        assert (custom_logs / "automation_log.jsonl").exists()
