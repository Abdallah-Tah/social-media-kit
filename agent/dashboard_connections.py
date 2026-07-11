"""Connections + Sources API route handlers."""
from __future__ import annotations
from typing import Any


def register_routes(
    path: str,
    query: dict[str, list[str]],
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path == "/api/connections":
        from .connections import check_connections
        return {"ok": True, "connections": check_connections()}

    if path == "/api/connections/save":
        from .connections import save_platform_secrets, check_connections
        if not body or not isinstance(body.get("values"), dict):
            return {"ok": False, "error": "values object is required"}
        result = save_platform_secrets(body["values"])
        if result.get("ok"):
            result["connections"] = check_connections()
        return result

    if path == "/api/intelligence/config":
        from .intelligence_config_store import get_intelligence_config_dict, save_config_overrides
        if body:
            save_config_overrides(body)
        return {"ok": True, "config": get_intelligence_config_dict()}

    return {"error": "not found"}
