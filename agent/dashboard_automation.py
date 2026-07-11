"""Automation API route handlers — wired into dashboard.py."""
from __future__ import annotations

from typing import Any

from .automation import list_automations, list_logs, run_job, update_automation


def register_routes(
    path: str,
    query: dict[str, list[str]],
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path == "/api/automations":
        return {"ok": True, "automations": list_automations()}

    if path.startswith("/api/automations/") and path.endswith("/run"):
        job_id = path[len("/api/automations/"):-len("/run")]
        return run_job(job_id)

    if path.startswith("/api/automations/"):
        job_id = path[len("/api/automations/"):]
        if body:
            updated = update_automation(job_id, body)
            if updated is None:
                return {"ok": False, "error": "unknown automation"}
            return {"ok": True, "automation": updated}
        all_automations = list_automations()
        found = next((a for a in all_automations if a["job_id"] == job_id), None)
        return found if found is not None else {"error": "not found"}

    if path == "/api/logs":
        try:
            limit = int((query.get("limit") or ["100"])[0])
        except (ValueError, TypeError):
            limit = 100
        return {"ok": True, "logs": list_logs(min(limit, 500))}

    return {"error": "not found"}
